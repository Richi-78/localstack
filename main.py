#!/usr/bin/env python3
"""
LocalStack - Local Web Development Environment Manager for Linux
===============================================================

A XAMPP-like tool for Linux that simplifies setting up Apache + PHP + MySQL.

Usage:
    ./localstack        # run as your normal user -- never with sudo

LocalStack requests administrator rights per-action through polkit (pkexec),
so only src/helper.py ever runs as root. Running the whole GUI as root causes
real damage: root-owned files appear in your projects and settings land in
/root instead of your home directory.
"""

import sys
import os

# Ensure the project directory is in the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def refuse_root():
    """Refuse to run the GUI as root."""
    if os.geteuid() != 0:
        return
    print("Error: LocalStack must not be run as root.\n")
    print("Running the GUI as root writes root-owned files into your projects")
    print("and stores your project list in /root instead of your home directory.\n")
    print("Start it as your normal user:")
    print("    ./localstack\n")
    print("You'll be prompted for a password only when LocalStack needs to")
    print("change Apache config, /etc/hosts, SELinux labels, or services.")
    sys.exit(1)


def check_prerequisites() -> bool:
    """Check if tkinter is available."""
    try:
        import tkinter  # noqa: F401
        return True
    except ImportError:
        return False


def main():
    """Main entry point."""
    refuse_root()

    if not check_prerequisites():
        print("Error: tkinter is not installed.")
        print("Install tkinter using your distribution's package manager (e.g. pacman -S tk).")
        sys.exit(1)

    from src.platform_info import is_arch
    package_manager = "pacman -S" if is_arch() else "dnf install"
    if not (os.path.exists("/usr/bin/dnf") or os.path.exists("/usr/bin/pacman")):
        print("Warning: supported package manager not found; package installation may not work.")

    import tkinter as tk
    from src import privileged
    from src.ui import LocalStackApp

    can_escalate, mechanism = privileged.available()
    if not can_escalate:
        print(f"Warning: {mechanism}.")
        print("Virtual hosts and service control will not work.")
        print(f"Install polkit with your package manager (e.g. sudo {package_manager} polkit).")
    else:
        print(f"Privileged actions will use: {mechanism}")

    root = tk.Tk()
    app = LocalStackApp(root)

    # Center the window
    root.update_idletasks()
    width = root.winfo_width()
    height = root.winfo_height()
    x = (root.winfo_screenwidth() // 2) - (width // 2)
    y = (root.winfo_screenheight() // 2) - (height // 2)
    root.geometry(f'+{x}+{y}')

    root.mainloop()


if __name__ == "__main__":
    main()
