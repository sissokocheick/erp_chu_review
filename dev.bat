@echo off
REM ─────────────────────────────────────────────────────────────
REM  NexusERP - Lanceur serveur de développement (Windows)
REM  Usage :  dev.bat            (port 8765)
REM           dev.bat 8000        (autre port)
REM ─────────────────────────────────────────────────────────────
setlocal
cd /d "%~dp0"

REM Mode développement : fournit la SECRET_KEY de dev et autorise
REM les valeurs par défaut (PostgreSQL local postgres/admin).
set DJANGO_DEBUG=True
if "%DJANGO_SECRET_KEY%"=="" set DJANGO_SECRET_KEY=8KWj8QB8VcDHFbWddy-6RrMemVPyGHthFZZtfJe1Ew0SQLC9KwnPndgfGlv5zYlwVY4

set PORT=%~1
if "%PORT%"=="" set PORT=8765

if not exist venv\Scripts\activate.bat (
  echo [ERREUR] Virtualenv introuvable : lancez d'abord "python -m venv venv" puis "venv\Scripts\pip install -r requirements.txt"
  pause
  exit /b 1
)

call venv\Scripts\activate.bat

echo.
echo  ── NexusERP en mode dev ──
echo     URL :  http://127.0.0.1:%PORT%/
echo     DEBUG : activé
echo     Base : PostgreSQL local (chu_angre_db / postgres / admin)
echo     Ctrl+C pour arrêter
echo.

python manage.py runserver 127.0.0.1:%PORT% --noreload

echo.
echo  Serveur arrêté.
endlocal
