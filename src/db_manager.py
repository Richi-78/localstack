"""
Database Manager - handles MySQL database and user creation.
"""

import os
import subprocess
from typing import Optional

from src import privileged
from src.privileged import PrivilegeError
from src.platform_info import mysql_service


def _run_mysql_sql(sql: str) -> tuple[int, str]:
    """Execute SQL as the MySQL superuser, via the privileged helper.

    Returns (returncode, stderr). SQL goes over stdin rather than argv so it
    never lands in the process table or a temp file.
    """
    try:
        ok, _out, err = privileged.run(["mysql"], stdin_data=sql)
    except PrivilegeError as exc:
        return 1, str(exc)
    return (0 if ok else 1), err


class DBManager:
    """Manages MySQL database and SQLite setup."""

    @classmethod
    def create_mysql_db(
        cls,
        db_name: str,
        db_user: str,
        db_pass: str,
        host: str = "127.0.0.1",
    ) -> tuple[bool, str]:
        """
        Create MySQL database and user.
        Returns (success, message).
        """
        if not cls._is_mysql_running():
            return False, "MySQL is not running. Start it first."

        sql = (
            f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
            f"CREATE USER IF NOT EXISTS '{db_user}'@'{host}' IDENTIFIED BY '{db_pass}';"
            f"GRANT ALL PRIVILEGES ON `{db_name}`.* TO '{db_user}'@'{host}';"
            "FLUSH PRIVILEGES;"
        )

        rc, err = _run_mysql_sql(sql)
        if rc == 0:
            return True, f"Database '{db_name}' and user '{db_user}' created."
        return False, f"MySQL error: {err}"

    @classmethod
    def create_sqlite_db(cls, db_path: str) -> tuple[bool, str]:
        """
        Create or verify SQLite database file.
        Returns (success, message).
        """
        db_dir = os.path.dirname(db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

        try:
            with open(db_path, 'a') as f:
                pass
            return True, f"SQLite database created at {db_path}"
        except Exception as e:
            return False, f"Failed to create SQLite database: {e}"

    @classmethod
    def delete_mysql_db(cls, db_name: str, db_user: str) -> tuple[bool, str]:
        """Delete MySQL database and user."""
        if not cls._is_mysql_running():
            return False, "MySQL is not running."

        sql = (
            f"DROP DATABASE IF EXISTS `{db_name}`;"
            f"DROP USER IF EXISTS '{db_user}'@'127.0.0.1';"
            "FLUSH PRIVILEGES;"
        )

        rc, err = _run_mysql_sql(sql)
        if rc == 0:
            return True, f"Database '{db_name}' and user '{db_user}' deleted."
        return False, f"MySQL error: {err}"

    @classmethod
    def _is_mysql_running(cls) -> bool:
        """Check if the MySQL-compatible service is active."""
        result = subprocess.run(
            ["systemctl", "is-active", mysql_service()],
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() == "active"

    @classmethod
    def start_mysql(cls) -> tuple[bool, str]:
        """Start MySQL-compatible service."""
        try:
            ok, out, err = privileged.run(["service", "--action", "start", "--unit", mysql_service()])
        except PrivilegeError as exc:
            return False, str(exc)
        return ok, "MySQL started" if ok else (err or "systemctl start mysqld failed")

    @classmethod
    def stop_mysql(cls) -> tuple[bool, str]:
        """Stop MySQL-compatible service."""
        try:
            ok, out, err = privileged.run(["service", "--action", "stop", "--unit", mysql_service()])
        except PrivilegeError as exc:
            return False, str(exc)
        return ok, "MySQL stopped" if ok else (err or "systemctl stop mysqld failed")

    @classmethod
    def enable_mysql(cls) -> tuple[bool, str]:
        """Enable MySQL-compatible service on boot."""
        try:
            ok, out, err = privileged.run(["service", "--action", "enable", "--unit", mysql_service()])
        except PrivilegeError as exc:
            return False, str(exc)
        return ok, "MySQL enabled on boot" if ok else (err or "systemctl enable mysqld failed")

    @classmethod
    def set_mysql_root_password(cls, password: str) -> tuple[bool, str]:
        """Set MySQL root password (for fresh install)."""
        if not cls._is_mysql_running():
            return False, "MySQL is not running."

        sql = f"ALTER USER 'root'@'localhost' IDENTIFIED BY '{password}';"

        # First try as the MySQL superuser via the helper.
        rc, err = _run_mysql_sql(sql)
        if rc == 0:
            return True, "MySQL root password set."

        # A fresh install may still accept a passwordless local root.
        result = subprocess.run(
            ["mysql", "-u", "root"],
            input=sql,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return True, "MySQL root password set."

        return False, f"Failed to set root password: {err or result.stderr.strip()}"

    @classmethod
    def get_mysql_status(cls) -> dict:
        """Get MySQL status information."""
        status = {
            "running": False,
            "version": "N/A",
            "databases": [],
        }

        result = subprocess.run(
            ["systemctl", "is-active", mysql_service()],
            capture_output=True,
            text=True,
        )
        status["running"] = result.stdout.strip() == "active"

        if status["running"]:
            result = subprocess.run(
                ["mysql", "--version"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                status["version"] = result.stdout.strip().split()[2]

            try:
                ok, out, _err = privileged.run(["mysql"], stdin_data="SHOW DATABASES;")
            except PrivilegeError:
                ok, out = False, ""
            if ok:
                status["databases"] = [
                    l for l in out.strip().split('\n') if l and l != "Database"
                ]

        return status
