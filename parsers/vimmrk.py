"""Revizto native .vimmrk format parser (reverse-engineered protobuf)."""
from __future__ import annotations
import os, re, json, zipfile, struct, base64, io
from datetime import datetime, timezone
from .utils import _sanitise, _extract_discipline, _make_thumbnail_b64, PILLOW_OK
try:
    from PIL import Image as PILImage
except ImportError:
    PILImage = None


# ─────────────────────────────────────────────────────────────────────────────
#  VIMMRK PARSER  (Revizto native format — reverse-engineered protobuf)
#
#  Structure of a .vimmrk file (ZIP archive):
#    .markers3/
#      custom                     → project config (workflows, stamps) — ignored
#      <issue-guid>/
#        small_snapshot.jpg       → ~4 KB preview image  ← used here
#        snapshot.jpg             → ~73 KB full image
#        marker                   → issue metadata (Protocol Buffers, no .proto)
#
#  Protobuf field map (reverse-engineered from issue_42.vimmrk):
#    marker root message:
#      field 1  varint   → issue ID (numeric)
#      field 2  string   → reporter email
#      field 3  string   → issue GUID
#      field 4  varint   → created  (.NET ticks, 100ns since 0001-01-01)
#      field 5  message  → camera/viewpoint (position, forward, up, fov)
#      field 6  message  → snapshot ref (field 2=filename, field 5=type)
#      field 9  string   → assignee email
#      field 13 string   → title
#      field 17 string   → author email
#      field 27 message  → repeated: viewpoints and comments
#        field 1 varint  → entry type (0=comment, 2=status change, 3=snapshot)
#        field 2 string  → author
#        field 3 string  → entry GUID
#        field 4 varint  → timestamp (.NET ticks)
#        field 6 string  → comment text
#        field 7 string  → mime type
#        field 10 string → snapshot name
#      field 61 string   → stamp abbreviation (e.g. "A040")
#      field 75 message  → element anchor
#        field 1 string  → element type (e.g. "Pipe")
#        field 6 string  → authoring ID (e.g. "470C")
#      field 82 message  → spatial data
#        field 1 string  → Level
#        field 3 string  → Room
#        field 5 string  → Zone
#      field 86 string   → workflow/type GUID
#      field 87 string   → status GUID
#
#  Status/priority/type GUIDs are resolved via the `custom` blob which
#  contains a lookup table of GUID → display name (also protobuf-encoded).
# ─────────────────────────────────────────────────────────────────────────────

def _dotnet_ticks_to_iso(ticks):
    """Convert .NET DateTime ticks (100ns since 0001-01-01) to ISO 8601 string."""
    if not ticks:
        return ""
    try:
        DOTNET_EPOCH_OFFSET = 621355968000000000  # ticks from 0001-01-01 to 1970-01-01
        unix_100ns = ticks - DOTNET_EPOCH_OFFSET
        if unix_100ns < 0:
            return ""
        dt = datetime(1970, 1, 1, tzinfo=timezone.utc) + \
             __import__('datetime').timedelta(microseconds=unix_100ns // 10)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return ""


def _pb_read_varint(data, pos):
    """Read a protobuf varint from data at pos. Returns (value, new_pos)."""
    result, shift = 0, 0
    while pos < len(data):
        b = data[pos]; pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
    return result, pos


def _pb_scan(data):
    """
    Minimal protobuf scanner — no schema required.
    Returns dict mapping field_number → list of values.
    wire_type 2 (length-delimited) values are returned as raw bytes so
    the caller can decide whether to decode as string or nested message.
    """
    import struct as _struct
    fields = {}
    pos = 0
    while pos < len(data):
        try:
            tag, pos = _pb_read_varint(data, pos)
            fnum = tag >> 3
            wtype = tag & 0x07
            if wtype == 0:
                val, pos = _pb_read_varint(data, pos)
            elif wtype == 1:
                val = _struct.unpack_from('<Q', data, pos)[0]; pos += 8
            elif wtype == 2:
                length, pos = _pb_read_varint(data, pos)
                val = data[pos:pos+length]; pos += length
            elif wtype == 5:
                val = _struct.unpack_from('<f', data, pos)[0]; pos += 4
            else:
                break  # unknown wire type — stop parsing
            fields.setdefault(fnum, []).append(val)
        except Exception:
            break
    return fields


def _pb_str(fields, fnum, default=""):
    """Get first string value for field number from a scanned field dict."""
    vals = fields.get(fnum, [])
    for v in vals:
        if isinstance(v, bytes):
            try:
                return _sanitise(v.decode('utf-8').strip())
            except UnicodeDecodeError:
                pass
        elif isinstance(v, str):
            return _sanitise(v.strip())
    return default


def _pb_int(fields, fnum, default=0):
    """Get first integer value for field number."""
    vals = fields.get(fnum, [])
    for v in vals:
        if isinstance(v, int):
            return v
    return default


def _parse_vimmrk_custom(data):
    """
    Parse the .markers3/custom blob to build a GUID → name lookup table.
    The custom blob contains workflow names, status names, stamp names etc.
    Each top-level repeated message (field 1 or 2) has:
      field 1 (bytes → nested): inner message with field 2=name string
      field 2 string → display name (directly readable)
    We scan for all string values and build guid→name from GUID-like strings
    followed by name strings in the same message.
    """
    import re as _re
    guid_re = _re.compile(
        rb'\$?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})',
        _re.IGNORECASE
    )
    # Extract all printable strings from the blob
    str_re = _re.compile(rb'[ -~]{4,}')
    guid_to_name = {}

    # Walk the raw bytes finding GUIDs and the text that follows them
    pos = 0
    while pos < len(data):
        m = guid_re.search(data, pos)
        if not m:
            break
        guid = m.group(1).decode('ascii').lower()
        # Look for a readable name in the next ~200 bytes
        window = data[m.end():m.end()+300]
        strings = str_re.findall(window)
        for s in strings:
            decoded = s.decode('ascii', errors='replace').strip()
            # Skip GUIDs and very short strings
            if len(decoded) >= 4 and not _re.match(
                    r'[0-9a-f]{8}-[0-9a-f]{4}', decoded, _re.I):
                guid_to_name[guid] = decoded
                break
        pos = m.end()

    return guid_to_name


def parse_vimmrk_file(path, assets_dir=None, snap_enabled=True, spatial_priority=None,
                      thumb_width=480, thumb_height=270, thumb_q=82):
    """
    Parse a Revizto .vimmrk file and return a list of issue dicts
    using the same schema as parse_bcf_file and parse_xlsx_file.

    Extracts per issue:
    - Metadata: GUID, title, stamp, author, assignee, created timestamp
    - Spatial:  Level, Room, Zone from field 82
    - Snapshot: small_snapshot.jpg (resized to thumbnail) — fast, ~4 KB each
    - Comments: text entries from repeated field 27
    """
    issues = []
    source  = os.path.basename(path)
    project = os.path.splitext(source)[0]

    if not zipfile.is_zipfile(path):
        print(f"[error] Not a valid ZIP/vimmrk file: {path}")
        return []

    try:
        with zipfile.ZipFile(path, 'r') as z:
            names = z.namelist()

            # Build GUID → name lookup from custom blob
            guid_to_name = {}
            if '.markers3/custom' in names:
                try:
                    custom_data = z.read('.markers3/custom')
                    guid_to_name = _parse_vimmrk_custom(custom_data)
                except Exception as e:
                    print(f"  [warn] Could not parse custom blob: {e}")

            # Find all marker files — path pattern: .markers3/<guid>/marker
            import re as _re
            marker_paths = [
                n for n in names
                if _re.match(
                    r'\.markers3/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-'
                    r'[0-9a-f]{4}-[0-9a-f]{12}/marker$', n, _re.I)
            ]

            for marker_path in marker_paths:
                try:
                    marker_data = z.read(marker_path)
                    f = _pb_scan(marker_data)

                    guid    = _pb_str(f, 3)
                    if not guid:
                        # Fall back to path component
                        guid = marker_path.split('/')[1]

                    issue_id  = _pb_int(f, 1)
                    reporter  = _pb_str(f, 2)
                    assignee  = _pb_str(f, 9)
                    title     = _pb_str(f, 13)
                    stamp_abbr= _pb_str(f, 61)
                    created_t = _pb_int(f, 4)
                    created   = _dotnet_ticks_to_iso(created_t)

                    # Spatial: field 82 → sub-message with Level/Room/Zone
                    level = room = zone = ""
                    spatial_blobs = f.get(82, [])
                    for blob in spatial_blobs:
                        if isinstance(blob, bytes):
                            sf = _pb_scan(blob)
                            level = _pb_str(sf, 1) or level
                            room  = _pb_str(sf, 3) or room
                            zone  = _pb_str(sf, 5) or zone

                    _sfp2 = spatial_priority or ["room","space","zone","area","level","grid_location"]
                    _sc2  = {"room":room,"zone":zone,"level":level,"space":"","area":"","grid_location":""}
                    spatial = next((v for f in _sfp2
                                    if (v := _sc2.get(f,""))), "") or ""

                    # Status/type from GUID lookup
                    status_guid = _pb_str(f, 87)
                    type_guid   = _pb_str(f, 86)
                    status = guid_to_name.get(status_guid.lower(), "Unknown")
                    ttype  = guid_to_name.get(type_guid.lower(),  "Unknown")

                    # Comments: repeated field 27
                    comments_data = []
                    for blob in f.get(27, []):
                        if not isinstance(blob, bytes):
                            continue
                        cf = _pb_scan(blob)
                        entry_type = _pb_int(cf, 1)  # 0=comment, 2=status, 3=snapshot
                        if entry_type != 0:           # only text comments
                            continue
                        text   = _pb_str(cf, 6)
                        author = _pb_str(cf, 2)
                        ts     = _dotnet_ticks_to_iso(_pb_int(cf, 4))
                        if text:
                            comments_data.append({
                                'text':   text,
                                'author': author,
                                'date':   ts,
                            })

                    # Small snapshot thumbnail
                    thumbnail_b64 = ""
                    has_snapshot  = False
                    small_snap_path = f".markers3/{guid}/small_snapshot.jpg"
                    if snap_enabled and small_snap_path in names:
                        try:
                            img_bytes = z.read(small_snap_path)
                            if img_bytes[:3] == b'\xff\xd8\xff':
                                has_snapshot  = True
                                thumbnail_b64 = _make_thumbnail_b64(
                                    img_bytes, thumb_width, thumb_height, quality=thumb_q)
                                if assets_dir:
                                    os.makedirs(assets_dir, exist_ok=True)
                                    with open(os.path.join(
                                            assets_dir, f"{guid}_small.jpg"), 'wb') as af:
                                        af.write(img_bytes)
                        except Exception as e:
                            print(f"    [warn] small_snapshot read error: {e}")

                    # Save full-size snapshot
                    if assets_dir:
                        full_snap_path = f".markers3/{guid}/snapshot.jpg"
                        if full_snap_path in names:
                            try:
                                full_bytes = z.read(full_snap_path)
                                with open(os.path.join(
                                        assets_dir, f"{guid}.jpg"), 'wb') as af:
                                    af.write(full_bytes)
                            except Exception:
                                pass

                    # Age + overdue
                    age_days = ""
                    overdue  = False
                    if created:
                        try:
                            c_dt = datetime.strptime(
                                created, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                            age_days = (datetime.now(timezone.utc) - c_dt).days
                        except Exception:
                            pass

                    issues.append({
                        "guid":          guid,
                        "title":         title or stamp_abbr or "(no title)",
                        "status":        status,
                        "type":          ttype,
                        "priority":      "Unknown",   # not in marker binary
                        "assigned":      assignee or "Unassigned",
                        "description":   "",
                        "labels":        [],
                        "discipline":    _extract_discipline(title or stamp_abbr),
                        "discipline_raw": "",
                        "level":         level,
                        "grid_location": "",
                        "room":          room,
                        "space":         "",
                        "area":          "",
                        "zone":          zone,
                        "spatial":       spatial,
                        "coords_m":      "",
                        "coords":        None,
                        "created":       created,
                        "modified":      "",
                        "due":           "",
                        "author":        reporter,
                        "stage":         "",
                        "age_days":      age_days,
                        "overdue":       overdue,
                        "comment_count": len(comments_data),
                        "comments":      comments_data,
                        "thumbnail":     thumbnail_b64,
                        "has_snapshot":  has_snapshot,
                        "snapshot_url":  "",
                        "source_file":   source,
                        "project":       project,
                        "bcf_version":   "vimmrk",
                    })

                except Exception as e:
                    print(f"  [warn] Skipping {marker_path}: {e}")

    except Exception as e:
        print(f"[error] Cannot open {path}: {e}")

    n_snap = sum(1 for i in issues if i.get('has_snapshot'))
    n_spat = sum(1 for i in issues if i.get('spatial'))
    print(f"    -> {len(issues)} issues, {n_snap} snapshots, {n_spat} with spatial data  (vimmrk)")
    return issues


# ─────────────────────────────────────────────────────────────────────────────
#  UNIFIED SOURCE LOADER  (auto-detects BCF vs XLSX vs VIMMRK)
# ─────────────────────────────────────────────────────────────────────────────

