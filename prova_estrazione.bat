@echo off
rem Estrazione di PROVA su una copia del database: il database vero non viene toccato.
rem Ogni volta riparte da una copia fresca, quindi riflette le ultime modifiche fatte nell'admin.
setlocal
cd /d "%~dp0"

rem Nome del partecipante di cui aprire il profilo di prova.
set "NOME=Vincenzo"

if not exist ".venv\Scripts\python.exe" (
    echo [ERRORE] Ambiente Python non trovato in .venv
    pause
    exit /b 1
)

powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 5056 -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
if not errorlevel 1 (
    echo [ATTENZIONE] Una prova e' gia' accesa sulla porta 5056.
    echo Chiudi la finestra "Secret Betting - PROVA" e rilancia questo file.
    pause
    exit /b 1
)

title Secret Betting - PROVA (chiudi questa finestra per spegnerla)
".venv\Scripts\python.exe" prova_estrazione.py "%NOME%"
echo.
pause
endlocal
