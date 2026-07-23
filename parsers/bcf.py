"""BCF (BIM Collaboration Format) parser."""
from __future__ import annotations
import os, re, json, zipfile, base64, io, glob
from pathlib import Path
from datetime import datetime, timezone
import xml.etree.ElementTree as ET
from .utils import _extract_discipline, _make_thumbnail_b64, _parse_date, PILLOW_OK, _sanitise
try:
    from PIL import Image as PILImage
except ImportError:
    PILImage = None


# ── BCF namespace variants ────────────────────────────────────────────────────
BCF_NS = [
    "http://www.buildingsmart-tech.org/extensions/bcf/2.1/",
    "http://www.buildingsmart-tech.org/extensions/bcf/2.0/",
    "",
]

# ─────────────────────────────────────────────────────────────────────────────
#  BCF PARSER
# ─────────────────────────────────────────────────────────────────────────────

def _find(element, tag):
    """Try multiple namespace variants for a tag."""
    for ns in BCF_NS:
        t = f"{{{ns}}}{tag}" if ns else tag
        found = element.find(t)
        if found is not None:
            return found
    return None

def _text(element, tag, default=""):
    """Return stripped text of a child element, or default."""
    if element is None:
        return default
    child = _find(element, tag)
    if child is not None and child.text:
        return _sanitise(child.text.strip())
    return default

def _attr(element, tag, attr, default=""):
    child = _find(element, tag)
    if child is not None:
        return child.get(attr, default)
    return default

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

def _detect_bcf_version(z):
    """
    Read bcf.version from the ZIP and return e.g. '2.1' or '3.0'.
    Falls back to '2.1' if the file is absent or unparseable.
    """
    try:
        raw = z.read("bcf.version")
        root = ET.fromstring(raw)
        vid = root.get("VersionId") or root.get("versionId") or ""
        if not vid:
            vid = _text(root, "VersionId")
        return vid or "2.1"
    except Exception:
        return "2.1"


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


def _extract_comments(root):
    """
    Extract all Comment elements from a markup.bcf root element.
    Returns a list of dicts with author, date, text.
    """
    comments = []
    for el in root.iter():
        if not (el.tag.endswith("Comment") or el.tag == "Comment"):
            continue
        # Skip elements that are just a GUID reference (e.g. <Comment>some-guid</Comment>)
        # Real comments have child elements
        if len(el) == 0 and el.text and len(el.text) == 36 and el.text.count("-") == 4:
            continue
        text   = _text(el, "Comment")
        author = _text(el, "Author")
        date   = _parse_date(_text(el, "Date"))
        if text or author:
            comments.append({
                "text":   text,
                "author": author,
                "date":   date,
            })
    return comments


def _find_snapshot(z, guid, markup_root=None):
    """
    Find the LATEST snapshot image for a BCF topic.

    Selection strategy (in order of preference):
    1. Parse <Viewpoints> in markup.bcf — pick the entry with the highest
       <Index> value, or the last one in document order if Index is absent.
       Then return the matching snapshot file (<ViewpointGuid>.jpg/png).
    2. Fall back to snapshot.jpg/snapshot.png (the BCF default first viewpoint).
    3. If multiple images exist with no markup guidance, pick the one with the
       latest modification timestamp in the ZIP central directory.

    Returns (raw_bytes, extension) or (None, None).
    """
    IMAGE_EXTS = (".jpg", ".jpeg", ".png")
    JPEG_SIG   = b"\xff\xd8\xff"
    PNG_SIG    = b"\x89PNG\r\n\x1a\n"

    def _valid_image(data, ext):
        """Return True if data looks like a valid image (by magic bytes, not ext)."""
        if data[:3] == JPEG_SIG:
            return True
        if data[:8] == PNG_SIG:
            return True
        if PILLOW_OK and len(data) > 16:
            try:
                PILImage.open(io.BytesIO(data)).verify()
                return True
            except Exception:
                pass
        return False

    def _detect_ext(data):
        """Return the actual extension based on magic bytes, ignoring declared name."""
        if data[:3] == JPEG_SIG:
            return ".jpg"
        if data[:8] == PNG_SIG:
            return ".png"
        return ".jpg"  # fallback

    def _read_image(path):
        try:
            data = z.read(path)
            if _valid_image(data, None):
                return data, _detect_ext(data)  # always use detected ext
        except KeyError:
            pass
        return None, None

    # ── Step 1: use markup to find the highest-indexed viewpoint ──────────────
    chosen_vp_guid = None
    if markup_root is not None:
        vp_entries = []
        for vp in markup_root.iter():
            if not (vp.tag.endswith("ViewPoint") or vp.tag.endswith("Viewpoints") or
                    vp.tag == "ViewPoint"):
                continue
            # Each <ViewPoint> has a Guid attribute or child <Guid>
            vp_guid = vp.get("Guid") or _text(vp, "Guid")
            if not vp_guid:
                continue
            try:
                idx = int(_text(vp, "Index"))
            except (ValueError, TypeError):
                idx = len(vp_entries)  # preserve document order
            vp_entries.append((idx, vp_guid))

        if vp_entries:
            # Highest index = latest viewpoint added in Revizto
            vp_entries.sort(key=lambda x: x[0], reverse=True)
            chosen_vp_guid = vp_entries[0][1]

    if chosen_vp_guid:
        for ext in (".jpg", ".jpeg", ".png"):
            data, found_ext = _read_image(f"{guid}/{chosen_vp_guid}{ext}")
            if data:
                return data, found_ext
        # Also try without extension match (some tools omit the snapshot extension)
        for name in z.namelist():
            if name.startswith(f"{guid}/{chosen_vp_guid}") and \
               name.lower().endswith(IMAGE_EXTS):
                data, found_ext = _read_image(name)
                if data:
                    return data, found_ext

    # ── Step 2: try standard BCF default snapshot names ───────────────────────
    for name in [f"{guid}/snapshot.jpg", f"{guid}/snapshot.jpeg",
                 f"{guid}/snapshot.png", f"{guid}/Snapshot.jpg",
                 f"{guid}/Snapshot.jpeg", f"{guid}/Snapshot.png"]:
        data, ext = _read_image(name)
        if data:
            return data, ext

    # ── Step 3: multiple images, no markup guidance — pick latest by ZIP mtime ─
    images_in_folder = []
    for info in z.infolist():
        name = info.filename
        if name.startswith(f"{guid}/") and name.lower().endswith(IMAGE_EXTS):
            # ZipInfo.date_time is (year, month, day, hour, min, sec)
            mtime = info.date_time  # tuple, sortable
            images_in_folder.append((mtime, name))

    if images_in_folder:
        images_in_folder.sort(key=lambda x: x[0], reverse=True)  # newest first
        for _, name in images_in_folder:
            data, ext = _read_image(name)
            if data:
                return data, ext

    return None, None






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


def parse_bcf_file(path, thumb_width=480, thumb_height=270, thumb_q=82,
                   assets_dir=None, snap_enabled=True):
    """
    Parse a single BCF file and return a list of issue dicts.
    Handles BCF 2.0, 2.1, and 3.0.

    Extracts per-topic:
    - Snapshot PNG → resized JPEG thumbnail embedded as base64 data URI
    - Full-size PNG → saved to assets_dir/<guid>.png (if assets_dir is set)
    - Comments → list of {author, date, text} dicts
    """
    issues = []
    source  = os.path.basename(path)
    project = os.path.splitext(source)[0]

    try:
        with zipfile.ZipFile(path, "r") as z:
            bcf_version = _detect_bcf_version(z)
            is_v3 = bcf_version.startswith("3")
            if bcf_version != "2.1":
                print(f"    BCF version: {bcf_version}")

            markups = [n for n in z.namelist()
                       if n.endswith("/markup.bcf") or n == "markup.bcf"]

            for markup_path in markups:
                try:
                    raw = z.read(markup_path)
                    root = ET.fromstring(raw)

                    topic = _find(root, "Topic")
                    if topic is None:
                        continue

                    guid     = topic.get("Guid") or topic.get("guid") or ""
                    _raw_st  = topic.get("TopicStatus") or _text(topic, "TopicStatus") or ""
                    # Normalise ACC/Autodesk snake_case statuses to display form
                    _ACC_STATUS = {"open":"Open","in_progress":"In progress",
                                   "in_review":"In progress","closed":"Closed",
                                   "resolved":"Resolved","done":"Closed","active":"Open"}
                    status   = _ACC_STATUS.get(_raw_st.lower(), _raw_st)
                    ttype    = topic.get("TopicType")  or _text(topic, "TopicType")
                    title    = _text(topic, "Title")
                    priority = _text(topic, "Priority")
                    desc     = _text(topic, "Description")
                    created  = _parse_date(_text(topic, "CreationDate"))
                    modified = _parse_date(_text(topic, "ModifiedDate"))
                    due      = _parse_date(_text(topic, "DueDate"))
                    author   = _text(topic, "CreationAuthor")
                    stage    = _text(topic, "Stage")

                    # AssignedTo — BCF 3.0 allows multiple
                    assigned_els = [c for c in topic
                                    if c.tag.endswith("AssignedTo") or c.tag == "AssignedTo"]
                    assignees_list = [_sanitise(e.text.strip()) for e in assigned_els if e.text]
                    assigned = ", ".join(assignees_list) if assignees_list else ""
                    # Labels
                    labels_el = _find(topic, "Labels")
                    labels = []
                    if labels_el is not None:
                        for lbl in list(labels_el):
                            if lbl.text:
                                labels.append(_sanitise(lbl.text.strip()))
                    if not labels and is_v3:
                        for lbl in topic:
                            if lbl.tag.endswith("Label") and lbl.text:
                                labels.append(_sanitise(lbl.text.strip()))

                    # Discipline — derived from title prefix (e.g. "P060_..." → "P")
                    # The prefix map is resolved at build time and injected via
                    # the CONFIG JSON; the raw prefix letter is stored here.
                    discipline = _extract_discipline(title)

                    # Comments (rich extraction)
                    comments_data = _extract_comments(root)
                    comment_count = len(comments_data)

                    # Snapshot thumbnail (base64 embedded)
                    thumbnail_b64 = ""
                    has_snapshot  = False
                    if guid and snap_enabled:
                        img_bytes, img_ext = _find_snapshot(z, guid, markup_root=root)
                        if img_bytes:
                            has_snapshot = True
                            thumbnail_b64 = _make_thumbnail_b64(
                                img_bytes, thumb_width, thumb_height, quality=thumb_q)
                            # Save full-size original to assets folder
                            if assets_dir:
                                os.makedirs(assets_dir, exist_ok=True)
                                asset_ext  = img_ext or ".jpg"
                                asset_path = os.path.join(assets_dir, f"{guid}{asset_ext}")
                                with open(asset_path, "wb") as af:
                                    af.write(img_bytes)

                    # Age in days
                    age_days = ""
                    if created:
                        try:
                            c_dt = datetime.strptime(created, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                            age_days = (datetime.now(timezone.utc) - c_dt).days
                        except Exception:
                            pass

                    # Overdue flag
                    overdue = False
                    if due and status not in ("Closed", "Resolved"):
                        try:
                            d_dt = datetime.strptime(due, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                            overdue = datetime.now(timezone.utc) > d_dt
                        except Exception:
                            pass

                    issues.append({
                        "guid":          guid,
                        "title":         title or "(no title)",
                        "status":        status or "Unknown",
                        "type":          ttype  or "Unknown",
                        "priority":      priority or "",
                        "assigned":      assigned or "Unassigned",
                        "assignees":     assignees_list if assigned else [],
                        "description":   desc,
                        "labels":        labels,
                        "discipline":    discipline,
                        "created":       created,
                        "modified":      modified,
                        "due":           due,
                        "author":        author,
                        "stage":         stage,
                        "age_days":      age_days,
                        "overdue":       overdue,
                        "comment_count": comment_count,
                        "comments":      comments_data,
                        "thumbnail":     thumbnail_b64,
                        "has_snapshot":  has_snapshot,
                        "snapshot_url":  "",
                        "source_file":   source,
                        "project":       project,
                        "bcf_version":   bcf_version,
                    })
                except ET.ParseError as e:
                    print(f"  [warn] XML parse error in {markup_path}: {e}")
                except Exception as e:
                    print(f"  [warn] Skipping {markup_path}: {e}")

    except zipfile.BadZipFile:
        print(f"[error] Not a valid ZIP/BCF file: {path}")
    except FileNotFoundError:
        print(f"[error] File not found: {path}")

    return issues




def load_all_bcf(sources, assets_dir=None, snap_enabled=True,
                 thumb_w=480, thumb_h=270, thumb_q=82):
    all_issues = []
    for pattern in sources:
        files = glob.glob(pattern)
        if not files:
            print(f"[warn] No files matched: {pattern}")
        for f in sorted(files):
            print(f"  Parsing {f} ...")
            batch = parse_bcf_file(f, assets_dir=assets_dir,
                                   snap_enabled=snap_enabled,
                                   thumb_width=thumb_w, thumb_height=thumb_h, thumb_q=thumb_q)
            n_snap = sum(1 for i in batch if i.get("has_snapshot"))
            print(f"    -> {len(batch)} issues, {n_snap} snapshots")
            all_issues.extend(batch)
    return all_issues


