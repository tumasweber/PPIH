# BCF Coordination Dashboard — Kundenhandbuch

**Produkt:** BCF Coordination Dashboard  
**Hersteller:** RHYBA Engineering | thomas.weber@rhyba-engineering.com  
**Live-URL:** wird von RHYBA bereitgestellt  

---

## Inhalt des Pakets

```
index.html              Dashboard-Shell (signiert, nicht bearbeitbar — build_dashboard.py
                        ist absichtlich NICHT Teil dieses Pakets)
data.js                 Verschlüsselte Projektdaten (täglich neu bauen)
build_data.py           Daten-Build-Script
admin_server_kunde.py   Lokaler Admin-Server (http://localhost:5050) — eingeschränkt:
                        kann NUR data.js bauen, index.html ist gesperrt (403)
admin_kunde.html        Admin-Oberfläche (Kunden-Variante)
config_utils.py         Konfigurationshelfer
config.yaml             Ihre Projektkonfiguration
config.private.yaml     Passwörter + Lizenz (NICHT committen)
parsers/                Daten-Parser (BCF, XLSX, VIMMRK, MSP)
exports/                Quelldaten-Ordner (BCF, XLSX, VIMMRK, XML)
setup_kunde.bat         Ersteinrichtung (einmalig ausführen)
```

---

## Schnellstart

### 1. Ersteinrichtung (einmalig)
```bat
setup_kunde.bat
```
Installiert alle Python-Abhängigkeiten.

### 2. Admin-Oberfläche starten
```bat
python admin_server_kunde.py
```
→ Browser öffnet automatisch http://localhost:5050

### 3. Neue Daten deployen

**Nur über die Admin-Oberfläche:**  
Tab „Build" → **⚡ Build Data** → Fortschritt im Log verfolgen → **Deploy Data**

Es gibt keinen Kommandozeilen-Weg mehr — `git_push_data.bat` wurde aus dem
Hauptprojekt entfernt (unsicheres Alt-Skript) und war nie Teil des
Kunden-Pakets.

---

## Täglicher Workflow

| Aufgabe | Aktion |
|---|---|
| Neue BCF/XLSX Exporte einlesen | Dateien in `exports/` kopieren → Build Data |
| Dashboard online aktualisieren | Build Data → Deploy Data |
| Konfiguration ändern | Admin-Oberfläche → jeweiliger Tab → Save |
| Admin-Oberfläche starten | `python admin_server_kunde.py` |
| Dashboard lokal testen | http://localhost:5050/dashboard |

---

## Quelldaten (`exports/`)

Legen Sie folgende Dateien in den `exports/`-Ordner:

| Format | Beschreibung |
|---|---|
| `*.bcf` | Revizto BCF-Export (BCF 2.x / 3.0) |
| `*.xlsx` | Revizto Excel-Export |
| `*.vimmrk` | VIMMRK Snapshot |
| `*.xml` | MS Project XML (für Gantt-Register) |

Die Pfade werden in `config.yaml` unter `bcf_sources` und `msp_xml_path` konfiguriert.

---

## Konfiguration (`config.yaml`)

Bearbeitbar über die Admin-Oberfläche oder direkt als YAML.  
Wichtige Felder:

```yaml
dashboard:
  title:    "BCF Coordination Dashboard"
  subtitle: "Plant Engineering — 3D Model Review"
  theme:    "dark"   # dark | light

bcf_sources:
  - "./exports/*.bcf"
  - "./exports/*.xlsx"

msp_xml_path: "./exports/PROJECT_PLAN.xml"
```

---

## Passwörter (`config.private.yaml`)

```yaml
data_password: "IhrDatenPasswort"    # Verschlüsselt data.js
admin_password: "IhrAdminPasswort"   # Admin-Oberfläche
license:
  customer: "Ihr Unternehmen"
  tier: professional
  features: [costs, docs, gantt, issues, overview]
  expires: "2027-05-19"
  token:
    payload: "..."   # Von RHYBA bereitgestellt — nicht ändern
    sig:     "..."   # Von RHYBA bereitgestellt — nicht ändern
```

> ⚠️ **Wichtig:** `config.private.yaml` niemals committen oder weitergeben.  
> Die `token`-Felder dürfen nicht verändert werden — das Dashboard prüft die Signatur kryptographisch.

---

## Lizenz

Das Dashboard wird mit einer kryptographisch signierten Lizenz ausgeliefert.  
Die Lizenz bestimmt, welche Register (Tabs) verfügbar sind.

| Tier | Register |
|---|---|
| Starter | Dashboard, Issue Management |
| Professional | + Costs, Document Management, Schedule & Gantt |
| Enterprise | + Engineering Documents, Scope |

**Lizenz erneuern oder erweitern:**  
Kontaktieren Sie RHYBA Engineering: thomas.weber@rhyba-engineering.com

---

## Deployment (Azure Static Web Apps)

Das Dashboard läuft auf Azure Static Web Apps.  
Deployment erfolgt automatisch via GitHub Actions, sobald Sie über die
Admin-Oberfläche **Deploy Data** ausführen.

**Voraussetzungen:**
- Git installiert und konfiguriert
- GitHub-Zugang zum Repository
- Azure-Deployment läuft automatisch nach Push

---

## Troubleshooting

| Problem | Lösung |
|---|---|
| `data.js` lädt nicht | Admin → Build Data ausführen |
| Falsches Passwort | `config.private.yaml` → `data_password` prüfen |
| Register gesperrt | Lizenz abgelaufen → RHYBA kontaktieren |
| Admin nicht erreichbar | `python admin_server_kunde.py` neu starten |
| Build schlägt fehl | Log in Admin → Build prüfen, Parser-Fehler? |
| Cache-Problem (Browser) | Hard-Reload: `Ctrl+Shift+R` |

---

## Support

**RHYBA Engineering**  
Thomas Weber  
thomas.weber@rhyba-engineering.com  

Bitte bei Supportanfragen immer folgende Infos mitschicken:
- Fehlermeldung / Screenshot
- Log aus der Admin-Oberfläche (Build-Tab)
- Version von `index.html` (steht im Footer des Dashboards)
