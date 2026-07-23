#!/usr/bin/env python3
"""
issue_license.py — Sign a license token for a customer.

Usage:
  python issue_license.py \
    --customer "ACME Engineering AG" \
    --tier professional \
    --features issues costs gantt \
    --expires 2027-12-31 \
    --output acme_license.json

Only `customer`/`tier`/`features`/`expires` actually matter: paste those four
under `license:` in config.yaml, then rebuild with build_dashboard.py — it
re-signs from license_private.pem itself at build time and ignores any
pre-existing `token` block. The `token` this script outputs is for
inspection/record-keeping only; nothing reads it back in.
"""
import argparse, json, base64, datetime
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

TIERS = {
    'starter':      ['overview', 'issues'],
    'professional': ['overview', 'issues', 'gantt', 'costs', 'docs'],
    'enterprise':   ['overview', 'issues', 'gantt', 'engdocs', 'costs', 'docs', 'scope'],
}

p = argparse.ArgumentParser()
p.add_argument('--customer',  required=True)
p.add_argument('--tier',      choices=list(TIERS), default='professional')
p.add_argument('--features',  nargs='+', default=None,
               help='Override tier features. Valid: overview issues gantt engdocs costs docs scope')
p.add_argument('--expires',   default=None, help='YYYY-MM-DD, default: 1 year from today')
p.add_argument('--key',       default='license_private.pem')
p.add_argument('--output',    default=None)
args = p.parse_args()

if not Path(args.key).exists():
    import sys; sys.exit(f'[ERROR] Key not found: {args.key}\nRun: python generate_license_keys.py')

with open(args.key, 'rb') as f:
    private_key = serialization.load_pem_private_key(f.read(), password=None)

features = args.features or TIERS[args.tier]
expires  = args.expires  or (datetime.date.today() + datetime.timedelta(days=365)).isoformat()

payload = {
    'customer': args.customer,
    'tier':     args.tier,
    'features': sorted(set(features)),
    'expires':  expires,
}

payload_bytes = json.dumps(payload, separators=(',',':')).encode()
sig_der = private_key.sign(payload_bytes, ec.ECDSA(hashes.SHA256()))
# Convert DER to IEEE P1363 (raw r||s) — required by Web Crypto's ECDSA verify,
# same conversion build_dashboard.py and license_manager.py already do.
r, s = decode_dss_signature(sig_der)
sig = r.to_bytes(32, 'big') + s.to_bytes(32, 'big')

def b64url(b): return base64.urlsafe_b64encode(b).rstrip(b'=').decode()

token = {
    'payload': b64url(payload_bytes),
    'sig':     b64url(sig),
}

# config.yaml snippet
cfg_snippet = {
    'license': {
        **payload,
        'token': token,
    }
}

out = args.output or f"{args.customer.replace(' ','_').lower()}_license.json"
with open(out, 'w') as f:
    json.dump(cfg_snippet, f, indent=2, ensure_ascii=False)

print(f'License issued for: {args.customer}')
print(f'  Tier:     {args.tier}')
print(f'  Features: {features}')
print(f'  Expires:  {expires}')
print(f'  Output:   {out}')
print()
print('Add to config.yaml:')
print(json.dumps(cfg_snippet, indent=2, ensure_ascii=False))
