#!/usr/bin/env python3
"""
LocalStack privileged helper.

This is the ONLY part of LocalStack that runs as root. It is invoked through
pkexec by src/privileged.py; the GUI itself always stays unprivileged.

Every subcommand validates its arguments before acting: the helper receives
its arguments from an unprivileged process, so it must not trust them.
"""

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile

try:
    from src.platform_info import is_arch, mysql_service, apache_config_dir, apache_config_file, log_dir
except ModuleNotFoundError:  # helper invoked directly by pkexec
    from platform_info import is_arch, mysql_service, apache_config_dir, apache_config_file, log_dir

# Only these units may be controlled. Anything else is rejected.
ALLOWED_UNITS = {"httpd", "php-fpm", "mysqld", "mariadb"}
ALLOWED_ACTIONS = {"start", "stop", "restart", "reload", "enable", "disable"}

VHOSTS_DIR = apache_config_dir()
HOSTS_FILE = "/etc/hosts"
CONFIG_PREFIX = "localstack_"

HOSTNAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*$")
PROJECT_RE = re.compile(r"^[A-Za-z0-9._-]+$")
PACKAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")

VHOST_TEMPLATE = """# LocalStack Virtual Host Configuration
# Project: {project}
# Hostname: {servername}
# Managed by LocalStack -- edits may be overwritten.
# ============================================================

<VirtualHost *:80>
    ServerName {servername}
    ServerAlias www.{servername}
    DocumentRoot "{documentroot}"
    DirectoryIndex index.php index.html

    <Directory "{documentroot}">
        AllowOverride All
        Require all granted
        Options FollowSymLinks
    </Directory>

    # PHP-FPM. Fedora's /etc/httpd/conf.d/php.conf already wires this up
    # globally; repeated here so the vhost is self-contained.
    <FilesMatch \\.php$>
        SetHandler "proxy:unix:{socket}|fcgi://localhost"
    </FilesMatch>

    ErrorLog "/var/log/httpd/{servername}_error.log"
    CustomLog "/var/log/httpd/{servername}_access.log" combined
</VirtualHost>
"""

VHOST_MODPHP_TEMPLATE = """# LocalStack Virtual Host Configuration
# Project: {project}
# Hostname: {servername}
# Managed by LocalStack -- edits may be overwritten.
# ============================================================

<VirtualHost *:80>
    ServerName {servername}
    ServerAlias www.{servername}
    DocumentRoot "{documentroot}"
    DirectoryIndex index.php index.html

    <Directory "{documentroot}">
        AllowOverride All
        Require all granted
        Options FollowSymLinks
        AddType application/x-httpd-php .php
    </Directory>

    ErrorLog "/var/log/httpd/{servername}_error.log"
    CustomLog "/var/log/httpd/{servername}_access.log" combined
</VirtualHost>
"""

HOSTS_MARKER = "# LocalStack"

# Apache may write only to these conventional runtime-data directories, never
# to the application code/document root as a whole.
APACHE_WRITABLE_DIRS = {
    "uploads", "storage", "cache", "tmp", "logs", "var",
    "database", "backups", "public/uploads",
}


def fail(msg: str, code: int = 1):
    print(msg, file=sys.stderr)
    sys.exit(code)


def check_hostname(hostname: str) -> str:
    hostname = hostname.strip().lower().rstrip(".")
    if not hostname or len(hostname) > 253 or not HOSTNAME_RE.match(hostname):
        fail(f"Invalid hostname: {hostname!r}")
    return hostname


def check_project(name: str) -> str:
    name = name.strip()
    if not PROJECT_RE.match(name):
        fail(f"Invalid project name: {name!r}")
    return name


def config_path(project: str) -> str:
    # basename() defends against a project name that tries to escape the dir.
    return apache_config_file(os.path.basename(project))


def check_docroot(path: str) -> str:
    path = os.path.realpath(path)
    if not os.path.isdir(path):
        fail(f"Document root does not exist or is not a directory: {path}")
    return path


def atomic_write(path: str, content: str, mode: int = 0o644):
    """Write via a temp file in the same directory, then rename.

    A half-written file in conf.d would take Apache down on the next reload.
    """
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".localstack-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


# --------------------------------------------------------------------------
# SELinux
# --------------------------------------------------------------------------

def selinux_enforcing() -> bool:
    if not shutil.which("getenforce"):
        return False
    r = subprocess.run(["getenforce"], capture_output=True, text=True)
    return r.stdout.strip() in ("Enforcing", "Permissive")


def selinux_label(path: str, setype: str) -> list[str]:
    """Apply a persistent SELinux file context. Returns a list of problems."""
    problems = []
    spec = f"{path}(/.*)?"

    if shutil.which("semanage"):
        add = subprocess.run(
            ["semanage", "fcontext", "-a", "-t", setype, spec],
            capture_output=True, text=True,
        )
        if add.returncode != 0:
            # Already defined -> modify the existing rule instead.
            mod = subprocess.run(
                ["semanage", "fcontext", "-m", "-t", setype, spec],
                capture_output=True, text=True,
            )
            if mod.returncode != 0:
                problems.append(
                    f"semanage fcontext failed for {path}: "
                    f"{(add.stderr or mod.stderr).strip()}"
                )
    else:
        problems.append(
            "semanage not found (install policycoreutils-python-utils) -- "
            "falling back to chcon, which does not survive a relabel"
        )
        cc = subprocess.run(
            ["chcon", "-R", "-t", setype, path], capture_output=True, text=True
        )
        if cc.returncode != 0:
            problems.append(f"chcon failed for {path}: {cc.stderr.strip()}")
        return problems

    rc = subprocess.run(["restorecon", "-RF", path], capture_output=True, text=True)
    if rc.returncode != 0:
        problems.append(f"restorecon failed for {path}: {rc.stderr.strip()}")
    return problems


# --------------------------------------------------------------------------
# Subcommands
# --------------------------------------------------------------------------

def cmd_prepare_docroot(args):
    """Make a project directory reachable by Apache.

    Two distinct things can block Apache under /home:
      * DAC   -- the home directory is typically mode 700, so httpd cannot
                 traverse into it. We add o+x on the path components between
                 the home directory and the docroot.
      * MAC   -- SELinux labels everything under /home as user_home_t, which
                 httpd_t may not read. We relabel persistently.
    Anything that fails is reported; this command never claims false success.
    """
    docroot = check_docroot(args.path)
    problems = []
    actions = []

    # In the common layout the docroot is <app>/public while the code, .env and
    # writable dirs are siblings above it. PHP-FPM still has to read them, so
    # label the app root too when one is given.
    app_root = check_docroot(args.app_root) if args.app_root else None
    if app_root and not docroot.startswith(app_root + os.sep):
        fail(f"--app-root {app_root} does not contain --path {docroot}")

    # --- traversal -------------------------------------------------------
    home = os.path.realpath(os.path.expanduser(f"~{args.owner}")) if args.owner else None
    parts = []
    cur = docroot
    while cur and cur != "/":
        parts.append(cur)
        cur = os.path.dirname(cur)
    apache_user = "http" if is_arch() else "apache"
    for path in reversed(parts):
        # Within the user's home, retain the existing traversal behavior.
        # Outside it (e.g. /mnt/data), grant Apache search-only ACLs rather
        # than making the mount's directory names world-readable.
        if home and not (path == home or path.startswith(home + os.sep)):
            if path == "/":
                continue
            if not shutil.which("setfacl"):
                problems.append(f"setfacl not found; Apache may not traverse {path}")
                continue
            result = subprocess.run(
                ["setfacl", "-m", f"u:{apache_user}:--x", "--", path],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                problems.append(
                    f"cannot grant Apache traversal on {path}: "
                    f"{result.stderr.strip() or result.stdout.strip()}"
                )
            else:
                actions.append(f"granted {apache_user} traversal on {path} (ACL)")
            continue
        try:
            mode = os.stat(path).st_mode
            if not mode & stat.S_IXOTH:
                os.chmod(path, mode | stat.S_IXOTH)
                actions.append(f"chmod o+x {path}")
        except OSError as exc:
            problems.append(f"cannot chmod {path}: {exc}")

    # --- DAC write access for runtime data -------------------------------
    # Apache runs as `http` on Arch-family systems and `apache` on Fedora.
    # ACLs preserve the project's ownership while allowing PHP to write only
    # to explicitly selected runtime-data directories.
    for rel in args.rw or []:
        if rel not in APACHE_WRITABLE_DIRS:
            problems.append(f"refusing unsupported writable directory: {rel}")
            continue

        candidate = os.path.join(app_root or docroot, rel)
        rw_path = os.path.realpath(candidate)
        base = os.path.realpath(app_root or docroot)
        if not (rw_path == base or rw_path.startswith(base + os.sep)):
            problems.append(f"refusing writable directory outside project: {rw_path}")
            continue
        if not os.path.isdir(rw_path):
            continue
        if os.path.islink(candidate):
            problems.append(f"refusing symlink as writable directory: {candidate}")
            continue

        if not shutil.which("setfacl"):
            problems.append("setfacl not found; install the acl package to grant Apache write access")
            continue
        # Existing DB files need write permission too; default ACLs cover files
        # and subdirectories created by the app in the future.
        for acl_args in (
            ["-R", "-m", f"u:{apache_user}:rwX", "--", rw_path],
            ["-m", f"d:u:{apache_user}:rwx", "--", rw_path],
        ):
            result = subprocess.run(["setfacl", *acl_args], capture_output=True, text=True)
            if result.returncode != 0:
                problems.append(
                    f"could not grant {apache_user} write access to {rw_path}: "
                    f"{result.stderr.strip() or result.stdout.strip()}"
                )
                break
        else:
            actions.append(f"granted {apache_user} write access to {rw_path} (ACL)")

    # --- SELinux ---------------------------------------------------------
    if selinux_enforcing():
        content_target = app_root or docroot
        errs = selinux_label(content_target, "httpd_sys_content_t")
        problems.extend(errs)
        if not errs:
            actions.append(f"labelled {content_target} httpd_sys_content_t")

        for rel in args.rw or []:
            base = app_root or docroot
            rw_path = os.path.realpath(os.path.join(base, rel))
            # Never relabel outside the tree we were asked to prepare.
            if not (rw_path == base or rw_path.startswith(base + os.sep)):
                problems.append(f"refusing to label {rw_path}: outside {base}")
                continue
            if not os.path.isdir(rw_path):
                continue
            errs = selinux_label(rw_path, "httpd_sys_rw_content_t")
            problems.extend(errs)
            if not errs:
                actions.append(f"labelled {rw_path} httpd_sys_rw_content_t")

        # Apache needs 'search' on user_home_dir_t to reach anything in /home.
        if docroot.startswith("/home/") and shutil.which("setsebool"):
            sb = subprocess.run(
                ["setsebool", "-P", "httpd_enable_homedirs", "on"],
                capture_output=True, text=True,
            )
            if sb.returncode != 0:
                problems.append(f"setsebool httpd_enable_homedirs failed: {sb.stderr.strip()}")
            else:
                actions.append("httpd_enable_homedirs=on")

    print(json.dumps({"actions": actions, "problems": problems}))
    return 0 if not problems else 2


def _prepare_arch_httpd():
    """Enable the modules and vhost include needed by Arch's stock httpd.conf."""
    if not is_arch():
        return
    main_conf = "/etc/httpd/conf/httpd.conf"
    with open(main_conf, encoding="utf-8") as f:
        content = f.read()
    additions = []
    for module in ("proxy_module", "proxy_fcgi_module", "rewrite_module"):
        directive = f"LoadModule {module} modules/mod_{module.removesuffix('_module')}.so"
        if not re.search(rf"^\s*LoadModule\s+{re.escape(module)}\s", content, re.M):
            additions.append(directive)
    include = "IncludeOptional conf/extra/localstack_*.conf"
    if include not in content:
        additions.append(include)
    if additions:
        atomic_write(main_conf, content.rstrip() + "\n\n# LocalStack managed settings\n" + "\n".join(additions) + "\n")


def cmd_vhost_write(args):
    project = check_project(args.name)
    hostname = check_hostname(args.hostname)
    docroot = check_docroot(args.docroot)

    template = VHOST_MODPHP_TEMPLATE if args.mod_php else VHOST_TEMPLATE
    content = template.format(
        project=project,
        servername=hostname,
        documentroot=docroot,
        socket=args.fpm_socket,
    )

    os.makedirs(VHOSTS_DIR, exist_ok=True)
    _prepare_arch_httpd()
    path = config_path(project)
    backup = None
    if os.path.exists(path):
        backup = path + ".bak"
        shutil.copy2(path, backup)

    atomic_write(path, content)

    # A broken vhost stops Apache from reloading at all, taking every other
    # site down with it -- so validate and roll back if we broke something.
    test = subprocess.run(["httpd", "-t"], capture_output=True, text=True)
    if test.returncode != 0:
        if backup:
            os.replace(backup, path)
        else:
            os.unlink(path)
        fail(f"Generated config is invalid, rolled back:\n{test.stderr.strip()}")
    if backup and os.path.exists(backup):
        os.unlink(backup)

    print(f"Wrote {path}")
    return 0


def cmd_vhost_delete(args):
    project = check_project(args.name)
    path = config_path(project)
    if not os.path.exists(path):
        fail(f"No virtual host config at {path}")
    os.unlink(path)
    print(f"Removed {path}")
    return 0


def _rewrite_hosts(transform):
    with open(HOSTS_FILE) as f:
        lines = f.readlines()
    new_lines = transform(lines)
    if new_lines is None:
        return False
    atomic_write(HOSTS_FILE, "".join(new_lines), mode=0o644)
    return True


def cmd_hosts_add(args):
    hostname = check_hostname(args.hostname)

    def transform(lines):
        for line in lines:
            stripped = line.split("#", 1)[0].split()
            if len(stripped) >= 2 and hostname in stripped[1:]:
                return None  # already mapped
        if lines and not lines[-1].endswith("\n"):
            lines.append("\n")
        lines.append(f"127.0.0.1 {hostname}  {HOSTS_MARKER}\n")
        return lines

    changed = _rewrite_hosts(transform)
    print(f"{'Added' if changed else 'Already present:'} {hostname}")
    return 0


def cmd_hosts_remove(args):
    hostname = check_hostname(args.hostname)

    def transform(lines):
        out = []
        removed = False
        for line in lines:
            fields = line.split("#", 1)[0].split()
            # Only drop lines LocalStack owns: exactly this hostname mapped to
            # loopback. Never touch a line the user maintains by hand.
            if (
                HOSTS_MARKER in line
                and len(fields) == 2
                and fields[0] in ("127.0.0.1", "::1")
                and fields[1] == hostname
            ):
                removed = True
                continue
            out.append(line)
        return out if removed else None

    changed = _rewrite_hosts(transform)
    print(f"{'Removed' if changed else 'Not managed by LocalStack:'} {hostname}")
    return 0


def cmd_service(args):
    if args.unit not in ALLOWED_UNITS:
        fail(f"Refusing to control unit {args.unit!r}")
    if args.action not in ALLOWED_ACTIONS:
        fail(f"Refusing action {args.action!r}")
    r = subprocess.run(
        ["systemctl", args.action, args.unit], capture_output=True, text=True
    )
    if r.returncode != 0:
        fail(r.stderr.strip() or f"systemctl {args.action} {args.unit} failed")
    print(f"{args.unit}: {args.action} ok")
    return 0


def _enable_arch_php_extensions():
    """Load installed split PHP modules; Arch packages do not enable them."""
    if not is_arch() or not shutil.which("php"):
        return
    result = subprocess.run(
        ["php", "-r", "echo ini_get('extension_dir');"], capture_output=True, text=True
    )
    extension_dir = result.stdout.strip()
    if result.returncode != 0 or not os.path.isdir(extension_dir):
        return

    modules = {"gd", "mysqli", "pdo_mysql", "pdo_sqlite", "sqlite3"}
    loaded = subprocess.run(["php", "-m"], capture_output=True, text=True)
    loaded_names = {line.strip().lower() for line in loaded.stdout.splitlines()}
    lines = [f"extension={module}.so" for module in sorted(modules)
             if module not in loaded_names and os.path.isfile(os.path.join(extension_dir, f"{module}.so"))]
    conf_dir = "/etc/php/conf.d"
    conf_file = os.path.join(conf_dir, "localstack.ini")
    if lines:
        os.makedirs(conf_dir, exist_ok=True)
        atomic_write(conf_file, "# PHP modules enabled by LocalStack\n" + "\n".join(lines) + "\n")


def cmd_install_packages(args):
    for pkg in args.packages:
        if not PACKAGE_RE.match(pkg):
            fail(f"Invalid package name: {pkg!r}")
    command = (["pacman", "-S", "--needed", "--noconfirm"] if is_arch()
               else ["dnf", "install", "-y"])
    r = subprocess.run(command + list(args.packages), capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.returncode != 0:
        fail(r.stderr.strip() or f"{command[0]} package installation failed")
    _enable_arch_php_extensions()
    return 0


def cmd_httpd_test(args):
    r = subprocess.run(["httpd", "-t"], capture_output=True, text=True)
    output = (r.stderr or r.stdout).strip()
    print(output)
    return r.returncode


def cmd_mysql(args):
    """Run SQL read from stdin as the MySQL superuser."""
    sql = sys.stdin.read()
    r = subprocess.run(["mysql"], input=sql, capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.returncode != 0:
        fail(r.stderr.strip() or "mysql failed")
    return 0


def cmd_read_log(args):
    """Return the tail of an Apache log (root-only readable)."""
    hostname = check_hostname(args.hostname)
    path = os.path.join(log_dir(), f"{hostname}_{args.kind}.log")
    if not os.path.exists(path):
        fail(f"No such log: {path}")
    r = subprocess.run(["tail", "-n", str(args.lines), path], capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    return r.returncode


def build_parser():
    p = argparse.ArgumentParser(description="LocalStack privileged helper")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("prepare-docroot")
    s.add_argument("--path", required=True)
    s.add_argument("--owner", help="username whose home bounds the chmod walk")
    s.add_argument("--app-root", help="application root above the docroot, e.g. <app> for <app>/public")
    s.add_argument("--rw", action="append", help="subdir needing write access, relative to --app-root (or docroot)")
    s.set_defaults(func=cmd_prepare_docroot)

    s = sub.add_parser("vhost-write")
    s.add_argument("--name", required=True)
    s.add_argument("--hostname", required=True)
    s.add_argument("--docroot", required=True)
    s.add_argument("--fpm-socket", default="/run/php-fpm/www.sock")
    s.add_argument("--mod-php", action="store_true")
    s.set_defaults(func=cmd_vhost_write)

    s = sub.add_parser("vhost-delete")
    s.add_argument("--name", required=True)
    s.set_defaults(func=cmd_vhost_delete)

    s = sub.add_parser("hosts-add")
    s.add_argument("--hostname", required=True)
    s.set_defaults(func=cmd_hosts_add)

    s = sub.add_parser("hosts-remove")
    s.add_argument("--hostname", required=True)
    s.set_defaults(func=cmd_hosts_remove)

    s = sub.add_parser("service")
    s.add_argument("--action", required=True)
    s.add_argument("--unit", required=True)
    s.set_defaults(func=cmd_service)

    s = sub.add_parser("install-packages")
    s.add_argument("packages", nargs="+")
    s.set_defaults(func=cmd_install_packages)

    s = sub.add_parser("httpd-test")
    s.set_defaults(func=cmd_httpd_test)

    s = sub.add_parser("mysql")
    s.set_defaults(func=cmd_mysql)

    s = sub.add_parser("read-log")
    s.add_argument("--hostname", required=True)
    s.add_argument("--kind", choices=["error", "access"], default="error")
    s.add_argument("--lines", type=int, default=50)
    s.set_defaults(func=cmd_read_log)

    return p


def main():
    if os.geteuid() != 0:
        fail("localstack helper must run as root (invoke it via privileged.py)")
    args = build_parser().parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
