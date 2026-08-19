"""
Package detection module - checks if required packages are installed.

On Fedora, PHP extensions (curl, json, zip, gd, etc.) are bundled
into php-common and don't have separate RPM packages.  We detect
them via `php -m` instead of `rpm -q`.
"""

import subprocess
import shutil
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class PackageStatus(Enum):
    INSTALLED = "installed"
    NOT_INSTALLED = "not installed"
    PARTIAL = "partially installed"


@dataclass
class PackageInfo:
    name: str
    status: PackageStatus
    version: Optional[str] = None
    service_name: Optional[str] = None  # systemd service name


class SystemDetector:
    """Detects installed system packages for web development."""

    # RPM-based packages (checked via rpm -q)
    RPM_PACKAGES = {
        "apache": {
            "rpm": "httpd",
            "service": "httpd",
            "description": "Apache Web Server",
        },
        "php_cli": {
            "rpm": "php-cli",
            "service": None,
            "description": "PHP Command Line Interface",
        },
        "php_fpm": {
            "rpm": "php-fpm",
            "service": "php-fpm",
            "description": "PHP-FPM (FastCGI Process Manager)",
        },
        "mysql": {
            "rpm": "mysql-server",
            "service": "mysqld",  # Fedora uses mysqld, not mysql
            "description": "MySQL Database Server",
        },
        "sqlite": {
            "rpm": "sqlite",
            "service": None,
            "description": "SQLite (embedded, no service)",
        },
    }

    # PHP extensions — detected via `php -m` (bundled in php-common on Fedora)
    # Maps internal key -> PHP module name (case-insensitive match)
    PHP_EXTENSIONS = {
        "php_mysql": "mysqlnd",
        "php_pdo": "pdo",
        "php_gd": "gd",
        "php_curl": "curl",
        "php_xml": "xml",
        "php_mbstring": "mbstring",
        "php_json": "json",
        "php_zip": "zip",
    }

    # Full package list exposed to callers (RPM + PHP extensions)
    PACKAGES: dict[str, dict] = {}

    @classmethod
    def _build_packages(cls):
        """Merge RPM packages and PHP extensions into a single PACKAGES dict."""
        cls.PACKAGES = {}
        for key, info in cls.RPM_PACKAGES.items():
            cls.PACKAGES[key] = {**info, "_type": "rpm"}
        for key, php_module in cls.PHP_EXTENSIONS.items():
            cls.PACKAGES[key] = {
                "rpm": None,
                "service": None,
                "description": cls._ext_description(key),
                "_type": "php_ext",
                "php_module": php_module,
            }

    @staticmethod
    def _ext_description(key: str) -> str:
        """Human-readable description for a PHP extension."""
        descs = {
            "php_mysql": "PHP MySQL Driver",
            "php_pdo": "PHP PDO Extension",
            "php_gd": "PHP GD Extension (image handling)",
            "php_curl": "PHP cURL Extension",
            "php_xml": "PHP XML Extension",
            "php_mbstring": "PHP Mbstring Extension",
            "php_json": "PHP JSON Extension",
            "php_zip": "PHP ZIP Extension",
        }
        return descs.get(key, key)

    @classmethod
    def _get_php_modules(cls) -> set[str]:
        """Return the set of loaded PHP module names (lowercase)."""
        result = subprocess.run(
            ["php", "-m"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return set()
        return {m.strip().lower() for m in result.stdout.splitlines()}

    @classmethod
    def check_all(cls) -> dict[str, PackageInfo]:
        """Check status of all packages. Returns dict of name -> PackageInfo."""
        cls._build_packages()
        results = {}
        php_modules = cls._get_php_modules()

        for name, info in cls.PACKAGES.items():
            if info["_type"] == "rpm":
                results[name] = cls._check_rpm(name, info)
            else:
                results[name] = cls._check_php_ext(name, info, php_modules)
        return results

    @classmethod
    def _check_rpm(cls, pkg_name: str, info: dict) -> PackageInfo:
        """Check an RPM-based package."""
        rpm_name = info["rpm"]
        result = subprocess.run(
            ["rpm", "-q", rpm_name],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            version = result.stdout.strip().replace(f"{rpm_name}-", "")
            return PackageInfo(
                name=info["description"],
                status=PackageStatus.INSTALLED,
                version=version,
                service_name=info["service"],
            )

        return PackageInfo(
            name=info["description"],
            status=PackageStatus.NOT_INSTALLED,
            service_name=info["service"],
        )

    @classmethod
    def _check_php_ext(cls, pkg_name: str, info: dict, php_modules: set[str]) -> PackageInfo:
        """Check a PHP extension via `php -m`."""
        php_module = info["php_module"]
        if php_module in php_modules:
            # Get PHP version (just "8.5.9")
            ver_result = subprocess.run(
                ["php", "-r", "echo PHP_MAJOR_VERSION . '.' . PHP_MINOR_VERSION . '.' . PHP_RELEASE_VERSION;"],
                capture_output=True,
                text=True,
            )
            version = ver_result.stdout.strip() if ver_result.returncode == 0 else ""
            return PackageInfo(
                name=info["description"],
                status=PackageStatus.INSTALLED,
                version=version,
                service_name=None,
            )

        return PackageInfo(
            name=info["description"],
            status=PackageStatus.NOT_INSTALLED,
            service_name=None,
        )

    @classmethod
    def check_package(cls, pkg_name: str) -> PackageInfo:
        """Check if a specific package is installed."""
        cls._build_packages()
        if pkg_name not in cls.PACKAGES:
            return PackageInfo(
                name=pkg_name,
                status=PackageStatus.NOT_INSTALLED,
            )

        info = cls.PACKAGES[pkg_name]
        if info["_type"] == "rpm":
            return cls._check_rpm(pkg_name, info)
        else:
            php_modules = cls._get_php_modules()
            return cls._check_php_ext(pkg_name, info, php_modules)

    @classmethod
    def check_service(cls, service_name: str) -> tuple[bool, bool]:
        """
        Check if a systemd service exists and its status.
        Returns (exists, is_active).
        """
        result = subprocess.run(
            ["systemctl", "is-active", service_name],
            capture_output=True,
            text=True,
        )
        is_active = result.stdout.strip() == "active"

        # Check if service file exists
        result2 = subprocess.run(
            ["systemctl", "list-unit-files", f"{service_name}.service"],
            capture_output=True,
            text=True,
        )
        exists = f"{service_name}.service" in result2.stdout

        return exists, is_active

    @classmethod
    def check_ports(cls, ports: list[int]) -> dict[int, bool]:
        """Check if ports are in use. Returns {port: is_in_use}."""
        results = {}
        for port in ports:
            result = subprocess.run(
                ["ss", "-tlnp"],
                capture_output=True,
                text=True,
            )
            results[port] = f":{port}" in result.stdout
        return results

    @classmethod
    def get_required_for_project(cls, use_mysql: bool = False) -> list[str]:
        """Get list of required packages for a project type."""
        # Core packages (RPM-based)
        required = ["apache", "php_cli", "php_fpm"]

        if use_mysql:
            required.extend(["mysql", "php_mysql"])
        else:
            required.append("sqlite")

        return required

    @classmethod
    def print_status(cls, results: dict[str, PackageInfo] = None):
        """Pretty-print package status."""
        if results is None:
            results = cls.check_all()

        print("\n" + "=" * 60)
        print("  LocalStack - System Package Status")
        print("=" * 60)

        for name, info in results.items():
            icon = "✓" if info.status == PackageStatus.INSTALLED else "✗"
            version_str = f" (v{info.version})" if info.version else ""
            print(f"  [{icon}] {name}{version_str}")

        print("=" * 60 + "\n")
