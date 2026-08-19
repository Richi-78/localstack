"""
Package installer module - handles installing packages via dnf.
"""

from typing import Optional

from src import privileged
from src.detector import SystemDetector, PackageStatus
from src.privileged import PrivilegeError


class PackageInstaller:
    """Handles package installation via dnf."""

    @staticmethod
    def install_packages(packages: list[str], dry_run: bool = False) -> tuple[bool, str]:
        """
        Install RPM packages using dnf.
        PHP extensions are skipped — they are bundled in php-common on Fedora.
        Returns (success, message).
        """
        if not packages:
            return True, "No packages to install."

        # Filter to only RPM-based packages (skip PHP extensions)
        rpm_names = []
        skipped = []
        for pkg in packages:
            if pkg in SystemDetector.PACKAGES:
                info = SystemDetector.PACKAGES[pkg]
                if info.get("_type") == "rpm" and info.get("rpm"):
                    rpm_names.append(info["rpm"])
                else:
                    # PHP extension — cannot be installed separately
                    skipped.append(pkg)
            else:
                rpm_names.append(pkg)

        if skipped:
            print(f"Skipping (bundled extensions): {', '.join(skipped)}")

        if not rpm_names:
            return True, "No RPM packages to install (PHP extensions are bundled)."

        if dry_run:
            return True, f"Would install: {', '.join(rpm_names)}"

        # dnf can take a while on a cold metadata cache.
        try:
            ok, out, err = privileged.run(
                ["install-packages"] + rpm_names, timeout=1800
            )
        except PrivilegeError as exc:
            return False, str(exc)

        if ok:
            return True, f"Successfully installed: {', '.join(rpm_names)}"
        return False, f"Installation failed:\n{err or out}"

    @classmethod
    def install_missing(cls, results: dict, packages: list[str] = None) -> tuple[bool, list[str]]:
        """Install only missing RPM packages from the given list."""
        if packages is None:
            packages = list(results.keys())

        missing = []
        for pkg in packages:
            if pkg in results and results[pkg].status == PackageStatus.NOT_INSTALLED:
                missing.append(pkg)

        if not missing:
            return True, []

        success, msg = cls.install_packages(missing)
        return success, missing

    @classmethod
    def create_project_packages(cls, use_mysql: bool = False) -> tuple[bool, list[str]]:
        """Ensure all RPM packages needed for a project are installed."""
        required = SystemDetector.get_required_for_project(use_mysql)

        results = SystemDetector.check_all()
        return cls.install_missing(results, required)
