"""Small distro-specific settings for Fedora and Arch-family systems."""

import os


def distro_id() -> str:
    try:
        with open("/etc/os-release", encoding="utf-8") as f:
            fields = dict(line.rstrip().split("=", 1) for line in f if "=" in line)
        return fields.get("ID", "").strip('"').lower()
    except OSError:
        return ""


def is_arch() -> bool:
    return distro_id() in {"arch", "cachyos", "manjaro", "endeavouros"}


def package_manager() -> str:
    return "pacman" if is_arch() else "dnf"


def mysql_service() -> str:
    return "mariadb" if is_arch() else "mysqld"


def apache_config_dir() -> str:
    return "/etc/httpd/conf/extra" if is_arch() else "/etc/httpd/conf.d"


def apache_config_file(name: str) -> str:
    return os.path.join(apache_config_dir(), f"localstack_{name}.conf")


def log_dir() -> str:
    return "/var/log/httpd" if is_arch() else "/var/log/httpd"


def php_fpm_socket() -> str:
    candidates = (["/run/php-fpm/php-fpm.sock", "/run/php-fpm/www.sock"] if is_arch()
                  else ["/run/php-fpm/www.sock", "/var/run/php-fpm/www.sock"])
    return next((p for p in candidates if os.path.exists(p)), candidates[0])
