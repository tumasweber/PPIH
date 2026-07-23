@echo off
REM ============================================================
REM  BCF Coordination Dashboard — Ersteinrichtung
REM  RHYBA Engineering | thomas.weber@rhyba-engineering.com
REM
REM  Einmalig ausfuehren nach Installation des Pakets.
REM ============================================================

echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║   BCF Coordination Dashboard — Ersteinrichtung       ║
echo  ║   RHYBA Engineering                                  ║
echo  ╚══════════════════════════════════════════════════════╝
echo.

REM ── Python pruefen ──────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [FEHLER] Python nicht gefunden.
    echo          Bitte Python 3.11+ installieren: https://www.python.org/downloads/
    echo          Wichtig: "Add Python to PATH" beim Installieren aktivieren!
    pause
    exit /b 1
)

for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo [OK] Python %PYVER% gefunden.

REM ── pip-Pakete installieren ─────────────────────────────────────
echo.
echo [1/4] Installiere Basis-Pakete...
pip install pyyaml openpyxl requests --quiet --break-system-packages 2>nul || pip install pyyaml openpyxl requests --quiet
if errorlevel 1 (
    echo [FEHLER] pip-Installation fehlgeschlagen. Bitte manuell ausfuehren:
    echo          pip install pyyaml openpyxl requests
    pause
    exit /b 1
)
echo [OK] Basis-Pakete installiert.

echo.
echo [2/4] Installiere Krypto-Pakete (fuer Datenverschluesselung)...
pip install pycryptodome --quiet --break-system-packages 2>nul || pip install pycryptodome --quiet
if errorlevel 1 (
    echo [WARNUNG] pycryptodome nicht installiert. Datenverschluesselung nicht verfuegbar.
) else (
    echo [OK] pycryptodome installiert.
)

echo.
echo [3/4] Installiere optionale Pakete (SharePoint, XML)...
pip install lxml python-docx --quiet --break-system-packages 2>nul || pip install lxml python-docx --quiet
echo [OK] Optionale Pakete verarbeitet.

REM ── Ordnerstruktur pruefen ──────────────────────────────────────
echo.
echo [4/4] Pruefe Ordnerstruktur und Dateien...

if not exist "exports" (
    mkdir exports
    echo [OK] exports\ Ordner erstellt.
) else (
    echo [OK] exports\ Ordner vorhanden.
)

if not exist "admin_server_kunde.py" (
    echo [FEHLER] admin_server_kunde.py nicht gefunden.
    echo          Bitte sicherstellen, dass das komplette Paket entpackt wurde.
    pause
    exit /b 1
)
echo [OK] admin_server_kunde.py vorhanden.

if not exist "admin_kunde.html" (
    echo [FEHLER] admin_kunde.html nicht gefunden.
    echo          Bitte sicherstellen, dass das komplette Paket entpackt wurde.
    pause
    exit /b 1
)
echo [OK] admin_kunde.html vorhanden.

if not exist "index.html" (
    echo [HINWEIS] index.html nicht gefunden.
    echo           Bitte die signierte index.html von RHYBA Engineering anfordern.
)  else (
    echo [OK] index.html (Dashboard-Shell) vorhanden.
)

if not exist "config.private.yaml" (
    echo.
    echo [HINWEIS] config.private.yaml nicht gefunden.
    echo           Bitte von RHYBA Engineering anfordern.
    echo           Enthaelt Passwort und Lizenz-Token.
)

if not exist "config.yaml" (
    if exist "config.template.yaml" (
        copy config.template.yaml config.yaml >nul
        echo [OK] config.yaml aus Template erstellt. Bitte anpassen!
    ) else (
        echo [HINWEIS] config.yaml nicht gefunden. Bitte von RHYBA erhalten.
    )
) else (
    echo [OK] config.yaml vorhanden.
)

REM ── Git pruefen ─────────────────────────────────────────────────
git --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo [HINWEIS] Git nicht gefunden. Fuer automatisches Deployment
    echo           Git installieren: https://git-scm.com/download/win
) else (
    for /f "tokens=3" %%v in ('git --version 2^>^&1') do set GITVER=%%v
    echo [OK] Git %GITVER% gefunden.
)

REM ── Fertig ──────────────────────────────────────────────────────
echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║   Einrichtung abgeschlossen!                         ║
echo  ╠══════════════════════════════════════════════════════╣
echo  ║                                                      ║
echo  ║   Naechste Schritte:                                 ║
echo  ║   1. Exportdateien in exports\ kopieren              ║
echo  ║   2. config.yaml anpassen (oder Admin nutzen)        ║
echo  ║   3. python admin_server_kunde.py                    ║
echo  ║      → http://localhost:5050                         ║
echo  ║                                                      ║
echo  ║   Support: thomas.weber@rhyba-engineering.com        ║
echo  ╚══════════════════════════════════════════════════════╝
echo.

set /p STARTADMIN=Admin-Oberflaeche jetzt starten? (j/n): 
if /i "%STARTADMIN%"=="j" (
    echo Starte Admin-Server...
    start "" python admin_server_kunde.py
    timeout /t 2 >nul
    start "" http://localhost:5050
)

pause
