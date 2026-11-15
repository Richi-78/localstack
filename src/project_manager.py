"""
Project Manager - handles project creation, metadata, and lifecycle.
"""

import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional


class ProjectManager:
    """Manages project metadata and creation."""

    # Project metadata is per-user state, not system state, so it lives in the
    # user's data dir. Keeping it out of /var/lib is what lets the GUI run
    # unprivileged -- and stops a sudo run from writing to root's home instead.
    PROJECTS_DIR = os.path.join(
        os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"),
        "localstack",
    )
    PROJECTS_FILE = os.path.join(PROJECTS_DIR, "projects.json")

    # Older versions stored projects here; read once, then never again.
    LEGACY_LOCATIONS = [
        "/var/lib/localstack/projects.json",
        "/root/.local/share/localstack/projects.json",
    ]

    # Default project template
    DEFAULT_INDEX_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{project_name}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
        }}
        .container {{ text-align: center; padding: 2rem; }}
        h1 {{ font-size: 2.5rem; margin-bottom: 1rem; }}
        .info {{ background: rgba(255,255,255,0.1); padding: 1.5rem; border-radius: 10px; margin-top: 1.5rem; }}
        .info p {{ margin: 0.5rem 0; }}
        a {{ color: #ffd700; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🚀 {project_name}</h1>
        <p>Your LocalStack project is running!</p>
        <div class="info">
            <p><strong>Document Root:</strong> {document_root}</p>
            <p><strong>URL:</strong> <a href="{url}">{url}</a></p>
            <p><strong>Database:</strong> {db_type}</p>
            <p><strong>PHP Version:</strong> <code>{php_info}</code></p>
        </div>
    </div>
</body>
</html>'''

    DEFAULT_PHP_TEMPLATE = '''<?php
/**
 * {project_name} - LocalStack Project
 * Created with LocalStack on Fedora
 */

echo "<h1>{project_name}</h1>";
echo "<p>PHP is working!</p>";
echo "<pre>";
echo "PHP Version: " . phpversion() . "\\n";
echo "Server: " . $_SERVER['SERVER_SOFTWARE'] . "\\n";
echo "Document Root: " . $_SERVER['DOCUMENT_ROOT'] . "\\n";
echo "Server Time: " . date('Y-m-d H:i:s') . "\\n";
echo "</pre>";
'''

    DEFAULT_DB_TEST_TEMPLATE = '''<?php
/**
 * Database connection test
 */

$host = '127.0.0.1';
$dbname = '{db_name}';
$username = '{db_user}';
$password = '{db_pass}';

try {{
    $pdo = new PDO("mysql:host=$host;dbname=$dbname", $username, $password);
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    echo "<h2>✅ MySQL Connection Successful!</h2>";
    echo "<p>Connected to database: $dbname</p>";
}} catch (PDOException $e) {{
    echo "<h2>❌ Connection Failed</h2>";
    echo "<p>" . $e->getMessage() . "</p>";
}}
'''

    DEFAULT_SQLITE_TEST_TEMPLATE = '''<?php
/**
 * SQLite connection test
 */

$dbPath = __DIR__ . '/database.sqlite';

try {{
    $pdo = new PDO("sqlite:$dbPath");
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    echo "<h2>✅ SQLite Connection Successful!</h2>";
    echo "<p>Database path: $dbPath</p>";
}} catch (PDOException $e) {{
    echo "<h2>❌ Connection Failed</h2>";
    echo "<p>" . $e->getMessage() . "</p>";
}}
'''

    @classmethod
    def _real_home(cls) -> str:
        """The desktop user's home, even if we were launched through sudo."""
        sudo_user = os.environ.get("SUDO_USER")
        if sudo_user and os.geteuid() == 0:
            import pwd
            try:
                return pwd.getpwnam(sudo_user).pw_dir
            except KeyError:
                pass
        return os.path.expanduser("~")

    @classmethod
    def ensure_dirs(cls):
        """Ensure the projects directory exists and migrate any legacy store."""
        # If we somehow got here as root, still write to the desktop user's
        # home rather than root's -- otherwise projects silently vanish when
        # the GUI is next started normally.
        if os.geteuid() == 0 and os.environ.get("SUDO_USER"):
            cls.PROJECTS_DIR = os.path.join(cls._real_home(), ".local/share/localstack")
            cls.PROJECTS_FILE = os.path.join(cls.PROJECTS_DIR, "projects.json")

        os.makedirs(cls.PROJECTS_DIR, mode=0o700, exist_ok=True)

        # An empty store counts as "not yet migrated" -- a previous sudo run
        # could have left a stub here while the real data went to /var/lib.
        try:
            with open(cls.PROJECTS_FILE) as f:
                if json.load(f):
                    return
        except (OSError, json.JSONDecodeError):
            pass

        for legacy in cls.LEGACY_LOCATIONS:
            try:
                with open(legacy) as f:
                    projects = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
            if projects:
                cls._save_projects(projects)
                return

        cls._save_projects({})

    @classmethod
    def _load_projects(cls) -> dict:
        """Load projects from JSON file."""
        cls.ensure_dirs()
        try:
            with open(cls.PROJECTS_FILE, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    @classmethod
    def _save_projects(cls, projects: dict):
        """Save projects atomically.

        Deliberately does not call ensure_dirs() -- ensure_dirs() calls this,
        and the two would recurse.
        """
        os.makedirs(cls.PROJECTS_DIR, mode=0o700, exist_ok=True)
        tmp = cls.PROJECTS_FILE + ".tmp"
        with open(tmp, 'w') as f:
            json.dump(projects, f, indent=2)
        # db_pass is stored here in the clear, so keep it owner-only.
        os.chmod(tmp, 0o600)
        os.replace(tmp, cls.PROJECTS_FILE)

    @classmethod
    def list_projects(cls) -> list[dict]:
        """List all registered projects."""
        projects = cls._load_projects()
        return list(projects.values())

    @classmethod
    def get_project(cls, name: str) -> Optional[dict]:
        """Get a project by name."""
        projects = cls._load_projects()
        return projects.get(name)

    @classmethod
    def create_project(
        cls,
        name: str,
        document_root: str,
        use_mysql: bool = False,
        db_name: Optional[str] = None,
        db_user: Optional[str] = None,
        db_pass: Optional[str] = None,
        hostname: Optional[str] = None,
        db_type: Optional[str] = None,
    ) -> tuple[bool, str, Optional[dict]]:
        """
        Create a new project.
        Returns (success, message, project_data).

        Args:
            name: Project name (used as identifier)
            document_root: Path to the web root directory
            use_mysql: Whether to use MySQL instead of SQLite
            db_name: Database name
            db_user: Database user
            db_pass: Database password
            hostname: Custom hostname (e.g. 'mysite.local'). Falls back to auto-generated.
        """
        cls.ensure_dirs()
        projects = cls._load_projects()

        # Validate name
        if not name.strip():
            return False, "Project name cannot be empty.", None

        if not name.replace("-", "").replace("_", "").replace(".", "").isalnum():
            return False, "Project name can only contain letters, numbers, hyphens, underscores, and dots.", None

        if name in projects:
            return False, f"Project '{name}' already exists.", None

        # Validate/prepare document root
        document_root = os.path.abspath(document_root)

        # Whether this is a brand new project decides if we scaffold. Adopting
        # an existing app must never drop template files into it -- that is how
        # a LocalStack index.html ends up shadowing a real front controller.
        is_new = not os.path.isdir(document_root) or not os.listdir(document_root)

        if not os.path.exists(document_root):
            try:
                os.makedirs(document_root, exist_ok=True)
            except Exception as e:
                return False, f"Cannot create document root: {e}", None

        # db_type is the explicit choice from the wizard (none/sqlite/mysql).
        # Older callers only pass use_mysql, so keep that behaviour as fallback.
        if db_type is None:
            db_type = "mysql" if use_mysql else "sqlite"
        if db_type not in {"none", "sqlite", "mysql"}:
            db_type = "sqlite"
        use_mysql = db_type == "mysql"

        # Set defaults
        if use_mysql:
            db_name = db_name or f"{name}_db"
            db_user = db_user or f"{name}_user"
            db_pass = db_pass or cls._generate_password()
        elif db_type == "sqlite":
            db_name = db_name or f"{name}.sqlite"
            db_user = None
            db_pass = None
        else:
            db_name = None
            db_user = None
            db_pass = None

        # Determine hostname
        if not hostname:
            hostname = f"{name.lower().replace(' ', '-')}.local"

        project_data = {
            "name": name,
            "document_root": document_root,
            "use_mysql": use_mysql,
            "db_type": db_type,
            "db_name": db_name,
            "db_user": db_user,
            "db_pass": db_pass,
            "created_at": datetime.now().isoformat(),
            "status": "created",  # created, running, stopped, error
            "hostname": hostname,
        }

        # Save project
        projects[name] = project_data
        cls._save_projects(projects)

        # Only scaffold into a directory we just created or found empty.
        if is_new:
            cls._create_default_files(project_data)
            return True, f"Project '{name}' created successfully!", project_data

        return (
            True,
            f"Project '{name}' adopted (existing files left untouched).",
            project_data,
        )

    @classmethod
    def update_project(
        cls,
        name: str,
        document_root: Optional[str] = None,
        hostname: Optional[str] = None,
        db_type: Optional[str] = None,
        db_name: Optional[str] = None,
        db_user: Optional[str] = None,
        db_pass: Optional[str] = None,
    ) -> tuple[bool, str, Optional[dict]]:
        """Update an existing project. The project name itself is immutable:
        it is the metadata key, the vhost filename and the MySQL identifier
        prefix all at once."""
        projects = cls._load_projects()
        project = projects.get(name)
        if project is None:
            return False, f"Project '{name}' not found.", None

        if document_root is not None:
            document_root = os.path.abspath(document_root)
            if not os.path.isdir(document_root):
                return False, f"Document root does not exist: {document_root}", None
            project["document_root"] = document_root

        if hostname:
            project["hostname"] = hostname

        if db_type is not None:
            if db_type not in {"none", "sqlite", "mysql"}:
                return False, f"Unknown database type: {db_type}", None
            project["db_type"] = db_type
            project["use_mysql"] = db_type == "mysql"
            if db_type == "mysql":
                project["db_name"] = db_name or f"{name}_db"
                project["db_user"] = db_user or f"{name}_user"
                project["db_pass"] = db_pass or project.get("db_pass") or cls._generate_password()
            elif db_type == "sqlite":
                project["db_name"] = db_name or f"{name}.sqlite"
                project["db_user"] = None
                project["db_pass"] = None
            else:
                project["db_name"] = None
                project["db_user"] = None
                project["db_pass"] = None

        project["updated_at"] = datetime.now().isoformat()
        projects[name] = project
        cls._save_projects(projects)
        return True, f"Project '{name}' updated.", project

    @classmethod
    def db_type_of(cls, project: dict) -> str:
        """Resolve the database kind, including projects from older versions."""
        db_type = project.get("db_type")
        if db_type in {"none", "sqlite", "mysql"}:
            return db_type
        if project.get("use_mysql"):
            return "mysql"
        return "sqlite" if project.get("db_name") else "none"

    @classmethod
    def generate_password(cls, length: int = 16) -> str:
        return cls._generate_password(length)

    @classmethod
    def delete_project(cls, name: str) -> tuple[bool, str]:
        """Delete a project (metadata only, doesn't delete files)."""
        projects = cls._load_projects()

        if name not in projects:
            return False, f"Project '{name}' not found."

        del projects[name]
        cls._save_projects(projects)

        return True, f"Project '{name}' removed from LocalStack (files preserved)."

    @classmethod
    def update_project_status(cls, name: str, status: str):
        """Update project status."""
        projects = cls._load_projects()
        if name in projects:
            projects[name]["status"] = status
            cls._save_projects(projects)

    @classmethod
    def _create_default_files(cls, project_data: dict):
        """Create default index.php and other files in the document root."""
        doc_root = project_data["document_root"]

        # Create index.html (welcome page)
        index_path = os.path.join(doc_root, "index.html")
        if not os.path.exists(index_path):
            with open(index_path, 'w') as f:
                f.write(cls.DEFAULT_INDEX_TEMPLATE.format(
                    project_name=project_data["name"],
                    document_root=project_data["document_root"],
                    url=f"http://{project_data['hostname']}",
                    db_type=(
                        "MySQL" if project_data["use_mysql"]
                        else ("SQLite" if project_data.get("db_type") == "sqlite" else "None")
                    ),
                    php_info="N/A (PHP not configured yet)",
                ))

        # Create info.php (PHP info page)
        info_path = os.path.join(doc_root, "info.php")
        if not os.path.exists(info_path):
            with open(info_path, 'w') as f:
                f.write(cls.DEFAULT_PHP_TEMPLATE.format(project_name=project_data["name"]))

        # Create database test file if using MySQL
        if project_data["use_mysql"]:
            db_test_path = os.path.join(doc_root, "db-test.php")
            if not os.path.exists(db_test_path):
                with open(db_test_path, 'w') as f:
                    f.write(cls.DEFAULT_DB_TEST_TEMPLATE.format(
                        db_name=project_data["db_name"],
                        db_user=project_data["db_user"],
                        db_pass=project_data["db_pass"],
                    ))

        # Create .htaccess for pretty URLs
        htaccess_path = os.path.join(doc_root, ".htaccess")
        if not os.path.exists(htaccess_path):
            with open(htaccess_path, 'w') as f:
                f.write("""# LocalStack .htaccess
# Enable mod_rewrite for pretty URLs
RewriteEngine On
RewriteBase /

# Redirect to index.php if file doesn't exist
RewriteCond %{REQUEST_FILENAME} !-f
RewriteCond %{REQUEST_FILENAME} !-d
RewriteRule . index.php [L]

# Security: deny access to hidden files
<FilesMatch "^\\.">
    Require all denied
</FilesMatch>
""")

    @classmethod
    def _generate_password(cls, length: int = 16) -> str:
        """Generate a random password."""
        import random
        import string
        chars = string.ascii_letters + string.digits + "!@#$%^&*"
        return ''.join(random.choice(chars) for _ in range(length))

    @classmethod
    def _xdg_open(cls, target: str) -> bool:
        """Open a path or URL in the user's desktop session.

        No sudo dance needed: LocalStack itself never runs as root, so we are
        already the desktop user with the right DISPLAY/WAYLAND_DISPLAY.
        """
        try:
            subprocess.run(["xdg-open", target], capture_output=True, timeout=5)
            return True
        except (OSError, subprocess.SubprocessError):
            return False

    @classmethod
    def open_project_folder(cls, name: str) -> bool:
        """Open project folder in file manager."""
        project = cls.get_project(name)
        if not project or not os.path.isdir(project["document_root"]):
            return False
        return cls._xdg_open(project["document_root"])

    @classmethod
    def open_in_browser(cls, name: str) -> bool:
        """Open project in system default browser."""
        project = cls.get_project(name)
        if not project:
            return False
        return cls._xdg_open(f"http://{project['hostname']}")
