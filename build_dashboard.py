#!/usr/bin/env python3
"""
BCF Coordination Dashboard — Build Script
  python build_dashboard.py                        # plain build
  python build_dashboard.py --password P           # AES-256-GCM encrypted build
"""
import os, sys, re, json, glob, argparse, base64, hashlib
import io as _io
from pathlib import Path

# Force UTF-8 output on Windows (console default codepage can't encode ✓/✗ etc.)
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
    sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = _io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

os.chdir(Path(__file__).parent)
sys.path.insert(0, '.')

parser = argparse.ArgumentParser()
parser.add_argument('--password', '-p', default=None)
parser.add_argument('--license-key', default='license_private.pem',
                    help='Path to ECDSA private key for license signing')
parser.add_argument('--lean', action='store_true',
                    help='Produce a lean shell index.html with empty data stubs. '
                         'Dashboard loads all data from data.js at runtime. '
                         'Results in a ~200KB index.html instead of 17MB.')
parser.add_argument('--output', '-o', default=None,
                    help='Output path override. Defaults to output_path from config.')
args = parser.parse_args()

# ── Load template ────────────────────────────────────────────────────
with open('template.html', encoding='utf-8') as f:
    tmpl = f.read()

# ── Parse project data ───────────────────────────────────────────────
import yaml
# ── Load merged config (public + private) ────────────────────────
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).parent))
try:
    from config_utils import load_merged_config
    cfg = load_merged_config()
except ImportError:
    _cfg_path = 'config.yaml' if os.path.exists('config.yaml') else 'config.public.yaml'
    print(f'  Config:  {_cfg_path}')
    with open(_cfg_path, encoding='utf-8') as f:
        cfg = yaml.safe_load(f) or {}

# All issue sources (BCF, XLSX, VIMMRK) — merged by GUID
from parsers.sources import load_all_sources
snap_cfg  = cfg.get('snapshots', {})
spa_pri   = cfg.get('spatial_field_priority', [])
all_issues, _proj_guids = load_all_sources(
    sources         = cfg.get('bcf_sources', ['./exports/*.bcf']),
    spatial_priority= spa_pri,
    snap_enabled    = snap_cfg.get('enabled', True),
    thumb_w         = snap_cfg.get('thumb_width',  480),
    thumb_h         = snap_cfg.get('thumb_height', 270),
    thumb_q         = snap_cfg.get('jpeg_quality',  82),
)

# Doc management
DOC_DATA_obj = None
try:
    from parsers.docmgt import parse_doc_management
    DOC_DATA_obj = parse_doc_management(cfg, config_dir=str(Path('.')))
except Exception as e:
    print(f"  [warn] parse_doc_management failed: {e}")

# Fallback mock document register when no xlsx source files are present
if not DOC_DATA_obj or not (DOC_DATA_obj or {}).get('documents'):
    DOC_DATA_obj = {
        "source_labels": {"sharepoint":"SharePoint","pid":"P&ID (AutoCAD Plant 3D)","navisworks":"3D Model (Navisworks)"},
        "status_colors": {"Approved":"#5ab87a","Signed":"#73b5e2","In Review":"#e09a2a","Missing":"#e05c5c","Rejected":"#c84b4b"},
        "documents": [
            {"doc_number":"M-PI-003","title":"Valve Part List","discipline":"Piping","asset_type":"Valves","overall_status":"In Review","required_status":"In Review","current_rev":"A","sources":{"navisworks":{"status":"In Review","rev":"Rev A"}},"date":"2026-04-10"},
            {"doc_number":"Q-BIM-002","title":"Clash Resolution Log","discipline":"BIM","asset_type":"BIM","overall_status":"In Review","required_status":"In Review","current_rev":"2.0, B","sources":{"sharepoint":{"status":"In Review","rev":"Rev 2.0"},"navisworks":{"status":"In Review","rev":"Rev B"}},"date":"2026-04-10"},
            {"doc_number":"E-EL-001","title":"Electrical SLD Rev 0","discipline":"Electrical","asset_type":"Electrical","overall_status":"In Review","required_status":"In Review","current_rev":"1.0, A","sources":{"sharepoint":{"status":"In Review","rev":"Rev 1.0"},"navisworks":{"status":"In Review","rev":"Rev A"}},"date":"2026-04-08"},
            {"doc_number":"M-EQ-003","title":"Heat Exchanger Datasheet E-201","discipline":"Mechanical","asset_type":"Equipment","overall_status":"In Review","required_status":"In Review","current_rev":"A","sources":{"navisworks":{"status":"In Review","rev":"Rev A"}},"date":"2026-04-05"},
            {"doc_number":"E-EL-002","title":"Cable Schedule Rev 0","discipline":"Electrical","asset_type":"Electrical","overall_status":"Approved","required_status":"Approved","current_rev":"1.0","sources":{"sharepoint":{"status":"Approved","rev":"Rev 1.0"}},"date":"2026-04-02"},
            {"doc_number":"P-PR-002","title":"P&ID Reactor Area","discipline":"Process","asset_type":"Piping","overall_status":"In Review","required_status":"Approved","current_rev":"1.0, A","sources":{"sharepoint":{"status":"In Review","rev":"Rev 1.0"},"pid":{"status":"In Review","rev":"Rev A"}},"date":"2026-04-01"},
            {"doc_number":"Q-BIM-001","title":"BIM Coordination Report 1","discipline":"BIM","asset_type":"BIM","overall_status":"Signed","required_status":"Signed","current_rev":"1.0, A","sources":{"sharepoint":{"status":"Signed","rev":"Rev 1.0"},"navisworks":{"status":"Signed","rev":"Rev A"}},"date":"2026-04-01"},
            {"doc_number":"M-EQ-004","title":"Material Certificate Vessel V-301","discipline":"Mechanical","asset_type":"Equipment","overall_status":"Approved","required_status":"Approved","current_rev":"A","sources":{"navisworks":{"status":"Approved","rev":"Rev A"}},"date":"2026-03-30"},
            {"doc_number":"I-IN-001","title":"Instrument Loop Diagram FT-101","discipline":"Instrumentation","asset_type":"Instrument","overall_status":"Signed","required_status":"Signed","current_rev":"B","sources":{"sharepoint":{"status":"Signed","rev":"Rev B"}},"date":"2026-03-28"},
            {"doc_number":"P-PR-001","title":"P&ID Feed Section","discipline":"Process","asset_type":"Piping","overall_status":"Approved","required_status":"Approved","current_rev":"3","sources":{"pid":{"status":"Approved","rev":"Rev 3"},"sharepoint":{"status":"Approved","rev":"Rev 3"}},"date":"2026-03-25"},
            {"doc_number":"C-CV-001","title":"Civil Foundation Drawing","discipline":"Civil","asset_type":"Civil","overall_status":"Signed","required_status":"Signed","current_rev":"1","sources":{"sharepoint":{"status":"Signed","rev":"Rev 1"}},"date":"2026-03-20"},
            {"doc_number":"E-EL-003","title":"Lighting Layout Level 1","discipline":"Electrical","asset_type":"Electrical","overall_status":"Approved","required_status":"Approved","current_rev":"0","sources":{"sharepoint":{"status":"Approved","rev":"Rev 0"}},"date":"2026-03-18"},
            {"doc_number":"M-PI-001","title":"Pipe Stress Analysis L-101","discipline":"Piping","asset_type":"Piping","overall_status":"Missing","required_status":"Approved","current_rev":"","sources":{},"date":""},
            {"doc_number":"M-PI-002","title":"Pipe Support Schedule","discipline":"Piping","asset_type":"Piping","overall_status":"In Review","required_status":"Approved","current_rev":"A","sources":{"pid":{"status":"In Review","rev":"Rev A"}},"date":"2026-03-10"},
            {"doc_number":"I-IN-002","title":"Thermocouple Schedule","discipline":"Instrumentation","asset_type":"Instrument","overall_status":"Approved","required_status":"Approved","current_rev":"1","sources":{"sharepoint":{"status":"Approved","rev":"Rev 1"}},"date":"2026-03-05"},
            {"doc_number":"H-HV-001","title":"HVAC Ductwork Layout","discipline":"HVAC","asset_type":"HVAC","overall_status":"In Review","required_status":"Signed","current_rev":"0","sources":{"navisworks":{"status":"In Review","rev":"Rev 0"}},"date":"2026-02-28"},
            {"doc_number":"S-ST-001","title":"Steel Structure Drawing","discipline":"Structural","asset_type":"Structural","overall_status":"Signed","required_status":"Signed","current_rev":"2","sources":{"sharepoint":{"status":"Signed","rev":"Rev 2"},"navisworks":{"status":"Signed","rev":"Rev 2"}},"date":"2026-02-20"},
            {"doc_number":"M-EQ-001","title":"Pump Datasheet P-101A","discipline":"Mechanical","asset_type":"Equipment","overall_status":"Approved","required_status":"Approved","current_rev":"B","sources":{"sharepoint":{"status":"Approved","rev":"Rev B"},"navisworks":{"status":"Approved","rev":"Rev B"}},"date":"2026-02-15"}
        ]
    }

# MSP / Gantt
MSP_obj = None
try:
    from parsers.msp import parse_msp_xml
    msp_path = cfg.get('msp_xml_path', '')
    if msp_path and os.path.exists(msp_path):
        MSP_obj = parse_msp_xml(msp_path)  # returns list of task dicts
except Exception as e:
    print(f"  [warn] MSP parse failed: {e}")

# Projects / PROJECTS map (project_name → [guids])
# load_all_sources returns this directly as the second element
PROJECTS_obj = {k: v for k, v in _proj_guids.items() if v}

import datetime
BUILD_TIME = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
BUILD_INFO = f"Built {BUILD_TIME}"

# ── Engineering Assets ───────────────────────────────────────────────────────
ENG_ASSETS_obj = []
try:
    from parsers.engassets import parse_eng_assets
    ENG_ASSETS_obj = parse_eng_assets(cfg) or []
except Exception as e:
    print(f"  [info] Engineering assets parser not found or no source configured: {e}")

# ── MTO Data ─────────────────────────────────────────────────────────────────
_MTO_FALLBACK = {'isometries':[],'fittings':[],'rev_base':'Rev A','rev_cmp':'Rev B'}
MTO_DATA_obj = _MTO_FALLBACK
try:
    from parsers.mtodata import parse_mto
    MTO_DATA_obj = parse_mto(cfg) or _MTO_FALLBACK
except Exception as e:
    print(f"  [info] MTO parser not found or no source configured: {e}")

# ── Costs Data ────────────────────────────────────────────────────────────────
_COST_FALLBACK = {'currency':'CHF','total_budget':0,'total_actual':0,'total_committed':0,
                  'budget_pct':0,'items':[],'scurve':[]}
COST_DATA_obj = _COST_FALLBACK
try:
    from parsers.costsdata import parse_costs
    COST_DATA_obj = parse_costs(cfg) or _COST_FALLBACK
except Exception as e:
    print(f"  [info] Costs parser not found or no source configured: {e}")

# ── Doc Milestones ────────────────────────────────────────────────────────────
_MILE_FALLBACK = {'labels':[],'datasets':[]}
DOC_MILESTONES_obj = _MILE_FALLBACK
try:
    from parsers.docmilestones import parse_doc_milestones
    DOC_MILESTONES_obj = parse_doc_milestones(cfg) or _MILE_FALLBACK
except Exception as e:
    print(f"  [info] Doc milestones parser not found or no source configured: {e}")

# ── Substitute placeholders ───────────────────────────────────────────────────

def js(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(',', ':'))

html = tmpl
# Lean mode: inject empty stubs — all data loaded from data.js at runtime
_EMPTY = {'documents':[]}
_dash = cfg.get('dashboard',{})
def _common(h):
    h = h.replace('"BUILD_TIME_PLACEHOLDER"', js(BUILD_TIME))
    h = h.replace('BUILD_INFO_PLACEHOLDER',   js(BUILD_INFO))
    h = h.replace('"BUILD_INFO_PLACEHOLDER"', js(BUILD_INFO))
    h = h.replace('TITLE_PLACEHOLDER',    _dash.get('title','BCF Dashboard'))
    h = h.replace('SUBTITLE_PLACEHOLDER', _dash.get('subtitle',''))
    h = h.replace('THEME_PLACEHOLDER',    _dash.get('theme','dark'))
    return h

if args.lean:
    html = html.replace('DATA_JSON_PLACEHOLDER',    '[]')
    html = html.replace('CONFIG_JSON_PLACEHOLDER',  js(cfg))
    html = html.replace('PROJECTS_JSON_PLACEHOLDER','{}')
    html = html.replace('MSP_JSON_PLACEHOLDER',     '[]')
    html = html.replace('DOC_JSON_PLACEHOLDER',     js(_EMPTY))
    html = html.replace('ENG_ASSETS_PLACEHOLDER',   '[]')
    html = html.replace('MTO_DATA_PLACEHOLDER',     'null')
    html = html.replace('COST_DATA_PLACEHOLDER',    'null')
    html = html.replace('DOC_MILESTONES_PLACEHOLDER','null')
    html = _common(html)
    # Change const → let in DATA block so FETCH_JS can reassign after decryption
    import re as _re
    html = _re.sub(r'/\* DATA_START \*/(.*?)/\* DATA_END \*/',
        lambda m: '/* DATA_START */' + m.group(1).replace('const ', 'let ') + '/* DATA_END */',
        html, flags=_re.DOTALL)
    print('  [lean] Lean build — empty stubs injected. Deploy with data.js.')

    # ── Inject data.js fetch + decrypt loader ───────────────
    FETCH_JS = '''
(function() {
  // Auto-fetch data.js from same origin and decrypt
  const _dataUrl = 'data.js';
  const _cachedPw = sessionStorage.getItem('bcf-pw') || null;

  // Entra ID auto-unlock: if Azure has already authenticated this request
  // (staticwebapp.config.json allowedRoles gate), /api/get-data-key returns
  // the password with no human ever typing or seeing it. Anywhere that API
  // isn't reachable — local dev, or a copy of these files opened outside
  // the real deployment — this 404s/network-errors and falls back to the
  // manual password prompt below, same as before this existed.
  async function _tryAutoUnlock(onSuccess) {
    try {
      const r = await fetch('/api/get-data-key', {cache: 'no-store'});
      if (!r.ok) throw new Error('auto-unlock unavailable');
      const body = await r.json();
      if (!body.password) throw new Error('no password in response');
      await new Promise((resolve, reject) => {
        const s = document.createElement('script');
        s.src = _dataUrl + '?v=' + Date.now();
        s.onload = resolve;
        s.onerror = () => reject(new Error('data.js load failed'));
        document.head.appendChild(s);
      });
      if (!window._BCF_DATA) throw new Error('data.js loaded but window._BCF_DATA not set');
      await _decryptAndLoad(window._BCF_DATA, body.password, null);
      const _lov = document.getElementById('loading-overlay');
      if (_lov) _lov.remove();
      onSuccess();
    } catch(e) {
      _showLoginOverlay(onSuccess);
    }
  }

  function _showLoginOverlay(onSuccess) {
    const shell = document.querySelector('.shell');
    const _lov  = document.getElementById('loading-overlay');
    if (_lov)  _lov.remove();
    if (shell) shell.style.display = 'none';
    const ov = document.createElement('div');
    ov.id = 'login-overlay';
    ov.innerHTML = `<div class="login-card">
      <div class="login-logo">
        <svg width="40" height="40" viewBox="0 0 40 40">
          <circle cx="20" cy="20" r="20" fill="#0081b1"/>
          <text x="20" y="27" text-anchor="middle" font-size="18"
            font-family="Arial,sans-serif" font-weight="700" fill="#fff">R</text>
        </svg>
        <span class="login-title">RHYBA Engineering</span>
      </div>
      <div class="login-subtitle" id="login-subtitle-el">${(window._LIC_DATA&&window._LIC_DATA.customer)||(window.CONFIG&&window.CONFIG.dashboard&&window.CONFIG.dashboard.subtitle)||""}</div>
      <div class="login-subtitle" style="font-size:.72rem;margin-top:2px">
        Enter the project password to load the data package.
      </div>
      <div class="login-field"><input type="password" id="pw-input"
        placeholder="Project password" autocomplete="current-password"/></div>
      <button class="login-btn" id="pw-btn">Unlock Dashboard</button>
      <div id="pw-error" class="login-error"></div>
      <div id="pw-status" style="font-size:.65rem;color:#4a8a6a;text-align:center"></div>
    </div>`;
    document.body.appendChild(ov);
    const inp = document.getElementById('pw-input');
    const btn = document.getElementById('pw-btn');
    const err = document.getElementById('pw-error');
    const sta = document.getElementById('pw-status');
    inp.addEventListener('keydown', e => { if (e.key==='Enter') tryLoad(); });
    btn.addEventListener('click', tryLoad);
    async function tryLoad() {
      const pw = inp.value.trim();
      if (!pw) { err.textContent = 'Please enter the password.'; return; }
      btn.disabled = true; err.textContent = '';
      btn.textContent = 'Loading\u2026';
      sta.textContent = 'Fetching data.js\u2026';
      try {
        // Load data.js via script tag — works reliably on Azure Static Web Apps
        await new Promise((resolve, reject) => {
          const s = document.createElement('script');
          s.src = _dataUrl + '?v=' + Date.now();
          s.onload = resolve;
          s.onerror = () => reject(new Error('data.js konnte nicht geladen werden. Prüfe ob die Datei auf dem Server liegt.'));
          document.head.appendChild(s);
        });
        if (!window._BCF_DATA) throw new Error('data.js geladen aber window._BCF_DATA nicht gesetzt.');
        const pkg = window._BCF_DATA;
        sta.textContent = 'Decrypting\u2026';
        await _decryptAndLoad(pkg, pw, ov);
        sessionStorage.setItem('bcf-pw', pw);
        onSuccess();
      } catch(e) {
        err.textContent = e.message || 'Decryption failed — wrong password?';
        btn.disabled = false; btn.textContent = 'Unlock Dashboard';
        sta.textContent = '';
      }
    }
    // sessionStorage: re-use password within same browser session
    if (_cachedPw) { inp.value = _cachedPw; tryLoad(); }
  }

  async function _decryptAndLoad(pkg, pw, ov) {
    if (pkg.fmt !== 'bcfdash-data') throw new Error('Not a valid data file (fmt=' + pkg.fmt + ')');
    const salt = Uint8Array.from(atob(pkg.s), c=>c.charCodeAt(0));
    const iv   = Uint8Array.from(atob(pkg.i), c=>c.charCodeAt(0));
    const ct   = Uint8Array.from(atob(pkg.c), c=>c.charCodeAt(0));
    const tag  = Uint8Array.from(atob(pkg.t), c=>c.charCodeAt(0));
    const ctag = new Uint8Array(ct.length + tag.length);
    ctag.set(ct); ctag.set(tag, ct.length);
    const km = await crypto.subtle.importKey(
      'raw', new TextEncoder().encode(pw), 'PBKDF2', false, ['deriveKey']);
    const k = await crypto.subtle.deriveKey(
      {name:'PBKDF2', salt, iterations:200000, hash:'SHA-256'},
      km, {name:'AES-GCM', length:256}, false, ['decrypt']);
    const pt  = await crypto.subtle.decrypt({name:'AES-GCM', iv, tagLength:128}, k, ctag);
    const obj = JSON.parse(new TextDecoder().decode(pt));
    // Populate globals
    if (obj.RAW_DATA       != null) RAW_DATA       = obj.RAW_DATA;
    if (obj.PROJECTS       != null) PROJECTS       = obj.PROJECTS;
    if (obj.CONFIG         != null) { Object.assign(CONFIG, obj.CONFIG); }
    if (obj.MSP_DATA       != null) MSP_DATA       = obj.MSP_DATA;
    if (obj.DOC_DATA       != null) DOC_DATA       = obj.DOC_DATA;
    if (obj.ENG_ASSETS     != null) ENG_ASSETS     = obj.ENG_ASSETS;
    if (obj.MTO_DATA       != null) MTO_DATA       = obj.MTO_DATA;
    if (obj.COST_DATA      != null) COST_DATA      = obj.COST_DATA;
    if (obj.DOC_MILESTONES != null) DOC_MILESTONES = obj.DOC_MILESTONES;
    if (obj.SCOPE_DATA     != null) SCOPE_DATA     = obj.SCOPE_DATA;
    if (obj.BUILD_TIME     != null) BUILD_TIME     = obj.BUILD_TIME;
    if (obj.BUILD_INFO     != null) BUILD_INFO     = obj.BUILD_INFO;
    // Apply org project mapping from loaded config
    if (typeof _buildOrgProjectMap === 'function') _buildOrgProjectMap();
    if (ov) ov.remove();
    const shell = document.querySelector('.shell');
    if (shell) shell.style.display = '';
  }

  window._reloadAll = function _reloadAll() {
    try {
      if (typeof _buildOrgProjectMap === 'function') _buildOrgProjectMap();
      if (typeof buildDeptDropdown === 'function') buildDeptDropdown();
      // Re-init web worker with newly loaded RAW_DATA
      if (typeof _reinitWorker === 'function') _reinitWorker();
      populateFilters(); applyFilters(); renderKPIs();
      Object.values(chartInstances).forEach(c=>{try{c.destroy()}catch(e){}});
      chartInstances={};
      const cg=document.getElementById('chart-grid');
      if(cg) cg.removeAttribute('data-built');
      renderCharts();
      if(typeof _renderOverview==='function') _renderOverview();
      if(typeof _renderCosts==='function')    _renderCosts();
      if(typeof _engInit==='function')         _engInit();
      if(typeof _docReinit==='function')       _docReinit();
      if(typeof _renderScope==='function')     _renderScope();
      if(typeof _renderScopeEvolution==='function') _renderScopeEvolution();
      const fb=document.getElementById('footer-built');
      if(fb) fb.textContent='Built '+BUILD_TIME;
      if(typeof _renderLicenceBadge==='function') _renderLicenceBadge();
    } catch(e) { console.error('[reload]', e); }
  }

  document.addEventListener('DOMContentLoaded', function() {
    _tryAutoUnlock(function() {
      _reloadAll();
      if(typeof _rebuildProjectDropdownForDept==='function') _rebuildProjectDropdownForDept();
    });
  });
})();
'''

    last = html.rfind('</script>')
    html = html[:last] + '\n' + FETCH_JS + '\n' + html[last:]
    # Inject login CSS inline (same as encrypted build)
    _LOGIN_CSS = '''
#login-overlay{position:fixed;inset:0;z-index:9999;background:var(--bg0,#0a1a22);
  display:flex;align-items:center;justify-content:center}
.login-card{background:var(--bg1,#0f1e26);border:1px solid var(--border,#1e3040);
  border-radius:10px;padding:36px 40px 32px;width:380px;display:flex;
  flex-direction:column;gap:14px;box-shadow:0 20px 60px rgba(0,0,0,.6)}
.login-logo{display:flex;align-items:center;gap:12px}
.login-title{font-size:1.05rem;font-weight:700;color:var(--text1,#e0eef5)}
.login-subtitle{font-size:.8rem;color:var(--text3,#4a6a7a)}
.login-field input{width:100%;box-sizing:border-box;background:var(--bg2,#182830);
  border:1px solid var(--border,#1e3040);border-radius:5px;color:var(--text1,#e0eef5);
  font-size:.9rem;padding:10px 14px;font-family:inherit;outline:none}
.login-field input:focus{border-color:var(--rhyba-teal,#0081b1)}
.login-btn{background:var(--rhyba-teal,#0081b1);color:#fff;border:none;border-radius:5px;
  font-size:.9rem;font-weight:700;padding:11px;cursor:pointer;font-family:inherit}
.login-btn:hover{background:#0091c8}
.login-error{font-size:.75rem;color:#e05c5c;text-align:center;min-height:1.2em}
'''
    html = html.replace('</style>', _LOGIN_CSS + '\n</style>', 1)

else:
    html = html.replace('DATA_JSON_PLACEHOLDER',    js(all_issues))
    html = html.replace('CONFIG_JSON_PLACEHOLDER',  js(cfg))
    html = html.replace('PROJECTS_JSON_PLACEHOLDER',js(PROJECTS_obj))
    html = html.replace('MSP_JSON_PLACEHOLDER',     js(MSP_obj or []))
    html = html.replace('DOC_JSON_PLACEHOLDER',     js(DOC_DATA_obj or _EMPTY))
    html = html.replace('ENG_ASSETS_PLACEHOLDER',   js(ENG_ASSETS_obj))
    html = html.replace('MTO_DATA_PLACEHOLDER',     js(MTO_DATA_obj))
    html = html.replace('COST_DATA_PLACEHOLDER',    js(COST_DATA_obj))
    html = html.replace('DOC_MILESTONES_PLACEHOLDER',js(DOC_MILESTONES_obj))
    html = _common(html)

# ── Scope Data ────────────────────────────────────────────────────────────────
_SCOPE_FALLBACK = {'systems':[],'doc_types':[],'entries':[]}
SCOPE_DATA_obj = _SCOPE_FALLBACK
try:
    from parsers.scopedata import parse_scope
    SCOPE_DATA_obj = parse_scope(cfg) or _SCOPE_FALLBACK
except Exception as e:
    print(f"  [info] Scope parser not found or no source configured: {e}")

html = html.replace('SCOPE_DATA_PLACEHOLDER', js(SCOPE_DATA_obj))

# ── License ──────────────────────────────────────────────────────────────────
_lic     = cfg.get('license', {})
_lic_key = Path(args.license_key)
_ALL_TABS = ['overview', 'issues', 'gantt', 'engdocs', 'costs', 'docs', 'scope']

# Default: all tabs enabled, no license badge
_features     = _lic.get('features', _ALL_TABS)
_lic_customer = _lic.get('customer', '')
_lic_tier     = _lic.get('tier', '')
_lic_expires  = _lic.get('expires', '')
_lic_token    = {}

# Sign/validate token if license section + private key present
if _lic and _lic_key.exists():
    try:
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import hashes, serialization

        with open(_lic_key, 'rb') as _f:
            _priv = serialization.load_pem_private_key(_f.read(), password=None)

        _payload = json.dumps({
            'customer': _lic_customer,
            'tier':     _lic_tier,
            'features': sorted(set(_features)),
            'expires':  _lic_expires,
        }, separators=(',',':')).encode()

        _sig_der = _priv.sign(_payload, ec.ECDSA(hashes.SHA256()))
        # Convert DER to IEEE P1363 (raw r||s) — required by Web Crypto API
        from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature as _dds
        _r, _s = _dds(_sig_der)
        _sig = _r.to_bytes(32,'big') + _s.to_bytes(32,'big')

        def _b64u(b): return base64.urlsafe_b64encode(b).rstrip(b'=').decode()
        _lic_token = {'payload': _b64u(_payload), 'sig': _b64u(_sig)}

        # Embed public key as JWK for browser verification
        _pub      = _priv.public_key()
        _pub_nums = _pub.public_numbers()
        _jwk      = {
            'kty': 'EC', 'crv': 'P-256',
            'x': _b64u(_pub_nums.x.to_bytes(32, 'big')),
            'y': _b64u(_pub_nums.y.to_bytes(32, 'big')),
        }
        html = html.replace('LICENSE_PUBKEY_PLACEHOLDER', json.dumps(_jwk))
        print(f'  License: {_lic_customer!r} | tier={_lic_tier} | features={_features} | expires={_lic_expires}')
    except Exception as _e:
        print(f'  [warn] License signing failed: {_e}')
        html = html.replace('LICENSE_PUBKEY_PLACEHOLDER', 'null')
elif _lic and not _lic_key.exists():
    print(f'  [warn] license_private.pem not found — skipping license signing. Run generate_license_keys.py')
    html = html.replace('LICENSE_PUBKEY_PLACEHOLDER', 'null')
else:
    html = html.replace('LICENSE_PUBKEY_PLACEHOLDER', 'null')

# Strip unlicensed tab buttons from HTML
_licensed = set(_features)
for _tab in _ALL_TABS:
    if _tab not in _licensed:
        # Remove tab button
        html = re.sub(
            r'<button[^>]*data-tab="' + _tab + r'"[^>]*>.*?</button>\s*',
            '', html, flags=re.DOTALL)
        # Remove tab panel
        html = re.sub(
            r'<div[^>]*id="tab-panel-' + _tab + r'"[^>]*>.*?(?=\n\s*<div[^>]*(?:tab-panel|<!-- TAB))',
            '', html, flags=re.DOTALL)
        print(f'  License: tab [{_tab}] stripped from build')

# Inject license data as JS global in DATA block
_lic_js_obj = json.dumps({
    'customer': _lic_customer,
    'tier':     _lic_tier,
    'features': sorted(set(_features)),
    'expires':  _lic_expires,
    'token':    _lic_token,
}, ensure_ascii=False, separators=(',',':'))
# LIC_DATA_BLOCK_PLACEHOLDER is outside the encrypted DATA_START/END block —
# it stays plaintext so the footer badge is always visible, even in encrypted builds.
html = html.replace('LIC_DATA_BLOCK_PLACEHOLDER', _lic_js_obj)
# Legacy placeholder (should not exist in new template, kept for safety)
html = html.replace('LICENSE_DATA_PLACEHOLDER', _lic_js_obj)
# ─────────────────────────────────────────────────────────────────────────────

# ── Encrypt if password given ────────────────────────────────────────
mode_tag = '[PLAIN]'
if args.password:
    try:
        import base64, secrets
        from Crypto.Cipher import AES
        from Crypto.Protocol.KDF import PBKDF2
        from Crypto.Hash import SHA256, HMAC
    except ImportError:
        sys.exit('[ERROR] pip install pycryptodome')

    DATA_RE = re.compile(r'/\* DATA_START \*/(.*?)/\* DATA_END \*/', re.DOTALL)
    m = DATA_RE.search(html)
    if not m:
        sys.exit('[ERROR] DATA_START/DATA_END markers not found')

    data_js = m.group(1).strip()

    # Transform const/let/var declarations to window.* assignments
    data_js = re.sub(r'^const (\w+)\s*=', r'window.\1 =', data_js, flags=re.MULTILINE)
    data_js = re.sub(r'^(let|var) (\w+)\s*=', r'window.\2 =', data_js, flags=re.MULTILINE)

    pw    = args.password.encode()
    salt  = secrets.token_bytes(16)
    key   = PBKDF2(pw, salt, dkLen=32, count=200_000,
                   prf=lambda p,s: HMAC.new(p, s, SHA256).digest())
    iv    = secrets.token_bytes(12)
    cipher = AES.new(key, AES.MODE_GCM, nonce=iv, mac_len=16)
    ct, tag = cipher.encrypt_and_digest(data_js.encode())

    blob = json.dumps({
        's': base64.b64encode(salt).decode(),
        'i': base64.b64encode(iv).decode(),
        'c': base64.b64encode(ct).decode(),
        't': base64.b64encode(tag).decode(),
    })

    STUBS = """/* DATA_START */
const __ENCRYPTED__ = """ + blob + """;
// Stub declarations — populated with real data after password entry
let RAW_DATA=[], PROJECTS={}, CONFIG={}, MSP_DATA=[];
let DOC_DATA={'documents':[]};
let ENG_ASSETS=[];
let MTO_DATA={'isometries':[],'fittings':[],'rev_base':'Rev A','rev_cmp':'Rev B'};
let COST_DATA={'currency':'CHF','total_budget':0,'total_actual':0,'total_committed':0,'budget_pct':0,'items':[],'scurve':[]};
let DOC_MILESTONES={'labels':[],'datasets':[]};
let SCOPE_DATA={'systems':[],'doc_types':[],'entries':[]};
let BUILD_TIME="", BUILD_INFO="";
/* DATA_END */"""

    if not args.lean:
        # Non-lean: replace DATA block with encrypted STUBS
        html = DATA_RE.sub(STUBS, html)
    else:
        # Lean: DATA block already has empty stubs; just store the blob
        # for the FETCH_JS to use as the password (already embedded above)
        pass

    DECRYPT_CSS = """
/* ── Login overlay ──────────────────────────────────── */
#login-overlay{position:fixed;inset:0;z-index:9999;background:var(--bg0,#0a1a22);
  display:flex;align-items:center;justify-content:center}
.login-card{background:var(--bg1,#0f1e26);border:1px solid var(--border,#1e3040);
  border-radius:10px;padding:36px 40px 32px;width:380px;display:flex;
  flex-direction:column;gap:14px;box-shadow:0 20px 60px rgba(0,0,0,.6)}
.login-logo{display:flex;align-items:center;gap:12px}
.login-title{font-size:1.05rem;font-weight:700;color:var(--text1,#e0eef5)}
.login-subtitle{font-size:.8rem;color:var(--text3,#4a6a7a)}
.login-field input{width:100%;box-sizing:border-box;background:var(--bg2,#182830);
  border:1px solid var(--border,#1e3040);border-radius:5px;color:var(--text1,#e0eef5);
  font-size:.9rem;padding:10px 14px;font-family:inherit;outline:none;transition:border-color .15s}
.login-field input:focus{border-color:var(--rhyba-teal,#0081b1)}
.login-btn{background:var(--rhyba-teal,#0081b1);color:#fff;border:none;border-radius:5px;
  padding:10px 0;font-size:.9rem;font-weight:600;cursor:pointer;font-family:inherit;transition:background .15s}
.login-btn:hover{background:#006fa0}.login-btn:disabled{opacity:.6;cursor:default}
.login-error{font-size:.75rem;color:#e05c5c;min-height:1rem;text-align:center}
"""

    DECRYPT_JS = """
// ── AES-256-GCM login ──────────────────────────────────────────────
(function() {
  if (typeof __ENCRYPTED__ === 'undefined') return;
  document.addEventListener('DOMContentLoaded', function() {
    const shell = document.querySelector('.shell');
    if (shell) shell.style.display = 'none';
    const _lov = document.getElementById('loading-overlay');
    if (_lov) _lov.remove();

    const ov = document.createElement('div');
    ov.id = 'login-overlay';
    ov.innerHTML = `<div class="login-card">
      <div class="login-logo">
        <svg width="40" height="40" viewBox="0 0 40 40">
          <circle cx="20" cy="20" r="20" fill="#0081b1"/>
          <text x="20" y="27" text-anchor="middle" font-size="18"
            font-family="Arial,sans-serif" font-weight="700" fill="#fff">R</text>
        </svg>
        <span class="login-title">RHYBA Engineering</span>
      </div>
      <div class="login-subtitle" id="login-subtitle-el">${(window._LIC_DATA&&window._LIC_DATA.customer)||(window.CONFIG&&window.CONFIG.dashboard&&window.CONFIG.dashboard.subtitle)||""}</div>
      <div class="login-subtitle" style="font-size:.72rem;margin-top:2px">
        This file is AES-256 encrypted. Enter the project password to continue.
      </div>
      <div class="login-field"><input type="password" id="pw-input"
        placeholder="Project password" autocomplete="current-password"/></div>
      <button class="login-btn" id="pw-btn">Unlock Dashboard</button>
      <div id="pw-error" class="login-error"></div>
    </div>`;
    document.body.appendChild(ov);

    const inp = document.getElementById('pw-input');
    const btn = document.getElementById('pw-btn');
    const err = document.getElementById('pw-error');

    async function tryDecrypt() {
      err.textContent = '';
      btn.disabled = true;
      btn.textContent = 'Decrypting\u2026';
      try {
        const e    = __ENCRYPTED__;
        const salt = Uint8Array.from(atob(e.s), c=>c.charCodeAt(0));
        const iv   = Uint8Array.from(atob(e.i), c=>c.charCodeAt(0));
        const ct   = Uint8Array.from(atob(e.c), c=>c.charCodeAt(0));
        const tag  = Uint8Array.from(atob(e.t), c=>c.charCodeAt(0));
        const ctag = new Uint8Array(ct.length + tag.length);
        ctag.set(ct); ctag.set(tag, ct.length);

        const km = await crypto.subtle.importKey(
          'raw', new TextEncoder().encode(inp.value), 'PBKDF2', false, ['deriveKey']);
        const k = await crypto.subtle.deriveKey(
          {name:'PBKDF2', salt, iterations:200000, hash:'SHA-256'},
          km, {name:'AES-GCM', length:256}, false, ['decrypt']);
        const pt = await crypto.subtle.decrypt({name:'AES-GCM', iv, tagLength:128}, k, ctag);
        const js = new TextDecoder().decode(pt);

        // Execute decrypted JS — sets window.* globals
        new Function(js)();

        // Assign window globals to stub let vars
        // Use != null to catch both null and undefined, but allow 
        // empty arrays/objects (which are falsy-adjacent but valid data)
        if (window.RAW_DATA       != null) RAW_DATA       = window.RAW_DATA;
        if (window.DOC_DATA       != null) DOC_DATA       = window.DOC_DATA;
        if (window.COST_DATA      != null) COST_DATA      = window.COST_DATA;
        if (window.ENG_ASSETS     != null) ENG_ASSETS     = window.ENG_ASSETS;
        if (window.MTO_DATA       != null) MTO_DATA       = window.MTO_DATA;
        if (window.DOC_MILESTONES != null) DOC_MILESTONES = window.DOC_MILESTONES;
        if (window.SCOPE_DATA     != null) SCOPE_DATA     = window.SCOPE_DATA;
        if (window.PROJECTS       != null) PROJECTS       = window.PROJECTS;
        if (window.CONFIG         != null) CONFIG         = window.CONFIG;
        if (window.MSP_DATA       != null) MSP_DATA       = window.MSP_DATA;

        // Show dashboard and re-initialise everything with decrypted data
        ov.remove();
        if (shell) shell.style.display = '';
        if (typeof window._verifyLicense === 'function') window._verifyLicense();

        function _reloadAll() {
          // 1. Re-seed Worker with real RAW_DATA and trigger filter/render
          if (typeof window._reinitWorker === 'function') {
            window._reinitWorker();
          }
          // 2. Re-run main-thread issue filter (updates register + charts)
          if (typeof applyFilters === 'function') applyFilters();
          // Clear chart cache so they rebuild on next Worker RESULT
          const _cg = document.getElementById('chart-grid');
          if (_cg) _cg.removeAttribute('data-built');
          // 3. Re-render overview KPIs/charts
          if (typeof _renderOverview === 'function') _renderOverview();
          // 4. Re-init doc management (IIFE was skipped at load due to empty DOC_DATA)
          if (typeof window._docReinit === 'function') window._docReinit();
          if (typeof _renderDocTimeline === 'function') _renderDocTimeline();
          // 5. Re-render gantt and costs
          if (typeof renderGantt === 'function') {
            // Update MSP-loaded flag and ganttMapping now that real data is available
            if (typeof vganttMspLoaded !== 'undefined') vganttMspLoaded = MSP_DATA.length > 0;
            if (typeof ganttMapping !== 'undefined') {
              Object.keys(ganttMapping).forEach(k => delete ganttMapping[k]);
              Object.assign(ganttMapping, CONFIG.msp_task_map || {});
            }
            renderGantt();
          }
          if (typeof _renderCosts === 'function') _renderCosts();
          // 6. Re-render engineering docs
          if (typeof _engInit === 'function') _engInit();
        }

        // First render pass after overlay removal
        setTimeout(_reloadAll, 250);
        // Second pass after Worker has had time to process INIT → READY → FILTER → RESULT
        // Ensures charts/table populate even if the first pass raced with Worker startup
        setTimeout(function() {
          if (typeof renderTable === 'function' && filtered.length) renderTable();
          if (typeof renderKPIs  === 'function') renderKPIs();
          if (typeof _renderOverview === 'function') _renderOverview();
          const _cg2 = document.getElementById('chart-grid');
          if (_cg2 && window._wLastAgg) {
            _cg2.removeAttribute('data-built');
            window._chartAgg = window._wLastAgg;
            if (typeof renderCharts === 'function') renderCharts();
            window._chartAgg = null;
          }
          if (typeof renderGantt === 'function') {
            if (typeof vganttMspLoaded !== 'undefined') vganttMspLoaded = MSP_DATA.length > 0;
            if (typeof ganttMapping !== 'undefined' && CONFIG.msp_task_map) {
              Object.keys(ganttMapping).forEach(k => delete ganttMapping[k]);
              Object.assign(ganttMapping, CONFIG.msp_task_map);
            }
            if (document.getElementById('tab-panel-gantt')?.classList.contains('active')) {
              renderGantt();
            }
          }
        }, 2500);
      } catch(e) {
        btn.disabled = false;
        btn.textContent = 'Unlock Dashboard';
        err.textContent = 'Incorrect password — please try again.';
        inp.value = '';
        inp.focus();
      }
    }

    btn.addEventListener('click', tryDecrypt);
    inp.addEventListener('keydown', e => { if (e.key==='Enter') tryDecrypt(); });
    setTimeout(() => inp.focus(), 200);
  });
})();
"""

    if not args.lean:
        # Non-lean: embed encrypted data + DECRYPT overlay
        html = html.replace('</style>', DECRYPT_CSS + '\n</style>', 1)
        last = html.rfind('</script>')
        html = html[:last] + '\n' + DECRYPT_JS + '\n' + html[last:]
    # Lean mode: FETCH_JS already injected above — DECRYPT_JS not needed
    mode_tag = f'[ENCRYPTED pw={len(args.password)} chars, PBKDF2-SHA256 200k, AES-256-GCM]'

# ── Write output ─────────────────────────────────────────────────────
out = args.output or cfg.get('output_path', 'index.html')
with open(out, 'w', encoding='utf-8') as f:
    f.write(html)
print(f'[OK] Dashboard written to: {Path(out).resolve()}  ({os.path.getsize(out)//1024} KB)  {mode_tag}')
