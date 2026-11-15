"""
Virtual Host Manager - creates and manages Apache virtual host configurations.

Nothing here writes to /etc directly. Every privileged step is delegated to
src/helper.py through src/privileged.py, so the GUI never needs to be root.
"""

import os
import re
from pathlib import Path
from typing import Optional

from src import privileged
from src.privileged import PrivilegeError
from src.platform_info import apache_config_dir, php_fpm_socket

# Subdirectories a PHP app commonly needs to write to. Used to pick the right
# SELinux label; missing ones are simply skipped.
COMMON_WRITABLE_DIRS = [
    "uploads", "storage", "cache", "tmp", "logs", "var",
    "database", "backups", "public/uploads",
]

# Docroot names that mean "this is <app>/public, the app itself is one level up".
PUBLIC_DIR_NAMES = {"public", "public_html", "web", "htdocs", "www", "dist"}

# php_value / php_flag are mod_php directives. Under PHP-FPM -- the Fedora
# default -- Apache does not know them, and an unknown directive in .htaccess
# is a hard 500. Detecting this early saves a genuinely baffling debug session.
PHP_DIRECTIVE_RE = re.compile(r"^\s*php_(value|flag|admin_value|admin_flag)\s", re.I)
IFMODULE_OPEN_RE = re.compile(r"^\s*<IfModule\s+.*mod_php", re.I)
IFMODULE_CLOSE_RE = re.compile(r"^\s*</IfModule>", re.I)


PHP_FPM_SOCKET = php_fpm_socket()


class VHostManager:
    """Manages Apache virtual host configurations."""

    VHOSTS_DIR = apache_config_dir()
    CONFIG_PREFIX = "localstack_"

    # ---------------------------------------------------------------- naming

    @classmethod
    def normalize_hostname(cls, hostname: str) -> str:
        """Normalise to a clean `<name>.local` hostname."""
        hostname = hostname.strip().lower().rstrip(".")
        hostname = hostname.replace(" ", "-")
        hostname = "".join(c for c in hostname if c.isalnum() or c in "-.")
        while hostname.endswith(".local.local"):
            hostname = hostname[:-6]
        if not hostname.endswith(".local"):
            hostname = f"{hostname}.local"
        return hostname

    @classmethod
    def get_available_hostname(cls, project_name: str, used_names: set = None) -> str:
        """Generate a unique hostname for a project."""
        hostname = cls.normalize_hostname(project_name)
        if used_names and hostname in used_names:
            base = hostname[: -len(".local")]
            num = 2
            while f"{base}-{num}.local" in used_names:
                num += 1
            hostname = f"{base}-{num}.local"
        return hostname

    @classmethod
    def config_path(cls, project_name: str) -> str:
        return os.path.join(
            cls.VHOSTS_DIR, f"{cls.CONFIG_PREFIX}{project_name.replace(' ', '-')}.conf"
        )

    # ------------------------------------------------------------- inspection

    @classmethod
    def get_existing_hosts(cls) -> list[dict]:
        """Read the vhosts LocalStack manages straight off disk."""
        hosts = []
        for conf_file in sorted(Path(cls.VHOSTS_DIR).glob(f"{cls.CONFIG_PREFIX}*.conf")):
            try:
                content = conf_file.read_text()
            except OSError:
                continue

            servername = ""
            documentroot = ""
            for line in content.splitlines():
                line = line.strip()
                if line.startswith("ServerName "):
                    servername = line.split(None, 1)[1].strip()
                elif line.startswith("DocumentRoot "):
                    value = line.split(None, 1)[1].strip()
                    documentroot = value.strip('"').rstrip("/")

            hosts.append({
                "config_file": str(conf_file),
                "servername": servername,
                "documentroot": documentroot,
                "config_name": conf_file.stem,
            })
        return hosts

    @classmethod
    def check_htaccess_compat(cls, document_root: str) -> list[str]:
        """Find .htaccess directives that will 500 under PHP-FPM.

        Returns a list of human-readable warnings, empty when the tree is fine.
        """
        warnings = []
        root = Path(document_root)
        if not root.is_dir():
            return warnings

        candidates = [root / ".htaccess"]
        candidates += list(root.rglob(".htaccess"))

        for htaccess in dict.fromkeys(candidates):
            if not htaccess.is_file():
                continue
            try:
                lines = htaccess.read_text(errors="replace").splitlines()
            except OSError:
                continue

            guarded = 0
            for num, line in enumerate(lines, 1):
                if IFMODULE_OPEN_RE.match(line):
                    guarded += 1
                    continue
                if IFMODULE_CLOSE_RE.match(line) and guarded:
                    guarded -= 1
                    continue
                if guarded == 0 and PHP_DIRECTIVE_RE.match(line):
                    warnings.append(
                        f"{htaccess}:{num}: '{line.strip().split()[0]}' only works "
                        f"under mod_php and causes HTTP 500 with PHP-FPM. Wrap it in "
                        f"<IfModule mod_php.c> and move the setting to a .user.ini."
                    )
        return warnings

    # ---------------------------------------------------------------- create

    @classmethod
    def create_vhost(
        cls,
        project_name: str,
        document_root: str,
        hostname: Optional[str] = None,
        use_mod_php: bool = False,
    ) -> tuple[bool, str]:
        """Create a virtual host configuration. Returns (success, message)."""
        hostname = cls.normalize_hostname(hostname or project_name)
        document_root = os.path.realpath(document_root).rstrip("/")

        if not os.path.isdir(document_root):
            return False, f"Document root does not exist: {document_root}"

        notes = []

        # Fedora blocks Apache under /home twice over: home dirs are mode 700
        # (DAC) and everything there is user_home_t (SELinux). Fix both, and
        # report honestly if we could not.
        access_ok, access_note = cls.prepare_document_root(document_root)
        if access_note:
            notes.append(access_note)

        try:
            ok, _out, err = privileged.run([
                "vhost-write",
                "--name", project_name,
                "--hostname", hostname,
                "--docroot", document_root,
                "--fpm-socket", PHP_FPM_SOCKET,
            ] + (["--mod-php"] if use_mod_php else []))
        except PrivilegeError as exc:
            return False, str(exc)

        if not ok:
            return False, f"Failed to write virtual host: {err}"

        try:
            hosts_ok, _out, hosts_err = privileged.run(["hosts-add", "--hostname", hostname])
            if not hosts_ok:
                notes.append(f"/etc/hosts not updated ({hosts_err}) -- add '127.0.0.1 {hostname}' manually")
        except PrivilegeError as exc:
            notes.append(f"/etc/hosts not updated: {exc}")

        for warning in cls.check_htaccess_compat(document_root):
            notes.append(warning)

        message = f"Virtual host '{hostname}' created for {document_root}"
        if notes:
            message += "\n  - " + "\n  - ".join(notes)
        return True, message

    @classmethod
    def prepare_document_root(cls, document_root: str) -> tuple[bool, str]:
        """Grant Apache traversal + SELinux access to a project directory."""
        args = ["prepare-docroot", "--path", document_root, "--owner", cls._owner()]

        # For an <app>/public layout, PHP still reads code, .env and writable
        # dirs from <app>, which is outside the docroot. Prepare the app root
        # so those do not silently fail with a permission error at runtime.
        app_root = cls.detect_app_root(document_root)
        base = document_root
        if app_root:
            args += ["--app-root", app_root]
            base = app_root

        for sub in COMMON_WRITABLE_DIRS:
            if os.path.isdir(os.path.join(base, sub)):
                args += ["--rw", sub]

        try:
            ok, payload, err = privileged.run_json(args)
        except PrivilegeError as exc:
            return False, f"could not prepare Apache access: {exc}"

        problems = payload.get("problems") or ([err] if err else [])
        if problems:
            return False, "Apache access only partly prepared: " + "; ".join(problems)
        return True, ""

    @staticmethod
    def detect_app_root(document_root: str) -> Optional[str]:
        """Return the app root when the docroot is an <app>/public style dir."""
        document_root = document_root.rstrip("/")
        if os.path.basename(document_root).lower() not in PUBLIC_DIR_NAMES:
            return None
        parent = os.path.dirname(document_root)
        # Refuse to walk up into a home directory or anything shallower.
        if not parent or parent in ("/", os.path.expanduser("~")):
            return None
        return parent

    @staticmethod
    def _owner() -> str:
        """The desktop user, even when we were launched through sudo."""
        return os.environ.get("SUDO_USER") or os.environ.get("USER") or ""

    # ---------------------------------------------------------------- delete

    @classmethod
    def delete_vhost(cls, project_name: str, hostname: Optional[str] = None) -> tuple[bool, str]:
        """Delete a virtual host config and its /etc/hosts entry.

        `hostname` must be the project's stored hostname -- deriving it from the
        project name breaks for custom or de-duplicated ('site-2.local') names.
        """
        try:
            ok, _out, err = privileged.run(["vhost-delete", "--name", project_name])
        except PrivilegeError as exc:
            return False, str(exc)

        if not ok:
            return False, err or f"No virtual host found for '{project_name}'"

        notes = []
        if hostname:
            try:
                hosts_ok, _out, hosts_err = privileged.run(
                    ["hosts-remove", "--hostname", cls.normalize_hostname(hostname)]
                )
                if not hosts_ok:
                    notes.append(f"/etc/hosts entry left in place ({hosts_err})")
            except PrivilegeError as exc:
                notes.append(f"/etc/hosts entry left in place: {exc}")

        message = f"Virtual host for '{project_name}' removed"
        if notes:
            message += " (" + "; ".join(notes) + ")"
        return True, message

    # -------------------------------------------------------------- services

    @classmethod
    def _service(cls, action: str, unit: str = "httpd") -> tuple[bool, str]:
        try:
            ok, out, err = privileged.run(["service", "--action", action, "--unit", unit])
        except PrivilegeError as exc:
            return False, str(exc)
        return ok, out if ok else (err or f"systemctl {action} {unit} failed")

    @classmethod
    def test_vhost_syntax(cls) -> tuple[bool, str]:
        try:
            ok, out, err = privileged.run(["httpd-test"])
        except PrivilegeError as exc:
            return False, str(exc)
        return ok, out or err or "Syntax OK"

    @classmethod
    def reload_httpd(cls) -> tuple[bool, str]:
        return cls._service("reload")

    @classmethod
    def start_httpd(cls) -> tuple[bool, str]:
        return cls._service("start")

    @classmethod
    def stop_httpd(cls) -> tuple[bool, str]:
        return cls._service("stop")

    @classmethod
    def enable_httpd(cls) -> tuple[bool, str]:
        return cls._service("enable")

    @classmethod
    def read_error_log(cls, hostname: str, lines: int = 50) -> tuple[bool, str]:
        """Apache logs are root-only; fetch them through the helper."""
        try:
            ok, out, err = privileged.run(
                ["read-log", "--hostname", cls.normalize_hostname(hostname),
                 "--kind", "error", "--lines", str(lines)]
            )
        except PrivilegeError as exc:
            return False, str(exc)
        return ok, out if ok else err

    # ------------------------------------------------------------ regenerate

    @classmethod
    def regenerate_all(cls) -> tuple[bool, str]:
        """Rewrite every project's vhost with the current template."""
        from src.project_manager import ProjectManager

        projects = ProjectManager.list_projects()
        if not projects:
            return True, "No projects to regenerate."

        updated, failures = 0, []
        for proj in projects:
            hostname = proj.get("hostname")
            doc_root = proj.get("document_root")
            if not hostname or not doc_root:
                continue
            ok, msg = cls.create_vhost(proj["name"], doc_root, hostname)
            if ok:
                updated += 1
            else:
                failures.append(f"{proj['name']}: {msg}")

        if failures:
            return False, f"Regenerated {updated}, failed:\n" + "\n".join(failures)

        reload_ok, reload_msg = cls.reload_httpd()
        suffix = "Apache reloaded." if reload_ok else f"Reload Apache manually ({reload_msg})."
        return True, f"Regenerated {updated} virtual host config(s). {suffix}"

    @classmethod
    def get_project_url(cls, project: dict | str) -> str:
        """URL for a project. Prefer passing the project dict so the stored
        hostname is used rather than re-derived from the name."""
        if isinstance(project, dict):
            hostname = project.get("hostname") or cls.normalize_hostname(project.get("name", ""))
        else:
            hostname = cls.normalize_hostname(project)
        return f"http://{hostname}"
