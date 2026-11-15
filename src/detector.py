"""Detect web-stack packages on Fedora and Arch-family distributions."""

import subprocess
import shutil
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from src.platform_info import is_arch, mysql_service


class PackageStatus(Enum):
    INSTALLED = "installed"
    NOT_INSTALLED = "not installed"
    PARTIAL = "partially installed"


@dataclass
class PackageInfo:
    name: str
    status: PackageStatus
    version: Optional[str] = None
    service_name: Optional[str] = None


class SystemDetector:
    """Detect installed packages and services using the host's package format."""

    MYSQL_SERVICE = mysql_service()
    RPM_PACKAGES = {
        "apache": ("httpd", "httpd", "Apache Web Server"),
        "php_cli": ("php-cli", None, "PHP Command Line Interface"),
        "php_fpm": ("php-fpm", "php-fpm", "PHP-FPM (FastCGI Process Manager)"),
        "mysql": ("mysql-server", "mysqld", "MariaDB/MySQL Database Server"),
        "sqlite": ("sqlite", None, "SQLite (embedded, no service)"),
    }
    ARCH_PACKAGES = {
        "apache": ("apache", "httpd", "Apache Web Server"),
        "php_cli": ("php", None, "PHP Command Line Interface"),
        "php_fpm": ("php-fpm", "php-fpm", "PHP-FPM (FastCGI Process Manager)"),
        "mysql": ("mariadb", "mariadb", "MariaDB Database Server"),
        "sqlite": ("sqlite", None, "SQLite (embedded, no service)"),
    }
    PHP_EXTENSIONS = {
        "php_mysql": ("mysqli", None),
        "php_pdo": ("PDO", None),
        "php_gd": ("gd", "php-gd"),
        "php_curl": ("curl", None),
        "php_xml": ("xml", None),
        "php_mbstring": ("mbstring", None),
        "php_json": ("json", None),
        "php_zip": ("zip", None),
        "php_sqlite": ("pdo_sqlite", "php-sqlite"),
    }
    DESCRIPTIONS = {
        "php_mysql": "PHP MySQL Driver", "php_pdo": "PHP PDO Extension",
        "php_gd": "PHP GD Extension (image handling)", "php_curl": "PHP cURL Extension",
        "php_xml": "PHP XML Extension", "php_mbstring": "PHP Mbstring Extension",
        "php_json": "PHP JSON Extension", "php_zip": "PHP ZIP Extension",
        "php_sqlite": "PHP SQLite Extension",
    }
    PACKAGES: dict[str, dict] = {}

    @classmethod
    def _build_packages(cls):
        cls.PACKAGES = {}
        packages = cls.ARCH_PACKAGES if is_arch() else cls.RPM_PACKAGES
        for key, (package, service, desc) in packages.items():
            if key == "mysql":
                service = mysql_service()
            cls.PACKAGES[key] = {"package": package, "service": service, "description": desc, "_type": "system"}
        for key, (module, arch_package) in cls.PHP_EXTENSIONS.items():
            cls.PACKAGES[key] = {"package": arch_package if is_arch() else None, "service": None,
                                 "description": cls.DESCRIPTIONS[key], "_type": "php_ext", "php_module": module}

    @classmethod
    def _get_php_modules(cls) -> set[str]:
        try:
            result = subprocess.run(["php", "-m"], capture_output=True, text=True)
        except FileNotFoundError:
            return set()
        return {m.strip().lower() for m in result.stdout.splitlines()} if result.returncode == 0 else set()

    @classmethod
    def _query_package(cls, package: str) -> tuple[bool, str]:
        command = ["pacman", "-Q", package] if is_arch() else ["rpm", "-q", package]
        if not shutil.which(command[0]):
            return False, ""
        result = subprocess.run(command, capture_output=True, text=True)
        return result.returncode == 0, result.stdout.strip().split()[-1] if result.returncode == 0 and result.stdout.strip() else ""

    @classmethod
    def check_all(cls) -> dict[str, PackageInfo]:
        cls._build_packages()
        modules = cls._get_php_modules()
        results = {}
        for key, info in cls.PACKAGES.items():
            if info["_type"] == "php_ext":
                installed = info["php_module"].lower() in modules
                version = ""
            else:
                installed, version = cls._query_package(info["package"])
            results[key] = PackageInfo(info["description"], PackageStatus.INSTALLED if installed else PackageStatus.NOT_INSTALLED,
                                       version or None, info["service"])
        return results

    @classmethod
    def check_package(cls, pkg_name: str) -> PackageInfo:
        return cls.check_all().get(pkg_name, PackageInfo(pkg_name, PackageStatus.NOT_INSTALLED))

    @classmethod
    def check_service(cls, service_name: str) -> tuple[bool, bool]:
        active = subprocess.run(["systemctl", "is-active", service_name], capture_output=True, text=True).stdout.strip() == "active"
        units = subprocess.run(["systemctl", "list-unit-files", f"{service_name}.service"], capture_output=True, text=True).stdout
        return f"{service_name}.service" in units, active

    @classmethod
    def check_ports(cls, ports: list[int]) -> dict[int, bool]:
        result = subprocess.run(["ss", "-tlnp"], capture_output=True, text=True)
        return {port: f":{port}" in result.stdout for port in ports}

    @classmethod
    def get_required_for_project(cls, use_mysql: bool = False) -> list[str]:
        required = ["apache", "php_cli", "php_fpm"]
        required.extend(["mysql", "php_mysql"] if use_mysql else ["sqlite", "php_sqlite"])
        return required

    @classmethod
    def print_status(cls, results: dict[str, PackageInfo] = None):
        results = results or cls.check_all()
        print("\n" + "=" * 60 + "\n  LocalStack - System Package Status\n" + "=" * 60)
        for name, info in results.items():
            icon = "✓" if info.status == PackageStatus.INSTALLED else "✗"
            print(f"  [{icon}] {name}" + (f" (v{info.version})" if info.version else ""))
        print("=" * 60 + "\n")
