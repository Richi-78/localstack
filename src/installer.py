"""Install packages through the host distribution's package manager."""

from src.detector import SystemDetector, PackageStatus
from src.privileged import PrivilegeError
from src import privileged


class PackageInstaller:
    """Handles package installation via the privileged helper."""

    @staticmethod
    def install_packages(packages: list[str], dry_run: bool = False) -> tuple[bool, str]:
        if not packages:
            return True, "No packages to install."
        SystemDetector._build_packages()
        names = []
        for package in packages:
            if package in SystemDetector.PACKAGES:
                actual = SystemDetector.PACKAGES[package].get("package")
                if actual:
                    names.append(actual)
            else:
                names.append(package)
        names = list(dict.fromkeys(names))
        if not names:
            return True, "No separate packages to install."
        if dry_run:
            return True, f"Would install: {', '.join(names)}"
        try:
            ok, out, err = privileged.run(["install-packages"] + names, timeout=1800)
        except PrivilegeError as exc:
            return False, str(exc)
        return (True, f"Successfully installed: {', '.join(names)}") if ok else (False, f"Installation failed:\n{err or out}")

    @classmethod
    def install_missing(cls, results: dict, packages: list[str] = None) -> tuple[bool, list[str]]:
        packages = list(results.keys()) if packages is None else packages
        missing = [p for p in packages if p in results and results[p].status == PackageStatus.NOT_INSTALLED]
        if not missing:
            return True, []
        success, _message = cls.install_packages(missing)
        return success, missing

    @classmethod
    def create_project_packages(cls, use_mysql: bool = False) -> tuple[bool, list[str]]:
        required = SystemDetector.get_required_for_project(use_mysql)
        return cls.install_missing(SystemDetector.check_all(), required)
