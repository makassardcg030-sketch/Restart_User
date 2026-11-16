import json
import os
import re
import socket
import sys
import threading
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

# ============================================================
# KONFIGURASI
# ============================================================

DB_DEFAULTS = {
    "host": "",
    "port": 3306,
    "user": "",
    "password": "",
    "database": "",
}

TIPE_OPTIONS = {
    "DPD": "STANDARD",
    "DCP": "P_MAP",
    "REOPEN DPD": "REOPEN",
}
TIPE_LABELS = {v: k for k, v in TIPE_OPTIONS.items()}

DB_TIMEOUT = 5
CLIENT_PORT = 5005
SOCKET_TIMEOUT = 2
CONFIRM_BEFORE_SEND = False

# Tema Warna (Dark Slate)
BG = "#0E1621"
PANEL = "#172335"
CARD_BG = "#1F3047"
WHITE = "#F0F5FC"
MUTED = "#9EB3C9"
BLUE = "#217AC7"
GREEN = "#1F9966"
ORANGE = "#D96E1F"
RED = "#CC3838"

SECTIONS = [
    ("RESTART", "STANDARD", lambda z: "RUN_MACRO", lambda z: "Zona " + z, BLUE),
    ("DCP", "P_MAP", lambda z: "RESTART_DCP_" + z, lambda z: "DCP " + z, GREEN),
    ("REOPEN DPD", "REOPEN", lambda z: "RESTART_PROGRAM", lambda z: "Zona " + z, ORANGE),
]


def get_app_dir():
    """Mendapatkan direktori tempat script atau .exe berada (Portabel)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_resource_path(relative_path):
    """Mendapatkan path asset (seperti app.ico) baik saat mode script maupun PyInstaller."""
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(get_app_dir(), relative_path)


# ============================================================
# FUNGSI DATABASE & FORMAT DATA
# ============================================================

def zona_sort_key(z):
    return (0, int(z)) if str(z).isdigit() else (1, str(z))


def group_and_sort_rows(rows):
    data = {}
    for zona, tipe, ip in rows:
        if ip and zona and tipe:
            data.setdefault(tipe, []).append((str(zona).strip(), str(ip).strip()))

    for tipe in data:
        data[tipe].sort(key=lambda r: zona_sort_key(r[0]))

    return data


def fetch_zones_from_db(cfg):
    import pymysql

    conn = pymysql.connect(
        host=cfg["host"],
        port=int(cfg["port"]),
        user=cfg["user"],
        password=cfg["password"],
        database=cfg["database"],
        connect_timeout=DB_TIMEOUT,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT zona, tipe, ip_target FROM tbl_restart")
            rows = cur.fetchall()
    finally:
        conn.close()

    return group_and_sort_rows(rows)


# ============================================================
# SOCKET CLIENT
# ============================================================

def send_command(ip, command):
    try:
        with socket.create_connection((ip, CLIENT_PORT), timeout=SOCKET_TIMEOUT) as s:
            s.sendall(command.encode("utf-8"))
            s.settimeout(SOCKET_TIMEOUT)
            try:
                resp = s.recv(1024).decode(errors="ignore").strip()
            except socket.timeout:
                resp = ""

        if "OK" in resp:
            return True, "Perintah berhasil dijalankan."
        if "BUSY" in resp:
            return False, "BENTROK: Target sedang menjalankan perintah user lain. Tunggu beberapa detik."
        return False, "Respons client: " + (resp or "Tidak ada respons")

    except Exception as e:
        return False, "Gagal koneksi ke {}: {}".format(ip, e)


# ============================================================
# APLIKASI WINDOWS (TKINTER)
# ============================================================

class RestartWinApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Restart DPD Control Center (Windows Edition)")
        self.root.geometry("760x640")
        self.root.minsize(640, 500)
        self.root.configure(bg=BG)

        self.set_window_icon(self.root)

        self.data = {}
        self.current_tab = 0
        self.busy = False

        app_dir = get_app_dir()
        self.cache_file = os.path.join(app_dir, "zones_cache.json")
        self.config_file = os.path.join(app_dir, "db_config.json")
        self.manual_file = os.path.join(app_dir, "manual_zones.json")
        self.mode_file = os.path.join(app_dir, "source_mode.json")

        self.source_mode = self.read_source_mode()
        self.db_config = self.read_db_config()
        self.manual_zones = self.read_manual_zones()

        self.setup_styles()
        self.build_ui()

        self.root.after(300, self.load_zones)

    def set_window_icon(self, win):
        ico_path = get_resource_path("app.ico")
        if os.path.exists(ico_path):
            try:
                win.iconbitmap(ico_path)
            except Exception:
                pass

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TCombobox", fieldbackground=CARD_BG, background=BLUE, foreground=WHITE)

    # --------------------------------------------------------
    # UI UTAMA
    # --------------------------------------------------------

    def build_ui(self):
        # 1. HEADER
        header = tk.Frame(self.root, bg=PANEL, padx=15, pady=12)
        header.pack(fill="x", padx=10, pady=(10, 5))

        title_frame = tk.Frame(header, bg=PANEL)
        title_frame.pack(side="left", fill="y")

        tk.Label(
            title_frame, text="RESTART DPD", font=("Segoe UI", 16, "bold"),
            bg=PANEL, fg=WHITE, anchor="w"
        ).pack(fill="x")
        tk.Label(
            title_frame, text="CONTROL CENTER  |  WINDOWS MANAGEMENT",
            font=("Segoe UI", 8), bg=PANEL, fg=MUTED, anchor="w"
        ).pack(fill="x")

        btn_refresh = tk.Button(
            header, text="REFRESH", font=("Segoe UI", 9, "bold"),
            bg=BLUE, fg=WHITE, activebackground="#1A62A1", activeforeground=WHITE,
            bd=0, padx=14, pady=8, cursor="hand2", command=self.load_zones
        )
        btn_refresh.pack(side="right", padx=(6, 0))

        btn_setting = tk.Button(
            header, text="SETTING", font=("Segoe UI", 9, "bold"),
            bg=CARD_BG, fg=WHITE, activebackground="#2A405E", activeforeground=WHITE,
            bd=0, padx=14, pady=8, cursor="hand2", command=self.open_settings
        )
        btn_setting.pack(side="right")

        # 2. QUICK INPUT BAR (ZONA / CZONA / PZONA)
        quick_frame = tk.Frame(self.root, bg=PANEL, padx=12, pady=10)
        quick_frame.pack(fill="x", padx=10, pady=5)

        tk.Label(
            quick_frame, text="QUICK COMMAND :", font=("Segoe UI", 9, "bold"),
            bg=PANEL, fg=WHITE
        ).pack(side="left", padx=(0, 8))

        self.quick_var = tk.StringVar()
        self.quick_entry = tk.Entry(
            quick_frame, textvariable=self.quick_var, font=("Consolas", 11, "bold"),
            bg=CARD_BG, fg=WHITE, insertbackground=WHITE, bd=0, width=22
        )
        self.quick_entry.pack(side="left", ipady=5, padx=(0, 8))
        self.quick_entry.bind("<Return>", lambda e: self.process_quick_input())

        btn_exec_quick = tk.Button(
            quick_frame, text="EKSEKUSI", font=("Segoe UI", 9, "bold"),
            bg=GREEN, fg=WHITE, bd=0, padx=12, pady=5, cursor="hand2",
            command=self.process_quick_input
        )
        btn_exec_quick.pack(side="left", padx=(0, 12))

        tk.Label(
            quick_frame,
            text="[1 / zona 1] = Standard  |  [c1 / czona 1] = Reopen  |  [p1 / pzona 1] = P-Map",
            font=("Segoe UI", 8), bg=PANEL, fg=MUTED
        ).pack(side="left")

        # 3. TAB NAVIGASI
        tab_frame = tk.Frame(self.root, bg=BG)
        tab_frame.pack(fill="x", padx=10, pady=5)

        self.tab_buttons = []
        for idx, sec in enumerate(SECTIONS):
            btn = tk.Button(
                tab_frame, text=sec[0], font=("Segoe UI", 10, "bold"),
                bg=sec[4] if idx == 0 else PANEL,
                fg=WHITE if idx == 0 else MUTED,
                bd=0, pady=8, cursor="hand2",
                command=lambda i=idx: self.select_tab(i)
            )
            btn.pack(side="left", fill="x", expand=True, padx=(0 if idx == 0 else 4, 0))
            self.tab_buttons.append(btn)

        # 4. AREA KONTEN (SCROLLABLE CANVAS)
        content_wrap = tk.Frame(self.root, bg=BG)
        content_wrap.pack(fill="both", expand=True, padx=10, pady=5)

        self.canvas = tk.Canvas(content_wrap, bg=BG, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(content_wrap, orient="vertical", command=self.canvas.yview)
        self.scroll_frame = tk.Frame(self.canvas, bg=BG)

        self.scroll_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        self.canvas_window = self.canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw")
        self.canvas.bind(
            "<Configure>",
            lambda e: self.canvas.itemconfig(self.canvas_window, width=e.width)
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        # 5. PANEL AKTIVITAS BAWAH
        activity = tk.Frame(self.root, bg=PANEL, padx=12, pady=8)
        activity.pack(fill="x", padx=10, pady=(5, 10))

        act_top = tk.Frame(activity, bg=PANEL)
        act_top.pack(fill="x")

        tk.Label(
            act_top, text="SYSTEM ACTIVITY", font=("Segoe UI", 8, "bold"),
            bg=PANEL, fg=WHITE
        ).pack(side="left")

        self.conn_label = tk.Label(
            act_top, text="READY", font=("Segoe UI", 8, "bold"),
            bg=PANEL, fg=GREEN
        )
        self.conn_label.pack(side="right")

        self.status_label = tk.Label(
            activity, text="Menunggu data zona...", font=("Segoe UI", 9),
            bg=PANEL, fg=MUTED, anchor="w"
        )
        self.status_label.pack(fill="x", pady=(3, 0))

    def _on_mousewheel(self, event):
        if self.canvas.winfo_exists():
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # --------------------------------------------------------
    # LOGIKA QUICK INPUT (ZONA, CZONA, PZONA)
    # --------------------------------------------------------

    def process_quick_input(self):
        raw = self.quick_var.get().strip()
        if not raw:
            return

        match = re.match(r"^(czona|pzona|zona|c|p|z)?\s*([a-zA-Z0-9_-]+)$", raw, re.IGNORECASE)
        if not match:
            self.set_status("[ERROR] Format input tidak valid: '{}'".format(raw))
            return

        prefix = (match.group(1) or "").lower()
        zona_val = match.group(2).strip()

        if prefix in ("c", "czona"):
            target_tipe = "REOPEN"
            tab_idx = 2
        elif prefix in ("p", "pzona"):
            target_tipe = "P_MAP"
            tab_idx = 1
        else:
            target_tipe = "STANDARD"
            tab_idx = 0

        self.select_tab(tab_idx)

        items = self.data.get(target_tipe, [])
        found_ip = None
        for z, ip in items:
            if z.lower() == zona_val.lower():
                found_ip = ip
                zona_val = z
                break

        if not found_ip:
            tipe_name = TIPE_LABELS.get(target_tipe, target_tipe)
            msg = "Zona '{}' tidak ditemukan pada kategori {}.".format(zona_val, tipe_name)
            self.set_status("[GAGAL] " + msg)
            messagebox.showwarning("Zona Tidak Ditemukan", msg)
            return

        _, _, cmd_fn, label_fn, _ = SECTIONS[tab_idx]
        self.quick_var.set("")
        self.on_card(label_fn(zona_val), found_ip, cmd_fn(zona_val))

    # --------------------------------------------------------
    # PENYIMPANAN KONFIGURASI
    # --------------------------------------------------------

    def read_source_mode(self):
        try:
            with open(self.mode_file, "r") as f:
                data = json.load(f)
            if data.get("mode") in ("db", "manual"):
                return data["mode"]
        except Exception:
            pass
        return "db"

    def save_source_mode(self, mode):
        with open(self.mode_file, "w") as f:
            json.dump({"mode": mode}, f, indent=2)
        self.source_mode = mode

    def read_db_config(self):
        try:
            with open(self.config_file, "r") as f:
                cfg = json.load(f)
            if cfg.get("host") and cfg.get("user") and cfg.get("database"):
                return cfg
        except Exception:
            pass
        return None

    def save_db_config(self, cfg):
        with open(self.config_file, "w") as f:
            json.dump(cfg, f, indent=2)
        self.db_config = cfg

    def read_manual_zones(self):
        try:
            with open(self.manual_file, "r") as f:
                rows = json.load(f)
            if isinstance(rows, list):
                return rows
        except Exception:
            pass
        return []

    def save_manual_zones(self, rows):
        with open(self.manual_file, "w") as f:
            json.dump(rows, f, indent=2)
        self.manual_zones = rows

    # --------------------------------------------------------
    # DIALOG PENGATURAN + EXPORT / IMPORT
    # --------------------------------------------------------

    def open_settings(self, first_time=False):
        win = tk.Toplevel(self.root)
        win.title("Pengaturan Sumber Zona")
        win.geometry("500x545")
        win.configure(bg=BG)
        win.transient(self.root)
        win.grab_set()
        self.set_window_icon(win)

        if first_time:
            win.protocol("WM_DELETE_WINDOW", lambda: None)

        mode_var = tk.StringVar(value=self.source_mode)

        # Pemilih Mode
        mode_bar = tk.Frame(win, bg=BG, pady=10, padx=12)
        mode_bar.pack(fill="x")

        container = tk.Frame(win, bg=PANEL, padx=14, pady=14)
        container.pack(fill="both", expand=True, padx=12)

        # --- FORM DATABASE ---
        db_frame = tk.Frame(container, bg=PANEL)
        cfg = self.db_config or DB_DEFAULTS
        db_entries = {}
        for key, label, secret in [
            ("host", "Host / IP", False),
            ("port", "Port", False),
            ("user", "User", False),
            ("password", "Password", True),
            ("database", "Nama Database", False),
        ]:
            tk.Label(db_frame, text=label, bg=PANEL, fg=MUTED, font=("Segoe UI", 9), anchor="w").pack(fill="x", pady=(4, 1))
            ent = tk.Entry(db_frame, bg=CARD_BG, fg=WHITE, insertbackground=WHITE, bd=0, font=("Segoe UI", 10), show="*" if secret else "")
            ent.insert(0, str(cfg.get(key, "")))
            ent.pack(fill="x", ipady=5)
            db_entries[key] = ent

        # --- FORM MANUAL ---
        manual_frame = tk.Frame(container, bg=PANEL)
        temp_manual = [list(r) for r in self.manual_zones]

        in_row = tk.Frame(manual_frame, bg=PANEL)
        in_row.pack(fill="x", pady=(0, 8))

        tk.Label(in_row, text="Zona", bg=PANEL, fg=MUTED, font=("Segoe UI", 8)).grid(row=0, column=0, sticky="w")
        tk.Label(in_row, text="Tipe", bg=PANEL, fg=MUTED, font=("Segoe UI", 8)).grid(row=0, column=1, sticky="w", padx=6)
        tk.Label(in_row, text="IP Target", bg=PANEL, fg=MUTED, font=("Segoe UI", 8)).grid(row=0, column=2, sticky="w")

        ent_zona = tk.Entry(in_row, bg=CARD_BG, fg=WHITE, insertbackground=WHITE, bd=0, width=10, font=("Segoe UI", 10))
        ent_zona.grid(row=1, column=0, ipady=4)

        cmb_tipe = ttk.Combobox(in_row, values=list(TIPE_OPTIONS.keys()), state="readonly", width=13)
        cmb_tipe.set("DPD")
        cmb_tipe.grid(row=1, column=1, padx=6, ipady=2)

        ent_ip = tk.Entry(in_row, bg=CARD_BG, fg=WHITE, insertbackground=WHITE, bd=0, width=18, font=("Segoe UI", 10))
        ent_ip.grid(row=1, column=2, ipady=4)

        listbox = tk.Listbox(manual_frame, bg=CARD_BG, fg=WHITE, bd=0, font=("Consolas", 9), selectbackground=BLUE)
        listbox.pack(fill="both", expand=True, pady=6)

        def refresh_listbox():
            listbox.delete(0, tk.END)
            for z, t_val, ip_addr in temp_manual:
                t_lbl = TIPE_LABELS.get(t_val, t_val)
                listbox.insert(tk.END, "Zona {:<4} | {:<10} | {}".format(z, t_lbl, ip_addr))

        def add_manual():
            z = ent_zona.get().strip()
            ip_addr = ent_ip.get().strip()
            t_val = TIPE_OPTIONS[cmb_tipe.get()]
            if not z or not ip_addr:
                messagebox.showwarning("Input Kosong", "Zona dan IP Target wajib diisi.", parent=win)
                return
            temp_manual.append([z, t_val, ip_addr])
            ent_zona.delete(0, tk.END)
            refresh_listbox()

        def del_manual():
            sel = listbox.curselection()
            if sel:
                temp_manual.pop(sel[0])
                refresh_listbox()

        btn_m_row = tk.Frame(manual_frame, bg=PANEL)
        btn_m_row.pack(fill="x", pady=(0, 6))
        tk.Button(btn_m_row, text="+ Tambah Zona", bg=BLUE, fg=WHITE, bd=0, padx=10, pady=4, cursor="hand2", command=add_manual).pack(side="left")
        tk.Button(btn_m_row, text="Hapus Terpilih", bg=RED, fg=WHITE, bd=0, padx=10, pady=4, cursor="hand2", command=del_manual).pack(side="right")

        refresh_listbox()

        def switch_mode(m):
            mode_var.set(m)
            db_frame.pack_forget()
            manual_frame.pack_forget()
            if m == "db":
                btn_db.config(bg=BLUE)
                btn_man.config(bg=CARD_BG)
                db_frame.pack(fill="both", expand=True)
            else:
                btn_man.config(bg=BLUE)
                btn_db.config(bg=CARD_BG)
                manual_frame.pack(fill="both", expand=True)

        btn_db = tk.Button(mode_bar, text="MODE DATABASE", font=("Segoe UI", 9, "bold"), fg=WHITE, bd=0, pady=7, cursor="hand2", command=lambda: switch_mode("db"))
        btn_db.pack(side="left", fill="x", expand=True, padx=(0, 4))

        btn_man = tk.Button(mode_bar, text="MODE MANUAL", font=("Segoe UI", 9, "bold"), fg=WHITE, bd=0, pady=7, cursor="hand2", command=lambda: switch_mode("manual"))
        btn_man.pack(side="left", fill="x", expand=True, padx=(4, 0))

        switch_mode(self.source_mode)

        # --- BARIS EXPORT & IMPORT SETTING ---
        io_bar = tk.Frame(win, bg=BG, pady=(8, 0), padx=12)
        io_bar.pack(fill="x")

        def export_settings():
            file_path = filedialog.asksaveasfilename(
                parent=win,
                title="Export Pengaturan ke JSON",
                defaultextension=".json",
                initialfile="restart_dpd_settings.json",
                filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
            )
            if not file_path:
                return

            try:
                current_db = {k: v.get().strip() for k, v in db_entries.items()}
                try:
                    current_db["port"] = int(current_db["port"] or 3306)
                except ValueError:
                    current_db["port"] = 3306

                payload = {
                    "app": "RestartDPD",
                    "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "source_mode": mode_var.get(),
                    "db_config": current_db,
                    "manual_zones
