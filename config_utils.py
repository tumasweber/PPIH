"""
config_utils.py — Merged config loader for BCF Dashboard.

Loads and merges public + private config files:
  config.public.yaml  — committed to git (org structure, layout, mappings)
  config.private.yaml — gitignored (passwords, credentials, licence)

Usage:
  from config_utils import load_merged_config, save_public_config, save_private_config

The merged dict behaves exactly like the old single config.yaml.
"""
from __future__ import annotations
import os
from pathlib import Path
import yaml

_HERE = Path(__file__).parent

PUBLIC_PATH  = _HERE / "config.public.yaml"
PRIVATE_PATH = _HERE / "config.private.yaml"

# Keys that belong in the PRIVATE file
PRIVATE_KEYS = {
    "data_password", "admin_password", "password",
    "license",
}
# Nested keys that are private (checked on doc_management.sources.*)
PRIVATE_SOURCE_KEYS = {"sharepoint"}  # sharepoint sub-dict contains OAuth credentials


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Merge overlay into base recursively. Overlay wins on conflicts."""
    result = base.copy()
    for k, v in overlay.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_merged_config(public_path=None, private_path=None) -> dict:
    """Load and merge public + private configs. Returns combined dict."""
    pub  = public_path  or PUBLIC_PATH
    priv = private_path or PRIVATE_PATH

    cfg = {}
    for path in (pub, priv):
        p = Path(path)
        if p.exists():
            with open(p, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                cfg = _deep_merge(cfg, data)

    return cfg


def _split_config(merged: dict):
    """Split merged config dict into (public_dict, private_dict)."""
    pub  = {}
    priv = {}
    for k, v in merged.items():
        if k in PRIVATE_KEYS:
            priv[k] = v
        elif k == "doc_management" and isinstance(v, dict):
            # Split doc_management: sources.sharepoint goes private
            pub_dm  = {sk: sv for sk, sv in v.items() if sk != "sources"}
            priv_dm = {}
            if "sources" in v and isinstance(v["sources"], dict):
                pub_sources  = {}
                priv_sources = {}
                for src_name, src_cfg in v["sources"].items():
                    if isinstance(src_cfg, dict) and src_name in PRIVATE_SOURCE_KEYS:
                        priv_sources[src_name] = src_cfg
                    elif isinstance(src_cfg, dict) and "sharepoint" in src_cfg:
                        # Strip nested sharepoint OAuth block
                        pub_src = {sk: sv for sk, sv in src_cfg.items() if sk != "sharepoint"}
                        priv_src = {"sharepoint": src_cfg["sharepoint"]}
                        pub_sources[src_name]  = pub_src
                        priv_sources[src_name] = priv_src
                    else:
                        pub_sources[src_name] = src_cfg
                pub_dm["sources"]  = pub_sources
                if priv_sources:
                    priv_dm["sources"] = priv_sources
            pub["doc_management"] = pub_dm
            if priv_dm:
                priv["doc_management"] = priv_dm
        elif k == "git" and isinstance(v, dict):
            # git.auto_push is public; git.token (if present) is private
            pub_git  = {gk: gv for gk, gv in v.items() if gk not in ("token", "password")}
            priv_git = {gk: gv for gk, gv in v.items() if gk in ("token", "password")}
            pub["git"] = pub_git
            if priv_git:
                priv["git"] = priv_git
        else:
            pub[k] = v
    return pub, priv


def save_public_config(data: dict, path=None):
    """Write only the public portion of data to config.public.yaml."""
    pub, _ = _split_config(data)
    p = Path(path or PUBLIC_PATH)
    with open(p, "w", encoding="utf-8") as f:
        yaml.dump(pub, f, allow_unicode=True, default_flow_style=False,
                  sort_keys=False, width=120)


def save_private_config(data: dict, path=None):
    """Write only the private portion of data to config.private.yaml."""
    _, priv = _split_config(data)
    p = Path(path or PRIVATE_PATH)
    # Only write if there's something to write
    if not priv:
        return
    with open(p, "w", encoding="utf-8") as f:
        yaml.dump(priv, f, allow_unicode=True, default_flow_style=False,
                  sort_keys=False, width=120)


def save_both_configs(data: dict, public_path=None, private_path=None):
    """Write both public and private configs from a merged dict."""
    save_public_config(data, public_path)
    save_private_config(data, private_path)


def migrate_from_single_config(source_path="config.yaml", backup=True):
    """One-time migration: split existing config.yaml into public + private."""
    src = Path(source_path)
    if not src.exists():
        print(f"[config_utils] {source_path} not found — nothing to migrate.")
        return
    with open(src, encoding="utf-8") as f:
        merged = yaml.safe_load(f) or {}
    if backup:
        bak = src.with_suffix(".yaml.bak")
        import shutil
        shutil.copy2(src, bak)
        print(f"[config_utils] Backed up to {bak}")
    save_both_configs(merged)
    print(f"[config_utils] Migrated to {PUBLIC_PATH} + {PRIVATE_PATH}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "migrate":
        src = sys.argv[2] if len(sys.argv) > 2 else "config.yaml"
        migrate_from_single_config(src)
    else:
        print("Usage: python config_utils.py migrate [config.yaml]")
