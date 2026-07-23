# BCF Coordination Dashboard

A self-contained HTML dashboard for EPC plant engineering projects. Parses Revizto BCF exports, XLSX issue lists, VIMMRK snapshots, MS Project XML, and document management data at build time. No server, no CDN, no runtime dependencies.

**Architecture:** the build produces two artifacts, not one — a lean `index.html` shell (~460 KB, login UI only, no data) plus a separate `data.js` (project data, AES-256-GCM encrypted with PBKDF2-SHA256 200k). The browser loads `index.html`, prompts for a password, then fetches and decrypts `data.js` client-side. `index.html` never embeds project data — see [HANDOVER.md](HANDOVER.md) rule #1 for why that must never change.

Day-to-day building, config editing, and git pushing goes through the **Admin Board** (`admin_server.py` + `admin.html`, `python admin_server.py` → http://localhost:5050), not by calling the build scripts directly.

---

## Features

### Dashboard (Overview)
- KPI summary cards for issues, schedule, document status, and costs
- Doughnut chart (document status), burn-down S-curve (costs), recent issues list
- "View All →" links navigate directly to the relevant tab

### Issue Management
- KPI cards — Open, Critical, Overdue, Avg Age (with totals vs. filtered project)
- 7 analysis charts — Status (doughnut), Issue Type, Priority, Assignee, Discipline, Location (Room/Zone), Level/Storey, Issues Over Time
- Filter bar — Status, Type, Priority, Assignee, Discipline, Location, Overdue toggle, full-text Search
- **Preset filters** — save and restore named filter combinations (stored in localStorage)
- **Project switcher** — switch between named export sources; "All Projects" aggregates all
- Sortable issue register — sort bar (A→Z, Z→A, Newest, Oldest, Priority, Due Date) and clickable column headers
- Paginated table (20 rows per page) with Previous / Next navigation
- **Detail modal** — BCF snapshot (embedded JPEG thumbnail or S3 URL fallback), comments thread, full metadata (status, type, priority, assignee, discipline, spatial location, due date, age)

### Schedule & Gantt
- Variance Gantt — planned bars (MS Project XML) vs actual bars (BCF issues) per WBS task
- View modes: Combined, Plan only, Issues only
- Collapsible WBS phase groups with full-project timeline navigator
- **Export modal** — export to MS Project XML or generate VBA Macro for bar colouring

### Engineering Documents
- Asset register (Pipes, Vessels, Pumps, Valves, Heat Exchangers, Instruments) with search and type filter
- Property panel — process & mechanical data per asset (DN, PN, material, medium, temperature, P&ID reference, isometry, line list)
- **PDF Datasheet Viewer** — auto-generated 2-page SVG datasheet per asset (process data sheet + P&ID schematic)
- **MTO Summary sub-tab** — revision comparison (Base Rev → Compare Rev):
  - KPI cards: Total Pipe Count, Total Length, Isometries Changed, Added/Removed ISOs
  - Pipe length by isometry chart (grouped bar, colour-coded by change direction)
  - Count by DN / Material chart
  - Isometry detail table with ADDED / CHANGED / REMOVED row highlighting
  - Fittings & bulk materials table with Δ quantities

### Document Management
- KPI cards — Total, Approved, Signed, In Review, Missing, Meets Requirement %
- Overall Status doughnut + Status by Source milestone line chart (5 project phases: Concept → Basic Design → Detail Design → IFC Issue → As-Built)
- Document register with sortable column headers, source filter toggles (SharePoint, P&ID, 3D Model), discipline and asset type filters

### Costs
- KPI cards — Total Budget, Actual Spend, Committed, Forecast at Completion
- S-Curve — Budget vs Actual vs Forecast cumulative line chart
- Cost by Discipline — horizontal bar chart (Budget vs Actual)
- Budget vs Actual by WBS — grouped bar chart (Budget / Actual / Committed per WBS element)
- Cost Items table — WBS, Description, Budget, Actual, Committed, % Spent bar, Status badge

### Scope
- Deliverable matrix — document types (PFD, P&ID, Equipment, Arrangement, Support, etc.) per discipline
- Scope register — filterable by system, document type, discipline, completion status
- Gap analysis — missing or overdue deliverables highlighted

### General
- Fully self-contained — works fully offline and behind corporate proxies (no CDN, no external requests)
- **Language switcher** — EN / DE / HR
- **Text size switcher** — S / A / A / A (11–17 px), persisted in sessionStorage
- **Light / Dark theme toggle**, persisted in sessionStorage
- **Build diagnostics panel** — build environment, file paths, issue counts, parser status (click build timestamp)
- AES-256-GCM client-side encryption for secure client delivery

---

## Quick Start

```bash
pip install -r requirements.txt

cp config.template.yaml config.yaml
# Edit config.yaml — set bcf_sources, msp_xml_path, title, etc.
# Or use the Admin Board (recommended) to edit config visually.

python admin_server.py
# Open http://localhost:5050 → Build Dashboard, Build Data, then push via the Git tab
```

Manual equivalent of what the Admin Board runs:
```bash
# Shell (lean, ~460KB, no data) — always pass --lean for the deployed shell
python build_dashboard.py --lean --output index.html --password "YourSecurePassword"

# Data package (data.js, ~MB-scale, AES-256-GCM encrypted)
python build_data.py --password "YourSecurePassword"
```

Open `index.html` in any modern browser. It shows a password prompt, then fetches and decrypts `data.js` before rendering any data.

---

## Repository Structure

```
index.html               Lean shell build output (~460KB) — tracked in git, Azure serves it
data.js                   Encrypted project data build output (~MB-scale) — tracked in git
template.html             Dashboard HTML/CSS/JS with DATA_START/END markers — edit this, never index.html
build_dashboard.py        Build script — shell only, always --lean for the deployed build
build_data.py              Build script — data.js only
admin.html / admin_server.py   Admin Board UI + local server (config editor, build, git push)
config.public.yaml         Org/layout/mappings — gitignored: no; tracked
config.private.yaml        Passwords, azure_swa_token — gitignored, local only
config.yaml                 Local merge of the two above — gitignored, local only
config.template.yaml       Config template — copy to config.yaml to start
config_utils.py            Merged config loader
README.md / HANDOVER.md    Docs — HANDOVER.md has the architecture rules and known-bug history
.gitignore

parsers/
  __init__.py
  bcf.py                  BCF 2.x / 3.0 parser
  xlsx.py                 Revizto XLSX export parser
  vimmrk.py               VIMMRK format parser (small_snapshot.jpg + spatial data)
  sources.py              Multi-source merger (BCF + XLSX + VIMMRK, merged by GUID)
  docmgt.py               Document management parser
  docmilestones.py        Document milestone / S-curve parser
  msp.py                  MS Project XML parser
  engassets.py            Engineering asset register parser
  mtodata.py              MTO (Material Take-Off) revision comparison parser
  costsdata.py            Costs / S-curve data parser (SAP, Primavera, or any XLSX)
  scopedata.py            Scope deliverable matrix parser
  utils.py                Shared utilities (thumbnail generation, date parsing, sanitisation)

# Gitignored — not committed:
exports/                  BCF / XLSX / VIMMRK / XML source files
config.yaml, config.private.yaml, license_private.pem
```

---

## Configuration

Config is split across three files (see [HANDOVER.md](HANDOVER.md) rule #3 for the full hierarchy):
- `config.public.yaml` — org structure, layout, colors, mappings. Tracked in git.
- `config.private.yaml` — passwords, `azure_swa_token`. Local only, never committed.
- `config.yaml` — merge of both, written by the Admin Board. Local only, never committed.

Edit via the Admin Board, or manually (copy from `config.template.yaml`):

```yaml
dashboard:
  title: "BCF Coordination Dashboard"
  subtitle: "Plant Engineering — 3D Model Review"
  theme: "dark"                    # "dark" | "light"

bcf_sources:
  - "./exports/*.bcf"
  - "./exports/*.xlsx"
  - "./exports/*.vimmrk"

# MS Project XML export — enables Variance Gantt
msp_xml_path: "./exports/EPC_Project_Plan.xml"

# Map Revizto stamp prefixes to MS Project task names
msp_task_map:
  H040: "HVAC Ductwork 3D Modelling"
  Q030: "Clash Resolution - All Disciplines"

output_path: "index.html"
```

Full schema documented inside `config.template.yaml`.

---

## Source File Formats

| Format | Issues | Snapshots | Spatial data |
|--------|--------|-----------|--------------|
| `.bcf` | BCF 2.x + 3.0, multi-assignee | Full-res JPEG embedded | — |
| `.xlsx` | All Revizto fields | S3 URL | Level, Room, Zone, Grid, Coords |
| `.vimmrk` | Title, status, comments | small_snapshot.jpg | Level, Room, Zone |

Files are merged by GUID. Priority: XLSX > VIMMRK > BCF. XLSX wins on metadata; BCF/VIMMRK contribute snapshots when XLSX has none.

---

## AES-256-GCM Encryption

### How it works

When `--password` is supplied, `build_dashboard.py`:

1. Parses all source files and substitutes all placeholders (identical to plain build)
2. Extracts the `/* DATA_START */ … /* DATA_END */` block — contains `RAW_DATA`, `CONFIG`, `PROJECTS`, `DOC_DATA`, `ENG_ASSETS`, `MTO_DATA`, `COST_DATA`, `DOC_MILESTONES`, `SCOPE_DATA`
3. Transforms all `const X =` declarations to `window.X =` assignments
4. Derives a 256-bit AES key using **PBKDF2-SHA256 with 200,000 iterations** and a random 128-bit salt
5. Encrypts with **AES-256-GCM** using a random 96-bit IV; appends the 128-bit GCM authentication tag
6. Replaces the data section with empty stub `let` declarations + the encrypted JSON blob
7. Injects a password prompt UI and a Web Crypto API decryption + re-render handler

The resulting `index.html` contains no readable project data. Correct password → Web Crypto API derives the same key, decrypts, re-populates all globals, and re-renders every tab. Wrong password → GCM tag mismatch, generic error, no partial data leaked.

### Security properties

| Property | Value |
|----------|-------|
| Cipher | AES-256-GCM |
| Key derivation | PBKDF2-SHA256, 200,000 iterations |
| Salt | 128-bit, random per build |
| IV / Nonce | 96-bit, random per build |
| Authentication | GCM tag 128-bit (tamper-evident) |
| Brute-force cost | ~200 ms per attempt on modern hardware |
| Data exposed without password | None — only ciphertext, salt, IV, tag |

### Rotating the password

Run a new encrypted build with the new password. A new random salt and IV are generated — the old password will not open the new file.

---

## CI/CD — GitHub Actions + Azure Static Web Apps

**Never write the password in plain text in a YAML file.** Use GitHub Secrets.

The only workflow is `.github/workflows/azure-static-web-apps.yml`. It builds the lean
shell (`build_dashboard.py --lean`), builds the data package (`build_data.py`), commits
both `index.html` and `data.js`, then deploys via `Azure/static-web-apps-deploy@v1`.

### Secrets

GitHub repo → Settings → Secrets and variables → Actions:

| Name | Value |
|------|-------|
| `DASHBOARD_PASSWORD` | Browser login password |
| `DATA_PASSWORD` | Data encryption password (falls back to `DASHBOARD_PASSWORD` if unset) |
| `AZURE_STATIC_WEB_APPS_API_TOKEN` | Generated automatically by Azure |
| `LICENSE_JSON` | Leave empty — no longer used |

### Connect to Azure

In the Azure portal: create a Static Web App → connect to your GitHub repository. Azure will automatically generate `AZURE_STATIC_WEB_APPS_API_TOKEN` and add it to your repository secrets.

### Additional access control (recommended)

| Option | Effort | What it adds |
|--------|--------|--------------|
| IP allowlist (Azure → Networking) | Low | Blocks non-office IPs at CDN edge |
| Azure Static Web Apps password protection | Low | Single shared HTTP-level password |
| Cloudflare Access (free tier) | Medium | OAuth2/SSO via Microsoft or Google |
| Azure AD / Entra ID | Medium | Per-user login, MFA, full audit log |
| VPN-only hosting | High | No public attack surface |

---

## Dependencies

| Package | Required | Purpose |
|---------|----------|---------|
| `pyyaml` | Yes | Read `config.yaml` |
| `openpyxl` | Yes | Parse XLSX exports |
| `pillow` | Recommended | Snapshot thumbnail generation (JPEG resize) |
| `pycryptodome` | Encrypted builds only | AES-256-GCM + PBKDF2 key derivation |

The dashboard uses a fully self-contained chart engine — no Chart.js CDN required. Works offline and behind corporate proxies.

---

## Variance Gantt Setup

1. In MS Project: File → Save As → XML format
2. Copy the `.xml` file into `exports/`
3. Set `msp_xml_path` in `config.yaml`
4. Map Revizto stamp prefixes to MS Project task names in `msp_task_map`
5. Rebuild

---

## Troubleshooting

**Charts empty after unlock (encrypted build)**
The Web Worker initialises on page load with empty stub data. After decryption the dashboard automatically re-renders all tabs. If charts appear empty, wait 2–3 seconds for the Worker to finish processing large datasets, then switch tabs.

**"No MS Project data" in Gantt**
`msp_xml_path` is empty or wrong. Verify the file exists at the configured path.

**`ModuleNotFoundError: No module named 'Crypto'`**
Install `pycryptodome`, not `pycrypto`:
```bash
pip install pycryptodome
```

**"Incorrect password" on the correct password**
The password must exactly match the string passed to `--password` at build time, including case and special characters.

**`UnicodeEncodeError` during build**
Set `PYTHONIOENCODING=utf-8` in your environment, or upgrade to Python 3.9+.

**`DeprecationWarning: datetime.datetime.utcnow()`**
Cosmetic warning only, does not affect output. Will be resolved in a future update.

---

## Development

Tested with Python 3.9–3.12 on Windows 10/11 and Ubuntu 22.04.

`template.html` contains the complete dashboard HTML, CSS, and JS with `/* DATA_START */` / `/* DATA_END */` markers delimiting the injectable data section. `build_dashboard.py --lean` substitutes all `*_PLACEHOLDER` tokens with empty stubs (data comes from `data.js` at runtime, not from this build).

To modify the dashboard layout, charts, or logic: edit `template.html` (never `index.html` directly — it's a build artifact), then rebuild via the Admin Board's "Build Dashboard", or manually:
```bash
python build_dashboard.py --lean --output index.html
```
