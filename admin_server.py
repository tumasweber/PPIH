"""
BCF Dashboard — Admin Server
============================
A lightweight local HTTP server that:
  - Serves admin.html at http://localhost:5050/
  - Exposes a REST API so the admin UI can read/write config.yaml
    and trigger dashboard builds without editing files manually.

Usage:
    python admin_server.py               # default port 5050
    python admin_server.py --port 8080   # custom port

The server only binds to localhost — it is not exposed to the network.
"""

import argparse, glob, json, os, subprocess, sys, threading, time, webbrowser
import io as _io

# Force UTF-8 output on Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8','utf8'):
    sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = _io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

try:
    import yaml
except ImportError:
    print("[error] PyYAML not installed. Run: pip install pyyaml")
    sys.exit(1)

BASE_DIR    = Path(__file__).parent.resolve()
CONFIG_PATH = BASE_DIR / "config.yaml"
BUILD_SCRIPT = BASE_DIR / "build_dashboard.py"

def get_output_html():
    """Return the dashboard output path from config, defaulting to dashboard.html."""
    try:
        cfg = load_config()
        p = cfg.get("output_path", "").strip()
        if p:
            return Path(p) if os.path.isabs(p) else BASE_DIR / p
    except Exception:
        pass
    return BASE_DIR / "dashboard.html"

# ── build log (in-memory ring buffer) ────────────────────────────
_build_log   = []
_build_lock  = threading.Lock()
_build_status = "idle"  # idle | running | done | error


def _append_log(line):
    with _build_lock:
        _build_log.append(line)
        if len(_build_log) > 500:
            _build_log.pop(0)

def _set_status(status):
    global _build_status
    with _build_lock:
        _build_status = status


# ── YAML helpers ─────────────────────────────────────────────────
def load_config():
    if not CONFIG_PATH.exists():
        return {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_private_config():
    priv = BASE_DIR / "config.private.yaml"
    if not priv.exists():
        return {}
    with open(priv, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _find_git():
    """Find git executable — handles Windows where git may not be on PATH for subprocesses."""
    import shutil, os
    git = shutil.which("git")
    if git:
        return git
    # Try via shell on Windows (inherits full user PATH)
    if sys.platform == "win32":
        try:
            r = subprocess.run("where git", shell=True, capture_output=True, text=True)
            first = r.stdout.strip().splitlines()[0].strip()
            if first and os.path.exists(first):
                return first
        except Exception:
            pass
    # Common Windows install paths
    candidates = [
        r"C:\Program Files\Git\bin\git.exe",
        r"C:\Program Files (x86)\Git\bin\git.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Git\bin\git.exe"),
        r"C:\Git\bin\git.exe",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def save_config(data):
    # Write full config to config.yaml (local, gitignored)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False,
                  sort_keys=False, width=120)
    # Also write public keys to config.public.yaml (tracked in git)
    PUBLIC_KEYS = [
        "dashboard", "bcf_sources", "spatial_field_priority", "msp_xml_path",
        "msp_task_map", "discipline_map", "discipline_colors", "colors",
        "layout", "filters", "snapshots", "organisation", "source_assignments",
        "departments", "source_patterns", "doc_management", "output_path",
    ]
    pub_path = BASE_DIR / "config.public.yaml"
    try:
        with open(pub_path, "r", encoding="utf-8") as f:
            pub = yaml.safe_load(f) or {}
    except FileNotFoundError:
        pub = {}
    for key in PUBLIC_KEYS:
        if key in data:
            pub[key] = data[key]
    with open(pub_path, "w", encoding="utf-8") as f:
        yaml.dump(pub, f, allow_unicode=True, default_flow_style=False,
                  sort_keys=False, width=120)


# ── build runner (background thread) ─────────────────────────────
def run_build(port=5050):
    global _build_status
    with _build_lock:
        _build_log.clear()
        _build_status = "running"

    output_html = get_output_html()
    _append_log(">> Starting build...\n")
    _append_log(f"  Script:  {BUILD_SCRIPT}\n")
    _append_log(f"  Output:  {output_html}\n\n")

    try:
        cmd = [sys.executable, str(BUILD_SCRIPT), "--lean"]
        # Pass password from private config for encrypted build
        priv = load_private_config()
        cfg  = load_config()
        pw   = (priv.get("data_password", "") or priv.get("password", "") or
                cfg.get("data_password",  "") or cfg.get("password",  "")).strip()
        if pw:
            cmd += ["--password", pw]
        op = cfg.get("output_path", "").strip()
        if op:
            cmd += ["--output", op]

        proc = subprocess.Popen(
            cmd,
            cwd=str(BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True, bufsize=1,
            # Windows: hide console window
            **( {"creationflags": 0x08000000} if sys.platform == "win32" else {} )
        )
        for line in proc.stdout:
            _append_log(line)
        proc.wait()
        with _build_lock:
            _build_status = "done" if proc.returncode == 0 else "error"
        if proc.returncode == 0:
            _append_log(f"\n[OK] Build complete -> {output_html}\n")
        else:
            _append_log(f"\n[FAIL] Build failed (exit code {proc.returncode}).\n")
    except Exception as e:
        _append_log(f"\n[ERROR] Exception: {e}\n")
        with _build_lock:
            _build_status = "error"


# ── Git auto-push ────────────────────────────────────────────────
def run_git_push(commit_msg=None):
    """Push only whitelisted code files.
    NEVER: exports/, data.js, config.yaml, config.private.yaml, reset --soft."""
    if commit_msg is None:
        commit_msg = f"Update code: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}"
    _append_log(f"\n[GIT] Code push — staging whitelisted files...\n")
    git = _find_git() or "git"

    def _r(args, lbl):
        try:
            p = subprocess.Popen(
                args, cwd=str(BASE_DIR),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
                **( {"creationflags": 0x08000000} if sys.platform == "win32" else {} )
            )
            for ln in p.stdout:
                _append_log(f"  {ln}")
            p.wait()
            _append_log(f"[GIT] {lbl} {'OK' if p.returncode==0 else 'FAILED (exit ' + str(p.returncode) + ')'}\n")
            return p.returncode == 0
        except FileNotFoundError:
            _append_log("[GIT] git not found\n")
            return False

    whitelist = [
        "index.html", "template.html", "build_dashboard.py", "build_data.py",
        "admin.html", "admin_server.py", "config_utils.py", "config.public.yaml",
        "staticwebapp.config.json", "requirements.txt", "default.html",
        "swa-cli.config.json", ".github", "parsers",
    ]
    for name in whitelist:
        p = BASE_DIR / name
        if p.exists():
            _r([git, "add", str(p)], f"git add {name}")

    r = subprocess.run([git, "diff", "--staged", "--quiet"], cwd=str(BASE_DIR))
    if r.returncode == 0:
        _append_log("[GIT] Nothing to commit — all files already up to date.\n")
        return True

    ok = _r([git, "commit", "-m", commit_msg], "git commit")
    # Reset data.js to remote state to avoid merge conflicts
    subprocess.run([git, "checkout", "origin/main", "--", "data.js"],
                   cwd=str(BASE_DIR), capture_output=True)
    ok = ok and _r([git, "pull", "--rebase", "--autostash", "origin", "main"], "git pull --rebase --autostash")
    ok = ok and _r([git, "push", "origin", "main"], "git push")
    if ok:
        _append_log("[GIT] Push complete — GitHub Actions triggered.\n")
    return ok


def run_build_and_push(port=5050):
    """Build, then optionally git-push if auto_push is enabled in config."""
    run_build(port)
    cfg = load_config()
    if cfg.get("git", {}).get("auto_push", False):
        with _build_lock:
            status = _build_status
        if status == "done":
            run_git_push()
        else:
            _append_log("[GIT] Build did not succeed — skipping push.\n")


# ── data build runner ────────────────────────────────────────────────────────
DATA_BUILD_SCRIPT = BASE_DIR / "build_data.py"

def run_data_build():
    global _build_status
    with _build_lock:
        _build_log.clear()
        _build_status = "running"
    _append_log(">> DATA build (build_data.py)...\n")
    try:
        cfg = load_config()
        cmd = [sys.executable, str(DATA_BUILD_SCRIPT)]
        pw  = cfg.get("data_password", "").strip() or cfg.get("password", "").strip()
        if pw:
            cmd += ["--password", pw]
        op  = cfg.get("data_output", "").strip()
        if op:
            cmd += ["--out", op]
        if not DATA_BUILD_SCRIPT.exists():
            _append_log(f"[ERROR] build_data.py not found at {DATA_BUILD_SCRIPT}\n")
            with _build_lock: _build_status = "error"
            return
        _append_log(f"  Script:   {DATA_BUILD_SCRIPT}\n")
        _append_log(f"  Password: {'set (' + str(len(pw)) + ' chars)' if pw else 'NOT SET — will fail'}\n\n")
        proc = subprocess.Popen(cmd, cwd=str(BASE_DIR),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
            **( {"creationflags": 0x08000000} if sys.platform == "win32" else {} ))
        for line in proc.stdout:
            _append_log(line)
        proc.wait()
        with _build_lock:
            _build_status = "done" if proc.returncode == 0 else "error"
        _append_log(f"\n[{'OK' if proc.returncode==0 else 'FAIL'}] Data build {'complete' if proc.returncode==0 else 'FAILED'}\n")
    except Exception as e:
        _append_log(f"\n[ERROR] {e}\n")
        with _build_lock: _build_status = "error"

def run_data_build_and_push():
    run_data_build()
    cfg = load_config()
    if cfg.get("git", {}).get("auto_push", False):
        with _build_lock: ok = _build_status == "done"
        if ok: run_git_push_data()
        else:  _append_log("[GIT] Data build failed — skipping push.\n")

def run_git_push_data(commit_msg=None):
    cfg = load_config()
    dp  = BASE_DIR / cfg.get("data_output", "data.js")
    if not dp.exists():
        _append_log(f"\n[GIT] {dp.name} not found.\n"); return False
    if commit_msg is None:
        commit_msg = f"Update data: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}"
    _append_log(f"\n[GIT] Pushing {dp.name}...\n")
    def _r(args, lbl):
        try:
            p = subprocess.Popen(args, cwd=str(BASE_DIR),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
                **( {"creationflags": 0x08000000} if sys.platform == "win32" else {} ))
            for ln in p.stdout: _append_log(f"  {ln}")
            p.wait()
            _append_log(f"[GIT] {lbl} {'OK' if p.returncode==0 else 'FAILED'}\n")
            return p.returncode == 0
        except FileNotFoundError:
            _append_log("[GIT] git not found — install Git for Windows: https://git-scm.com/download/win\n"); return False
    git = _find_git() or "git"
    ok = _r([git, "add", "-f", str(dp)], f"git add -f {dp.name}")
    if subprocess.run([git, "diff", "--staged", "--quiet"], cwd=str(BASE_DIR)).returncode == 0:
        _append_log("[GIT] Nothing new.\n"); return True
    ok = ok and _r([git, "commit", "-m", commit_msg], "git commit")
    # Remote moves on every push (CI commits its own rebuild back within ~60s) —
    # rebase first and keep OUR data.js on conflict, same reason run_git_push()
    # resets data.js from origin first (just the opposite side winning here).
    ok = ok and _r([git, "pull", "--rebase", "-X", "ours", "--autostash", "origin", "main"],
                    "git pull --rebase -X ours --autostash")
    ok = ok and _r([git, "push", "origin", "main"], "git push")
    if ok: _append_log("[GIT] Push complete.\n")
    return ok


def run_git_push_all(commit_msg=None):
    """Deprecated — redirects to safe whitelist push."""
    _append_log("\n[GIT] Push All → safe whitelist push (exports/ excluded).\n")
    return run_git_push(commit_msg)


def run_swa_deploy():
    """Deploy directly to Azure Static Web Apps via SWA CLI — bypasses GitHub Actions.
    Requires 'azure_swa_token' in config.private.yaml and 'swa' CLI on PATH."""
    _append_log("\n[SWA] Direct deploy to Azure Static Web Apps...\n")

    priv  = load_private_config()
    token = priv.get("azure_swa_token", "").strip()
    if not token:
        _append_log("[SWA] ERROR: 'azure_swa_token' not found in config.private.yaml.\n")
        _append_log("[SWA] Add it like:\n  azure_swa_token: \"your-deployment-token\"\n")
        with _build_lock:
            global _build_status
            _build_status = "error"
        return

    # Check swa CLI available
    import shutil, os
    swa_cmd = shutil.which("swa") or shutil.which("swa.cmd")
    if not swa_cmd:
        # Try common npm global paths on Windows
        npm_prefix = subprocess.run(
            ["npm", "config", "get", "prefix"],
            capture_output=True, text=True,
            **( {"creationflags": 0x08000000} if sys.platform == "win32" else {} )
        ).stdout.strip()
        candidates = [
            os.path.join(npm_prefix, "swa.cmd"),
            os.path.join(npm_prefix, "swa"),
        ]
        for c in candidates:
            if os.path.exists(c):
                swa_cmd = c
                break
    if not swa_cmd:
        _append_log("[SWA] ERROR: 'swa' CLI not found on PATH.\n")
        _append_log("[SWA] Install with: npm install -g @azure/static-web-apps-cli\n")
        with _build_lock:
            _build_status = "error"
        return

    with _build_lock:
        _build_status = "running"

    try:
        swa_config = BASE_DIR / "swa-cli.config.json"
        cmd = [swa_cmd, "deploy", str(BASE_DIR),
               "--deployment-token", token,
               "--env", "production"]
        if swa_config.exists():
            cmd += ["--config-name", "dashboard"]
        _append_log(f"[SWA] Running: swa deploy . --env production\n\n")
        env = {**__import__('os').environ, "SWA_CLI_DEPLOYMENT_TOKEN": token}

        # Temporarily rename workflow file — SWA CLI reads it and warns about unsupported properties
        wf_dir  = BASE_DIR / ".github" / "workflows"
        wf_file = next(wf_dir.glob("azure-static-web-apps*.yml"), None) if wf_dir.exists() else None
        wf_bak  = wf_file.with_suffix(".yml.bak") if wf_file else None
        try:
            if wf_file and wf_file.exists():
                wf_file.rename(wf_bak)
        except Exception:
            wf_bak = None
        proc = subprocess.Popen(
            cmd, cwd=str(BASE_DIR),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, env=env,
            shell=(sys.platform == "win32"),
            **( {"creationflags": 0x08000000} if sys.platform == "win32" else {} )
        )
        for line in proc.stdout:
            _append_log(line)
        proc.wait()
        # Restore workflow file
        try:
            if wf_bak and wf_bak.exists():
                wf_bak.rename(wf_file)
        except Exception:
            pass
        with _build_lock:
            _build_status = "done" if proc.returncode == 0 else "error"
        if proc.returncode == 0:
            _append_log("\n[SWA] Deploy complete — site is live.\n")
        else:
            _append_log(f"\n[SWA] Deploy failed (exit {proc.returncode}).\n")
    except Exception as e:
        _append_log(f"\n[SWA] Exception: {e}\n")
        with _build_lock:
            _build_status = "error"


# ── HTTP handler ─────────────────────────────────────────────────
class AdminHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass  # silence default request log

    def send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, mime="text/html"):
        try:
            data = Path(path).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", len(data))
            self.end_headers()
            self.wfile.write(data)
        except FileNotFoundError:
            self.send_error(404)
            try:
                r_status = subprocess.run(
                    [(_find_git() or "git"), "status", "--porcelain"],
                    cwd=str(BASE_DIR), capture_output=True, text=True, timeout=5,
                    **( {"creationflags": 0x08000000} if sys.platform == "win32" else {} )
                )
                r_remote = subprocess.run(
                    [(_find_git() or "git"), "remote", "get-url", "origin"],
                    cwd=str(BASE_DIR), capture_output=True, text=True, timeout=5,
                    **( {"creationflags": 0x08000000} if sys.platform == "win32" else {} )
                )
                cfg = load_config()
                self.send_json({
                    "git_available": r_status.returncode == 0,
                    "remote":        r_remote.stdout.strip() if r_remote.returncode == 0 else None,
                    "has_changes":   bool(r_status.stdout.strip()),
                    "auto_push":     cfg.get("git", {}).get("auto_push", False),
                })
            except Exception as e:
                self.send_json({"git_available": False, "error": str(e)})
            return

        self.send_error(404)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/") or "/"

        # ── serve admin UI ────────────────────────────────────────
        if path in ("/", "/admin"):
            admin_html = BASE_DIR / "admin.html"
            if not admin_html.exists():
                self.send_error(404, "admin.html not found — place it in the same folder as admin_server.py")
                return
            # Inject the actual server port so API calls and links always work
            html = admin_html.read_text(encoding="utf-8")
            html = html.replace("SERVER_PORT_PLACEHOLDER", str(_server_port))
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)
            return

        # ── serve built dashboard ─────────────────────────────────
        if path == "/dashboard":
            output_html = get_output_html()
            if output_html.exists():
                self.send_file(output_html)
            else:
                msg = f"<h2>Dashboard not found</h2><p>Expected: {output_html}</p><p>Run a build first.</p>"
                body = msg.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", len(body))
                self.end_headers()
                self.wfile.write(body)
            return

        # ── API: read config ──────────────────────────────────────
        if path == "/api/config":
            self.send_json(load_config())
            return

        # ── API: list source files (glob) ─────────────────────────
        if path == "/api/sources":
            cfg = load_config()
            patterns = cfg.get("bcf_sources", [])
            files = []
            for pattern in patterns:
                full = str(BASE_DIR / pattern) if not os.path.isabs(pattern) else pattern
                for f in sorted(glob.glob(full)):
                    size = os.path.getsize(f)
                    files.append({
                        "path":    f,
                        "name":    os.path.basename(f),
                        "size_kb": round(size / 1024, 1),
                        "ext":     os.path.splitext(f)[1].lower(),
                    })
            self.send_json({"patterns": patterns, "files": files})
            return

        # ── API: build status + log ───────────────────────────────
        if path == "/api/build/status":
            with _build_lock:
                self.send_json({"status": _build_status, "log": "".join(_build_log)})
            return

        # ── API: dashboard file info ──────────────────────────────
        if path == "/api/dashboard/info":
            output_html = get_output_html()
            info = {"exists": output_html.exists(), "path": str(output_html), "port": _server_port}
            if info["exists"]:
                stat = output_html.stat()
                info["size_kb"]   = round(stat.st_size / 1024, 1)
                info["modified"]  = time.strftime(
                    "%Y-%m-%d %H:%M", time.localtime(stat.st_mtime))
            self.send_json(info)
            return

        # ── API: git status ───────────────────────────────────────
        if path == "/api/git/status":
            try:
                r_st = subprocess.run(
                    [(_find_git() or "git"), "status", "--porcelain"],
                    cwd=str(BASE_DIR), capture_output=True, text=True, timeout=5,
                    **( {"creationflags": 0x08000000} if sys.platform == "win32" else {} )
                )
                r_rm = subprocess.run(
                    [(_find_git() or "git"), "remote", "get-url", "origin"],
                    cwd=str(BASE_DIR), capture_output=True, text=True, timeout=5,
                    **( {"creationflags": 0x08000000} if sys.platform == "win32" else {} )
                )
                cfg = load_config()
                self.send_json({
                    "git_available": r_st.returncode == 0,
                    "remote":        r_rm.stdout.strip() if r_rm.returncode == 0 else None,
                    "has_changes":   bool(r_st.stdout.strip()),
                    "auto_push":     cfg.get("git", {}).get("auto_push", False),
                })
            except Exception as e:
                self.send_json({"git_available": False, "error": str(e)})
            return

        self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path

        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(body)
        except Exception:
            self.send_json({"error": "Invalid JSON"}, 400)
            return

        # ── API: save config ──────────────────────────────────────
        if path == "/api/config":
            try:
                save_config(data)
                self.send_json({"ok": True})
            except Exception as e:
                self.send_json({"error": str(e)}, 500)
            return

        # ── API: trigger build ────────────────────────────────────
        if path == "/api/build/start":
            with _build_lock:
                if _build_status == "running":
                    self.send_json({"ok": False, "error": "Build already running"})
                    return
            auto = data.get("auto_push", None)
            if auto is None:
                cfg = load_config()
                auto = cfg.get("git", {}).get("auto_push", False)
            target = run_build_and_push if auto else run_build
            t = threading.Thread(target=target, daemon=True)
            t.start()
            self.send_json({"ok": True, "auto_push": auto})
            return

        # ── API: data-only build ───────────────────────────────────────────────────
        if path == "/api/data/build":
            with _build_lock:
                if _build_status == "running":
                    self.send_json({"ok": False, "error": "Build already running"}); return
            cfg  = load_config()
            auto = cfg.get("git", {}).get("auto_push", False)
            threading.Thread(
                target=run_data_build_and_push if auto else run_data_build,
                daemon=True).start()
            self.send_json({"ok": True})
            return

        # ── API: push data file only ────────────────────────────────────────────────
        if path == "/api/data/push":
            with _build_lock:
                if _build_status == "running":
                    self.send_json({"ok": False, "error": "Build running"}); return
            threading.Thread(target=run_git_push_data,
                args=(data.get("commit_msg"),), daemon=True).start()
            self.send_json({"ok": True})
            return

        # ── API: data file info ─────────────────────────────────────────────────────
        if path == "/api/data/info":
            cfg = load_config()
            dp  = BASE_DIR / cfg.get("data_output", "data.js")
            info = {"exists": dp.exists(), "path": str(dp)}
            if dp.exists():
                st = dp.stat()
                info["size_kb"]  = round(st.st_size / 1024, 1)
                info["modified"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))
                try:
                    import json as _j; pkg = _j.loads(dp.read_text(encoding="utf-8"))
                    info.update({"ts": pkg.get("ts",""), "info": pkg.get("info",""), "n": pkg.get("n",0)})
                except Exception: pass
            self.send_json(info)
            return

        # ── API: manual git push ──────────────────────────────────
        if path == "/api/git/push":
            with _build_lock:
                if _build_status == "running":
                    self.send_json({"ok": False, "error": "Build is running — wait for it to finish"})
                    return
            _set_status("running")
            _build_log.clear()
            msg = data.get("commit_msg", None)
            def _git_push_wrapped(m):
                try:
                    run_git_push(m)
                finally:
                    _set_status("done")
            t = threading.Thread(target=_git_push_wrapped, args=(msg,), daemon=True)
            t.start()
            self.send_json({"ok": True})
            return

        if path == "/api/git/push-all":
            with _build_lock:
                if _build_status == "running":
                    self.send_json({"ok": False, "error": "Build is running — wait for it to finish"})
                    return
            msg = data.get("commit_msg", None)
            t = threading.Thread(target=run_git_push_all, args=(msg,), daemon=True)
            t.start()
            self.send_json({"ok": True})
            return

        # ── API: direct SWA deploy ────────────────────────────────
        if path == "/api/swa/deploy":
            with _build_lock:
                if _build_status == "running":
                    self.send_json({"ok": False, "error": "Build already running"})
                    return
            threading.Thread(target=run_swa_deploy, daemon=True).start()
            self.send_json({"ok": True})
            return

        # ── API: shutdown server ──────────────────────────────────
        if path == "/api/shutdown":
            self.send_json({"ok": True, "message": "Server shutting down..."})
            threading.Thread(
                target=lambda: (__import__("time").sleep(0.3), __import__("os")._exit(0)),
                daemon=True
            ).start()
            return

        self.send_error(404)


# ── main ─────────────────────────────────────────────────────────
_server_port = 5050  # set in main(), used by handlers

def main():
    global _server_port
    parser = argparse.ArgumentParser(description="BCF Dashboard Admin Server")
    parser.add_argument("--port", type=int, default=5050)
    args = parser.parse_args()
    _server_port = args.port

    url = f"http://localhost:{args.port}"
    print(f"\n  BCF Dashboard Admin Server")
    print(f"  ---------------------------------")
    print(f"  Admin UI:   {url}/")
    print(f"  Dashboard:  {url}/dashboard")
    print(f"  Config API: {url}/api/config")
    print(f"\n  Press Ctrl+C to stop.\n")

    server = HTTPServer(("127.0.0.1", args.port), AdminHandler)

    # Open browser after a short delay
    def open_browser():
        time.sleep(0.8)
        webbrowser.open(url)
    threading.Thread(target=open_browser, daemon=True).start()

    import signal
    def _shutdown(sig=None, frame=None):
        print("\n  Stopping server...")
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _shutdown()
    print("  Server stopped.")


if __name__ == "__main__":
    main()
