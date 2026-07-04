@echo off
REM Office LAN deployment — run on the server PC (keep this window open).
cd /d "%~dp0"
set DJANGO_DEBUG=0
python -m waitress --listen=0.0.0.0:8000 config.wsgi:application
