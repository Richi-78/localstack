#!/usr/bin/env python3
"""
LocalStack - Local Web Development Environment Manager for Fedora
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
        print("Install it with: sudo dnf install python3-tkinter")
        sys.exit(1)

    if not os.path.exists("/usr/bin/dnf"):
        print("Warning: dnf not found. Package management features may not work.")
        print("LocalStack is designed for Fedora-based distributions.")

    import tkinter as tk
    from src import privileged
    from src.ui import LocalStackApp

    can_escalate, mechanism = privileged.available()
    if not can_escalate:
        print(f"Warning: {mechanism}.")
        print("Virtual hosts and service control will not work.")
        print("Install polkit with: sudo dnf install polkit")
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
