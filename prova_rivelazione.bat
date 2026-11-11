@echo off
rem Rivelazione di PROVA (con telecomando dal cellulare) su una copia del database.
rem Ogni volta: copia fresca, estrazione nuova e pronostici casuali per tutti.
setlocal
cd /d "%~dp0"

rem Nome del partecipante (non usato per la rivelazione, lasciato per coerenza).
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

title Secret Betting - PROVA RIVELAZIONE (chiudi questa finestra per spegnerla)
".venv\Scripts\python.exe" prova_estrazione.py --rivelazione "%NOME%"
echo.
pause
endlocal
