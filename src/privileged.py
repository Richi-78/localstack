"""
Privilege escalation for LocalStack.

The GUI runs as a normal user. Whenever it needs to touch something only root
can change -- Apache config, /etc/hosts, SELinux labels, systemd units, dnf --
it goes through here, which re-invokes src/helper.py as root via pkexec.

pkexec is preferred over sudo because it talks to the desktop's polkit agent
and can prompt graphically, so LocalStack works when launched from a desktop
icon with no terminal attached.
"""

import json
import os
import shutil
import subprocess
import sys

HELPER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "helper.py")

# pkexec's own exit codes, distinct from anything the helper returns.
PKEXEC_DISMISSED = 126
PKEXEC_NOT_AUTHORISED = 127


class PrivilegeError(Exception):
    """Raised when the privileged call could not be attempted or authorised."""


def is_root() -> bool:
    return os.geteuid() == 0


def _build_command(args: list[str]) -> list[str]:
    helper_cmd = [sys.executable, HELPER] + args

    if is_root():
        return helper_cmd

    if shutil.which("pkexec"):
        # --disable-internal-agent forces use of the desktop's polkit agent so
        # we get a real dialog rather than a text prompt on an absent tty.
        return ["pkexec", "--disable-internal-agent"] + helper_cmd

    if shutil.which("sudo"):
        return ["sudo", "-A" if os.environ.get("SUDO_ASKPASS") else "-n"] + helper_cmd

    raise PrivilegeError(
        "Neither pkexec nor sudo is available. Install polkit "
        "(sudo dnf install polkit) so LocalStack can request privileges."
    )


def run(args: list[str], stdin_data: str | None = None, timeout: int = 600):
    """Run one helper subcommand as root.

    Returns (ok, stdout, stderr). Raises PrivilegeError only when we could not
    ask for privileges at all -- a helper that ran and failed comes back as
    ok=False so callers can show the real error.
    """
    cmd = _build_command(args)

    try:
        result = subprocess.run(
            cmd,
            input=stdin_data,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, "", f"Timed out after {timeout}s: {' '.join(args)}"
    except FileNotFoundError as exc:
        raise PrivilegeError(f"Cannot launch privilege helper: {exc}") from exc

    if not is_root() and cmd[0] == "pkexec":
        if result.returncode == PKEXEC_DISMISSED:
            raise PrivilegeError("Authentication cancelled.")
        if result.returncode == PKEXEC_NOT_AUTHORISED:
            raise PrivilegeError(
                "Not authorised to run the LocalStack helper. "
                "You need to be an administrator on this machine."
            )

    return result.returncode == 0, result.stdout.strip(), result.stderr.strip()


def run_json(args: list[str], **kwargs):
    """Run a helper subcommand whose stdout is JSON."""
    ok, out, err = run(args, **kwargs)
    try:
        return ok, json.loads(out), err
    except (json.JSONDecodeError, ValueError):
        return ok, {}, err or out


def available() -> tuple[bool, str]:
    """Check whether privilege escalation can work at all, for the UI to show."""
    if is_root():
        return True, "running as root"
    if shutil.which("pkexec"):
        return True, "pkexec (polkit)"
    if shutil.which("sudo"):
        return True, "sudo"
    return False, "no pkexec or sudo found"
