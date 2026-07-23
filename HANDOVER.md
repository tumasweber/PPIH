# BCF Dashboard — Handover (Mai 2026)

**Repo:** https://github.com/tumasweber/dashboard  
**Live:** https://witty-grass-0a188ad03.7.azurestaticapps.net  
**Lokal:** `C:\Users\ThomasWeber\Documents\py-scripts\dashboard_clean`  
**Kontakt:** thomas.weber@rhyba-engineering.com

---

## Architektur

```
index.html          ~460 KB   Lean Shell — Login + UI, KEINE Daten
data.js             ~17 MB    AES-256-GCM verschlüsselte Projektdaten
config.public.yaml            Org-Struktur, Layout, Mappings  ← Git ✅
config.private.yaml           Passwörter, azure_swa_token     ← lokal ❌
config.yaml                   Lokaler Merge beider            ← lokal ❌
config.template.yaml          Vorlage für config.public.yaml  ← Git ✅
config.private.template.yaml  Vorlage für config.private.yaml ← Git ✅
config_utils.py               Merged Config Loader (deep merge, name-basierter Public/Private-Split)
```

**Login-Flow:**
1. Browser lädt `index.html` (lean, ~460KB, keine Daten)
2. Login-Overlay — Passwort eingeben
3. `data.js` via `<script>`-Tag geladen, AES-256-GCM im Browser entschlüsselt
4. Web Worker mit RAW_DATA initialisiert (`_reinitWorker()`)
5. `_reloadAll()` ruft alle Re-Init-Hooks auf

---

## KRITISCHE ARCHITEKTUR-REGELN

### 1. index.html ist IMMER lean — niemals Daten einbetten

`build_dashboard.py` baut mit `--lean` NUR die Shell. Alle Platzhalter = leere Stubs.

**Symptom wenn falsch:** `index.html` ist 17MB statt ~460KB.
**Ursache:** Parser-Daten in Platzhalter eingesetzt statt leere Stubs (`--lean` fehlt beim Aufruf).

### 2. build_dashboard.py — argparse Flags

```python
parser.add_argument('--password', '-p', default=None)
parser.add_argument('--license-key', default='license_private.pem')
parser.add_argument('--lean', action='store_true')   # lean shell statt Vollbuild
parser.add_argument('--output', '-o', default=None)  # Admin übergibt --output <path>
```

`--lean` bleibt als expliziter Flag bestehen (Kunden-Paket kann theoretisch einen
Vollbuild mit eingebetteten Daten brauchen) — **der Admin-Server hängt `--lean` aber
immer an**, wenn er den Haupt-Build auslöst (`admin_server.py::run_build`).

Output-Pfad:
```python
out = args.output or cfg.get('output_path', 'index.html')
```

**Symptom wenn `--output` fehlt (WAR BIS 2026-07-21 LIVE KAPUTT):** Admin-Server übergibt
`--output index.html`, `build_dashboard.py` kannte das Flag nicht →
`unrecognized arguments: --output index.html` → Exit 2. Jeder Klick auf „Build
Dashboard“ im Admin-Board schlug fehl. Fix: `--output`/`-o` zum argparse hinzugefügt,
`out = args.output or cfg.get(...)`.
**Symptom wenn `--lean` beim Admin-Build fehlt:** Build „gelingt“, aber erzeugt den
17MB-Vollbuild statt der Lean Shell (Punkt 1). Fix: `admin_server.py` hängt `--lean`
jetzt fest an den Build-Befehl.

### 3. Config-Hierarchie

```
config.public.yaml  ← Git ✅   org, layout, discipline_map, colors, msp_task_map
config.private.yaml ← lokal ❌  data_password, admin_password, azure_swa_token
config.yaml         ← lokal ❌  Merge beider (gitignored, von Admin-Board geschrieben)
```

`save_config()` in `admin_server.py` schreibt BEIDE Dateien:
- `config.yaml` — vollständig (alle Keys)
- `config.public.yaml` — nur PUBLIC_KEYS: `organisation`, `source_assignments`, `departments`, `dashboard`, `bcf_sources`, `discipline_map`, `colors`, `layout`, `filters`, etc.

**Symptom wenn falsch:** `organisation:` verschwindet nach Git-Reset, da nur in `config.yaml`

`build_dashboard.py` liest Config:
```python
_cfg_path = 'config.yaml' if os.path.exists('config.yaml') else 'config.public.yaml'
cfg = yaml.safe_load(open(_cfg_path)) or {}
# Merge: public.yaml füllt fehlende Keys auf
if _cfg_path == 'config.yaml' and os.path.exists('config.public.yaml'):
    pub = yaml.safe_load(open('config.public.yaml')) or {}
    for k, v in pub.items():
        if k not in cfg: cfg[k] = v
```

### 4. Git Push — Whitelist Only

`run_git_push()` in `admin_server.py` staged NUR:
```python
whitelist = [
    "index.html", "template.html", "build_dashboard.py", "build_data.py",
    "admin.html", "admin_server.py", "config_utils.py", "config.public.yaml",
    "staticwebapp.config.json", "requirements.txt", "default.html",
    "swa-cli.config.json", ".github", "parsers",
]
# NIEMALS: exports/, data.js (via Whitelist), config.yaml, config.private.yaml
```

Pull vor Push:
```python
# Reset data.js vor rebase (verhindert Merge-Konflikt):
subprocess.run([git, "checkout", "origin/main", "--", "data.js"], ...)
_r([git, "pull", "--rebase", "--autostash", "origin", "main"], ...)
```

**Symptom ohne `--autostash`:** `error: cannot pull with rebase: You have unstaged changes` → Exit 128
**Symptom ohne data.js reset:** `CONFLICT (content): Merge conflict in data.js`

**Gefundene und entfernte Gefahrenquelle (2026-07-21):** `git_push.bat` und
`git_push_data.bat` lagen noch im Repo, tracked in Git, und machten genau das, was
oben verboten ist — `git reset --soft origin/main` + automatischer `git push --force`
bei Fehlschlag — und pushten zusätzlich das seit langem tote `data.json`
(`build_data.py` schreibt nur noch `data.js`). Beide Skripte waren ein zweiter,
ungesicherter Schreibpfad ins Repo parallel zum Admin-Board und sind wahrscheinlich
Ursache eines Teils der früheren Git-Katastrophen. **Gelöscht.**

### 5. Git Push Endpoint — _set_status

```python
# KORREKT — _set_status() verwenden, nie global in if-Block:
def _set_status(status):
    global _build_status
    with _build_lock:
        _build_status = status

# Im Endpoint:
_set_status("running")   # ← nicht: global _build_status; _build_status = "running"
_build_log.clear()
def _git_push_wrapped(m):
    try:    run_git_push(m)
    finally: _set_status("done")
t = threading.Thread(target=_git_push_wrapped, args=(msg,), daemon=True)
```

**Symptom wenn falsch:** `UnboundLocalError: cannot access local variable '_build_status'`
**Symptom wenn fehlt:** Log-Panel zeigt nur 2 Zeilen, dann "Done" — Push läuft unsichtbar

### 6. Admin-Layout — git-log-wrap MUSS in eigener Card sein (wiederkehrender Bug!)

```html
<!-- KORREKT: -->
      </div><!-- schließt SWA-Card content-div -->
      </div><!-- schließt SWA-Card -->
      <div class="card">
        <div id="git-log-wrap" style="display:none;margin-top:10px">
          ...
        </div>
      </div>
    </section>

<!-- FALSCH (zerreißt Layout aller Sections): -->
      </div><!-- schließt SWA-Card -->
        <div id="git-log-wrap" ...>  ← außerhalb der Card!
```

**Symptom:** Project Structure und alle anderen Sections rendern unterhalb der Sidebar
**Ursache:** Flex-Layout bricht wenn ein Element aus `.main` herausfällt

### 7. showSection('orgstructure') muss _loadOrg aufrufen

```javascript
// In showSection():
if (id === 'orgstructure') {
    if (typeof _loadOrg === 'function') _loadOrg(window._getCfg ? window._getCfg() : {});
}

// cfg global zugänglich machen:
let cfg = {};
window._getCfg = function() { return cfg; };
```

**Warum:** Org-IIFE überschreibt `window.showSection` per Hook — aber `showSection` ist
eine normale Funktion (kein `window`-Property). Der Hook greift nicht bei `onclick="showSection(...)"`.

### 8. Log-Panel Polling — prevLen updaten

```javascript
const fullLog = s.log || '';
const newOutput = fullLog.slice(prevLen);
if (newOutput) prevLen = fullLog.length;  // ← KRITISCH: sonst Endlos-Wiederholung
if (gitLog) { gitLog.textContent = fullLog; ... }
if (newOutput) _logAppend(newOutput);
```

**Symptom wenn `prevLen` nicht updated:** Log wiederholt sich hundertfach im Panel

### 9. Niemals template.html direkt bearbeiten

`index.html` ist Build-Artefakt. Fixes gehen in `template.html`.

### 10. Color/Discipline Lookups müssen lazy sein

```javascript
// FALSCH (zur Load-Zeit, CONFIG noch leer):
const colorMap = buildColorMap(CONFIG);

// KORREKT (lazy, bei jedem Aufruf):
function colorFor(discipline) { return CONFIG.colors?.[discipline] ?? '#888'; }
```

### 11. build_dashboard.py MUSS UTF-8 stdout/stderr forcen

```python
import io as _io
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
    sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = _io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
```

`admin_server.py` hatte das schon (Zeile ~20), `build_dashboard.py` nicht.
**Symptom (WAR BIS 2026-07-21 LIVE KAPUTT):** Windows-Konsole nutzt cp1252 statt UTF-8;
`print('✓ ...')` in `parsers/docmgt.py` warf `UnicodeEncodeError`, der von
`build_dashboard.py`s try/except um `parse_doc_management()` verschluckt wurde →
SharePoint-Dokumente fehlten stillschweigend im Dashboard (Document Management Tab
zeigte weniger Dokumente als real vorhanden, ohne Fehlermeldung). Gleicher Bugtyp wie
Fix #10 in der Fixes-Tabelle unten — dort nur für `PYTHONIOENCODING` als Env-Var
dokumentiert, aber nie im Script selbst erzwungen.

---

## Admin-Board Features

### Build-Tab
- **Build Dashboard** → `build_dashboard.py --lean --output index.html` → ~460KB lean shell
- **Build Data** → `build_data.py` → `data.js` (~17MB verschlüsselt)
- **Build & Deploy** → Build Data + Push data.js in einem Schritt
- **Push data.js only** → nur data.js pushen (kein Build)

### Git — Code pushen
- Whitelist-Only Push (sichere Dateien)
- Log-Panel zeigt vollständigen Output in Echtzeit
- Badge: `● Running` / `✓ Done` / `✗ Error`

### Direktes Azure-Deployment
- SWA CLI deploy (kein Git nötig)
- Braucht `azure_swa_token` in `config.private.yaml`
- Fallback wenn GitHub Actions down

### Project Structure Tab
- Org-Hierarchie: Abteilung → Projekt → Subprojekt
- Source-Zuweisung via Drag & Drop
- "Save structure" → schreibt `config.yaml` UND `config.public.yaml`

---

## Git-Workflow

### Täglicher Workflow

| Aktion | Methode |
|---|---|
| Neue BCF/XLSX Daten | Admin → Build Data → Push data.js only |
| Code-Änderungen | Admin → Build Dashboard → ⬆ Code pushen |
| Beides | Admin → Build Data & Push, dann Code pushen |
| Azure direkt | Admin → ☁️ Direkt zu Azure deployen |

**Nur über das Admin-Board pushen.** Es gibt keinen zweiten, manuellen Git-Weg mehr
(die alten `.bat`-Skripte mit `reset --soft` / `push --force` sind entfernt, siehe Punkt 4).

### Git kaputt — Notfall-Reparatur

```powershell
$git  = "C:\Program Files\Git\cmd\git.exe"
$repo = "C:\Users\ThomasWeber\Documents\py-scripts\dashboard_clean"

# Hängendes Rebase:
& $git -C $repo rebase --abort
& $git -C $repo checkout main

# Rebase-Verzeichnis manuell löschen:
Remove-Item "$repo\.git\rebase-merge" -Recurse -Force
& $git -C $repo checkout main

# Diverged (lokale Commits wegwerfen, Remote gewinnt):
& $git -C $repo fetch origin main
& $git -C $repo reset --hard origin/main

# .git verloren/korrupt:
Remove-Item "$repo\.git" -Recurse -Force
Copy-Item "C:\Users\ThomasWeber\Documents\py-scripts\dashboard\.git" "$repo\.git" -Recurse -Force
& $git -C $repo status
```

### NIEMALS
- `git add -A` oder `git add .` → Binary-Dateien, exports/ → Repo-Korruption
- `git reset --soft origin/main` → verliert staged Änderungen
- `git push -f` ohne vorherige Prüfung (138 Objekte = Binary war drin!)
- Die alten `.bat`-Skripte wieder anlegen — genau diese Muster waren drin

---

## Re-Init Hooks (Reihenfolge nach Decrypt)

```javascript
_buildOrgProjectMap()     // source_file → Org-Projekt-GUIDs
buildDeptDropdown()       // Dept/Projekt-Dropdowns
_reinitWorker()           // RAW_DATA → Web Worker
populateFilters()         // Filter-Panels
applyFilters()            // Worker überschreibt diese Funktion
renderKPIs()
renderCharts()
_renderOverview()
_renderCosts()
_engInit()
_docReinit()
_renderScope()
_renderScopeEvolution()
_attachAllChartTooltips()
```

---

## GitHub Secrets

| Secret | Inhalt |
|---|---|
| `DASHBOARD_PASSWORD` | Browser-Login-Passwort |
| `DATA_PASSWORD` | Datenverschlüsselung |
| `AZURE_STATIC_WEB_APPS_API_TOKEN` | Auto von Azure |
| `LICENSE_JSON` | **LEER LASSEN** — nicht mehr verwendet |

---

## Lizenz-System (ECDSA P-256)

- **Dev-Build:** kein `license:` in config → alle Tabs aktiv, Console: `[DEV BUILD]`
- **Kunden-Build:** `license:` in `config.private.yaml` + `license_private.pem`
- `license_private.pem` → NIEMALS committen

---

## Bekannte Fixes (chronologisch)

| # | Problem | Symptom | Fix | Datei |
|---|---|---|---|---|
| 1 | Chart Maximize | Kein Resize | `Chart.prototype.resize` Alias auf `_draw()` | template.html |
| 2 | X-Achse Font | Skaliert nicht | `Math.round(rem * 0.72)` statt `\|\| 8` | template.html |
| 3 | Chart Tooltips | Kein Hover | Custom Hit-Testing, `canvas._chart` fix | template.html |
| 4 | KPI-Einheiten | Fehlende Labels | `unit_issues`, `unit_days` zu KPI_DEFS | template.html |
| 5 | Auto-Login | PW im HTML | `_builtInPw` entfernt | build_dashboard.py |
| 6 | Lizenz | Kein Enforcement | ECDSA P-256 via Web Crypto API | template.html |
| 7 | Azure Cache | Alter Stand | `default.html` Cache-Busting | staticwebapp.config.json |
| 8 | Actions baut data.js | Unnötig | Build-Step aus Workflow entfernt | .github/workflows/ |
| 9 | git-log-wrap Layout | Sections falsch | In eigene Card (WIEDERKEHREND!) | admin.html |
| 10 | charmap Encoding | ✓ Zeichen crasht | UTF-8 stdout/stderr Wrapper (siehe Punkt 11 — war nur teilweise gefixt) | build_dashboard.py |
| 11 | `--lean` fehlte | Exit 2 | `add_argument('--lean', action='store_true')` | build_dashboard.py |
| 12 | `--output` fehlte | Exit 2 | `add_argument('--output', '-o', default=None)` (2026-07-21 erneut nötig, siehe Punkt 2) | build_dashboard.py |
| 13 | FETCH_JS fehlte | `_dataUrl` undefined | Originale Version als Basis genommen | build_dashboard.py |
| 14 | config.yaml Fallback | FileNotFoundError | Fallback + Merge mit config.public.yaml | build_dashboard.py |
| 15 | 17MB index.html | Zu groß | Alle Platzhalter = leere Stubs (WIEDERKEHREND!) | build_dashboard.py |
| 16 | pull --rebase Exit 128 | Unstaged changes | `--autostash` hinzugefügt | admin_server.py |
| 17 | Project Structure fehlt | Tab leer | showSection + _getCfg Fix | admin.html |
| 18 | Push All gefährlich | exports/ staged | Whitelist-Only, kein reset --soft | admin_server.py |
| 19 | --lean kein Flag mehr | Exit 2 | --lean aus argparse + Admin-Server entfernt (2026-07-21 revidiert: --lean bleibt, siehe Punkt 2) | build_dashboard.py, admin_server.py |
| 20 | data.js Merge-Konflikt | Exit 1 bei rebase | `git checkout origin/main -- data.js` vor rebase | admin_server.py |
| 21 | UnboundLocalError | Server crash | `_set_status()` Helper statt global in if-Block | admin_server.py |
| 22 | Log-Wiederholung | 100x selber Text | `prevLen = fullLog.length` nach jedem Poll | admin.html |
| 23 | organisation fehlt | Leere Dropdowns | `save_config()` schreibt config.public.yaml | admin_server.py |
| 24 | Git-Push unsichtbar | Log bricht nach 2 Zeilen ab | `_set_status("running")` im Push-Endpoint | admin_server.py |
| 25 | Admin „Build Dashboard" Exit 2 | `unrecognized arguments: --output` | `--output`/`-o` zu argparse hinzugefügt | build_dashboard.py |
| 26 | Admin-Build erzeugte 17MB statt Lean Shell | `--lean` fehlte im Admin-Aufruf | `cmd = [..., "--lean"]` fest in `run_build()` | admin_server.py |
| 27 | SharePoint-Dokumente fehlten stillschweigend | `UnicodeEncodeError` bei `✓` verschluckt | UTF-8 stdout/stderr Wrapper wie in admin_server.py | build_dashboard.py |
| 28 | Gefährliche Alt-Skripte im Repo | `reset --soft` + `push --force` + totes `data.json` | `git_push.bat`, `git_push_data.bat` gelöscht | Repo-Root |
| 29 | Totes `data.json` noch getrackt | Verwirrung mit `data.js` | `git rm data.json` | Repo-Root |
| 30 | Verwaiste Workflow-Entwürfe | `build_shell.yml` / `build_data.yml` lagen im Root, nie in `.github/workflows/`, nie ausgeführt | Gelöscht — einzige aktive Pipeline ist `azure-static-web-apps.yml` | Repo-Root |
| 31 | Stray `.data-updated` Datei | Ungetrackt, von keinem Code mehr referenziert | Gelöscht | Repo-Root |
| 32 | `run_git_push_data()` ohne Fetch/Rebase | `git push` direkt, ohne vorher zu prüfen ob Remote sich bewegt hat — CI committed nach JEDEM Push innerhalb ~60s zurück, daher schlug ein zeitnaher zweiter Push oft mit "rejected (fetch first)" fehl | `git pull --rebase -X ours --autostash origin main` vor dem Push ergänzt (analog zu `run_git_push()`, aber unser neues `data.js` gewinnt bei Konflikt) | admin_server.py |
| 33 | `config.template.yaml` stark veraltet | Fehlte: `organisation`, `source_assignments`, `doc_management`, `data_output`, `spatial_field_priority`; `output_path` zeigte noch auf `dashboard.html` statt `index.html`; keine private Vorlage existierte | Template vervollständigt, `config.private.template.yaml` neu angelegt (nur Platzhalterwerte, keine echten Secrets) | config.template.yaml, config.private.template.yaml |
| 34 | `license_private.pem` fehlte komplett | Auf keiner Maschine mehr vorhanden — Lizenzsignierung war lokal nicht funktionsfähig | Neues Schlüsselpaar via `generate_license_keys.py` erzeugt. Alte Bachem/Novartis-Tokens sind damit nicht mehr gegen den neuen Public Key verifizierbar (waren aber ohnehin nie live gegen einen echten Kundenbuild getestet) | license_private.pem (lokal, gitignored) |
| 35 | Echte Kundendaten in Git | `licenses.json` / `license_bachem.yaml` enthielten echte Firmennamen (Bachem, Novartis) samt signierten Tokens | Durch synthetische Testdaten ersetzt; `license_bachem.yaml` → `license_example.yaml` umbenannt. **Alte Werte bleiben in der Git-Historie** bis zu einem expliziten History-Rewrite (nicht durchgeführt — separate, invasivere Entscheidung) | licenses.json, license_example.yaml |
| 36 | `issue_license.py` signierte DER statt Raw | Web Crypto (`crypto.subtle.verify`) erwartet IEEE-P1363 `r\|\|s` (64 Byte), `issue_license.py` gab aber die rohen DER-Bytes von `private_key.sign()` aus — inkonsistent zu `build_dashboard.py` und `license_manager.py`, die beide korrekt per `decode_dss_signature()` umwandeln | `decode_dss_signature()`-Konvertierung ergänzt, wie in den anderen beiden Signierstellen | issue_license.py |
| 37 | `token:`-Feld in Config ist wirkungslos | `build_dashboard.py` liest beim Build **nie** ein vorhandenes `license.token`, sondern signiert bei jedem Build aus `customer`/`tier`/`features`/`expires` + lokalem `license_private.pem` neu. Nur diese vier Felder zählen. README_KUNDE.md suggerierte fälschlich, der Kunde dürfe `token.payload`/`token.sig` nicht ändern, als wären sie live relevant | Klarstellung in `issue_license.py`-Docstring ergänzt; kein Codefix nötig, nur Doku-Korrektur | issue_license.py |
| 38 | `[DEV BUILD]`-Konsolenmeldung fehlte im Code | HANDOVER dokumentierte sie als bestehendes Verhalten, `template.html` hatte aber nur ein stilles `return` bei fehlendem Public Key | `console.log('[DEV BUILD] ...')` ergänzt | template.html |
| 39 | Lizenz-Gating end-to-end verifiziert (2026-07-23) | — | Vier Szenarien im Browser getestet (gebaut mit `--lean`, echtem `license_private.pem`): **gültig** (professional) → nur lizenzierte Tabs im DOM, keine Fehlermeldung; **abgelaufen** → alle 7 Tabs `display:none`, rote Banner "Licence expired"; **manipulierte Signatur** (1 Zeichen im `sig`-Feld geflippt) → `crypto.subtle.verify` schlägt fehl, alle Tabs gesperrt, Konsole warnt; **kein `license:`** → alle Tabs sichtbar, `[DEV BUILD]`-Log. Serverseitiges Stripping (`build_dashboard.py`) UND clientseitige ECDSA-Prüfung (`template.html`) arbeiten korrekt zusammen | — |
| 40 | AES-256-GCM Tamper-Detection end-to-end verifiziert (2026-07-23) | — | 1 Zeichen im ciphertext-Feld (`c`) eines gebauten `data.js` geflippt, mit korrektem Passwort geladen: Login-Overlay bleibt bestehen, `RAW_DATA` bleibt leer (kein Teil-Leak), UI zeigt "Incorrect password" statt Absturz/Stacktrace. Grund: `_decryptAndLoad()` (build_dashboard.py FETCH_JS/DECRYPT_JS) ruft `crypto.subtle.decrypt({name:'AES-GCM',...})` — verify-then-decrypt ist Spec-Garantie der Web-Crypto-API, kein Anwendungscode kann den GCM-Tag-Check umgehen; alle Codezeilen nach dem `decrypt()`-Call (Globals befüllen, Overlay entfernen) liegen hinter dem `await` und werden bei Tag-Mismatch nie erreicht. **Achtung beim Nachtesten:** die Browser-Preview cached `data.js` teils trotz `?v=`-Cache-Busting-Query, wenn derselbe Dateipfad zuvor schon geladen wurde — für einen sauberen Test einen komplett neuen, nie zuvor aufgerufenen Ordner/Pfad verwenden | — |

---

## Disaster Recovery

### Repo zu groß (Binary-Daten committed):
```powershell
$git  = "C:\Program Files\Git\cmd\git.exe"
$repo = "C:\Users\ThomasWeber\Documents\py-scripts\dashboard_clean"
& $git -C $repo checkout --orphan new_main
& $git -C $repo add index.html template.html build_dashboard.py admin.html admin_server.py
& $git -C $repo add config_utils.py staticwebapp.config.json parsers/ requirements.txt
& $git -C $repo add config.public.yaml .github/ default.html swa-cli.config.json
& $git -C $repo commit -m "Clean start"
& $git -C $repo branch -D main
& $git -C $repo branch -m main
& $git -C $repo push --force origin main
```

### Azure zeigt alten Stand:
1. Incognito + Strg+Shift+R
2. Azure Portal → Static Web App → Purge content cache

---

## Bekannte Falle: config.yaml und config.public/private.yaml können auseinanderlaufen

`build_dashboard.py` liest Config über `config_utils.load_merged_config()` — das
mischt **`config.public.yaml` + `config.private.yaml` direkt**, `config.yaml` wird
dabei komplett ignoriert (nur als Fallback falls `config_utils` nicht importierbar
ist). `admin_server.py`s `load_config()` liest dagegen ausschließlich `config.yaml`
selbst — kein Merge. Beide bleiben nur synchron, solange jede Änderung über
`save_config()` im Admin-Board läuft (schreibt alle drei Dateien neu). Bearbeitet
man `config.public.yaml`/`config.private.yaml` manuell, oder zieht man per
`git pull` eine von woanders geänderte `config.public.yaml`, bleibt das lokale
`config.yaml` (gitignored, wird nie per Git aktualisiert) veraltet — der Admin-Board
zeigt dann alte Werte, während `build_dashboard.py` bereits die neuen einbaut.
**Noch nicht behoben** — TODO: entweder `admin_server.py` ebenfalls auf
`load_merged_config()` umstellen, oder bei jedem Server-Start/Request neu mergen.

## Offene Punkte / TODOs

| Thema | Status |
|---|---|
| organisation: in config.public.yaml | Einmalig manuell aus config.yaml kopieren → dann automatisch |
| Node.js 20 Actions Deprecation | actions/checkout@v4 + setup-python@v5 upgraden |
| Mobile Touch-Tooltips | Implementiert, nicht auf echtem Gerät getestet |
| Scope — Responsibility Matrix | TODO |
| Scope — Equipment Tag Register | TODO |
| Scope — Interface Log | TODO |
| Kunden-Paket | admin_kunde.html, admin_server_kunde.py, setup_kunde.bat — wird aktuell geprüft/aufgeräumt |

---

## Tech Stack

| Komponente | Technologie |
|---|---|
| Frontend | Vanilla JS + HTML/CSS |
| Charts | Custom Canvas-Engine (kein CDN) |
| Verschlüsselung | AES-256-GCM, PBKDF2-SHA256 200k (SubtleCrypto) |
| Lizenz | ECDSA P-256 (Web Crypto API) |
| Build | Python 3.11, PyYAML, openpyxl, pycryptodome |
| CI/CD | GitHub Actions → Azure Static Web Apps |
| Datenverarbeitung | Web Worker (inline Blob URL) |
| Admin | admin_server.py (Python HTTP :5050) + admin.html |

---

## Pre-Ship Test Suite (vor jeder Auslieferung ausführen)

```python
import ast, re, subprocess, sys

# build_dashboard.py
bd = open('build_dashboard.py').read()
assert ast.parse(bd)                                          # Syntax
assert "'--output'" in bd                                     # --output vorhanden
assert "replace('DATA_JSON_PLACEHOLDER',    '[]')" in bd    # leere Stubs
assert 'args.output or' in bd                                 # output verdrahtet
assert "sys.stdout = _io.TextIOWrapper" in bd                 # UTF-8 stdout Fix

# admin_server.py
srv = open('admin_server.py').read()
assert ast.parse(srv)
push_fn = srv.split('def run_git_push(')[1].split('def run_build_and_push')[0]
push_code = push_fn[push_fn.find('"""', push_fn.find('"""')+3)+3:]
assert '"--output"' in srv                                    # --output im Build-Cmd
assert '"--lean"' in srv.split('def run_build(')[1].split('\ndef ')[0]  # --lean im Haupt-Build
assert '"config.yaml"' not in push_code                      # config.yaml nicht in Whitelist
assert 'reset --soft' not in push_code                       # kein reset --soft
assert '--autostash' in push_code                             # autostash vorhanden
assert 'checkout' in push_code and 'data.js' in push_code   # data.js conflict fix
assert 'def _set_status(' in srv                              # _set_status Helper
assert 'config.public.yaml' in srv.split('def save_config')[1].split('\ndef ')[0]  # public write
assert '"organisation"' in srv.split('def save_config')[1].split('\ndef ')[0]

# admin.html
html = open('admin.html').read()
assert 'id="sec-orgstructure"' in html
assert 'swaDirectDeploy' in html
assert 'pushAll()' not in html
assert 'id="unified-log"' in html
assert 'window._getCfg' in html
assert 'class="card">\n        <div id="git-log-wrap"' in html
assert 'if (newOutput) prevLen = fullLog.length;' in html
assert html.count('const _ulb') <= 1

# Repo-Hygiene
import os
assert not os.path.exists('git_push.bat')
assert not os.path.exists('git_push_data.bat')
```
