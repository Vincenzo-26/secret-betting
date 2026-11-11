@echo off
rem Avvia Secret Betting (se non e' gia' acceso) e apre la pagina admin nel browser.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERRORE] Ambiente Python non trovato in .venv
    echo Crealo con:  python -m venv .venv  e poi  .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)

rem Controlla se qualcosa e' gia' in ascolto sulla porta 5000 (indipendente dalla lingua di Windows).
powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
if errorlevel 1 (
    echo Avvio del server Secret Betting...
    start "Secret Betting - server (chiudi questa finestra per spegnerlo)" ".venv\Scripts\python.exe" app.py
    timeout /t 3 /nobreak >nul
) else (
    echo Il server e' gia' acceso.
)

start "" "http://localhost:5000/admin"
endlocal
