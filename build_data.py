#!/usr/bin/env python3
"""
build_data.py  —  BCF Dashboard Data Build Script
==================================================
Parses all project data sources and produces a single encrypted
data package: data.js

This script is SEPARATE from build_dashboard.py:
  build_dashboard.py  →  dashboard.html   (shell, JS, CSS, licence)
                         run rarely: new features, licence changes
  build_data.py       →  data.js     (project data only)
                         run daily or on new BCF/XLSX exports

Usage:
  python build_data.py                         # uses config.yaml, same password as dashboard
  python build_data.py --password "secret"     # explicit password
  python build_data.py --config my_config.yaml
  python build_data.py --out exports/data.js

The .bcfdash file format:
  {
    "v":  1,                    # format version
    "s":  "<base64 salt>",      # PBKDF2 salt (16 bytes)
    "i":  "<base64 iv>",        # AES-GCM nonce (12 bytes)
    "c":  "<base64 ciphertext>",
    "t":  "<base64 GCM tag>",
    "ts": "2026-05-19T06:00Z",  # build timestamp (plaintext for display)
    "info": "Project X — 142 issues"  # plaintext summary
  }

The ciphertext decrypts to a JSON object with the same shape as
the DATA_START block in dashboard.html:
  {
    "RAW_DATA":      [...],
    "PROJECTS":      {...},
    "CONFIG":        {...},
    "MSP_DATA":      [...],
    "DOC_DATA":      {...},
    "ENG_ASSETS":    [...],
    "MTO_DATA":      {...},
    "COST_DATA":     {...},
    "DOC_MILESTONES":{...},
    "SCOPE_DATA":    {...},
    "BUILD_TIME":    "...",
    "BUILD_INFO":    "..."
  }
"""
import os, sys, re, json, glob, argparse, base64, datetime
import io as _io
# Force UTF-8 output on Windows
if hasattr(sys.stdout, "buffer"):
    sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = _io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
from pathlib import Path

os.chdir(Path(__file__).parent)
sys.path.insert(0, '.')

# ── CLI args ─────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description='Build BCF Dashboard data package')
parser.add_argument('--password', '-p', default=None,
                    help='Encryption password (default: read from config.yaml)')
parser.add_argument('--config',   '-c', default='config.yaml')
parser.add_argument('--out',      '-o', default=None,
                    help='Output path (default: from config or ./data.js)')
parser.add_argument('--plain',    action='store_true',
                    help='Write unencrypted JSON for debugging (data.js.json)')
args = parser.parse_args()

# ── Config ────────────────────────────────────────────────────────────────────
import yaml
# ── Load merged config (public + private) ────────────────────────
# Supports both old single-file and new split-file modes.
# Priority: config.private.yaml > config.public.yaml > config.yaml (legacy)
sys.path.insert(0, str(Path(__file__).parent))
try:
    from config_utils import load_merged_config, PUBLIC_PATH, PRIVATE_PATH
    cfg_path = Path(args.config)
    if cfg_path.name == 'config.yaml' and not cfg_path.exists():
        # Legacy fallback handled by load_merged_config
        cfg = load_merged_config()
    elif cfg_path.name in ('config.public.yaml', 'config.private.yaml'):
        cfg = load_merged_config()
    else:
        # Explicit --config path: load that file + private sidecar
        if cfg_path.exists():
            with open(cfg_path, encoding='utf-8') as f:
                cfg = yaml.safe_load(f) or {}
        else:
            sys.exit(f'[ERROR] Config not found: {cfg_path}')
        # Merge private sidecar if present
        priv_path = cfg_path.parent / 'config.private.yaml'
        if priv_path.exists():
            with open(priv_path, encoding='utf-8') as f:
                priv = yaml.safe_load(f) or {}
                cfg.update(priv)
except ImportError:
    # config_utils not available — fall back to legacy single file
    cfg_path = Path(args.config)
    if not cfg_path.exists():
        sys.exit(f'[ERROR] Config not found: {cfg_path}')
    with open(cfg_path, encoding='utf-8') as f:
        cfg = yaml.safe_load(f) or {}

password = args.password or cfg.get('data_password') or cfg.get('password')
if not password and not args.plain:
    sys.exit('[ERROR] No password. Set data_password in config.yaml or use --password / --plain')

out_path = Path(args.out) if args.out else Path(
    cfg.get('data_output', 'data.js'))

print(f'\n  BCF Dashboard — Data Build')
print(f'  Config:  {cfg_path}')
print(f'  Output:  {out_path}')
print()

# ── Parse all data sources ────────────────────────────────────────────────────
BUILD_TIME = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ')

# Issues (BCF + XLSX + VIMMRK)
from parsers.sources import load_all_sources
snap_cfg = cfg.get('snapshots', {})
spa_pri  = cfg.get('spatial_field_priority', [])
print('  Parsing issues...')
all_issues, _proj_guids = load_all_sources(
    sources             = cfg.get('bcf_sources', ['./exports/*.bcf']),
    spatial_priority    = spa_pri,
    snap_enabled        = snap_cfg.get('enabled', True),
    thumb_w             = snap_cfg.get('thumb_width',  480),
    thumb_h             = snap_cfg.get('thumb_height', 270),
    thumb_q             = snap_cfg.get('jpeg_quality',  82),
    source_assignments  = cfg.get('source_assignments', {}),
)
PROJECTS_obj = {k: v for k, v in _proj_guids.items() if v}

# Doc management
DOC_DATA_obj = {'documents': []}
try:
    from parsers.docmgt import parse_doc_management
    result = parse_doc_management(cfg, config_dir=str(Path('.')))
    if result: DOC_DATA_obj = result
except Exception as e:
    print(f'  [warn] Doc management: {e}')

# MSP / Gantt
MSP_obj = []
try:
    from parsers.msp import parse_msp_xml
    msp_path = cfg.get('msp_xml_path', '')
    if msp_path and os.path.exists(msp_path):
        MSP_obj = parse_msp_xml(msp_path) or []
        print(f'  MSP: {len(MSP_obj)} tasks')
except Exception as e:
    print(f'  [warn] MSP: {e}')

# Engineering assets
ENG_ASSETS_obj = []
try:
    from parsers.engassets import parse_eng_assets
    ENG_ASSETS_obj = parse_eng_assets(cfg) or []
except Exception as e:
    print(f'  [info] Eng assets: {e}')

# MTO
_MTO_FALLBACK = {'isometries': [], 'fittings': [], 'rev_base': 'Rev A', 'rev_cmp': 'Rev B'}
MTO_DATA_obj = _MTO_FALLBACK
try:
    from parsers.mtodata import parse_mto
    MTO_DATA_obj = parse_mto(cfg) or _MTO_FALLBACK
except Exception as e:
    print(f'  [info] MTO: {e}')

# Costs
_COST_FALLBACK = {'currency': 'CHF', 'total_budget': 0, 'total_actual': 0,
                  'total_committed': 0, 'budget_pct': 0, 'items': [], 'scurve': []}
COST_DATA_obj = _COST_FALLBACK
try:
    from parsers.costsdata import parse_costs
    COST_DATA_obj = parse_costs(cfg) or _COST_FALLBACK
except Exception as e:
    print(f'  [info] Costs: {e}')

# Doc milestones
_MILE_FALLBACK = {'labels': [], 'datasets': []}
DOC_MILESTONES_obj = _MILE_FALLBACK
try:
    from parsers.docmilestones import parse_doc_milestones
    DOC_MILESTONES_obj = parse_doc_milestones(cfg) or _MILE_FALLBACK
except Exception as e:
    print(f'  [info] Doc milestones: {e}')

# Scope
_SCOPE_FALLBACK = {'systems': [], 'doc_types': [], 'entries': []}
SCOPE_DATA_obj = _SCOPE_FALLBACK
try:
    from parsers.scopedata import parse_scope
    SCOPE_DATA_obj = parse_scope(cfg) or _SCOPE_FALLBACK
except Exception as e:
    print(f'  [info] Scope: {e}')

# Build info
BUILD_INFO = f"Built {BUILD_TIME} — {len(all_issues)} issues"

print(f'\n  Summary: {len(all_issues)} issues | {len(MSP_obj)} MSP tasks | {len(ENG_ASSETS_obj)} assets')

# ── Assemble payload ──────────────────────────────────────────────────────────
payload = {
    'RAW_DATA':       all_issues,
    'PROJECTS':       PROJECTS_obj,
    'CONFIG':         cfg,
    'MSP_DATA':       MSP_obj,
    'DOC_DATA':       DOC_DATA_obj,
    'ENG_ASSETS':     ENG_ASSETS_obj,
    'MTO_DATA':       MTO_DATA_obj,
    'COST_DATA':      COST_DATA_obj,
    'DOC_MILESTONES': DOC_MILESTONES_obj,
    'SCOPE_DATA':     SCOPE_DATA_obj,
    'BUILD_TIME':     BUILD_TIME,
    'BUILD_INFO':     BUILD_INFO,
}

payload_json = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
print(f'  Payload: {len(payload_json)/1024:.0f} KB uncompressed')

# ── Plain debug output ────────────────────────────────────────────────────────
if args.plain:
    debug_path = out_path.with_suffix('.json')
    debug_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\n[OK] Plain JSON written to: {debug_path}  (DEBUG ONLY — not for distribution)')
    sys.exit(0)

# ── Encrypt ───────────────────────────────────────────────────────────────────
import secrets
try:
    from Crypto.Cipher import AES
    from Crypto.Protocol.KDF import PBKDF2
    from Crypto.Hash import SHA256, HMAC
except ImportError:
    sys.exit('[ERROR] pip install pycryptodome')

pw    = password.encode()
salt  = secrets.token_bytes(16)
key   = PBKDF2(pw, salt, dkLen=32, count=200_000,
               prf=lambda p, s: HMAC.new(p, s, SHA256).digest())
iv    = secrets.token_bytes(12)
cipher = AES.new(key, AES.MODE_GCM, nonce=iv, mac_len=16)
ct, tag = cipher.encrypt_and_digest(payload_json)

def b64(b): return base64.b64encode(b).decode()

package = {
    'v':    1,
    'fmt':  'bcfdash-data',
    's':    b64(salt),
    'i':    b64(iv),
    'c':    b64(ct),
    't':    b64(tag),
    'ts':   BUILD_TIME,
    'info': BUILD_INFO,
    'n':    len(all_issues),   # issue count — visible without decryption
}

# ── Write output ──────────────────────────────────────────────────────────────
out_path.parent.mkdir(parents=True, exist_ok=True)
# Wrap as JS so Azure Static Web Apps serves it reliably
js_content = 'window._BCF_DATA=' + json.dumps(package) + ';'
out_path.write_text(js_content, encoding='utf-8')

size_kb = out_path.stat().st_size // 1024
print(f'\n[OK] Data package written: {out_path.resolve()}')
print(f'     Size:    {size_kb} KB  |  Issues: {len(all_issues)}  |  Encrypted: AES-256-GCM')
print(f'     Deploy this file alongside dashboard.html\n')
