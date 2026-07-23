"""Source loader — coordinates BCF, XLSX and VIMMRK parsers."""
from __future__ import annotations
import os, glob
import xml.etree.ElementTree as ET
from pathlib import Path
from .bcf    import parse_bcf_file
from .xlsx   import parse_xlsx_file
from .vimmrk import parse_vimmrk_file

def load_all_sources(sources, assets_dir=None, spatial_priority=None, snap_enabled=True,
                     thumb_w=480, thumb_h=270, thumb_q=82,
                     source_assignments=None):
    """
    Load issues from BCF, XLSX, and/or VIMMRK files.
    Files are matched by glob pattern; type is detected by extension.

    Merge priority when the same GUID appears in multiple sources:
      XLSX > VIMMRK > BCF
    (XLSX has the most complete metadata; VIMMRK adds small snapshots;
     BCF contributes full-resolution snapshots when nothing else does.)
    """
    bcf_files    = []
    xlsx_files   = []
    vimmrk_files = []

    for pattern in sources:
        for f in sorted(glob.glob(pattern)):
            ext = os.path.splitext(f)[1].lower()
            if ext in ('.bcf', '.bcfzip'):
                bcf_files.append(f)
            elif ext in ('.xlsx', '.xls'):
                xlsx_files.append(f)
            elif ext == '.vimmrk':
                vimmrk_files.append(f)
            else:
                print(f"  [warn] Unknown file type, skipping: {f}")

    # ── Parse each source ────────────────────────────────────────────────────
    bcf_by_guid    = {}
    xlsx_by_guid   = {}
    vimmrk_by_guid = {}

    for f in bcf_files:
        print(f"  Parsing BCF: {f} ...")
        batch = parse_bcf_file(f, assets_dir=assets_dir, snap_enabled=snap_enabled,
                               thumb_width=thumb_w, thumb_height=thumb_h, thumb_q=thumb_q)
        n_snap = sum(1 for i in batch if i.get("has_snapshot"))
        print(f"    -> {len(batch)} issues, {n_snap} snapshots")
        for issue in batch:
            issue.setdefault('source_file', os.path.basename(f))
            bcf_by_guid[issue['guid']] = issue

    for f in xlsx_files:
        print(f"  Parsing XLSX: {f} ...")
        for issue in parse_xlsx_file(f, spatial_priority=spatial_priority):
            issue.setdefault('source_file', os.path.basename(f))
            xlsx_by_guid[issue['guid']] = issue

    for f in vimmrk_files:
        print(f"  Parsing VIMMRK: {f} ...")
        for issue in parse_vimmrk_file(
                f, assets_dir=assets_dir, snap_enabled=snap_enabled,
                spatial_priority=spatial_priority,
                thumb_width=thumb_w, thumb_height=thumb_h, thumb_q=thumb_q):
            issue.setdefault('source_file', os.path.basename(f))
            vimmrk_by_guid[issue['guid']] = issue

    # ── Merge: XLSX > VIMMRK > BCF ───────────────────────────────────────────
    all_guids = set(bcf_by_guid) | set(xlsx_by_guid) | set(vimmrk_by_guid)
    merged = {}
    for guid in all_guids:
        # Start with lowest-priority source, overlay higher-priority on top
        issue = bcf_by_guid.get(guid, {}).copy()

        if guid in vimmrk_by_guid:
            vm = vimmrk_by_guid[guid]
            if issue:
                # Overlay spatial + snapshot from VIMMRK onto BCF base
                for spatial_field in ('level', 'room', 'space', 'area',
                                      'zone', 'spatial', 'grid_location'):
                    if vm.get(spatial_field):
                        issue[spatial_field] = vm[spatial_field]
                if vm.get('thumbnail') and not issue.get('thumbnail'):
                    issue['thumbnail']    = vm['thumbnail']
                    issue['has_snapshot'] = True
            else:
                issue = vm.copy()

        if guid in xlsx_by_guid:
            xl = xlsx_by_guid[guid]
            if issue:
                # XLSX wins on all metadata; preserve snapshot from BCF/VIMMRK
                saved_thumb    = issue.get('thumbnail')
                saved_snap     = issue.get('has_snapshot')
                saved_snap_url = issue.get('snapshot_url', '')
                issue = xl.copy()
                if not issue.get('thumbnail') and saved_thumb:
                    issue['thumbnail']    = saved_thumb
                    issue['has_snapshot'] = saved_snap
                # XLSX snapshot_url takes priority, but keep fallback
                if not issue.get('snapshot_url') and saved_snap_url:
                    issue['snapshot_url'] = saved_snap_url
            else:
                issue = xl.copy()

        merged[guid] = issue

    all_issues = list(merged.values())

    # ── Apply org project assignments ────────────────────────────────────────
    # Build a unified lookup: lowercase_basename → org_project_name
    # Sources: (1) explicit source_assignments dict, (2) organisation.departments structure
    assign_map = {}  # lowercase filename → org project name

    # Source 1: source_assignments = { "path/to/file.xlsx": {project: "Name"}, ... }
    if source_assignments:
        for path, assign in source_assignments.items():
            if assign and assign.get('project'):
                key = os.path.basename(path).lower()
                assign_map[key] = assign['project']
                # Also index without extension for looser matching
                stem = os.path.splitext(key)[0]
                if stem not in assign_map:
                    assign_map[stem] = assign['project']

    # Source 2: organisation.departments[].projects[].sources[] (written by Admin UI)
    # sources is a list of file paths assigned to that project
    org = (source_assignments or {})  # not used here — cfg not passed in
    # (cfg is not available here; source_assignments is the only external input)

    if assign_map:
        for issue in all_issues:
            sf = (issue.get('source_file') or '').lower()
            if not sf:
                continue
            sf_stem = os.path.splitext(sf)[0]
            # Exact basename match first, then stem match
            org_proj = assign_map.get(sf) or assign_map.get(sf_stem)
            if org_proj:
                issue['org_project'] = org_proj

    # ── Build project map ────────────────────────────────────────────────────
    # Group GUIDs by project stem (filename without extension).
    # Files with the same stem (e.g. project1.bcf + project1.xlsx) belong to
    # the same project. The display name is the stem with underscores/hyphens
    # replaced by spaces and title-cased.
    projects = {}   # display_name → [guid, ...]
    for issue in all_issues:
        # org_project (from source_assignments) takes priority over BCF-internal name
        if issue.get('org_project'):
            projects.setdefault(issue['org_project'], []).append(issue['guid'])
        else:
            stem = issue.get('project', issue.get('source_file', 'Unknown'))
            stem = stem.replace('_', ' ').replace('-', ' ').strip()
            projects.setdefault(stem, []).append(issue['guid'])

    n_spatial  = sum(1 for i in all_issues if i.get('spatial'))
    n_snap     = sum(1 for i in all_issues if i.get('has_snapshot'))
    if bcf_files:    print(f"    BCF:    {len(bcf_files)} file(s) -> {len(bcf_by_guid)} issues")
    if xlsx_files:   print(f"    XLSX:   {len(xlsx_files)} file(s) -> {len(xlsx_by_guid)} issues")
    if vimmrk_files: print(f"    VIMMRK: {len(vimmrk_files)} file(s) -> {len(vimmrk_by_guid)} issues")
    print(f"    Total: {len(all_issues)} unique issues  |  spatial: {n_spatial}  |  snapshots: {n_snap}")
    print(f"    Projects: {list(projects.keys())}")
    return all_issues, projects




