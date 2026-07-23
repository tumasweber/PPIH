"""MS Project XML parser."""
from __future__ import annotations
import re
from pathlib import Path
import xml.etree.ElementTree as ET

# ── MS Project XML parser ─────────────────────────────────────────────────────
def parse_msp_xml(xml_path):
    """Parse a MS Project XML export and return a list of task dicts.

    Returns [] if the file does not exist or cannot be parsed.
    Each dict has: uid, name, wbs, level, summary, pct, start, finish
    """
    if not xml_path:
        return []
    path = Path(xml_path)
    if not path.exists():
        print(f"  [warn] msp_xml_path not found: {xml_path}")
        return []

    try:
        tree = ET.parse(str(path))
        root = tree.getroot()
    except ET.ParseError as e:
        print(f"  [warn] Could not parse MS Project XML: {e}")
        return []

    # MS Project XML uses a namespace — try with and without
    ns = "http://schemas.microsoft.com/project"
    def gt(el, tag):
        v = el.find(f"{{{ns}}}{tag}")
        if v is None:
            v = el.find(tag)
        return v.text.strip() if v is not None and v.text else ""

    tasks = []
    for task_el in root.iter(f"{{{ns}}}Task") or root.iter("Task"):
        uid = gt(task_el, "UID")
        if uid == "0":
            continue  # project root task
        name = gt(task_el, "n") or gt(task_el, "Name")
        if not name:
            continue
        raw_start  = gt(task_el, "Start")
        raw_finish = gt(task_el, "Finish")
        tasks.append({
            "uid":     uid,
            "name":    name,
            "wbs":     gt(task_el, "WBS") or gt(task_el, "OutlineNumber"),
            "level":   int(gt(task_el, "OutlineLevel") or "1"),
            "summary": gt(task_el, "Summary") == "1",
            "pct":     int(gt(task_el, "PercentComplete") or "0"),
            "start":   raw_start[:10]  if raw_start  else None,
            "finish":  raw_finish[:10] if raw_finish else None,
        })

    print(f"  MS Project XML: {len(tasks)} tasks loaded from {path.name}")
    return tasks


