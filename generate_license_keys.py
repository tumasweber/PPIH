#!/usr/bin/env python3
"""
generate_license_keys.py
Run ONCE to create your ECDSA P-256 keypair.
  python generate_license_keys.py

Outputs:
  license_private.pem   — keep SECRET, never commit
  license_public.pem    — embed in template.html (already done by build_dashboard.py)

The private key signs license tokens at build time.
The public key verifies tokens in the browser (Web Crypto API, ECDSA P-256 SHA-256).
"""
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

key = ec.generate_private_key(ec.SECP256R1())

with open('license_private.pem', 'wb') as f:
    f.write(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()
    ))

pub = key.public_key()
with open('license_public.pem', 'wb') as f:
    f.write(pub.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo
    ))

# Also export raw JWK-compatible format for Web Crypto
import json, base64
from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1
from cryptography.hazmat.backends import default_backend

pub_nums = pub.public_key().public_numbers() if hasattr(pub, 'public_key') else pub.public_numbers()
x = pub_nums.x.to_bytes(32, 'big')
y = pub_nums.y.to_bytes(32, 'big')

def b64url(b): return base64.urlsafe_b64encode(b).rstrip(b'=').decode()

jwk = {"kty":"EC","crv":"P-256","x":b64url(x),"y":b64url(y)}
with open('license_public.jwk', 'w') as f:
    json.dump(jwk, f, indent=2)

print("Generated:")
print("  license_private.pem  — KEEP SECRET, add to .gitignore")
print("  license_public.pem   — safe to commit")
print("  license_public.jwk   — embedded in dashboard by build script")
print()
print("JWK public key:")
print(json.dumps(jwk, indent=2))
