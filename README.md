# 🦆 LocalStack

Disclaimer: This app is born out of my frustration for managing web projects in developement locally. 
Main idea was developped and scaffolded with Qwen3.6-35B-A3B locally, refined and fixed with Opus 5 

A **XAMPP-like local web development environment manager** for Fedora Linux.

> Finally, an easy way to set up Apache + PHP + MySQL locally on Linux!

## Features

- **📦 Auto-detect** — Checks if Apache, PHP (CLI + FPM), MySQL, SQLite are installed
- **🔧 Easy Install** — Installs missing packages with one click (uses dnf)
- **➕ Project Wizard** — Create projects with a simple form
- **🌐 Virtual Hosts** — Automatically creates Apache virtual host configs
- **🐘 Database Support** — Choose MySQL or SQLite per project
- **🔧 Service Manager** — Start/stop/restart Apache, MySQL, PHP-FPM
- **📁 Project Dashboard** — List, open, and manage all your projects

## Installation

### Prerequisites

```bash
# Install Python 3 and tkinter (usually pre-installed on Fedora)
sudo dnf install python3 python3-tkinter
```

### Run

```bash
cd localstack
./localstack
```

**Run it as your normal user — never with `sudo`.** LocalStack refuses to start
as root, on purpose. See [Privileges](#privileges) below.

## How It Works

### 1. System Tab
Checks your system for required packages:
- `httpd` (Apache Web Server)
- `php-cli` + `php-fpm` (PHP)
- `mysql-server` (MySQL Database)
- Various PHP extensions (gd, curl, xml, etc.)

Click **"Install Missing Packages"** to install everything you need.

### 2. New Project Tab
1. Enter a project name (e.g., `mywebsite`)
2. Select or create a project folder
3. Choose your database: None / SQLite / MySQL
4. Click **"Create Project"**

LocalStack will:
- Create the project folder with default files
- Set up an Apache virtual host at `http://mywebsite.local`
- Create a MySQL database (if selected)
- Add the hostname to `/etc/hosts`

### 3. Projects Tab
- See all your projects in one place
- Open any project in your browser
- Open the project folder in your file manager
- Delete projects (keeps your files!)

### 4. Services Tab
- Start/stop/restart Apache, MySQL, PHP-FPM
- Enable services to start on boot
- See current status of each service

## Project Structure

```
localstack/
├── main.py              # Entry point
├── requirements.txt     # Python dependencies
├── README.md            # This file
├── config/              # Configuration files (auto-created)
└── src/
    ├── __init__.py
    ├── detector.py      # Package detection
    ├── installer.py     # Package installation
    ├── vhost_manager.py # Apache virtual host management
    ├── project_manager.py # Project creation & management
    ├── db_manager.py    # Database management
    ├── privileged.py    # Escalates to the helper via pkexec
    ├── helper.py        # The ONLY code that runs as root
    └── ui.py            # Main GUI application
```

## Privileges

LocalStack never runs as root. The GUI runs as you; the small number of
operations that genuinely need root are delegated to `src/helper.py`, which is
re-invoked through **pkexec** (polkit) and prompts graphically.

Only these are privileged:

| Operation | Why root |
|---|---|
| Write/delete `/etc/httpd/conf.d/localstack_*.conf` | root-owned directory |
| Add/remove `/etc/hosts` entries | root-owned file |
| `semanage fcontext` / `restorecon` / `setsebool` | SELinux policy |
| `systemctl` on httpd, php-fpm, mysqld | system services |
| `dnf install` | package management |
| Reading `/var/log/httpd/*` | root-readable only |

The helper validates every argument it receives — hostnames and project names
against strict patterns, systemd units against an allowlist — because it is
called by an unprivileged process. It also runs `httpd -t` after writing a
vhost and rolls the file back if the config is invalid, so a bad project can
never take Apache down.

### Why not run the GUI as root?

Two concrete failures, both of which this project hit:

- Template files (`index.html`, `info.php`) get written into your project as
  **root-owned**, where they can shadow a real front controller.
- `projects.json` lands in `/root/.local/share/`, so your project list appears
  empty the next time you start normally.

## Configuration

Projects are stored in `~/.local/share/localstack/projects.json` (mode `0600` —
it holds generated database passwords). A store left behind at
`/var/lib/localstack/` or in `/root` by an older version is migrated on first run.

Virtual host configs are created in `/etc/httpd/conf.d/localstack_<name>.conf`.

## Troubleshooting

### HTTP 500 on a project that works elsewhere

Check your `.htaccess` for `php_value` / `php_flag`. Those are **mod_php**
directives, and Fedora serves PHP through **PHP-FPM**, where Apache does not
recognise them — an unknown directive in `.htaccess` is a hard 500.

```apache
<IfModule mod_php.c>
    php_value upload_max_filesize 256M
</IfModule>
```

…and put the real setting in a `.user.ini` next to your front controller, which
PHP-FPM reads:

```ini
upload_max_filesize = 256M
```

LocalStack scans for this when creating a vhost and warns you.

### HTTP 403 "Server unable to read htaccess file"

SELinux. Everything under `/home` is labelled `user_home_t`, which Apache may
not read. LocalStack fixes this with `semanage fcontext` + `restorecon` (which
survives a relabel, unlike `chcon`) and sets `httpd_enable_homedirs`. If it
still fails, check:

```bash
ls -Zd /path/to/docroot          # want httpd_sys_content_t
getsebool httpd_enable_homedirs  # want on
sudo ausearch -m avc -ts recent  # see what was actually denied
```

### Virtual host not working
1. Check Apache is running: `systemctl status httpd`
2. Check the config: `sudo httpd -t`
3. Reload Apache: `systemctl reload httpd`
4. Confirm the hostname resolves: `getent hosts myproject.local`

### MySQL connection fails
1. Make sure MySQL is running: `systemctl status mysqld`
2. Check credentials in the project folder's `db-test.php`

### Authentication dialog never appears
You need a polkit agent running. On a bare WM, install one
(`polkit-gnome`, `lxpolkit`, …) or start LocalStack from a terminal, where it
falls back to `sudo`.

## Future Enhancements

- [ ] SSL/HTTPS support with Let's Encrypt
- [ ] Import/Export project configurations
- [ ] PHP version selection
- [ ] Database import/export (SQL)
- [ ] Project templates (WordPress, Laravel, etc.)
- [x] Log viewer (per-project Apache error log)
- [ ] Dark theme
- [ ] System tray icon
- [ ] Flatpak packaging

## License

MIT License - feel free to use and modify!

## Contributing

Pull requests welcome! This is a project born from the frustration of "why is there no XAMPP for Linux?"

---

_Built with ❤️ for the Fedora community_
