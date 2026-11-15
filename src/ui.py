"""
LocalStack UI - main tkinter application.

Layout is a dark sidebar plus card-based content pages.  All colours, fonts and
widget styles come from :mod:`src.theme`, which also drives the light/dark
switch, so no widget hardcodes a colour here.
"""

import os
import shutil
import subprocess
import threading
import webbrowser
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from src import privileged
from src import theme
from src.detector import SystemDetector, PackageStatus
from src.installer import PackageInstaller
from src.vhost_manager import VHostManager
from src.project_manager import ProjectManager
from src.db_manager import DBManager
from src.privileged import PrivilegeError


NAV_ITEMS = (
    ("dashboard", "\u25a6", "Dashboard"),
    ("create", "+", "New Project"),
    ("projects", "\u25a4", "Projects"),
    ("services", "\u2699", "Services"),
)


def _round_rect(canvas, x1, y1, x2, y2, r, fill):
    """Draw a filled rounded rectangle on a canvas."""
    points = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, fill=fill, outline="")


class LocalStackApp:
    """Main LocalStack application window."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("LocalStack")
        self.root.geometry("1120x760")
        self.root.minsize(1000, 680)

        self.theme = theme.ThemeManager(root, theme.load_preference())
        self._icon_image = self._make_icon()
        self.root.iconphoto(True, self._icon_image)

        self._screens = {}
        self._nav_buttons = {}
        self._active_screen = None
        self._editing_project = None
        self._form_reset_after = None
        self._toast_widget = None
        self._toast_after = None

        self._build_shell()
        self._build_dashboard()
        self._build_create_page()
        self._build_projects_page()
        self._build_services_page()
        self._show_screen("dashboard")

        self.theme.on_change(self._on_theme_change)
        self._bind_shortcuts()
        self._apply_tree_tags()
        self._detect_system()

    # ==================================================================
    # Shell: sidebar, page container, status bar
    # ==================================================================

    def _build_shell(self):
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(1, weight=1)

        self._build_sidebar()

        content = ttk.Frame(self.root, style="App.TFrame")
        content.grid(row=0, column=1, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(0, weight=1)

        self.pages = ttk.Frame(content, style="App.TFrame")
        self.pages.grid(row=0, column=0, sticky="nsew", padx=28, pady=(24, 6))
        self.pages.grid_columnconfigure(0, weight=1)
        self.pages.grid_rowconfigure(0, weight=1)

        self._build_status_bar(content)

    def _build_sidebar(self):
        bar = ttk.Frame(self.root, style="Sidebar.TFrame", width=238)
        bar.grid(row=0, column=0, sticky="nsew")
        bar.grid_propagate(False)
        bar.grid_columnconfigure(0, weight=1)
        bar.grid_rowconfigure(2, weight=1)

        # Brand ---------------------------------------------------------
        brand = ttk.Frame(bar, style="Sidebar.TFrame")
        brand.grid(row=0, column=0, sticky="ew", padx=18, pady=(22, 22))

        logo = tk.Canvas(brand, width=38, height=38, highlightthickness=0, bd=0)
        logo.pack(side="left")
        self.theme.register_canvas(logo, self._paint_logo)

        wordmark = ttk.Frame(brand, style="Sidebar.TFrame")
        wordmark.pack(side="left", padx=(11, 0))
        ttk.Label(wordmark, text="LocalStack", style="Brand.TLabel").pack(anchor="w")
        ttk.Label(wordmark, text="local web dev", style="BrandSub.TLabel").pack(anchor="w")

        # Navigation ----------------------------------------------------
        nav = ttk.Frame(bar, style="Sidebar.TFrame")
        nav.grid(row=1, column=0, sticky="new", padx=12)
        ttk.Label(nav, text="WORKSPACE", style="NavSection.TLabel").pack(
            anchor="w", padx=10, pady=(0, 8)
        )
        for key, glyph, label in NAV_ITEMS:
            btn = ttk.Button(
                nav,
                text=f"{glyph}    {label}",
                style="Nav.TButton",
                takefocus=0,
                command=(
                    self._start_new_project if key == "create"
                    else lambda k=key: self._show_screen(k)
                ),
            )
            btn.pack(fill="x", pady=2)
            self._nav_buttons[key] = btn

        # Footer --------------------------------------------------------
        footer = ttk.Frame(bar, style="Sidebar.TFrame")
        footer.grid(row=3, column=0, sticky="ew", padx=12, pady=(12, 16))
        ttk.Frame(footer, style="SidebarRule.TFrame", height=1).pack(
            fill="x", pady=(0, 8)
        )

        self.theme_btn = ttk.Button(
            footer,
            text="\u263e    Dark mode" if self.theme.mode == "light" else "\u2600    Light mode",
            style="Nav.TButton",
            takefocus=0,
            command=self._toggle_theme,
        )
        self.theme_btn.pack(fill="x", pady=2)

        for text, command in (
            ("\u25b8    Terminal", self._open_terminal),
            ("\u24d8    About", self._show_about),
        ):
            ttk.Button(
                footer, text=text, style="Nav.TButton",
                takefocus=0, command=command,
            ).pack(fill="x", pady=2)

        meta = ttk.Frame(footer, style="Sidebar.TFrame")
        meta.pack(fill="x", pady=(12, 0), padx=4)
        ttk.Label(meta, text="v0.1.0", style="BrandSub.TLabel").pack(side="left")
        ttk.Button(
            meta, text="Quit", style="Link.TButton", takefocus=0,
            command=self.root.quit,
        ).pack(side="right")

    def _paint_logo(self, canvas, p):
        canvas.configure(background=p["sidebar"])
        canvas.delete("all")
        _round_rect(canvas, 4, 24, 34, 33, 4, p["accent_soft"])
        _round_rect(canvas, 4, 14, 34, 23, 4, p["accent"])
        _round_rect(canvas, 4, 4, 34, 13, 4, p["accent_hover"])

    def _make_icon(self):
        """A 32x32 stack mark for the window manager / task bar."""
        p = self.theme.p
        image = tk.PhotoImage(width=32, height=32)
        image.put(p["sidebar"], to=(0, 0, 32, 32))
        image.put(p["accent_soft"], to=(4, 22, 28, 27))
        image.put(p["accent"], to=(4, 13, 28, 18))
        image.put(p["accent_hover"], to=(4, 4, 28, 9))
        return image

    def _build_status_bar(self, parent):
        bar = ttk.Frame(parent, style="Surface.TFrame")
        bar.grid(row=1, column=0, sticky="ew")
        ttk.Frame(bar, style="Rule.TFrame", height=1).pack(fill="x")
        inner = ttk.Frame(bar, style="Surface.TFrame")
        inner.pack(fill="x", padx=28, pady=(7, 9))

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(inner, textvariable=self.status_var, style="StatusBar.TLabel").pack(
            side="left"
        )

        can_escalate, mechanism = privileged.available()
        privilege_text = (
            f"Privileged actions: {mechanism}"
            if can_escalate
            else "polkit unavailable \u2014 system changes disabled"
        )
        ttk.Label(
            inner, text=privilege_text, style="StatusBar.TLabel",
        ).pack(side="right")

    def _page_header(self, parent, title, subtitle=None, subtitle_var=None):
        """Create a page title row; returns (header, actions_container)."""
        head = ttk.Frame(parent, style="App.TFrame")
        left = ttk.Frame(head, style="App.TFrame")
        left.pack(side="left", anchor="w")
        ttk.Label(left, text=title, style="H1.TLabel").pack(anchor="w")
        if subtitle_var is not None:
            ttk.Label(left, textvariable=subtitle_var, style="Subtitle.TLabel").pack(
                anchor="w", pady=(2, 0)
            )
        elif subtitle:
            ttk.Label(left, text=subtitle, style="Subtitle.TLabel").pack(
                anchor="w", pady=(2, 0)
            )
        actions = ttk.Frame(head, style="App.TFrame")
        actions.pack(side="right", anchor="e")
        return head, actions

    def _secondary_button(self, parent, text, command):
        return ttk.Button(parent, text=text, style="Secondary.TButton", command=command)

    # ==================================================================
    # Dashboard / system page
    # ==================================================================

    def _build_dashboard(self):
        page = ttk.Frame(self.pages, style="App.TFrame")
        page.grid(row=0, column=0, sticky="nsew")
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(2, weight=1)

        head, actions = self._page_header(
            page, "Dashboard", "Your local web stack at a glance."
        )
        head.grid(row=0, column=0, sticky="ew")
        self._secondary_button(actions, "\u21bb  Refresh", self._detect_system).pack(
            side="right"
        )

        # Stat cards ----------------------------------------------------
        stats = ttk.Frame(page, style="App.TFrame")
        stats.grid(row=1, column=0, sticky="ew", pady=(18, 16))
        for col in range(4):
            stats.grid_columnconfigure(col, weight=1, uniform="stat")

        self.pkg_stat_value, self.pkg_stat_detail = self._stat_card(
            stats, 0, "Packages", last=False
        )
        self.apache_stat_value, self.apache_stat_detail = self._stat_card(
            stats, 1, "Apache", last=False
        )
        self.mysql_stat_value, self.mysql_stat_detail = self._stat_card(
            stats, 2, "MySQL", last=False
        )
        self.php_stat_value, self.php_stat_detail = self._stat_card(
            stats, 3, "PHP-FPM", last=True
        )

        # Packages ------------------------------------------------------
        card = ttk.Frame(page, style="Card.TFrame")
        card.grid(row=2, column=0, sticky="nsew")
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(1, weight=1)

        card_head = ttk.Frame(card, style="Surface.TFrame")
        card_head.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 12))
        card_head.grid_columnconfigure(0, weight=1)

        ttk.Label(card_head, text="Packages", style="H2.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            card_head,
            text="Components LocalStack checks for on this system",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        pkg_actions = ttk.Frame(card_head, style="Surface.TFrame")
        pkg_actions.grid(row=0, column=1, rowspan=2, sticky="e")
        self.pkg_status_label = ttk.Label(pkg_actions, text="", style="Muted.TLabel")
        self.pkg_status_label.pack(side="left", padx=(0, 12))
        self.install_btn = ttk.Button(
            pkg_actions,
            text="Install missing",
            style="Accent.TButton",
            command=self._install_missing,
        )
        self.install_btn.pack(side="left")

        holder = ttk.Frame(card, style="Surface.TFrame")
        holder.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 18))

        columns = ("package", "status", "version")
        self.pkg_tree = ttk.Treeview(
            holder, columns=columns, show="headings", height=8, selectmode="none"
        )
        for col, title, width, stretch in (
            ("package", "Component", 340, True),
            ("status", "Status", 120, False),
            ("version", "Version", 160, False),
        ):
            self.pkg_tree.heading(col, text=title, anchor="w")
            self.pkg_tree.column(col, width=width, minwidth=80, stretch=stretch,
                                 anchor="w")

        scrollbar = ttk.Scrollbar(holder, orient="vertical",
                                  command=self.pkg_tree.yview)
        self.pkg_tree.configure(yscrollcommand=scrollbar.set)
        self.pkg_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Quick start ---------------------------------------------------
        quick = ttk.Frame(page, style="Card.TFrame")
        quick.grid(row=3, column=0, sticky="ew", pady=(16, 0))
        inner = ttk.Frame(quick, style="Surface.TFrame")
        inner.pack(fill="x", padx=20, pady=13)
        ttk.Label(inner, text="Quick start", style="H3.TLabel").pack(side="left")
        steps = (
            (1, "Install missing packages"),
            (2, "Create a project"),
            (3, "Open it from Projects"),
        )
        for num, text in steps:
            ttk.Label(inner, text="\u203a", style="Muted.TLabel").pack(
                side="left", padx=(18, 8)
            )
            ttk.Label(inner, text=str(num), style="StepNum.TLabel").pack(side="left")
            ttk.Label(inner, text="  " + text, style="Step.TLabel").pack(side="left")

        self._screens["dashboard"] = page

    def _stat_card(self, parent, column, label, last=False):
        card = ttk.Frame(parent, style="Card.TFrame")
        card.grid(row=0, column=column, sticky="nsew",
                  padx=(0, 0 if last else 12))
        inner = ttk.Frame(card, style="Surface.TFrame")
        inner.pack(fill="both", expand=True, padx=16, pady=13)

        ttk.Label(inner, text=label.upper(), style="StatLabel.TLabel").pack(anchor="w")
        value = ttk.Label(inner, text="\u2014", style="StatValue.TLabel")
        value.pack(anchor="w", pady=(3, 0))
        detail = ttk.Label(inner, text="Checking\u2026", style="Hint.TLabel")
        detail.pack(anchor="w")
        return value, detail

    # ==================================================================
    # New project page
    # ==================================================================

    def _build_create_page(self):
        page = ttk.Frame(self.pages, style="App.TFrame")
        page.grid(row=0, column=0, sticky="nsew")
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)

        head = ttk.Frame(page, style="App.TFrame")
        head.grid(row=0, column=0, sticky="ew")
        head_left = ttk.Frame(head, style="App.TFrame")
        head_left.pack(side="left", anchor="w")
        self.create_title_label = ttk.Label(
            head_left, text="New project", style="H1.TLabel"
        )
        self.create_title_label.pack(anchor="w")
        self.create_subtitle_label = ttk.Label(
            head_left,
            text="Create a folder, a virtual host and, if you want, a database.",
            style="Subtitle.TLabel",
        )
        self.create_subtitle_label.pack(anchor="w", pady=(2, 0))

        body = ttk.Frame(page, style="App.TFrame")
        body.grid(row=1, column=0, sticky="nsew", pady=(18, 0))
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=2)

        # Form ---------------------------------------------------------
        card = ttk.Frame(body, style="Card.TFrame")
        card.grid(row=0, column=0, sticky="new", padx=(0, 16))
        card.grid_columnconfigure(0, weight=1)
        form = ttk.Frame(card, style="Surface.TFrame")
        form.grid(row=0, column=0, sticky="nsew", padx=22, pady=20)
        form.grid_columnconfigure(0, weight=1)

        ttk.Label(form, text="Project details", style="H2.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 14)
        )

        # Name
        self._field_label(form, 1, "Project name", "letters, numbers, hyphens")
        self.project_name_var = tk.StringVar()
        self.project_name_entry = ttk.Entry(form, textvariable=self.project_name_var)
        self.project_name_entry.grid(row=2, column=0, sticky="ew", pady=(5, 14))

        # URL
        self._field_label(form, 3, "Local URL", "leave blank to use the project name")
        url_frame = ttk.Frame(form, style="Surface.TFrame")
        url_frame.grid(row=4, column=0, sticky="ew", pady=(5, 14))
        url_frame.grid_columnconfigure(0, weight=1)
        self.custom_url_var = tk.StringVar()
        self.custom_url_entry = ttk.Entry(url_frame, textvariable=self.custom_url_var)
        self.custom_url_entry.grid(row=0, column=0, sticky="ew")
        ttk.Label(url_frame, text=".local", style="Muted.TLabel").grid(
            row=0, column=1, sticky="w", padx=(8, 0)
        )

        # Folder
        self._field_label(form, 5, "Project folder", "")
        folder_frame = ttk.Frame(form, style="Surface.TFrame")
        folder_frame.grid(row=6, column=0, sticky="ew", pady=(5, 4))
        folder_frame.grid_columnconfigure(0, weight=1)
        self.project_path_var = tk.StringVar()
        self.project_path_entry = ttk.Entry(
            folder_frame, textvariable=self.project_path_var
        )
        self.project_path_entry.grid(row=0, column=0, sticky="ew")
        ttk.Button(
            folder_frame, text="Browse\u2026", style="Secondary.TButton",
            command=self._browse_project_path,
        ).grid(row=0, column=1, padx=(8, 0))

        self.public_hint_var = tk.StringVar(value="")
        self.public_hint_label = ttk.Label(
            form, textvariable=self.public_hint_var, style="Hint.TLabel"
        )
        self.public_hint_label.grid(row=7, column=0, sticky="w", pady=(0, 14))

        # Database
        self._field_label(form, 8, "Database", "")
        db_frame = ttk.Frame(form, style="Surface.TFrame")
        db_frame.grid(row=9, column=0, sticky="w", pady=(6, 8))
        self.db_type_var = tk.StringVar(value="none")
        for text, value in (
            ("None", "none"), ("MySQL / MariaDB", "mysql"), ("SQLite", "sqlite"),
        ):
            ttk.Radiobutton(
                db_frame, text=text, value=value, variable=self.db_type_var,
                style="Segment.TRadiobutton",
            ).pack(side="left", padx=(0, 8))

        self.mysql_settings = ttk.Frame(form, style="Surface.TFrame")
        self.mysql_settings.grid(row=10, column=0, sticky="ew", pady=(0, 6))
        self.mysql_settings.grid_columnconfigure(0, weight=1)
        self.mysql_settings.grid_columnconfigure(1, weight=1)

        ttk.Label(self.mysql_settings, text="Database name", style="Hint.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(self.mysql_settings, text="Database user", style="Hint.TLabel").grid(
            row=0, column=1, sticky="w", padx=(10, 0)
        )
        self.mysql_db_var = tk.StringVar()
        self.mysql_user_var = tk.StringVar()
        self.mysql_db_entry = ttk.Entry(
            self.mysql_settings, textvariable=self.mysql_db_var
        )
        self.mysql_db_entry.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.mysql_user_entry = ttk.Entry(
            self.mysql_settings, textvariable=self.mysql_user_var
        )
        self.mysql_user_entry.grid(row=1, column=1, sticky="ew", padx=(10, 0),
                                   pady=(4, 0))
        self.mysql_settings.grid_remove()

        # Actions
        buttons = ttk.Frame(form, style="Surface.TFrame")
        buttons.grid(row=11, column=0, sticky="w", pady=(10, 0))
        self.create_project_btn = ttk.Button(
            buttons, text="Create project", style="Accent.TButton",
            command=self._create_project,
        )
        self.create_project_btn.pack(side="left")
        self.reset_project_btn = ttk.Button(
            buttons, text="Reset", style="Ghost.TButton",
            command=self._reset_project_form,
        )
        self.reset_project_btn.pack(side="left", padx=(8, 0))

        self.project_status_label = ttk.Label(
            form, text="", style="OkText.TLabel", justify="left", wraplength=520
        )
        self.project_status_label.grid(row=12, column=0, sticky="w", pady=(12, 0))
        form.bind(
            "<Configure>",
            lambda e: self.project_status_label.configure(
                wraplength=max(280, e.width - 8)
            ),
        )

        # URL preview, anchored to the bottom of the card
        form.grid_rowconfigure(13, weight=1)
        preview = ttk.Frame(form, style="Preview.TFrame")
        preview.grid(row=14, column=0, sticky="ew", pady=(18, 0))
        ttk.Label(preview, text="LOCAL URL", style="PreviewLabel.TLabel").pack(
            anchor="w", padx=14, pady=(10, 0)
        )
        self.url_preview_var = tk.StringVar()
        ttk.Label(
            preview, textvariable=self.url_preview_var, style="PreviewValue.TLabel"
        ).pack(anchor="w", padx=14, pady=(2, 10))

        self.db_type_var.trace_add("write", lambda *a: self._toggle_mysql_settings())
        self.project_name_var.trace_add("write", self._update_url_preview)
        self.custom_url_var.trace_add("write", self._update_url_preview)
        self._update_url_preview()

        # Side card ----------------------------------------------------
        side = ttk.Frame(body, style="Card.TFrame")
        side.grid(row=0, column=1, sticky="new")
        side_inner = ttk.Frame(side, style="Surface.TFrame")
        side_inner.pack(fill="both", expand=True, padx=20, pady=20)

        ttk.Label(side_inner, text="What you get", style="H2.TLabel").pack(anchor="w")
        ttk.Label(
            side_inner,
            text="LocalStack wires the pieces together for you:",
            style="Muted.TLabel", wraplength=280, justify="left",
        ).pack(anchor="w", pady=(4, 12))

        for item in (
            "An Apache virtual host on <name>.local",
            "A matching entry in /etc/hosts",
            "Starter index.html and info.php files",
            "A MySQL database and user (optional)",
            "SELinux labels and file permissions",
        ):
            ttk.Label(
                side_inner, text="\u2713  " + item, style="Check.TLabel",
                wraplength=280, justify="left",
            ).pack(anchor="w", pady=3)

        ttk.Frame(side_inner, style="Rule.TFrame", height=1).pack(fill="x", pady=16)
        ttk.Label(
            side_inner,
            text="Changing system files needs administrator rights. "
                 "polkit will ask for your password once.",
            style="Muted.TLabel", wraplength=280, justify="left",
        ).pack(anchor="w")

        self._screens["create"] = page

    def _field_label(self, parent, row, text, hint):
        line = ttk.Frame(parent, style="Surface.TFrame")
        line.grid(row=row, column=0, sticky="ew")
        ttk.Label(line, text=text, style="H3.TLabel").pack(side="left")
        if hint:
            ttk.Label(line, text=hint, style="Hint.TLabel").pack(
                side="right", padx=(8, 0)
            )
        return line

    def _toggle_mysql_settings(self):
        if self.db_type_var.get() == "mysql":
            self.mysql_settings.grid()
        else:
            self.mysql_settings.grid_remove()

    @staticmethod
    def _hostname_from(value):
        """Normalise a user-supplied name into the label part of <name>.local."""
        clean = value.lower().replace(" ", "-").strip().rstrip(".")
        if clean.endswith(".local"):
            clean = clean[: -len(".local")]
        return "".join(c for c in clean if c.isalnum() or c == "-")

    def _update_url_preview(self, *_args):
        """Keep the URL preview in sync with the name / custom URL fields."""
        hostname = (
            self._hostname_from(self.custom_url_var.get())
            or self._hostname_from(self.project_name_var.get())
            or "your-project"
        )
        self.url_preview_var.set(f"http://{hostname}.local")

    # ==================================================================
    # Projects page
    # ==================================================================

    def _build_projects_page(self):
        page = ttk.Frame(self.pages, style="App.TFrame")
        page.grid(row=0, column=0, sticky="nsew")
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)

        self.projects_subtitle = tk.StringVar(value="No projects yet")
        head, actions = self._page_header(
            page, "Projects", subtitle_var=self.projects_subtitle
        )
        head.grid(row=0, column=0, sticky="ew")

        ttk.Button(
            actions, text="+  New project", style="Accent.TButton",
            command=self._start_new_project,
        ).pack(side="right")
        self._secondary_button(
            actions, "Reapply virtual hosts", self._reapply_vhosts
        ).pack(side="right", padx=(0, 8))
        self._secondary_button(actions, "\u21bb  Refresh", self._refresh_projects_list).pack(
            side="right", padx=(0, 8)
        )

        card = ttk.Frame(page, style="Card.TFrame")
        card.grid(row=1, column=0, sticky="nsew", pady=(18, 0))
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(0, weight=1)

        holder = ttk.Frame(card, style="Surface.TFrame")
        holder.grid(row=0, column=0, sticky="nsew", padx=20, pady=(18, 16))

        columns = ("name", "url", "database", "status")
        self.proj_tree = ttk.Treeview(
            holder, columns=columns, show="headings", selectmode="browse"
        )
        for col, title, width, stretch in (
            ("name", "Project", 170, False),
            ("url", "URL", 280, True),
            ("database", "Database", 120, False),
            ("status", "Status", 120, False),
        ):
            self.proj_tree.heading(col, text=title, anchor="w")
            self.proj_tree.column(col, width=width, minwidth=90, anchor="w",
                                  stretch=stretch)

        scrollbar = ttk.Scrollbar(holder, orient="vertical",
                                  command=self.proj_tree.yview)
        self.proj_tree.configure(yscrollcommand=scrollbar.set)
        self.proj_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.proj_empty = ttk.Label(
            holder,
            text="No projects yet.\nCreate one and it will show up here.",
            style="Muted.TLabel", justify="center", anchor="center",
        )

        self.proj_tree.bind("<Double-1>", lambda e: self._open_selected_browser())
        self.proj_tree.bind("<<TreeviewSelect>>", self._on_project_selection)

        # Action bar ----------------------------------------------------
        actions_bar = ttk.Frame(page, style="App.TFrame")
        actions_bar.grid(row=2, column=0, sticky="ew", pady=(14, 0))

        self.open_browser_btn = ttk.Button(
            actions_bar, text="Open in browser", style="Accent.TButton",
            command=self._open_selected_browser,
        )
        self.open_browser_btn.pack(side="left")
        self.open_folder_btn = ttk.Button(
            actions_bar, text="Open folder", style="Secondary.TButton",
            command=self._open_selected_folder,
        )
        self.open_folder_btn.pack(side="left", padx=(8, 0))
        self.logs_btn = ttk.Button(
            actions_bar, text="View error log", style="GhostApp.TButton",
            command=self._view_logs,
        )
        self.logs_btn.pack(side="left", padx=(4, 0))
        self.delete_proj_btn = ttk.Button(
            actions_bar, text="Remove", style="Danger.TButton",
            command=self._delete_selected_project,
        )
        self.delete_proj_btn.pack(side="right")
        self.edit_proj_btn = ttk.Button(
            actions_bar, text="Edit", style="Secondary.TButton",
            command=self._edit_selected_project,
        )
        self.edit_proj_btn.pack(side="right", padx=(0, 8))

        self._screens["projects"] = page
        self._refresh_projects_list()
        self._update_project_actions()

    def _on_project_selection(self, _event=None):
        self._update_project_actions()
        project = self._get_selected_project()
        if project:
            self._set_status(project.get("document_root", ""))

    def _update_project_actions(self):
        enabled = self._get_selected_project() is not None
        state = "normal" if enabled else "disabled"
        for button in (
            self.open_browser_btn, self.open_folder_btn,
            self.logs_btn, self.delete_proj_btn, self.edit_proj_btn,
        ):
            button.configure(state=state)

    def _refresh_projects_list(self):
        self.proj_tree.delete(*self.proj_tree.get_children())

        projects = ProjectManager.list_projects()
        for index, proj in enumerate(projects, start=1):
            db_type = ProjectManager.db_type_of(proj)
            db_label = {"mysql": "MySQL", "sqlite": "SQLite"}.get(db_type, "None")
            status = proj.get("status", "created")
            status_text = (
                "\u25cf Running" if status == "running" else "\u25cb " + status.capitalize()
            )
            hostname = proj.get("hostname", f"{proj['name']}.local")

            self.proj_tree.insert(
                "", "end", iid=proj["name"],
                values=(proj["name"], f"http://{hostname}", db_label, status_text),
                tags=("even",) if index % 2 == 0 else (),
            )

        count = len(projects)
        self.projects_subtitle.set(
            "No projects yet" if count == 0
            else f"{count} project{'s' if count != 1 else ''} registered"
        )
        if count == 0:
            self.proj_empty.place(relx=0.5, rely=0.5, anchor="center")
        else:
            self.proj_empty.place_forget()
        self._update_project_actions()

    def _get_selected_project(self):
        selection = self.proj_tree.selection()
        if not selection:
            return None
        return ProjectManager.get_project(selection[0])

    def _reapply_vhosts(self):
        success, msg = VHostManager.regenerate_all()
        if success:
            self._toast(msg, "ok")
        else:
            self._toast(msg, "error")
        if success:
            self._refresh_projects_list()

    # ==================================================================
    # Services page
    # ==================================================================

    def _build_services_page(self):
        page = ttk.Frame(self.pages, style="App.TFrame")
        page.grid(row=0, column=0, sticky="nsew")
        page.grid_columnconfigure(0, weight=1)

        head, actions = self._page_header(
            page,
            "Services",
            "Start, stop and enable the daemons that serve your projects.",
        )
        head.grid(row=0, column=0, sticky="ew")
        self._secondary_button(
            actions, "\u21bb  Refresh", self._update_service_status
        ).pack(side="right")

        cards = ttk.Frame(page, style="App.TFrame")
        cards.grid(row=1, column=0, sticky="ew", pady=(18, 0))
        cards.grid_columnconfigure(0, weight=1)

        (self.apache_pill_var, self.apache_pill) = self._service_card(
            cards, 1, "Apache",
            "httpd.service \u2014 serves your virtual hosts and PHP through FPM",
            self._start_apache, self._stop_apache, self._restart_apache,
            self._enable_apache,
        )
        (self.mysql_pill_var, self.mysql_pill) = self._service_card(
            cards, 2, "MySQL / MariaDB",
            f"{SystemDetector.MYSQL_SERVICE}.service \u2014 databases for your projects",
            self._start_mysql, self._stop_mysql, self._restart_mysql,
            self._enable_mysql,
        )
        (self.php_pill_var, self.php_pill) = self._service_card(
            cards, 3, "PHP-FPM",
            "php-fpm.service \u2014 interprets PHP for Apache",
            self._start_php, self._stop_php, self._restart_php, None,
        )

        ttk.Label(
            page,
            text="Service changes need administrator rights \u2014 polkit will "
                 "prompt for your password.",
            style="MutedApp.TLabel",
        ).grid(row=2, column=0, sticky="w", pady=(4, 0))

        self._screens["services"] = page

    def _service_card(self, parent, row, title, description,
                      start, stop, restart, enable):
        card = ttk.Frame(parent, style="Card.TFrame")
        card.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        card.grid_columnconfigure(1, weight=1)

        inner = ttk.Frame(card, style="Surface.TFrame")
        inner.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=20, pady=15)
        inner.grid_columnconfigure(2, weight=1)

        ttk.Label(inner, text=title, style="H2.TLabel").grid(row=0, column=0,
                                                             sticky="w")
        pill_var = tk.StringVar(value="Checking\u2026")
        pill = ttk.Label(inner, textvariable=pill_var, style="NeutralBadge.TLabel")
        pill.grid(row=0, column=1, sticky="w", padx=(10, 0))
        ttk.Label(inner, text=description, style="Muted.TLabel",
                  wraplength=640, justify="left").grid(
            row=1, column=0, columnspan=4, sticky="w", pady=(4, 0)
        )

        buttons = ttk.Frame(inner, style="Surface.TFrame")
        buttons.grid(row=0, column=3, sticky="e")
        ttk.Button(buttons, text="Start", style="Success.TButton",
                   command=start).pack(side="left")
        ttk.Button(buttons, text="Stop", style="Secondary.TButton",
                   command=stop).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="Restart", style="Secondary.TButton",
                   command=restart).pack(side="left", padx=(8, 0))
        if enable:
            ttk.Button(buttons, text="Enable on boot", style="Ghost.TButton",
                       command=enable).pack(side="left", padx=(4, 0))
        return pill_var, pill

    # ==================================================================
    # Theme / navigation helpers
    # ==================================================================

    def _show_screen(self, key):
        screen = self._screens.get(key)
        if screen is None:
            return
        screen.tkraise()
        self._active_screen = key
        for nav_key, button in self._nav_buttons.items():
            button.configure(
                style="NavActive.TButton" if nav_key == key else "Nav.TButton"
            )
        hints = {
            "dashboard": "Ready",
            "create": "Fill in the details to create a project",
            "projects": "Select a project to see its folder",
            "services": "Service changes need your password",
        }
        self._set_status(hints.get(key, "Ready"))
        if key == "create":
            if self._editing_project is not None:
                self._set_status(
                    f"Editing {self._editing_project} \u2014 saving reapplies the virtual host"
                )
                self.custom_url_entry.focus_set()
            else:
                self.project_name_entry.focus_set()

    def _toggle_theme(self):
        mode = self.theme.toggle()
        self.theme_btn.configure(
            text="\u263e    Dark mode" if mode == "light" else "\u2600    Light mode"
        )

    def _on_theme_change(self, _palette):
        if self._toast_after is not None:
            self.root.after_cancel(self._toast_after)
            self._toast_after = None
        if self._toast_widget is not None:
            self._toast_widget.destroy()
            self._toast_widget = None
        self._apply_tree_tags()

    def _apply_tree_tags(self):
        p = self.theme.p
        for tree in (getattr(self, "pkg_tree", None), getattr(self, "proj_tree", None)):
            if tree is not None:
                tree.tag_configure("even", background=p["surface_alt"])
                tree.tag_configure("odd", background=p["surface"])

    def _bind_shortcuts(self):
        for index, (key, _glyph, _label) in enumerate(NAV_ITEMS, start=1):
            self.root.bind(
                f"<Control-Key-{index}>",
                lambda _e, k=key: self._show_screen(k),
            )
        self.root.bind("<F5>", lambda _e: self._refresh_active_screen())

    def _refresh_active_screen(self):
        if self._active_screen == "projects":
            self._refresh_projects_list()
        elif self._active_screen == "services":
            self._update_service_status()
        else:
            self._detect_system()

    def _set_status(self, text):
        self.status_var.set(text)

    def _toast(self, message, kind="info"):
        """Show a transient message in the bottom-right corner."""
        if self._toast_after is not None:
            self.root.after_cancel(self._toast_after)
            self._toast_after = None
        if self._toast_widget is not None:
            self._toast_widget.destroy()

        prefix = {"ok": "\u2713  ", "error": "\u2715  ", "warn": "!  "}.get(kind, "")
        frame = ttk.Frame(self.root, style="Toast.TFrame", padding=(16, 11))
        ttk.Label(
            frame, text=prefix + message, style="Toast.TLabel",
            wraplength=460, justify="left",
        ).pack()
        frame.place(relx=1.0, rely=1.0, x=-26, y=-64, anchor="se")
        frame.lift()
        self._toast_widget = frame

        def dismiss():
            if self._toast_widget is frame:
                frame.destroy()
                self._toast_widget = None
            self._toast_after = None

        # Errors usually carry a longer explanation, so keep them on screen.
        self._toast_after = self.root.after(6500 if kind == "error" else 4200, dismiss)

    # ==================================================================
    # System detection / package handling
    # ==================================================================

    def _detect_system(self):
        self._set_status("Scanning installed packages\u2026")
        self.root.update_idletasks()

        results = SystemDetector.check_all()
        self._update_package_tree(results)

        missing = [n for n, i in results.items() if i.status == PackageStatus.NOT_INSTALLED]
        installed = len(results) - len(missing)

        self.pkg_status_label.config(
            text=f"{installed} of {len(results)} installed"
        )
        self.install_btn.configure(
            state="normal" if missing else "disabled",
            text="Install missing" if missing else "All installed",
        )

        self.pkg_stat_value.configure(
            text=f"{installed}/{len(results)}",
            style="StatGood.TLabel" if not missing else "StatWarn.TLabel",
        )
        self.pkg_stat_detail.configure(
            text="Everything installed" if not missing else f"{len(missing)} missing"
        )

        self._update_service_status()
        self._set_status(
            f"Detected {installed} installed packages"
            + (f" \u2014 {len(missing)} missing" if missing else "")
        )

    def _update_package_tree(self, results):
        self.pkg_tree.delete(*self.pkg_tree.get_children())
        for index, (_key, info) in enumerate(results.items(), start=1):
            installed = info.status == PackageStatus.INSTALLED
            if info.version:
                version = f"v{info.version}"
            elif info.service_name:
                version = f"{info.service_name}.service"
            else:
                version = "PHP extension"

            self.pkg_tree.insert(
                "", "end",
                values=(
                    info.name,
                    "\u2713 Installed" if installed else "\u2715 Missing",
                    version,
                ),
                tags=("even",) if index % 2 == 0 else (),
            )

    def _install_missing(self):
        results = SystemDetector.check_all()
        missing = [n for n, i in results.items()
                   if i.status == PackageStatus.NOT_INSTALLED]

        if not missing:
            self._toast("All packages are already installed.", "ok")
            return

        listing = "\n".join(f"  \u2022 {results[m].name}" for m in missing)
        msg = (
            "The following packages will be installed:\n\n"
            f"{listing}\n\nYou will be asked for your password."
        )
        if not messagebox.askyesno("Install packages", msg):
            return

        self._set_status("Installing packages\u2026 this may take a moment.")
        self.install_btn.configure(state="disabled")

        def install_thread():
            success, installed = PackageInstaller.install_missing(results, missing)

            if success:
                self.root.after(
                    0, lambda: messagebox.showinfo(
                        "Success", f"Successfully installed: {', '.join(installed)}"
                    ),
                )
            else:
                self.root.after(
                    0, lambda: messagebox.showerror(
                        "Error", "Installation failed. Check the terminal for details."
                    ),
                )
            self.root.after(0, self._detect_system)

        threading.Thread(target=install_thread, daemon=True).start()

    # ==================================================================
    # Project creation and editing
    # ==================================================================

    def _browse_project_path(self):
        path = self._system_directory_picker()
        if path is None:
            # No desktop-specific chooser installed: Tk's fallback still works.
            path = filedialog.askdirectory()
        if not path:
            return
        self.project_path_var.set(path)
        self._update_public_hint(path)

    @staticmethod
    def _system_directory_picker():
        """Ask the desktop's file chooser for a folder.

        Tk's own dialog is not the system picker and looks out of place. Prefer
        the chooser shipped by the running desktop; return None when none of
        them is available so the caller can fall back to tkinter.
        """
        choices = (
            ("zenity", ["zenity", "--file-selection", "--directory",
                        "--title=Select project folder"]),
            ("kdialog", ["kdialog", "--getexistingdirectory",
                         os.path.expanduser("~"),
                         "--title", "Select project folder"]),
            ("qarma", ["qarma", "--file-selection", "--directory",
                       "--title=Select project folder"]),
        )
        for executable, command in choices:
            if not shutil.which(executable):
                continue
            try:
                result = subprocess.run(
                    command, capture_output=True, text=True, timeout=300
                )
            except (OSError, subprocess.SubprocessError):
                continue
            if result.returncode == 0:
                return result.stdout.strip()
            return ""  # the user cancelled in the native dialog
        return None

    def _update_public_hint(self, path=None):
        path = (path if path is not None else self.project_path_var.get()).strip()
        if not path:
            self.public_hint_var.set("")
            self.public_hint_label.configure(style="Hint.TLabel")
        elif os.path.isdir(os.path.join(path, "public")):
            self.public_hint_var.set(
                "A 'public' folder was found and will be used as document root."
            )
            self.public_hint_label.configure(style="AccentHint.TLabel")
        else:
            self.public_hint_var.set(
                "No 'public' folder \u2014 the project root will be the document root."
            )
            self.public_hint_label.configure(style="Hint.TLabel")

    def _start_new_project(self):
        if self._editing_project is not None or self.create_project_btn.cget("state") == "disabled":
            self._reset_project_form()
        self._show_screen("create")

    def _edit_selected_project(self):
        project = self._get_selected_project()
        if not project:
            self._toast("Select a project first.", "warn")
            return

        self._cancel_pending_reset()
        name = project["name"]
        self._editing_project = name
        document_root = project.get("document_root", "")
        folder = VHostManager.detect_app_root(document_root) or document_root
        hostname = project.get("hostname") or VHostManager.normalize_hostname(name)

        self.create_title_label.configure(text=f"Edit {name}")
        self.create_subtitle_label.configure(
            text="Saving reapplies the virtual host, the hosts entry and Apache."
        )
        self.project_name_var.set(name)
        self.project_name_entry.configure(state="readonly")
        self.custom_url_var.set(
            hostname[: -len(".local")] if hostname.endswith(".local") else hostname
        )
        self.project_path_var.set(folder)
        self._update_public_hint(folder)

        db_type = ProjectManager.db_type_of(project)
        self.db_type_var.set(db_type)
        self.mysql_db_var.set(
            (project.get("db_name") or "") if db_type == "mysql" else ""
        )
        self.mysql_user_var.set(
            (project.get("db_user") or "") if db_type == "mysql" else ""
        )

        self.create_project_btn.configure(text="Save changes", state="normal")
        self.reset_project_btn.configure(
            text="Cancel", command=self._cancel_project_form
        )
        self.project_status_label.configure(text="")
        self._update_url_preview()
        self._show_screen("create")
        self.custom_url_entry.focus_set()

    def _create_project(self):
        if self._editing_project is not None:
            self._save_project_edit()
            return

        name = self.project_name_var.get().strip()
        path = self.project_path_var.get().strip()
        custom_url = self.custom_url_var.get().strip()

        if not name:
            self._set_form_status("Please enter a project name.", "error")
            self.project_name_entry.focus_set()
            return
        if not path:
            self._set_form_status("Please select a project folder.", "error")
            self.project_path_entry.focus_set()
            return

        db_type = self.db_type_var.get()
        db_name = db_user = None
        if db_type == "mysql":
            db_name = self.mysql_db_var.get().strip() or f"{name}_db"
            db_user = self.mysql_user_var.get().strip() or f"{name}_user"

        document_root = path
        public_path = os.path.join(path, "public")
        if os.path.isdir(public_path):
            document_root = public_path

        # Accept a full hostname too; otherwise a pasted "site.local" would
        # become "site.local.local", which never resolves.
        hostname = None
        if custom_url:
            clean = self._hostname_from(custom_url)
            if clean:
                hostname = f"{clean}.local"

        success, message, project_data = ProjectManager.create_project(
            name=name,
            document_root=document_root,
            db_type=db_type,
            db_name=db_name,
            db_user=db_user,
            hostname=hostname,
        )

        if not success:
            self._set_form_status(message, "error")
            return

        # The database is created inside the same privileged batch as the
        # vhost, so the user is asked for their password only once.
        mysql = None
        if db_type == "mysql":
            mysql = {
                "name": project_data["db_name"],
                "user": project_data["db_user"],
                "password": project_data["db_pass"],
                "host": "127.0.0.1",
            }

        actual_url = project_data.get("hostname", f"{name}.local")
        lines = [message, f"http://{actual_url}"]

        vhost_success, vhost_msg = VHostManager.create_vhost(
            project_name=name,
            document_root=document_root,
            hostname=actual_url,
            mysql=mysql,
            reload=True,
        )
        lines.append(vhost_msg)

        if not vhost_success:
            # Metadata is saved before the privileged work. If that work fails
            # (cancelled authentication, vhost error, database down), drop the
            # entry again so the project list never shows a half-created project.
            ProjectManager.delete_project(name)
            self._refresh_projects_list()
            self._set_form_status(
                "\n".join(lines) + "\n\nNo project was registered; fix the "
                "problem and try again.",
                "error",
            )
            return

        self._set_form_status("\n".join(lines), "ok")
        self._refresh_projects_list()

        self.create_project_btn.configure(state="disabled", text="Created")
        self.reset_project_btn.configure(state="disabled")
        self._cancel_pending_reset()
        self._form_reset_after = self.root.after(3000, self._reset_project_form)

    def _save_project_edit(self):
        name = self._editing_project
        project = ProjectManager.get_project(name) if name else None
        if not project:
            self._set_form_status("This project no longer exists.", "error")
            return

        path = self.project_path_var.get().strip()
        if not path:
            self._set_form_status("Please select a project folder.", "error")
            self.project_path_entry.focus_set()
            return

        document_root = path
        public_path = os.path.join(path, "public")
        if os.path.isdir(public_path):
            document_root = public_path

        custom_url = self.custom_url_var.get().strip()
        if custom_url:
            clean = self._hostname_from(custom_url)
            hostname = f"{clean}.local" if clean else None
        else:
            # Clearing the field means "derive it from the project name again".
            hostname = VHostManager.normalize_hostname(name)

        db_type = self.db_type_var.get()
        db_name = db_user = db_pass = None
        if db_type == "mysql":
            db_name = self.mysql_db_var.get().strip() or f"{name}_db"
            db_user = self.mysql_user_var.get().strip() or f"{name}_user"
            # Keep the existing password unless this project had none.
            db_pass = project.get("db_pass") or ProjectManager.generate_password()

        old_hostname = project.get("hostname")
        previous = (
            [old_hostname]
            if old_hostname and old_hostname != VHostManager.normalize_hostname(hostname)
            else []
        )

        mysql = None
        if db_type == "mysql":
            mysql = {
                "name": db_name,
                "user": db_user,
                "password": db_pass,
                "host": "127.0.0.1",
            }

        # Apply the system side first: if authentication is cancelled or the
        # vhost cannot be written, the saved metadata stays untouched.
        vhost_ok, vhost_msg = VHostManager.create_vhost(
            project_name=name,
            document_root=document_root,
            hostname=hostname,
            mysql=mysql,
            reload=True,
            previous_hostnames=previous,
        )
        if not vhost_ok:
            self._set_form_status(
                "Could not apply the changes; nothing was saved:\n" + vhost_msg,
                "warn",
            )
            return

        success, message, _updated = ProjectManager.update_project(
            name=name,
            document_root=document_root,
            hostname=hostname,
            db_type=db_type,
            db_name=db_name,
            db_user=db_user,
            db_pass=db_pass,
        )
        self._refresh_projects_list()

        if not success:
            self._set_form_status(
                "The virtual host was updated, but saving the project failed:\n"
                + message,
                "error",
            )
            return

        self._toast(f"Project '{name}' updated and virtual hosts reapplied.", "ok")
        self._reset_project_form()
        self._show_screen("projects")

    def _set_form_status(self, text, kind="ok"):
        style = {"ok": "OkText.TLabel", "warn": "WarnText.TLabel",
                 "error": "ErrorText.TLabel"}.get(kind, "OkText.TLabel")
        self.project_status_label.configure(text=text, style=style)

    def _cancel_project_form(self):
        self._cancel_pending_reset()
        self._reset_project_form()
        self._show_screen("projects")

    def _cancel_pending_reset(self):
        if self._form_reset_after is not None:
            try:
                self.root.after_cancel(self._form_reset_after)
            except tk.TclError:
                pass
            self._form_reset_after = None

    def _reset_project_form(self):
        self._cancel_pending_reset()
        self._editing_project = None
        for var in (
            self.project_name_var, self.project_path_var, self.custom_url_var,
            self.public_hint_var, self.mysql_db_var, self.mysql_user_var,
        ):
            var.set("")
        self.db_type_var.set("none")
        self.public_hint_label.configure(style="Hint.TLabel")
        self.project_status_label.configure(text="")
        self.project_name_entry.configure(state="normal")
        self.create_title_label.configure(text="New project")
        self.create_subtitle_label.configure(
            text="Create a folder, a virtual host and, if you want, a database."
        )
        self.create_project_btn.configure(state="normal", text="Create project")
        self.reset_project_btn.configure(
            state="normal", text="Reset", command=self._reset_project_form
        )
        self._update_url_preview()

    # ==================================================================
    # Project actions
    # ==================================================================

    def _open_selected_browser(self):
        project = self._get_selected_project()
        if not project:
            self._toast("Select a project first.", "warn")
            return

        url = f"http://{project['hostname']}"
        try:
            result = subprocess.run(["xdg-open", url], capture_output=True, timeout=5)
            if result.returncode == 0:
                return
        except (OSError, subprocess.SubprocessError):
            pass
        if not webbrowser.open(url):
            self._toast("Could not open a browser.", "error")

    def _open_selected_folder(self):
        project = self._get_selected_project()
        if not project:
            self._toast("Select a project first.", "warn")
            return
        if not ProjectManager.open_project_folder(project["name"]):
            self._toast("Could not open the project folder.", "error")

    def _delete_selected_project(self):
        project = self._get_selected_project()
        if not project:
            self._toast("Select a project first.", "warn")
            return

        db_type = ProjectManager.db_type_of(project)
        mysql = None
        if db_type == "mysql" and project.get("db_name") and project.get("db_user"):
            answer = messagebox.askyesnocancel(
                "Delete project",
                f"Delete project '{project['name']}'?\n\n"
                "This removes the LocalStack configuration but keeps your files.\n\n"
                f"Also delete the MySQL database '{project['db_name']}' "
                f"and user '{project['db_user']}'?\n\n"
                "Yes: delete the database and user\n"
                "No: keep the database and user\n"
                "Cancel: do nothing",
            )
            if answer is None:
                return
            if answer:
                mysql = {
                    "name": project["db_name"],
                    "user": project["db_user"],
                    "host": "127.0.0.1",
                }
        elif not messagebox.askyesno(
            "Delete project",
            f"Delete project '{project['name']}'?\n\n"
            "This removes the LocalStack configuration but keeps your files.",
        ):
            return

        # Use the stored hostname: deriving it from the project name misses
        # custom and de-duplicated names. The helper also reloads Apache in the
        # same privileged call, so deleting costs one password prompt.
        vhost_ok, vhost_msg = VHostManager.delete_vhost(
            project["name"], project.get("hostname"), reload=True, mysql=mysql
        )
        success, message = ProjectManager.delete_project(project["name"])
        if not vhost_ok:
            message += f"\n\nVirtual host: {vhost_msg}"
        if self._editing_project == project["name"]:
            self._reset_project_form()
        messagebox.showinfo("Result", message)
        self._refresh_projects_list()

    # ==================================================================
    # Service controls
    # ==================================================================

    def _apply_service_state(self, exists, active, pill_var, pill,
                             value, detail, unit):
        if not exists:
            pill_var.set("Not installed")
            pill.configure(style="BadBadge.TLabel")
            value.configure(text="Missing", style="StatBad.TLabel")
            detail.configure(text=f"{unit} not found")
        elif active:
            pill_var.set("Running")
            pill.configure(style="OkBadge.TLabel")
            value.configure(text="Running", style="StatGood.TLabel")
            detail.configure(text=f"{unit} active")
        else:
            pill_var.set("Stopped")
            pill.configure(style="WarnBadge.TLabel")
            value.configure(text="Stopped", style="StatWarn.TLabel")
            detail.configure(text=f"{unit} inactive")

    def _update_service_status(self):
        apache_exists, apache_active = SystemDetector.check_service("httpd")
        self._apply_service_state(
            apache_exists, apache_active, self.apache_pill_var, self.apache_pill,
            self.apache_stat_value, self.apache_stat_detail, "httpd.service",
        )

        mysql_unit = SystemDetector.MYSQL_SERVICE
        mysql_exists, mysql_active = SystemDetector.check_service(mysql_unit)
        self._apply_service_state(
            mysql_exists, mysql_active, self.mysql_pill_var, self.mysql_pill,
            self.mysql_stat_value, self.mysql_stat_detail, f"{mysql_unit}.service",
        )

        php_exists, php_active = SystemDetector.check_service("php-fpm")
        self._apply_service_state(
            php_exists, php_active, self.php_pill_var, self.php_pill,
            self.php_stat_value, self.php_stat_detail, "php-fpm.service",
        )

    def _run_service_action(self, action):
        try:
            success, message = action()
        except PrivilegeError as exc:
            self._toast(str(exc), "error")
            return
        self._toast(message, "ok" if success else "error")
        self._update_service_status()

    def _start_apache(self):
        self._run_service_action(VHostManager.start_httpd)

    def _stop_apache(self):
        self._run_service_action(VHostManager.stop_httpd)

    def _restart_apache(self):
        success, msg = VHostManager.stop_httpd()
        if not success:
            self._toast(msg, "error")
            self._update_service_status()
            return
        self.root.after(1000, lambda: self._run_service_action(
            VHostManager.start_httpd))

    def _enable_apache(self):
        self._run_service_action(VHostManager.enable_httpd)

    def _start_mysql(self):
        self._run_service_action(DBManager.start_mysql)

    def _stop_mysql(self):
        self._run_service_action(DBManager.stop_mysql)

    def _restart_mysql(self):
        success, msg = DBManager.stop_mysql()
        if not success:
            self._toast(msg, "error")
            self._update_service_status()
            return
        self.root.after(1000, lambda: self._run_service_action(
            DBManager.start_mysql))

    def _enable_mysql(self):
        self._run_service_action(DBManager.enable_mysql)

    def _php_action(self, verb, unit_label):
        try:
            ok, _out, err = privileged.run(
                ["service", "--action", verb, "--unit", "php-fpm"]
            )
            message = f"{unit_label} {verb}ed" if ok else f"Failed: {err}"
        except PrivilegeError as exc:
            self._toast(str(exc), "error")
            return
        self._toast(message, "ok" if ok else "error")
        self._update_service_status()

    def _start_php(self):
        self._php_action("start", "PHP-FPM")

    def _stop_php(self):
        self._php_action("stop", "PHP-FPM")

    def _restart_php(self):
        self._php_action("stop", "PHP-FPM")
        self.root.after(1000, lambda: self._php_action("start", "PHP-FPM"))

    # ==================================================================
    # Utilities
    # ==================================================================

    def _open_terminal(self):
        for terminal in (
            "x-terminal-emulator", "gnome-terminal", "konsole", "alacritty",
            "kitty", "foot", "xterm",
        ):
            result = subprocess.run(["which", terminal], capture_output=True, text=True)
            if result.returncode == 0:
                try:
                    subprocess.Popen([terminal])
                    return
                except OSError:
                    continue
        self._toast("No terminal emulator found.", "error")

    def _view_logs(self):
        project = self._get_selected_project()
        if not project:
            self._toast("Select a project to view its Apache error log.", "warn")
            return

        if project.get("hostname"):
            ok, output = VHostManager.read_error_log(project["hostname"], lines=200)
            title = f"Error log \u2014 {project['hostname']}"
            if ok:
                content = output or "(the log is empty)"
            else:
                content = output
            self._show_text_window(title, content)
            return

        messagebox.showinfo(
            "Logs",
            "Select a project to view its Apache error log.\n\n"
            "All logs live in /var/log/httpd/ (readable as root).",
        )

    def _show_text_window(self, title, content):
        win = tk.Toplevel(self.root)
        win.title(title)
        win.geometry("900x520")
        win.configure(background=self.theme.p["bg"])

        frame = ttk.Frame(win, style="Card.TFrame")
        frame.pack(fill="both", expand=True, padx=18, pady=18)

        text = tk.Text(
            frame, wrap="none", font="LSMono", relief="flat",
            borderwidth=0, highlightthickness=0, padx=12, pady=10,
        )
        self.theme.register_text(text)
        yscroll = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        xscroll = ttk.Scrollbar(frame, orient="horizontal", command=text.xview)
        text.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)

        yscroll.pack(side="right", fill="y")
        xscroll.pack(side="bottom", fill="x")
        text.pack(side="left", fill="both", expand=True, padx=(12, 0), pady=(12, 0))
        text.insert("1.0", content)
        text.configure(state="disabled")

    def _show_about(self):
        about_text = """LocalStack v0.1.0

A local web development environment manager for Linux.

Features:
\u2022 Automatic package detection & installation
\u2022 Virtual host management
\u2022 Project creation wizard
\u2022 MySQL & SQLite support
\u2022 Service management

Built with Python & tkinter.
        """
        messagebox.showinfo("About LocalStack", about_text.strip())
