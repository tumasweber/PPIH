#!/usr/bin/env python3
"""
license_manager.py  —  BCF Dashboard License Manager
RHYBA Engineering  |  EngTools Suite

Requires: pip install cryptography --break-system-packages
"""
import sys, os, json, base64
from pathlib import Path
from datetime import date, datetime, timedelta
import tkinter as tk
from tkinter import filedialog, messagebox

# ── Palette ──────────────────────────────────────────────────────────────────
BG0    = "#141416"
BG1    = "#1C1C1E"
BG2    = "#28282C"
BG3    = "#323236"
ACCENT = "#E8854A"
GREEN  = "#1D9E75"
BLUE   = "#5A8FD4"
RED    = "#E05C5C"
YELLOW = "#E09A2a"
FG     = "#F0F0F0"
FG2    = "#AAAAAA"
FG3    = "#606064"
BORDER = "#3A3A3E"

FF     = "Segoe UI"
MONO   = "Consolas"

ALL_TABS = [
    ("overview", "Dashboard (Overview)",     True),
    ("issues",   "Issue Management",         True),
    ("gantt",    "Schedule & Gantt",         False),
    ("engdocs",  "Engineering Documents",    False),
    ("costs",    "Costs",                    False),
    ("docs",     "Document Management",      False),
    ("scope",    "Scope",                    False),
]

TIERS = {
    "starter":      ("Starter",      BLUE,   ["overview","issues"]),
    "professional": ("Professional", ACCENT, ["overview","issues","gantt","costs","docs"]),
    "enterprise":   ("Enterprise",   GREEN,  ["overview","issues","gantt","engdocs","costs","docs","scope"]),
    "custom":       ("Custom",       FG2,    []),
}

KEY_FILE      = Path("license_private.pem")
LICENSES_FILE = Path("licenses.json")


# ── Crypto helpers ────────────────────────────────────────────────────────────
def b64u(b):  return base64.urlsafe_b64encode(b).rstrip(b"=").decode()
def b64ud(s):
    s=s.replace("-","+").replace("_","/"); s+="="*(4-len(s)%4)
    return base64.b64decode(s)

def load_licenses():
    if LICENSES_FILE.exists():
        try: return json.loads(LICENSES_FILE.read_text(encoding="utf-8"))
        except: pass
    return []

def save_licenses(lst):
    LICENSES_FILE.write_text(json.dumps(lst, indent=2, ensure_ascii=False), encoding="utf-8")

def generate_keys():
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    key = ec.generate_private_key(ec.SECP256R1())
    KEY_FILE.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    pub = key.public_key()
    Path("license_public.pem").write_bytes(pub.public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    n = pub.public_numbers()
    jwk = {"kty":"EC","crv":"P-256","x":b64u(n.x.to_bytes(32,"big")),"y":b64u(n.y.to_bytes(32,"big"))}
    Path("license_public.jwk").write_text(json.dumps(jwk, indent=2))
    return jwk

def sign_license(customer, tier, features, expires):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    priv = serialization.load_pem_private_key(KEY_FILE.read_bytes(), password=None)
    payload = json.dumps({"customer":customer,"tier":tier,
                          "features":sorted(features),"expires":expires},
                         separators=(",",":")).encode()
    sig_der = priv.sign(payload, ec.ECDSA(hashes.SHA256()))
    r,s = decode_dss_signature(sig_der)
    return {"payload":b64u(payload),"sig":b64u(r.to_bytes(32,"big")+s.to_bytes(32,"big"))}

def days_left(exp_str):
    try: return (datetime.strptime(exp_str,"%Y-%m-%d").date()-date.today()).days
    except: return None


# ── Widget helpers ────────────────────────────────────────────────────────────
def lbl(p, text, fg=FG, bg=BG1, font=(FF,10), **kw):
    return tk.Label(p, text=text, fg=fg, bg=bg, font=font, **kw)

def ent(p, var, width=28, **kw):
    return tk.Entry(p, textvariable=var, width=width, bg=BG3, fg=FG,
                    insertbackground=FG, relief="flat", font=(FF,10),
                    highlightthickness=1, highlightbackground=BORDER,
                    highlightcolor=ACCENT, bd=0, **kw)

def btn(p, text, cmd, bg=ACCENT, fg="#fff", **kw):
    b = tk.Button(p, text=text, command=cmd, bg=bg, fg=fg,
                  font=(FF,10,"bold"), relief="flat", bd=0,
                  cursor="hand2", activebackground=bg,
                  activeforeground=fg, padx=12, pady=5, **kw)
    b.bind("<Enter>", lambda e,b=b,c=bg: b.config(bg=_lt(c)))
    b.bind("<Leave>", lambda e,b=b,c=bg: b.config(bg=c))
    return b

def _lt(h):
    r,g,b=int(h[1:3],16),int(h[3:5],16),int(h[5:7],16)
    return f"#{min(255,r+28):02x}{min(255,g+28):02x}{min(255,b+28):02x}"

def sep(p, bg=BORDER, h=1):
    return tk.Frame(p, bg=bg, height=h)

def card(p, **kw):
    return tk.Frame(p, bg=BG2, highlightthickness=1,
                    highlightbackground=BORDER, **kw)


# ── App ───────────────────────────────────────────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("BCF Dashboard — License Manager  |  RHYBA Engineering")
        self.geometry("1100x760")
        self.minsize(960, 640)
        self.configure(bg=BG0)
        self.resizable(True, True)

        self._licenses = load_licenses()
        self._sel_idx  = None
        self._feat_vars = {t[0]: tk.BooleanVar(value=t[2]) for t in ALL_TABS}
        self._tier_var  = tk.StringVar(value="professional")
        self._cust_var  = tk.StringVar()
        self._exp_var   = tk.StringVar(value=(date.today()+timedelta(days=365)).isoformat())
        self._note_var  = tk.StringVar()
        self._search_var= tk.StringVar()
        self._filtered  = []

        self._build()
        self._search_var.trace_add('write', lambda *_: self._refresh_list())
        self._refresh_list()
        self._update_key_status()
        self._on_tier_change()   # set checkboxes to professional default

    # ── Layout ───────────────────────────────────────────────────────────────
    def _build(self):
        # Topbar
        top = tk.Frame(self, bg=BG0, height=50)
        top.pack(fill="x"); top.pack_propagate(False)
        lbl(top," 🔑  BCF Dashboard License Manager",bg=BG0,
            font=(FF,12,"bold")).pack(side="left", pady=12)
        self._key_lbl = lbl(top,"",bg=BG0,fg=FG2,font=(FF,9))
        self._key_lbl.pack(side="right", padx=14)
        sep(self).pack(fill="x")

        # Body
        body = tk.Frame(self, bg=BG0)
        body.pack(fill="both", expand=True)

        # ── Left sidebar ─────────────────────────────────────────────
        sb = tk.Frame(body, bg=BG0, width=260)
        sb.pack(side="left", fill="y"); sb.pack_propagate(False)

        tk.Frame(sb,bg=BG0,height=8).pack()
        lbl(sb,"  LICENSES",bg=BG0,fg=FG3,font=(FF,8,"bold")).pack(anchor="w",padx=6)
        tk.Frame(sb,bg=BG0,height=4).pack()

        # Search box
        sf = tk.Frame(sb,bg=BG0); sf.pack(fill="x",padx=6,pady=3)
        # trace added after _build() to avoid firing before _lb exists
        se = ent(sf, self._search_var, width=30)
        se.pack(fill="x")
        se.insert(0,"Search…")
        se.bind("<FocusIn>",  lambda e: se.delete(0,"end") if se.get()=="Search…" else None)
        se.bind("<FocusOut>", lambda e: se.insert(0,"Search…") if not se.get() else None)

        # Listbox
        lf = tk.Frame(sb,bg=BG0); lf.pack(fill="both",expand=True,padx=6,pady=3)
        sc = tk.Scrollbar(lf,orient="vertical",bg=BG0,troughcolor=BG2)
        self._lb = tk.Listbox(lf, bg=BG2, fg=FG, font=(FF,9),
                               relief="flat", bd=0, activestyle="none",
                               selectbackground=BG3, selectforeground=ACCENT,
                               highlightthickness=0,
                               yscrollcommand=sc.set)
        sc.config(command=self._lb.yview)
        sc.pack(side="right",fill="y"); self._lb.pack(fill="both",expand=True)
        self._lb.bind("<<ListboxSelect>>", self._on_select)

        # Sidebar buttons
        sbf = tk.Frame(sb,bg=BG0); sbf.pack(fill="x",padx=6,pady=6)
        btn(sbf,"+ New", self._new_license).pack(side="left")
        btn(sbf,"🗑 Delete", self._delete_license, bg=BG3, fg=RED).pack(side="right")

        # Divider
        tk.Frame(body,bg=BORDER,width=1).pack(side="left",fill="y")

        # ── Main panel ───────────────────────────────────────────────
        main = tk.Frame(body,bg=BG1); main.pack(side="left",fill="both",expand=True)

        # Key bar
        kb = tk.Frame(main,bg=BG2); kb.pack(fill="x")
        lbl(kb,"  Signing Key",bg=BG2,fg=FG2,font=(FF,9)).pack(side="left",padx=4,pady=7)
        self._key_path = lbl(kb,str(KEY_FILE.absolute()),bg=BG2,fg=FG3,font=(MONO,8))
        self._key_path.pack(side="left",padx=4)
        btn(kb,"Generate New Keypair",self._gen_keys,bg=BG3,fg=BLUE).pack(side="right",padx=8,pady=4)
        btn(kb,"Load Key…",self._load_key,bg=BG3,fg=FG2).pack(side="right",padx=0,pady=4)
        sep(main).pack(fill="x")

        # Scrollable form area
        canvas = tk.Canvas(main,bg=BG1,bd=0,highlightthickness=0)
        vsb = tk.Scrollbar(main,orient="vertical",command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right",fill="y")
        canvas.pack(side="left",fill="both",expand=True)

        form = tk.Frame(canvas,bg=BG1)
        form_win = canvas.create_window((0,0),window=form,anchor="nw")
        form.bind("<Configure>", lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(
            form_win, width=e.width))
        form.bind("<MouseWheel>", lambda e: canvas.yview_scroll(-1*(e.delta//120),"units"))

        self._build_form(form)

    def _build_form(self, p):
        pad = dict(padx=20)

        tk.Frame(p,bg=BG1,height=14).pack()
        self._title_lbl = lbl(p,"New License",bg=BG1,font=(FF,14,"bold"))
        self._title_lbl.pack(anchor="w",**pad)
        tk.Frame(p,bg=BG1,height=10).pack()

        # ── Row 1: Customer + Tier ────────────────────────────────────
        r1 = tk.Frame(p,bg=BG1); r1.pack(fill="x",**pad,pady=6)

        # Customer card
        cc = card(r1); cc.pack(side="left",fill="both",expand=True,padx=(0,8))
        lbl(cc,"Customer / Company",bg=BG2,fg=FG2,font=(FF,9)).pack(anchor="w",padx=10,pady=(8,2))
        ent(cc,self._cust_var,width=40).pack(fill="x",padx=10,pady=(0,10))

        # Tier card — fixed width, all 4 tiers
        tc = card(r1); tc.pack(side="left",fill="y")
        lbl(tc,"Tier",bg=BG2,fg=FG2,font=(FF,9)).pack(anchor="w",padx=10,pady=(8,4))
        for tid,(tlabel,tcolor,_) in TIERS.items():
            tk.Radiobutton(tc, text=tlabel, variable=self._tier_var, value=tid,
                           bg=BG2, fg=tcolor, selectcolor=BG3,
                           activebackground=BG2, activeforeground=tcolor,
                           font=(FF,10,"bold"), command=self._on_tier_change
                           ).pack(anchor="w",padx=14,pady=2)
        tk.Frame(tc,bg=BG2,height=8).pack()

        # ── Row 2: Features ───────────────────────────────────────────
        fc = card(p); fc.pack(fill="x",**pad,pady=4)
        lbl(fc,"Features / Tabs",bg=BG2,fg=FG2,font=(FF,9)).pack(anchor="w",padx=10,pady=(8,4))
        fg_ = tk.Frame(fc,bg=BG2); fg_.pack(fill="x",padx=10,pady=(0,10))

        # 2 columns: left and right
        col0 = tk.Frame(fg_,bg=BG2); col0.pack(side="left",fill="x",expand=True)
        col1 = tk.Frame(fg_,bg=BG2); col1.pack(side="left",fill="x",expand=True)

        for i,(tid,tlabel,core) in enumerate(ALL_TABS):
            col = col0 if i%2==0 else col1
            row = tk.Frame(col,bg=BG2); row.pack(fill="x",pady=2)
            cb = tk.Checkbutton(row, text=tlabel, variable=self._feat_vars[tid],
                                bg=BG2, fg=FG, selectcolor=BG3,
                                activebackground=BG2, activeforeground=FG,
                                font=(FF,10), command=self._on_feat_change,
                                state="disabled" if core else "normal",
                                disabledforeground=FG2)
            cb.pack(side="left",anchor="w")
            if core:
                lbl(row,"  (core)",bg=BG2,fg=FG3,font=(FF,8)).pack(side="left")

        # ── Row 3: Expiry + Notes ─────────────────────────────────────
        r3 = tk.Frame(p,bg=BG1); r3.pack(fill="x",**pad,pady=6)

        ec_ = card(r3); ec_.pack(side="left",fill="both",expand=True,padx=(0,8))
        lbl(ec_,"Expiry Date  (YYYY-MM-DD)",bg=BG2,fg=FG2,font=(FF,9)).pack(anchor="w",padx=10,pady=(8,2))
        er = tk.Frame(ec_,bg=BG2); er.pack(fill="x",padx=10,pady=(0,10))
        ent(er,self._exp_var,width=16).pack(side="left")
        for txt,d in [("+ 6m",183),("+ 1y",365),("+ 2y",730)]:
            btn(er,txt,lambda d=d:self._set_exp(d),bg=BG3,fg=FG2).pack(side="left",padx=3)

        nc = card(r3); nc.pack(side="left",fill="both",expand=True)
        lbl(nc,"Notes",bg=BG2,fg=FG2,font=(FF,9)).pack(anchor="w",padx=10,pady=(8,2))
        ent(nc,self._note_var,width=30).pack(fill="x",padx=10,pady=(0,10))

        sep(p,bg=BORDER).pack(fill="x",**pad,pady=10)

        # ── Action buttons ────────────────────────────────────────────
        ab = tk.Frame(p,bg=BG1); ab.pack(fill="x",**pad)
        btn(ab,"Sign & Save License",self._save).pack(side="left")
        btn(ab,"Export YAML snippet",self._export,bg=BG3,fg=BLUE).pack(side="left",padx=8)
        btn(ab,"Copy JSON",self._copy_json,bg=BG3,fg=FG2).pack(side="left")
        self._status = lbl(ab,"",bg=BG1,fg=GREEN,font=(FF,9))
        self._status.pack(side="right",padx=6)

        # ── Output ────────────────────────────────────────────────────
        tk.Frame(p,bg=BG1,height=6).pack()
        lbl(p,"config.yaml  snippet",bg=BG1,fg=FG3,font=(FF,9)).pack(anchor="w",**pad)
        of = tk.Frame(p,bg=BG1); of.pack(fill="both",expand=True,**pad,pady=(2,16))
        self._out = tk.Text(of, bg=BG2, fg=GREEN, font=(MONO,9),
                            relief="flat", bd=0, height=10,
                            wrap="none", state="disabled",
                            highlightthickness=1, highlightbackground=BORDER,
                            insertbackground=FG)
        sb2 = tk.Scrollbar(of,orient="vertical",command=self._out.yview)
        self._out.configure(yscrollcommand=sb2.set)
        sb2.pack(side="right",fill="y")
        self._out.pack(fill="both",expand=True)

    # ── Key management ────────────────────────────────────────────────────────
    def _update_key_status(self):
        if KEY_FILE.exists():
            mt = datetime.fromtimestamp(KEY_FILE.stat().st_mtime).strftime("%Y-%m-%d")
            self._key_lbl.config(text=f"✓  Key found  (created {mt})", fg=GREEN)
        else:
            self._key_lbl.config(text="⚠  No signing key — generate one first", fg=YELLOW)

    def _gen_keys(self):
        if KEY_FILE.exists() and not messagebox.askyesno("Overwrite keypair",
            "Generating a NEW keypair will INVALIDATE all previously signed licenses.\n\nContinue?"):
            return
        try:
            jwk = generate_keys()
            self._update_key_status()
            self._key_path.config(text=str(KEY_FILE.absolute()))
            self._msg(f"✓  Keypair generated", GREEN)
            messagebox.showinfo("Done",
                "Created:\n  license_private.pem  ← KEEP SECRET\n"
                "  license_public.pem\n  license_public.jwk\n\n"
                f"JWK:\n{json.dumps(jwk,indent=2)}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _load_key(self):
        global KEY_FILE
        p = filedialog.askopenfilename(title="Select private key",
            filetypes=[("PEM","*.pem"),("All","*.*")])
        if p:
            KEY_FILE = Path(p)
            self._key_path.config(text=str(KEY_FILE))
            self._update_key_status()

    # ── Listbox ───────────────────────────────────────────────────────────────
    def _refresh_list(self):
        q = self._search_var.get().lower()
        if q in ("search…","search...",""):  q=""
        self._filtered = [(i,lic) for i,lic in enumerate(self._licenses)
                          if q in lic.get("customer","").lower()
                          or q in lic.get("tier","").lower()]
        self._lb.delete(0,"end")
        for _,(orig_i,lic) in enumerate(self._filtered):
            d = days_left(lic.get("expires",""))
            dot = "🔴" if d is not None and d<0 else "🟡" if d is not None and d<30 else "🟢"
            self._lb.insert("end", f" {dot}  {lic.get('customer','—')}  [{lic.get('tier','?')[:3].upper()}]")

    def _on_select(self, _=None):
        sel = self._lb.curselection()
        if not sel: return
        orig_i, lic = self._filtered[sel[0]]
        self._sel_idx = orig_i
        self._cust_var.set(lic.get("customer",""))
        self._tier_var.set(lic.get("tier","professional"))
        self._exp_var.set(lic.get("expires",""))
        self._note_var.set(lic.get("notes",""))
        for tid,var in self._feat_vars.items():
            core = any(t[0]==tid and t[2] for t in ALL_TABS)
            var.set(tid in lic.get("features",[]) or core)
        self._title_lbl.config(text=f"Edit — {lic.get('customer','')}")
        self._show(lic)

    def _new_license(self):
        self._sel_idx = None
        self._lb.selection_clear(0,"end")
        self._title_lbl.config(text="New License")
        self._cust_var.set(""); self._note_var.set("")
        self._exp_var.set((date.today()+timedelta(days=365)).isoformat())
        self._tier_var.set("professional")
        self._on_tier_change()
        self._out.config(state="normal"); self._out.delete("1.0","end")
        self._out.config(state="disabled"); self._msg("")

    def _delete_license(self):
        if self._sel_idx is None:
            messagebox.showwarning("","Select a license first."); return
        c = self._licenses[self._sel_idx].get("customer","?")
        if messagebox.askyesno("Delete", f"Delete license for\n{c}?"):
            self._licenses.pop(self._sel_idx)
            save_licenses(self._licenses)
            self._sel_idx = None
            self._refresh_list()
            self._new_license()

    # ── Form logic ────────────────────────────────────────────────────────────
    def _on_tier_change(self):
        tier = self._tier_var.get()
        if tier == "custom": return
        feats = set(TIERS[tier][2])
        for tid,var in self._feat_vars.items():
            core = any(t[0]==tid and t[2] for t in ALL_TABS)
            var.set(tid in feats or core)

    def _on_feat_change(self):
        sel = {tid for tid,var in self._feat_vars.items() if var.get()}
        for tid,(_,_,feats) in TIERS.items():
            if tid=="custom": continue
            if set(feats)==sel: self._tier_var.set(tid); return
        self._tier_var.set("custom")

    def _set_exp(self, days):
        self._exp_var.set((date.today()+timedelta(days=days)).isoformat())

    def _collect(self):
        return (self._cust_var.get().strip(),
                self._tier_var.get(),
                sorted([t for t,v in self._feat_vars.items() if v.get()]),
                self._exp_var.get().strip(),
                self._note_var.get().strip())

    def _validate(self, cust, exp):
        if not cust:
            messagebox.showwarning("","Enter a customer name."); return False
        try: datetime.strptime(exp,"%Y-%m-%d")
        except: messagebox.showwarning("","Expiry must be YYYY-MM-DD."); return False
        if not KEY_FILE.exists():
            messagebox.showwarning("","Generate or load a signing key first."); return False
        return True

    def _save(self):
        cust,tier,feats,exp,notes = self._collect()
        if not self._validate(cust,exp): return
        try: token = sign_license(cust,tier,feats,exp)
        except Exception as e: messagebox.showerror("Signing error",str(e)); return
        lic = {"customer":cust,"tier":tier,"features":feats,"expires":exp,
               "notes":notes,"token":token,"issued":date.today().isoformat()}
        if self._sel_idx is not None:
            self._licenses[self._sel_idx] = lic
        else:
            self._licenses.append(lic)
            self._sel_idx = len(self._licenses)-1
        save_licenses(self._licenses)
        self._refresh_list()
        self._title_lbl.config(text=f"Edit — {cust}")
        self._show(lic)
        self._msg(f"✓  Saved  ({tier}, expires {exp})", GREEN)

    def _snippet(self, lic):
        lines = ["license:"]
        lines.append(f"  customer: \"{lic['customer']}\"")
        lines.append(f"  tier:     {lic['tier']}")
        lines.append(f"  features:")
        for f in lic.get("features",[]): lines.append(f"    - {f}")
        lines.append(f"  expires:  \"{lic.get('expires','')}\"")
        if lic.get("notes"): lines.append(f"  notes:    \"{lic['notes']}\"")
        tok = lic.get("token",{})
        if tok:
            lines.append(f"  token:")
            lines.append(f"    payload: \"{tok.get('payload','')}\"")
            lines.append(f"    sig:     \"{tok.get('sig','')}\"")
        return "\n".join(lines)

    def _show(self, lic):
        s = self._snippet(lic)
        self._out.config(state="normal")
        self._out.delete("1.0","end")
        self._out.insert("1.0",s)
        self._out.config(state="disabled")

    def _export(self):
        if self._sel_idx is None: messagebox.showinfo("","Save first."); return
        lic = self._licenses[self._sel_idx]
        p = filedialog.asksaveasfilename(title="Save snippet",
            defaultextension=".yaml",
            initialfile=f"license_{lic['customer'].replace(' ','_').lower()}.yaml",
            filetypes=[("YAML","*.yaml"),("All","*.*")])
        if p:
            Path(p).write_text(self._snippet(lic),encoding="utf-8")
            self._msg(f"Exported {Path(p).name}", BLUE)

    def _copy_json(self):
        if self._sel_idx is None: messagebox.showinfo("","Save first."); return
        self.clipboard_clear()
        self.clipboard_append(json.dumps({"license":self._licenses[self._sel_idx]},
                                         indent=2,ensure_ascii=False))
        self._msg("Copied JSON", BLUE)

    def _msg(self, text, color=GREEN):
        self._status.config(text=text, fg=color)
        if text: self.after(4000, lambda: self._status.config(text=""))


if __name__ == "__main__":
    App().mainloop()
