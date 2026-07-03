# Employee Attendance Management System (Django + MySQL)

## Features
- Custom user model with **employee_id** login
- Roles: **admin (HR)** and **employee**
- Employee: check-in (once/day), check-out, today status, history
- Admin: employee CRUD, attendance filters, stats, CSV/PDF export

## Setup

1) Install dependencies

```bash
pip install -r requirements.txt
```

2) Install and start **MySQL** (XAMPP, WAMP, or MySQL Server). MySQL is the **default** database for this project.

3) Set your MySQL password (PowerShell example):

```powershell
$env:DB_NAME="attendance_db"
$env:DB_USER="root"
$env:DB_PASSWORD="your_mysql_password"
$env:DB_HOST="127.0.0.1"
$env:DB_PORT="3306"
```

Optional env vars (see `.env.example`):

```powershell
$env:DJANGO_DEBUG="1"
$env:DJANGO_SECRET_KEY="your-secret-key"
$env:DJANGO_ALLOWED_HOSTS="localhost,127.0.0.1"
```

4) Create the database and run migrations:

```bash
python manage.py create_mysql_db
python manage.py migrate
```

If you already have data in SQLite, export/import separately or run `migrate` on a fresh MySQL database.

5) Create an HR admin user (or use `/setup/` on first run):

```bash
python manage.py createsuperuser
```

When prompted, enter:
- **employee_id** (e.g. `HR001`)
- **username** (name)
- password

6) Run the server

```bash
python manage.py runserver
```

## Seed Indian holidays (starter set)

```bash
python manage.py seed_indian_holidays --year 2026
```

## URLs
- **Home (portal picker):** `/` — always shows the landing page with Employee / HR / CEO / Director options
- Employee login: `/employee/login/`
- HR login: `/hr/login/`
- Initial setup (first HR admin only): `/setup/`
- Employee dashboard: `/employee/dashboard/`
- HR dashboard: `/hr/dashboard/`
- Django admin: `/admin/`

---

## Deploy for everyone in the office (LAN)

Use one **office PC or laptop** as the server. All employees open the same URL in their browser.

### Step 1 — One-time server setup

On the server PC:

```bash
pip install -r requirements.txt
pip install -r requirements-prod.txt
```

Copy `.env.example` to `.env` and set MySQL password, then:

```bash
python manage.py create_mysql_db
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py seed_leadership
python manage.py configure_office
```

Find the server WiFi IP (PowerShell):

```powershell
ipconfig
```

Look for **IPv4 Address** under Wi-Fi (e.g. `192.168.1.50`).

### Step 2 — Configure `.env` for office access

```env
DJANGO_DEBUG=0
DJANGO_SECRET_KEY=use-a-long-random-string-here
DJANGO_ALLOWED_HOSTS=192.168.1.50,localhost,127.0.0.1
```

Replace `192.168.1.50` with your server’s real IP.

### Step 3 — Start the office server

Double-click **`run_office_server.bat`** or run:

```bash
python -m waitress --listen=0.0.0.0:8000 config.wsgi:application
```

Keep this PC **on**, connected to **office WiFi**, and do not close the window.

### Step 4 — Share the link with staff

Everyone opens in Chrome/Safari on phone or laptop:

```
http://192.168.1.50:8000/
```

They see the **home page** with portal cards (Employee, HR, CEO, Director). They pick their role and log in.

> Replace `192.168.1.50` with your server IP.

### Step 5 — Windows Firewall (if others cannot connect)

Allow port **8000** on the server PC:

1. Windows Security → Firewall → Advanced settings → Inbound Rules → New Rule
2. Port → TCP → **8000** → Allow

### GPS on mobile phones (important)

Browsers require **HTTPS** for location on phones in many cases. Options:

| Option | How |
|--------|-----|
| **Office PC browsers** | `http://192.168.1.x:8000` often works on same WiFi |
| **Phones (recommended)** | Use [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/) or deploy to a VPS with HTTPS |
| **Quick test** | Chrome on Android may allow location on local HTTP |

### Optional — Run on Windows startup

Create a Task Scheduler task to run `run_office_server.bat` when the server PC logs in.

### Cloud deployment (internet access from anywhere)

For access outside the office LAN, deploy to **Railway**, **Render**, **PythonAnywhere**, or a **VPS** with:

- MySQL database
- `DJANGO_DEBUG=0`
- HTTPS enabled
- `python manage.py collectstatic` + WhiteNoise or nginx for static files

Home page URL stays: `https://yourdomain.com/`

