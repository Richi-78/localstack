"""
LocalStack UI - Main GUI application using tkinter.
A clean, intuitive interface for managing local web development environments.
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
import webbrowser
import os
import subprocess

from src import privileged
from src.detector import SystemDetector, PackageStatus
from src.installer import PackageInstaller
from src.vhost_manager import VHostManager
from src.project_manager import ProjectManager
from src.db_manager import DBManager
from src.privileged import PrivilegeError


class LocalStackApp:
    """Main LocalStack application window."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("LocalStack - Local Web Dev Environment")
        self.root.geometry("900x700")
        self.root.minsize(800, 600)

        # Style configuration
        self._setup_styles()

        # Build UI
        self._create_menu()
        self._create_header()
        self._create_notebook()
        self._create_status_bar()

        # Auto-detect on startup
        self._detect_system()

    def _setup_styles(self):
        """Configure ttk styles for a modern look."""
        style = ttk.Style()

        # Try to use a modern theme
        available_themes = style.theme_names()
        if 'clam' in available_themes:
            style.theme_use('clam')
        elif 'azure' in available_themes:
            style.theme_use('azure')

        # Custom colors
        style.configure('Header.TFrame', background='#2c3e50')
        style.configure('Title.TLabel', font=('Helvetica', 16, 'bold'), foreground='white')
        style.configure('Subtitle.TLabel', font=('Helvetica', 9), foreground='#bdc3c7')
        style.configure('Status.TLabelframe', background='#ecf0f1')
        style.configure('Status.TLabelframe.Label', font=('Helvetica', 10, 'bold'), foreground='#2c3e50')

        # Button styles
        style.configure('Install.TButton', font=('Helvetica', 9, 'bold'))
        style.map('Install.TButton', foreground=[('active', '#fff')], background=[('active', '#27ae60')])

        style.configure('Danger.TButton', font=('Helvetica', 9, 'bold'))
        style.map('Danger.TButton', foreground=[('active', '#fff')], background=[('active', '#e74c3c')])

        style.configure('Action.TButton', font=('Helvetica', 9))
        style.map('Action.TButton', background=[('active', '#3498db')])

    def _create_menu(self):
        """Create application menu bar."""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Exit", command=self.root.quit)

        # Tools menu
        tools_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Tools", menu=tools_menu)
        tools_menu.add_command(label="Open Terminal", command=self._open_terminal)
        tools_menu.add_command(label="View Logs", command=self._view_logs)
        tools_menu.add_command(label="Refresh System Status", command=self._detect_system)

        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="About LocalStack", command=self._show_about)

    def _create_header(self):
        """Create the app header."""
        header = ttk.Frame(self.root, style='Header.TFrame')
        header.pack(fill='x', padx=0, pady=0)

        title = ttk.Label(header, text="🦆 LocalStack", style='Title.TLabel')
        title.pack(side='left', padx=20, pady=10)

        subtitle = ttk.Label(header, text="Local Web Development Environment", style='Subtitle.TLabel')
        subtitle.pack(side='left', padx=5, pady=10)

    def _create_notebook(self):
        """Create the main tabbed interface."""
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill='both', expand=True, padx=10, pady=5)

        # Tab 1: System Status
        self.tab_system = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_system, text="  📊 System  ")
        self._create_system_tab()

        # Tab 2: Create Project
        self.tab_create = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_create, text="  ➕ New Project  ")
        self._create_project_tab()

        # Tab 3: Projects
        self.tab_projects = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_projects, text="  📁 Projects  ")
        self._create_projects_tab()

        # Tab 4: Services
        self.tab_services = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_services, text="  🔧 Services  ")
        self._create_services_tab()

    def _create_system_tab(self):
        """Create the system status tab."""
        # Instructions
        instructions = """
Welcome to LocalStack! This tool helps you set up a local web development
environment, similar to XAMPP on Windows.

Quick Start:
1. Check the System tab for required packages
2. Install any missing packages
3. Go to "New Project" to create your first site
4. Manage projects and services from the other tabs
        """

        info_frame = ttk.LabelFrame(self.tab_system, text="ℹ️ Getting Started", padding=10)
        info_frame.pack(fill='x', padx=10, pady=10)

        info_text = tk.Text(info_frame, height=8, wrap='word', font=('monospace', 9), state='disabled')
        info_text.pack(fill='x')
        info_text.insert('1.0', instructions.strip())
        info_text.config(state='disabled')

        # Package status
        pkg_frame = ttk.LabelFrame(self.tab_system, text="📦 Package Status", padding=10)
        pkg_frame.pack(fill='both', expand=True, padx=10, pady=10)

        # Create treeview for packages
        columns = ('package', 'status', 'version')
        self.pkg_tree = ttk.Treeview(pkg_frame, columns=columns, show='headings', height=12)

        self.pkg_tree.heading('package', text='Package')
        self.pkg_tree.heading('status', text='Status')
        self.pkg_tree.heading('version', text='Version')

        self.pkg_tree.column('package', width=250)
        self.pkg_tree.column('status', width=120)
        self.pkg_tree.column('version', width=150)

        scrollbar = ttk.Scrollbar(pkg_frame, orient='vertical', command=self.pkg_tree.yview)
        self.pkg_tree.configure(yscrollcommand=scrollbar.set)

        self.pkg_tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

        # Install button
        btn_frame = ttk.Frame(self.tab_system)
        btn_frame.pack(fill='x', padx=10, pady=10)

        self.install_btn = ttk.Button(
            btn_frame,
            text="🔧 Install Missing Packages",
            command=self._install_missing,
            style='Install.TButton',
        )
        self.install_btn.pack(side='left', padx=5)

        self.refresh_btn = ttk.Button(
            btn_frame,
            text="🔄 Refresh",
            command=self._detect_system,
        )
        self.refresh_btn.pack(side='right', padx=5)

        self.pkg_status_label = ttk.Label(btn_frame, text="", foreground='gray')
        self.pkg_status_label.pack(side='right', padx=10)

    def _create_project_tab(self):
        """Create the new project creation tab."""
        # Form frame
        form_frame = ttk.LabelFrame(self.tab_create, text="✨ Create New Project", padding=15)
        form_frame.pack(fill='x', padx=10, pady=10)

        # Project Name
        ttk.Label(form_frame, text="Project Name:").grid(row=0, column=0, sticky='w', pady=5)
        self.project_name_var = tk.StringVar()
        self.project_name_entry = ttk.Entry(form_frame, textvariable=self.project_name_var, width=40)
        self.project_name_entry.grid(row=0, column=1, sticky='ew', pady=5, padx=5)
        ttk.Label(form_frame, text="(letters, numbers, hyphens only)", foreground='gray').grid(row=0, column=2, sticky='w', pady=5)

        # Custom URL
        ttk.Label(form_frame, text="Local URL:").grid(row=2, column=0, sticky='w', pady=5)
        self.custom_url_var = tk.StringVar()
        url_frame = ttk.Frame(form_frame)
        url_frame.grid(row=2, column=1, sticky='w', pady=5, padx=5)

        ttk.Entry(url_frame, textvariable=self.custom_url_var, width=30).pack(side='left', fill='x', expand=True)
        ttk.Label(url_frame, text=".local", foreground='gray').pack(side='left')
        ttk.Label(form_frame, text="(leave blank for auto-generated)", foreground='gray').grid(row=2, column=2, sticky='w', pady=5)

        # Document Root
        ttk.Label(form_frame, text="Project Folder:").grid(row=3, column=0, sticky='w', pady=5)
        self.project_path_var = tk.StringVar()
        self.project_path_entry = ttk.Entry(form_frame, textvariable=self.project_path_var, width=50)
        self.project_path_entry.grid(row=3, column=1, sticky='ew', pady=5, padx=5)

        browse_btn = ttk.Button(form_frame, text="Browse...", command=self._browse_project_path)
        browse_btn.grid(row=3, column=2, sticky='w', pady=5, padx=5)

        # Auto-detect public folder hint
        self.public_hint_var = tk.StringVar(value="")
        ttk.Label(form_frame, textvariable=self.public_hint_var, foreground='#3498db').grid(row=4, column=1, sticky='w', pady=2, padx=5)

        # Database Type
        ttk.Label(form_frame, text="Database:").grid(row=5, column=0, sticky='w', pady=5)

        self.db_type_var = tk.StringVar(value="none")
        db_frame = ttk.Frame(form_frame)
        db_frame.grid(row=5, column=1, sticky='w', pady=5, padx=5)

        ttk.Radiobutton(db_frame, text="None (SQLite)", variable=self.db_type_var, value="none").pack(side='left')
        ttk.Radiobutton(db_frame, text="MySQL", variable=self.db_type_var, value="mysql").pack(side='left', padx=15)
        ttk.Radiobutton(db_frame, text="SQLite", variable=self.db_type_var, value="sqlite").pack(side='left')

        # MySQL settings (shown when MySQL selected)
        self.mysql_settings = ttk.Frame(form_frame)
        self.mysql_settings.grid(row=6, column=1, sticky='w', pady=5, padx=5)

        ttk.Label(self.mysql_settings, text="DB Name:").pack(side='left', padx=(0, 5))
        self.mysql_db_var = tk.StringVar()
        self.mysql_db_entry = ttk.Entry(self.mysql_settings, textvariable=self.mysql_db_var, width=15)
        self.mysql_db_entry.pack(side='left', padx=5)

        ttk.Label(self.mysql_settings, text="User:").pack(side='left', padx=(10, 5))
        self.mysql_user_var = tk.StringVar()
        self.mysql_user_entry = ttk.Entry(self.mysql_settings, textvariable=self.mysql_user_var, width=15)
        self.mysql_user_entry.pack(side='left', padx=5)

        # Create button
        create_frame = ttk.Frame(form_frame)
        create_frame.grid(row=7, column=0, columnspan=3, pady=15)

        self.create_project_btn = ttk.Button(
            create_frame,
            text="🚀 Create Project",
            command=self._create_project,
            style='Install.TButton',
        )
        self.create_project_btn.pack(padx=5)

        self.project_status_label = ttk.Label(form_frame, text="", foreground='gray')
        self.project_status_label.grid(row=8, column=0, columnspan=3, pady=5)

        # Register trace to show/hide MySQL settings
        self.db_type_var.trace_add('write', lambda *args: self._toggle_mysql_settings())

    def _toggle_mysql_settings(self):
        """Show/hide MySQL settings based on database type."""
        if self.db_type_var.get() == "mysql":
            self.mysql_settings.grid(row=6, column=1, sticky='w', pady=5, padx=5)
        else:
            self.mysql_settings.grid_remove()

    def _create_projects_tab(self):
        """Create the projects list tab."""
        # Header with actions
        header_frame = ttk.Frame(self.tab_projects)
        header_frame.pack(fill='x', padx=10, pady=5)

        ttk.Label(header_frame, text="Your Projects", font=('Helvetica', 12, 'bold')).pack(side='left')

        refresh_btn = ttk.Button(header_frame, text="🔄 Refresh", command=self._refresh_projects_list)
        refresh_btn.pack(side='right', padx=5)
        
        self.reapply_vhost_btn = ttk.Button(
            header_frame, text="🔄 Reapply VHosts", command=self._reapply_vhosts
        )
        self.reapply_vhost_btn.pack(side='right', padx=5)

        # Projects treeview
        proj_frame = ttk.Frame(self.tab_projects)
        proj_frame.pack(fill='both', expand=True, padx=10, pady=5)

        columns = ('name', 'url', 'database', 'status')
        self.proj_tree = ttk.Treeview(proj_frame, columns=columns, show='headings', height=15)

        self.proj_tree.heading('name', text='Project')
        self.proj_tree.heading('url', text='URL')
        self.proj_tree.heading('database', text='Database')
        self.proj_tree.heading('status', text='Status')

        self.proj_tree.column('name', width=150)
        self.proj_tree.column('url', width=300)
        self.proj_tree.column('database', width=100)
        self.proj_tree.column('status', width=100)

        scrollbar = ttk.Scrollbar(proj_frame, orient='vertical', command=self.proj_tree.yview)
        self.proj_tree.configure(yscrollcommand=scrollbar.set)

        self.proj_tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

        # Action buttons
        action_frame = ttk.Frame(self.tab_projects)
        action_frame.pack(fill='x', padx=10, pady=5)

        self.open_browser_btn = ttk.Button(action_frame, text="🌐 Open in Browser", command=self._open_selected_browser)
        self.open_browser_btn.pack(side='left', padx=2)

        self.open_folder_btn = ttk.Button(action_frame, text="📂 Open Folder", command=self._open_selected_folder)
        self.open_folder_btn.pack(side='left', padx=2)

        self.delete_proj_btn = ttk.Button(action_frame, text="🗑️ Delete", command=self._delete_selected_project, style='Danger.TButton')
        self.delete_proj_btn.pack(side='right', padx=2)

        self.proj_tree.bind('<Double-1>', lambda e: self._open_selected_browser())

        # Populate
        self._refresh_projects_list()

    def _create_services_tab(self):
        """Create the services management tab."""
        # Apache section
        apache_frame = ttk.LabelFrame(self.tab_services, text="🌐 Apache Web Server", padding=10)
        apache_frame.pack(fill='x', padx=10, pady=5)

        self.apache_status_var = tk.StringVar(value="Checking...")
        self.apache_status_label = ttk.Label(apache_frame, textvariable=self.apache_status_var)
        self.apache_status_label.pack(side='left', padx=5)

        apache_btns = ttk.Frame(apache_frame)
        apache_btns.pack(side='right')

        self.apache_start_btn = ttk.Button(apache_btns, text="▶ Start", command=self._start_apache)
        self.apache_start_btn.pack(side='left', padx=2)

        self.apache_stop_btn = ttk.Button(apache_btns, text="⏹ Stop", command=self._stop_apache)
        self.apache_stop_btn.pack(side='left', padx=2)

        self.apache_restart_btn = ttk.Button(apache_btns, text="🔄 Restart", command=self._restart_apache)
        self.apache_restart_btn.pack(side='left', padx=2)

        self.apache_enable_btn = ttk.Button(apache_btns, text="⚡ Enable on Boot", command=self._enable_apache)
        self.apache_enable_btn.pack(side='left', padx=2)

        # MySQL section
        mysql_frame = ttk.LabelFrame(self.tab_services, text="🐘 MySQL Database", padding=10)
        mysql_frame.pack(fill='x', padx=10, pady=5)

        self.mysql_status_var = tk.StringVar(value="Checking...")
        self.mysql_status_label = ttk.Label(mysql_frame, textvariable=self.mysql_status_var)
        self.mysql_status_label.pack(side='left', padx=5)

        mysql_btns = ttk.Frame(mysql_frame)
        mysql_btns.pack(side='right')

        self.mysql_start_btn = ttk.Button(mysql_btns, text="▶ Start", command=self._start_mysql)
        self.mysql_start_btn.pack(side='left', padx=2)

        self.mysql_stop_btn = ttk.Button(mysql_btns, text="⏹ Stop", command=self._stop_mysql)
        self.mysql_stop_btn.pack(side='left', padx=2)

        self.mysql_restart_btn = ttk.Button(mysql_btns, text="🔄 Restart", command=self._restart_mysql)
        self.mysql_restart_btn.pack(side='left', padx=2)

        self.mysql_enable_btn = ttk.Button(mysql_btns, text="⚡ Enable on Boot", command=self._enable_mysql)
        self.mysql_enable_btn.pack(side='left', padx=2)

        # PHP-FPM section
        php_frame = ttk.LabelFrame(self.tab_services, text="🐘 PHP-FPM", padding=10)
        php_frame.pack(fill='x', padx=10, pady=5)

        self.php_status_var = tk.StringVar(value="Checking...")
        self.php_status_label = ttk.Label(php_frame, textvariable=self.php_status_var)
        self.php_status_label.pack(side='left', padx=5)

        php_btns = ttk.Frame(php_frame)
        php_btns.pack(side='right')

        self.php_start_btn = ttk.Button(php_btns, text="▶ Start", command=self._start_php)
        self.php_start_btn.pack(side='left', padx=2)

        self.php_stop_btn = ttk.Button(php_btns, text="⏹ Stop", command=self._stop_php)
        self.php_stop_btn.pack(side='left', padx=2)

        self.php_restart_btn = ttk.Button(php_btns, text="🔄 Restart", command=self._restart_php)
        self.php_restart_btn.pack(side='left', padx=2)

    def _create_status_bar(self):
        """Create the status bar at the bottom."""
        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief='sunken', anchor='w')
        status_bar.pack(fill='x', side='bottom', padx=0, pady=0)

    # ========== Event Handlers ==========

    def _detect_system(self):
        """Detect system packages and update UI."""
        self.status_var.set("Detecting system packages...")
        self.root.update()

        results = SystemDetector.check_all()
        self._update_package_tree(results)

        # Update service status
        self._update_service_status()

        missing_count = sum(1 for p in results.values() if p.status == PackageStatus.NOT_INSTALLED)
        installed_count = sum(1 for p in results.values() if p.status == PackageStatus.INSTALLED)

        self.pkg_status_label.config(text=f"{installed_count} installed, {missing_count} missing")

        if missing_count > 0:
            self.install_btn.config(state='normal')
        else:
            self.install_btn.config(state='disabled')

        self.status_var.set(f"Detected: {installed_count} packages installed, {missing_count} missing")

    def _update_package_tree(self, results: dict):
        """Update the package treeview with detection results."""
        # Clear existing
        for item in self.pkg_tree.get_children():
            self.pkg_tree.delete(item)

        for name, info in results.items():
            status_text = "✓ Installed" if info.status == PackageStatus.INSTALLED else "✗ Missing"
            status_color = "#27ae60" if info.status == PackageStatus.INSTALLED else "#e74c3c"
            version = info.version if info.version else ("(service: " + (info.service_name or "none") + ")")

            self.pkg_tree.insert('', 'end', values=(name, status_text, version))

    def _install_missing(self):
        """Install missing packages."""
        results = SystemDetector.check_all()
        missing = [name for name, info in results.items() if info.status == PackageStatus.NOT_INSTALLED]

        if not missing:
            messagebox.showinfo("LocalStack", "All packages are already installed!")
            return

        # Show confirmation
        msg = f"The following packages will be installed:\n\n" + "\n".join(f"  • {results[m].name}" for m in missing) + "\n\nYou will be asked for your password."
        if not messagebox.askyesno("Install Packages", msg):
            return

        self.status_var.set("Installing packages... This may take a moment.")
        self.install_btn.config(state='disabled')

        # Run in thread to not block UI
        def install_thread():
            success, installed = PackageInstaller.install_missing(results, missing)

            if success:
                self.root.after(0, lambda: messagebox.showinfo("Success", f"Successfully installed: {', '.join(installed)}"))
            else:
                self.root.after(0, lambda: messagebox.showerror("Error", f"Installation failed. Check the terminal for details."))

            self.root.after(0, self._detect_system)

        threading.Thread(target=install_thread, daemon=True).start()

    def _browse_project_path(self):
        """Open folder browser for project path."""
        path = filedialog.askdirectory()
        if path:
            self.project_path_var.set(path)
            # Auto-detect public/ folder
            public_path = os.path.join(path, "public")
            if os.path.isdir(public_path):
                self.public_hint_var.set(f"💡 Found 'public' folder — will use it as document root")
            else:
                self.public_hint_var.set(f"💡 No 'public' folder found — will use project root")
            self.root.update()

    def _create_project(self):
        """Create a new project."""
        name = self.project_name_var.get().strip()
        path = self.project_path_var.get().strip()
        custom_url = self.custom_url_var.get().strip()

        if not name:
            messagebox.showerror("Error", "Please enter a project name.")
            return

        if not path:
            messagebox.showerror("Error", "Please select a project folder.")
            return

        use_mysql = self.db_type_var.get() == "mysql"

        # Get MySQL settings if needed
        db_name = None
        db_user = None
        db_pass = None

        if use_mysql:
            db_name = self.mysql_db_var.get().strip() or f"{name}_db"
            db_user = self.mysql_user_var.get().strip() or f"{name}_user"

        # Determine document root (prefer public/ folder)
        document_root = path
        public_path = os.path.join(path, "public")
        if os.path.isdir(public_path):
            document_root = public_path

        # Determine hostname
        hostname = None
        if custom_url:
            # Clean and validate custom URL
            clean = custom_url.lower().replace(" ", "-").strip().rstrip('.')
            # The UI shows `.local` as a suffix, but also accept a complete
            # hostname pasted by the user.  Previously this produced
            # `site.local.local`, which never matched /etc/hosts.
            if clean.endswith('.local'):
                clean = clean[:-len('.local')]
            clean = "".join(c for c in clean if c.isalnum() or c == '-')
            if clean:
                hostname = f"{clean}.local"

        # Create project
        success, message, project_data = ProjectManager.create_project(
            name=name,
            document_root=document_root,
            use_mysql=use_mysql,
            db_name=db_name,
            db_user=db_user,
            hostname=hostname,
        )

        if success:
            actual_url = project_data.get("hostname", f"{name}.local")
            self.project_status_label.config(text=f"✅ {message}\n🌐 URL: http://{actual_url}", foreground='#27ae60')

            # Create virtual host
            vhost_success, vhost_msg = VHostManager.create_vhost(
                project_name=name,
                document_root=document_root,
                hostname=hostname,
            )
            if vhost_success:
                # Apache does not read new files in conf.d until it is
                # reloaded.  Without this, requests are handled by Fedora's
                # default welcome virtual host.
                reload_success, reload_msg = VHostManager.reload_httpd()
                if reload_success:
                    vhost_status = "✅ Virtual host created and Apache reloaded!"
                    status_color = '#27ae60'
                else:
                    vhost_status = f"⚠️ Virtual host created, but Apache was not reloaded: {reload_msg}"
                    status_color = '#f39c12'

                # create_vhost appends notes (SELinux problems, .htaccess
                # directives that will 500) after the first line. Showing them
                # is the whole point of collecting them.
                notes = vhost_msg.split("\n", 1)
                if len(notes) > 1:
                    vhost_status += "\n⚠️ " + notes[1].strip()
                    status_color = '#f39c12'

                self.project_status_label.config(
                    text=f"✅ {message}\n🌐 URL: http://{actual_url}\n{vhost_status}",
                    foreground=status_color
                )
            else:
                self.project_status_label.config(
                    text=f"✅ {message}\n🌐 URL: http://{actual_url}\n⚠️ Virtual host creation failed: {vhost_msg}",
                    foreground='#f39c12'
                )

            # Create database if MySQL
            if use_mysql:
                db_success, db_msg = DBManager.create_mysql_db(
                    db_name=db_name,
                    db_user=db_user,
                    db_pass=project_data.get("db_pass", ""),
                )
                if db_success:
                    self.project_status_label.config(text=message + "\n✅ Database created!", foreground='#27ae60')
                else:
                    self.project_status_label.config(
                        text=message + "\n⚠️ Database creation failed: " + db_msg,
                        foreground='#f39c12'
                    )

            # Refresh projects list
            self._refresh_projects_list()

            # Update button state
            self.create_project_btn.config(state='disabled')
            # ttk.Button does not support a foreground option on all Tk themes.
            # Passing it raised TclError and interrupted the rest of the callback.
            self.create_project_btn.config(text="✅ Created!")

            # Reset form after delay
            self.root.after(3000, self._reset_project_form)
        else:
            self.project_status_label.config(text="❌ " + message, foreground='#e74c3c')

    def _reset_project_form(self):
        """Reset the project creation form."""
        self.project_name_var.set("")
        self.project_path_var.set("")
        self.custom_url_var.set("")
        self.public_hint_var.set("")
        self.db_type_var.set("none")
        self.project_status_label.config(text="")
        self.create_project_btn.config(state='normal')
        self.create_project_btn.config(text="🚀 Create Project")

    def _refresh_projects_list(self):
        """Refresh the projects list."""
        for item in self.proj_tree.get_children():
            self.proj_tree.delete(item)

        projects = ProjectManager.list_projects()
        for proj in projects:
            db_type = "MySQL" if proj.get("use_mysql") else ("SQLite" if proj.get("db_name") else "None")
            status = proj.get("status", "created")
            status_icon = "●" if status == "running" else "○"
            hostname = proj.get("hostname", f"{proj['name']}.local")
            doc_root = proj.get("document_root", "")

            self.proj_tree.insert('', 'end', values=(
                proj["name"],
                f"http://{hostname}\n{doc_root}",
                db_type,
                f"{status_icon} {status}",
            ))

    def _reapply_vhosts(self):
        """Regenerate all vhost configs and reload Apache."""
        from src.vhost_manager import VHostManager
        success, msg = VHostManager.regenerate_all()
        if success:
            messagebox.showinfo("VHosts Reapplied", msg)
        else:
            messagebox.showerror("Error", msg)

    def _get_selected_project(self):
        """Get the selected project from the tree."""
        selection = self.proj_tree.selection()
        if not selection:
            return None
        item = self.proj_tree.item(selection[0])
        project_name = item['values'][0]
        return ProjectManager.get_project(project_name)

    def _open_selected_browser(self):
        """Open selected project in system default browser."""
        project = self._get_selected_project()
        if not project:
            messagebox.showinfo("Info", "Please select a project first.")
            return

        url = f"http://{project['hostname']}"

        # LocalStack always runs as the desktop user, so a plain xdg-open works
        # and inherits the right DISPLAY / WAYLAND_DISPLAY.
        try:
            result = subprocess.run(
                ['xdg-open', url], capture_output=True, timeout=5
            )
            if result.returncode == 0:
                return
        except (OSError, subprocess.SubprocessError):
            pass

        webbrowser.open(url)

    def _open_selected_folder(self):
        """Open selected project folder."""
        project = self._get_selected_project()
        if not project:
            messagebox.showinfo("Info", "Please select a project first.")
            return

        ProjectManager.open_project_folder(project["name"])

    def _delete_selected_project(self):
        """Delete selected project."""
        project = self._get_selected_project()
        if not project:
            messagebox.showinfo("Info", "Please select a project first.")
            return

        if messagebox.askyesno("Delete Project", f"Delete project '{project['name']}'?\n\nThis removes the LocalStack configuration but keeps your files."):
            # Remove the vhost first, passing the *stored* hostname -- deriving
            # it from the project name misses custom and de-duplicated names.
            vhost_ok, vhost_msg = VHostManager.delete_vhost(
                project["name"], project.get("hostname")
            )
            success, message = ProjectManager.delete_project(project["name"])
            if vhost_ok:
                VHostManager.reload_httpd()
            else:
                message += f"\n\nVirtual host: {vhost_msg}"
            messagebox.showinfo("Result", message)
            self._refresh_projects_list()

    # ========== Service Controls ==========

    def _update_service_status(self):
        """Update service status labels."""
        # Apache
        apache_exists, apache_active = SystemDetector.check_service("httpd")
        if not apache_exists:
            self.apache_status_var.set("✗ Apache not installed")
            self.apache_status_label.config(foreground='#e74c3c')
        elif apache_active:
            self.apache_status_var.set("● Apache running")
            self.apache_status_label.config(foreground='#27ae60')
        else:
            self.apache_status_var.set("○ Apache stopped")
            self.apache_status_label.config(foreground='#f39c12')

        # MySQL
        mysql_exists, mysql_active = SystemDetector.check_service(SystemDetector.MYSQL_SERVICE)
        if not mysql_exists:
            self.mysql_status_var.set("✗ MySQL not installed")
            self.mysql_status_label.config(foreground='#e74c3c')
        elif mysql_active:
            self.mysql_status_var.set("● MySQL running")
            self.mysql_status_label.config(foreground='#27ae60')
        else:
            self.mysql_status_var.set("○ MySQL stopped")
            self.mysql_status_label.config(foreground='#f39c12')

        # PHP-FPM
        php_exists, php_active = SystemDetector.check_service("php-fpm")
        if not php_exists:
            self.php_status_var.set("✗ PHP-FPM not installed")
            self.php_status_label.config(foreground='#e74c3c')
        elif php_active:
            self.php_status_var.set("● PHP-FPM running")
            self.php_status_label.config(foreground='#27ae60')
        else:
            self.php_status_var.set("○ PHP-FPM stopped")
            self.php_status_label.config(foreground='#f39c12')

    def _start_apache(self):
        success, msg = VHostManager.start_httpd()
        messagebox.showinfo("Apache", msg)
        self._update_service_status()

    def _stop_apache(self):
        success, msg = VHostManager.stop_httpd()
        messagebox.showinfo("Apache", msg)
        self._update_service_status()

    def _restart_apache(self):
        self._stop_apache()
        self.root.after(1000, self._start_apache)

    def _enable_apache(self):
        success, msg = VHostManager.enable_httpd()
        messagebox.showinfo("Apache", msg)

    def _start_mysql(self):
        success, msg = DBManager.start_mysql()
        messagebox.showinfo("MySQL", msg)
        self._update_service_status()

    def _stop_mysql(self):
        success, msg = DBManager.stop_mysql()
        messagebox.showinfo("MySQL", msg)
        self._update_service_status()

    def _restart_mysql(self):
        self._stop_mysql()
        self.root.after(1000, self._start_mysql)

    def _enable_mysql(self):
        success, msg = DBManager.enable_mysql()
        messagebox.showinfo("MySQL", msg)

    def _start_php(self):
        try:
            ok, _out, err = privileged.run(["service", "--action", "start", "--unit", "php-fpm"])
            msg = "PHP-FPM started" if ok else f"Failed: {err}"
        except PrivilegeError as exc:
            msg = str(exc)
        messagebox.showinfo("PHP-FPM", msg)
        self._update_service_status()

    def _stop_php(self):
        try:
            ok, _out, err = privileged.run(["service", "--action", "stop", "--unit", "php-fpm"])
            msg = "PHP-FPM stopped" if ok else f"Failed: {err}"
        except PrivilegeError as exc:
            msg = str(exc)
        messagebox.showinfo("PHP-FPM", msg)
        self._update_service_status()

    def _restart_php(self):
        self._stop_php()
        self.root.after(1000, self._start_php)

    # ========== Utility ==========

    def _open_terminal(self):
        """Open a terminal."""
        # Try common terminals; fall back gracefully
        for term in ['gnome-terminal', 'konsole', 'xterm', 'alacritty']:
            result = subprocess.run(['which', term], capture_output=True, text=True)
            if result.returncode == 0:
                subprocess.Popen([term])
                return
        # Last resort: try xdg-open on a terminal .desktop file
        try:
            webbrowser.open('xdg-terminal-exec')
        except Exception:
            pass

    def _view_logs(self):
        """Open Apache logs directory."""
        project = self._get_selected_project()

        # /var/log/httpd is root-only, so read the selected project's error log
        # through the helper rather than trying to open the directory.
        if project and project.get("hostname"):
            ok, output = VHostManager.read_error_log(project["hostname"], lines=200)
            title = f"Error log - {project['hostname']}"
            self._show_text_window(title, output or "(log is empty)" if ok else output)
            return

        messagebox.showinfo(
            "Logs",
            "Select a project to view its Apache error log.\n\n"
            "All logs live in /var/log/httpd/ (readable as root).",
        )

    def _show_text_window(self, title: str, content: str):
        """Show read-only text in a scrollable window."""
        win = tk.Toplevel(self.root)
        win.title(title)
        win.geometry("900x500")
        text = tk.Text(win, wrap='none', font=('monospace', 9))
        yscroll = ttk.Scrollbar(win, orient='vertical', command=text.yview)
        xscroll = ttk.Scrollbar(win, orient='horizontal', command=text.xview)
        text.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        yscroll.pack(side='right', fill='y')
        xscroll.pack(side='bottom', fill='x')
        text.pack(side='left', fill='both', expand=True)
        text.insert('1.0', content)
        text.configure(state='disabled')

    def _show_about(self):
        """Show about dialog."""
        about_text = """LocalStack v0.1.0

A local web development environment manager for Linux.

Features:
• Automatic package detection & installation
• Virtual host management
• Project creation wizard
• MySQL & SQLite support
• Service management

Built with Python & tkinter.
        """
        messagebox.showinfo("About LocalStack", about_text.strip())
