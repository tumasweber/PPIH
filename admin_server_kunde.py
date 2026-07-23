"""
BCF Dashboard — Admin Server
============================
A lightweight local HTTP server that:
  - Serves admin_kunde.html at http://localhost:5050/
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
# BUILD_SCRIPT (build_dashboard.py) is not available in the customer package.
# Dashboard HTML is pre-built and signed by RHYBA Engineering.

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


# ── YAML helpers ─────────────────────────────────────────────────
def load_config():
    if not CONFIG_PATH.exists():
        return {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_config(data):
    # Preserve the original file's comments as best we can by doing a
    # targeted merge rather than a full rewrite.
    # For simplicity we do a full rewrite — comments are not preserved,
    # but the YAML is valid and round-trips correctly.
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False,
                  sort_keys=False, width=120)


# ── build runner (DISABLED in customer package) ───────────────────
# Dashboard HTML (index.html) is pre-built and licence-signed by RHYBA Engineering.
# Customers only build data.js via build_data.py.
def run_build(port=5050):
    with _build_lock:
        _build_log.clear()
        _build_status = "error"
    _append_log("[INFO] Dashboard rebuild is not available in the customer package.\n")
    _append_log("[INFO] index.html is pre-built and licence-signed by RHYBA Engineering.\n")
    _append_log("[INFO] Use 'Build Data' to refresh project data (data.js) instead.\n")
    with _build_lock:
        _build_status = "error"

def run_build_and_push(port=5050):
    run_build(port)


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
            _append_log("[GIT] git not found\n"); return False
    ok = _r(["git", "add", str(dp)], f"git add {dp.name}")
    if subprocess.run(["git", "diff", "--staged", "--quiet"], cwd=str(BASE_DIR)).returncode == 0:
        _append_log("[GIT] Nothing new.\n"); return True
    ok = ok and _r(["git", "commit", "-m", commit_msg], "git commit")
    ok = ok and _r(["git", "push", "origin", "main"], "git push")
    if ok: _append_log("[GIT] Push complete.\n")
    return ok


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
                    ["git", "status", "--porcelain"],
                    cwd=str(BASE_DIR), capture_output=True, text=True, timeout=5,
                    **( {"creationflags": 0x08000000} if sys.platform == "win32" else {} )
                )
                r_remote = subprocess.run(
                    ["git", "remote", "get-url", "origin"],
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
            admin_html = BASE_DIR / "admin_kunde.html"
            if not admin_html.exists():
                self.send_error(404, "admin_kunde.html not found — place it in the same folder as admin_server_kunde.py")
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
                    ["git", "status", "--porcelain"],
                    cwd=str(BASE_DIR), capture_output=True, text=True, timeout=5,
                    **( {"creationflags": 0x08000000} if sys.platform == "win32" else {} )
                )
                r_rm = subprocess.run(
                    ["git", "remote", "get-url", "origin"],
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
            self.send_json({"ok": False,
                "error": "Dashboard rebuild not available. index.html is pre-built by RHYBA Engineering."}, 403)
            return
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
            msg = data.get("commit_msg", None)
            t = threading.Thread(target=run_git_push, args=(msg,), daemon=True)
            t.start()
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

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Server stopped.")


if __name__ == "__main__":
    main()
