"""
Virtual Host Manager - creates and manages Apache virtual host configurations.

Nothing here writes to /etc directly. Every privileged step is delegated to
src/helper.py through src/privileged.py, so the GUI never needs to be root.
"""

import json
import os
import re
from pathlib import Path
from typing import Optional

from src import privileged
from src.privileged import PrivilegeError
from src.platform_info import apache_config_dir

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
    def _project_spec(
        cls,
        project_name: str,
        document_root: str,
        hostname: Optional[str] = None,
        use_mod_php: bool = False,
        prepare: bool = True,
        previous_hostnames: Optional[list] = None,
        mysql: Optional[dict] = None,
    ) -> dict:
        """Describe one project change for the helper's apply-projects call."""
        document_root = os.path.realpath(document_root).rstrip("/")
        app_root = cls.detect_app_root(document_root)
        base = app_root or document_root
        spec = {
            "name": project_name,
            "hostname": cls.normalize_hostname(hostname or project_name),
            "docroot": document_root,
            "owner": cls._owner(),
            "prepare": prepare,
            "mod_php": use_mod_php,
            "rw": [
                sub for sub in COMMON_WRITABLE_DIRS
                if os.path.isdir(os.path.join(base, sub))
            ],
            "previous_hostnames": [
                cls.normalize_hostname(h) for h in (previous_hostnames or []) if h
            ],
        }
        if app_root:
            spec["app_root"] = app_root
        if mysql:
            spec["mysql"] = mysql
        return spec

    @classmethod
    def apply_projects(
        cls,
        projects: Optional[list] = None,
        remove: Optional[list] = None,
        reload: bool = False,
    ) -> tuple[bool, dict, str]:
        """Run every privileged change for a project operation in one go.

        One pkexec prompt covers permissions, the vhost, /etc/hosts, MySQL and
        the Apache reload. Returns (ok, payload, error).
        """
        spec = {
            "projects": projects or [],
            "remove": remove or [],
            "reload": reload,
        }
        try:
            ok, payload, err = privileged.run_json(
                ["apply-projects"], stdin_data=json.dumps(spec)
            )
        except PrivilegeError as exc:
            return False, {}, str(exc)
        if not payload:
            return False, {}, err or "The privileged helper returned no result."
        return ok, payload, err

    @classmethod
    def create_vhost(
        cls,
        project_name: str,
        document_root: str,
        hostname: Optional[str] = None,
        use_mod_php: bool = False,
        mysql: Optional[dict] = None,
        reload: bool = True,
        previous_hostnames: Optional[list] = None,
    ) -> tuple[bool, str]:
        """Create (or update) a virtual host. Returns (success, message)."""
        document_root = os.path.realpath(document_root).rstrip("/")
        if not os.path.isdir(document_root):
            return False, f"Document root does not exist: {document_root}"

        spec = cls._project_spec(
            project_name, document_root, hostname,
            use_mod_php=use_mod_php,
            previous_hostnames=previous_hostnames,
            mysql=mysql,
        )
        ok, payload, err = cls.apply_projects([spec], reload=reload)
        if not payload:
            return False, err

        entry = (payload.get("projects") or [{}])[0]
        notes = list(entry.get("problems") or [])
        vhost = entry.get("vhost")

        reload_state = payload.get("reload")
        if reload and isinstance(reload_state, dict) and not reload_state.get("ok"):
            notes.append(
                "Apache was not reloaded: "
                + (reload_state.get("message") or "unknown error")
            )

        if not vhost:
            detail = err or "; ".join(notes) or "the virtual host was not written"
            return False, f"Failed to write virtual host: {detail}"

        for warning in cls.check_htaccess_compat(document_root):
            notes.append(warning)

        message = f"Virtual host '{spec['hostname']}' created for {document_root}"
        if entry.get("database"):
            database = entry["database"]
            message += (
                f"\n  - Database '{database['name']}' and user "
                f"'{database['user']}' ready."
            )
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
    def delete_vhost(
        cls,
        project_name: str,
        hostname: Optional[str] = None,
        reload: bool = True,
        mysql: Optional[dict] = None,
    ) -> tuple[bool, str]:
        """Delete a virtual host config and its /etc/hosts entry.

        `hostname` must be the project's stored hostname -- deriving it from the
        project name breaks for custom or de-duplicated ('site-2.local') names.
        When `mysql` is given, the project's database and user are dropped in
        the same privileged batch. The removal runs in the same privileged
        batch as the Apache reload.
        """
        hostnames = [cls.normalize_hostname(hostname)] if hostname else []
        removal = {"name": project_name, "hostnames": hostnames}
        if mysql:
            removal["mysql"] = mysql
        ok, payload, err = cls.apply_projects(remove=[removal], reload=reload)
        if not payload:
            return False, err

        entry = (payload.get("removed") or [{}])[0]
        notes = list(entry.get("problems") or [])
        reload_state = payload.get("reload")
        if reload and isinstance(reload_state, dict) and not reload_state.get("ok"):
            notes.append(
                "Apache was not reloaded: "
                + (reload_state.get("message") or "unknown error")
            )

        if entry.get("problems"):
            return False, "; ".join(notes)

        message = f"Virtual host for '{project_name}' removed"
        database = entry.get("database")
        if database:
            message += (
                f"; database '{database['name']}' and user "
                f"'{database['user']}' dropped"
            )
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

        specs, skipped = [], []
        for proj in projects:
            hostname = proj.get("hostname")
            doc_root = proj.get("document_root")
            if not hostname or not doc_root or not os.path.isdir(doc_root):
                skipped.append(proj.get("name", "?"))
                continue
            specs.append(cls._project_spec(
                proj["name"], doc_root, hostname,
            ))

        if not specs:
            return False, "No project folder is available to regenerate."

        ok, payload, err = cls.apply_projects(specs, reload=True)
        if not payload:
            return False, err

        failures = []
        updated = 0
        for entry in payload.get("projects") or []:
            if entry.get("vhost"):
                updated += 1
            else:
                failures.append(
                    f"{entry.get('name')}: "
                    + ("; ".join(entry.get("problems") or []) or "not written")
                )

        notes = []
        if skipped:
            notes.append("Skipped missing folders: " + ", ".join(skipped))
        reload_state = payload.get("reload")
        if isinstance(reload_state, dict):
            if reload_state.get("ok"):
                notes.append("Apache reloaded.")
            else:
                notes.append(
                    "Reload Apache manually ("
                    + (reload_state.get("message") or "unknown error") + ")."
                )
        if err and not ok:
            notes.append(err)

        if failures:
            return False, (
                f"Regenerated {updated}, failed:\n" + "\n".join(failures)
                + ("\n" + "\n".join(notes) if notes else "")
            )
        return True, (
            f"Regenerated {updated} virtual host config(s)."
            + (" " + " ".join(notes) if notes else "")
        )

    @classmethod
    def get_project_url(cls, project: dict | str) -> str:
        """URL for a project. Prefer passing the project dict so the stored
        hostname is used rather than re-derived from the name."""
        if isinstance(project, dict):
            hostname = project.get("hostname") or cls.normalize_hostname(project.get("name", ""))
        else:
            hostname = cls.normalize_hostname(project)
        return f"http://{hostname}"
