"""Shared utility functions used across parser modules."""
from __future__ import annotations
import re, json, io, base64
from datetime import datetime, timezone
from pathlib import Path
try:
    from PIL import Image as PILImage
    PILLOW_OK = True
except ImportError:
    PILImage = None
    PILLOW_OK = False


def _sanitise(s):
    """
    Remove characters that would break JSON inside a <script> block:
    null bytes, lone surrogates, and other control characters except
    tab/newline/CR which json.dumps handles safely.
    Also strips the vertical tab and form-feed control chars common
    in copy-pasted text from Windows apps.
    """
    if not isinstance(s, str):
        return s
    # Remove null bytes and non-printable control chars (keep \t \n \r)
    return "".join(c for c in s if c == "\t" or c == "\n" or c == "\r"
                   or (ord(c) >= 32 and ord(c) != 127))


def _extract_discipline(title):
    """
    Derive the discipline prefix letter from an issue title.
    Expected format: <PREFIX><digits>_<rest>  e.g. "P060_Pump suction..."
    Returns the uppercase prefix letter, or "" if none matches.
    The prefix map (letter → full name) lives in config.yaml and is
    resolved in JavaScript at render time so the dashboard stays configurable.
    """
    if not title:
        return ""
    import re
    m = re.match(r'^([A-Za-z]+)\d', title.strip())
    if m:
        return m.group(1).upper()
    return ""


def _make_thumbnail_b64(img_bytes, max_width=480, max_height=270, quality=82):
    """
    Resize any image (JPEG or PNG) to a thumbnail and return as a base64 data URI.
    Always outputs JPEG for consistent compression.
    Falls back to the original (capped at 150 KB) if Pillow is unavailable.
    """
    if not PILLOW_OK:
        if len(img_bytes) <= 150_000:
            # Detect mime type from signature
            mime = "image/jpeg" if img_bytes[:3] == b"\xff\xd8\xff" else "image/png"
            return f"data:{mime};base64," + base64.b64encode(img_bytes).decode()
        return ""
    try:
        img = PILImage.open(io.BytesIO(img_bytes))
        img.thumbnail((max_width, max_height), PILImage.LANCZOS)
        # Convert to RGB (strips alpha channel and palette modes)
        if img.mode in ("RGBA", "P"):
            bg = PILImage.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3] if img.mode == "RGBA" else None)
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        print(f"    [warn] Thumbnail error: {e}")
        return ""


def _parse_date(s):
    """Return ISO date string or empty string."""
    if not s:
        return ""
    s = s.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            pass
    return ""  # unrecognised format — treat as missing


def apply_filters(issues, flt):
    def matches(issue):
        for field in ("status", "type", "priority"):
            allowed = flt.get(field, [])
            if allowed and issue.get(field) not in allowed:
                return False
        inc = flt.get("label_include", [])
        exc = flt.get("label_exclude", [])
        lbls = set(issue.get("labels", []))
        if inc and not lbls.intersection(inc):
            return False
        if exc and lbls.intersection(exc):
            return False
        return True
    return [i for i in issues if matches(i)]
