@echo off
rem Avvia Secret Betting (se non e' gia' acceso) e apre la pagina personale nel browser.
rem Il link viene letto dal database ogni volta: funziona anche se dall'admin rigeneri il link.
setlocal
cd /d "%~dp0"

rem Nome del partecipante di cui aprire il profilo (come scritto nella pagina admin).
set "NOME=Vincenzo"

if not exist ".venv\Scripts\python.exe" (
    echo [ERRORE] Ambiente Python non trovato in .venv
    echo Crealo con:  python -m venv .venv  e poi  .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)

set "CODE="
for /f "usebackq delims=" %%c in (`.venv\Scripts\python.exe -c "import os,sqlite3;r=sqlite3.connect('instance/secret_santa.db').execute('select code from participants where name=? collate nocase',[os.environ['NOME']]).fetchone();print(r[0] if r else '')"`) do set "CODE=%%c"
if not defined CODE (
    echo [ERRORE] Nessun partecipante chiamato "%NOME%" nel database.
    echo Controlla il nome nella pagina admin e correggi la riga  set "NOME=..."  in questo file.
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

start "" "http://localhost:5000/p/%CODE%"
endlocal
