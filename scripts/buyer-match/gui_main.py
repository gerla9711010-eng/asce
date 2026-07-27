"""
買方配案 — Tkinter GUI

雙擊開沒有黑窗、輸入行政區/總價等條件按一顆鈕就查，結果直接複製到剪貼簿。
沿用桌面「自動比對專約」工具的黑底風格與 CDP 偵測/Chrome 啟動手法。

啟動：
  雙擊 啟動工具.vbs（pythonw、無 console 黑窗）
  或   python gui_main.py
"""
from __future__ import annotations

import asyncio
import json
import queue
import subprocess
import sys
import threading
import traceback
import urllib.error
import urllib.request
from argparse import Namespace
from pathlib import Path

import tkinter as tk
from tkinter import messagebox, ttk

import buyer_match

SCRIPT_DIR = Path(__file__).resolve().parent
CDP_URL = f"http://localhost:{buyer_match.CDP_PORT}/json/version"
CDP_TIMEOUT_SEC = 1.5

CHROME_EXE_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

# 黑底主題（跟自動比對專約同款配色）
BG = "#1e1e1e"
FG = "#FFFFFF"
ACCENT = "#5DA9FF"
INPUT_BG = "#2d2d2d"
BTN_BG = "#3a3a3a"
BTN_HOVER = "#4a4a4a"
DIM = "#888888"
OK_COLOR = "#7BC97B"
WARN_COLOR = "#FFB347"
ERR_COLOR = "#FF7B7B"


def find_chrome_exe():
    import os

    paths = list(CHROME_EXE_CANDIDATES)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        paths.append(str(Path(local) / "Google" / "Chrome" / "Application" / "chrome.exe"))
    for p in paths:
        if Path(p).is_file():
            return p
    return None


def _no_window_flags():
    return 0x08000000 if sys.platform.startswith("win") else 0  # CREATE_NO_WINDOW


def cdp_alive() -> bool:
    try:
        req = urllib.request.Request(CDP_URL, headers={"User-Agent": "buyer-match-gui"})
        with urllib.request.urlopen(req, timeout=CDP_TIMEOUT_SEC) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return bool(data.get("Browser"))
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError):
        return False


def launch_chrome() -> tuple[bool, str]:
    exe = find_chrome_exe()
    if not exe:
        return False, "找不到 chrome.exe，請確認 Chrome 有裝在預設路徑"
    profile_dir = SCRIPT_DIR / "chrome_profile"
    args = [
        exe,
        f"--remote-debugging-port={buyer_match.CDP_PORT}",
        "--remote-allow-origins=*",
        f"--user-data-dir={profile_dir}",
        buyer_match.ISMART_SEARCH_URL,
    ]
    try:
        subprocess.Popen(args, creationflags=_no_window_flags())
        return True, "Chrome 啟動中..."
    except Exception as e:
        return False, f"啟動失敗：{e}"


class QueueWriter:
    """把 print() 導進 queue，GUI 主執行緒用 after() 輪詢取出寫進 Text（Tkinter 不能跨執行緒直接改 widget）。"""

    def __init__(self, q: queue.Queue):
        self.q = q

    def write(self, s):
        if s:
            self.q.put(s)

    def flush(self):
        pass


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("買方配案")
        self.root.configure(bg=BG)
        self.root.geometry("720x640")

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.running = False

        self._build_ui()
        self._poll_log_queue()
        self._refresh_chrome_status()

    # ── UI ──────────────────────────────────────────────

    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}

        top = tk.Frame(self.root, bg=BG)
        top.pack(fill="x", **pad)

        self.chrome_status_lbl = tk.Label(
            top, text="Chrome 狀態：檢查中...", bg=BG, fg=DIM, font=("Microsoft JhengHei", 10)
        )
        self.chrome_status_lbl.pack(side="left")

        self.chrome_btn = tk.Button(
            top, text="啟動 Chrome（第一次要手動登入 i智慧）", command=self._on_launch_chrome,
            bg=BTN_BG, fg=FG, activebackground=BTN_HOVER, relief="flat", padx=10, pady=4,
        )
        self.chrome_btn.pack(side="right")

        form = tk.Frame(self.root, bg=BG)
        form.pack(fill="x", **pad)

        def add_row(r, label, width=20):
            tk.Label(form, text=label, bg=BG, fg=FG, font=("Microsoft JhengHei", 10)).grid(
                row=r, column=0, sticky="w", pady=4
            )
            e = tk.Entry(form, bg=INPUT_BG, fg=FG, insertbackground=FG, relief="flat", width=width)
            e.grid(row=r, column=1, sticky="w", padx=8, pady=4)
            return e

        form.grid_columnconfigure(1, weight=1)

        self.area_entry = add_row(0, "行政區／社區／路名關鍵字*", width=30)
        self.price_min_entry = add_row(1, "總價下限（萬，可留空）")
        self.price_max_entry = add_row(2, "總價上限（萬，可留空）")
        self.rooms_entry = add_row(3, "至少幾房（可留空）")
        self.usage_entry = add_row(4, "用途關鍵字（可留空，例：住宅）")
        self.limit_entry = add_row(5, "最多處理幾筆（預設 15）")
        self.limit_entry.insert(0, "15")

        self.list_only_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            form, text="只看筆數，不開詳情頁/不抓專員與分享連結（快速預覽）",
            variable=self.list_only_var, bg=BG, fg=FG, selectcolor=BG,
            activebackground=BG, activeforeground=FG,
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(4, 0))

        btn_row = tk.Frame(self.root, bg=BG)
        btn_row.pack(fill="x", **pad)

        self.run_btn = tk.Button(
            btn_row, text="開始查詢", command=self._on_run, bg=ACCENT, fg="#111111",
            activebackground=ACCENT, relief="flat", padx=16, pady=6, font=("Microsoft JhengHei", 11, "bold"),
        )
        self.run_btn.pack(side="left")

        self.copy_btn = tk.Button(
            btn_row, text="複製結果", command=self._on_copy, bg=BTN_BG, fg=FG,
            activebackground=BTN_HOVER, relief="flat", padx=10, pady=6,
        )
        self.copy_btn.pack(side="left", padx=8)

        tk.Button(
            btn_row, text="關閉", command=self.root.destroy, bg=BTN_BG, fg=FG,
            activebackground=BTN_HOVER, relief="flat", padx=10, pady=6,
        ).pack(side="right")

        self.status_lbl = tk.Label(self.root, text="", bg=BG, fg=DIM, font=("Microsoft JhengHei", 10))
        self.status_lbl.pack(fill="x", padx=10)

        log_frame = tk.Frame(self.root, bg=BG)
        log_frame.pack(fill="both", expand=True, padx=10, pady=(4, 10))

        self.log_text = tk.Text(
            log_frame, bg="#111111", fg="#CCCCCC", insertbackground=FG,
            relief="flat", wrap="word", font=("Consolas", 10),
        )
        scroll = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    # ── Chrome 狀態 ─────────────────────────────────────

    def _refresh_chrome_status(self):
        alive = cdp_alive()
        if alive:
            self.chrome_status_lbl.config(text="Chrome 狀態：已連線 ✓", fg=OK_COLOR)
        else:
            self.chrome_status_lbl.config(text="Chrome 狀態：尚未啟動", fg=WARN_COLOR)
        self.root.after(4000, self._refresh_chrome_status)

    def _on_launch_chrome(self):
        ok, msg = launch_chrome()
        if ok:
            messagebox.showinfo(
                "Chrome 啟動中",
                "Chrome 開好後，請在跳出的視窗登入 i智慧（is.ycut.com.tw）。\n"
                "登入一次之後，之後開這個工具都不用再登，除非過期。",
            )
        else:
            messagebox.showerror("啟動失敗", msg)

    # ── log ─────────────────────────────────────────────

    def _append_log(self, s: str):
        self.log_text.insert("end", s)
        self.log_text.see("end")

    def _poll_log_queue(self):
        try:
            while True:
                s = self.log_queue.get_nowait()
                self._append_log(s)
        except queue.Empty:
            pass
        self.root.after(150, self._poll_log_queue)

    # ── 執行查詢 ─────────────────────────────────────────

    def _on_run(self):
        if self.running:
            return

        area = self.area_entry.get().strip()
        if not area:
            messagebox.showwarning("缺條件", "行政區／社區／路名關鍵字是必填")
            return

        def to_int(entry):
            v = entry.get().strip()
            return int(v) if v else None

        try:
            args = Namespace(
                area=area,
                price_min=to_int(self.price_min_entry),
                price_max=to_int(self.price_max_entry),
                rooms_min=to_int(self.rooms_entry),
                usage=(self.usage_entry.get().strip() or None),
                limit=to_int(self.limit_entry) or 15,
                list_only=self.list_only_var.get(),
                dry_run=False,
            )
        except ValueError:
            messagebox.showwarning("輸入錯誤", "總價/房數/筆數請填數字")
            return

        self.log_text.delete("1.0", "end")
        self.running = True
        self.run_btn.config(state="disabled", text="查詢中...")
        self.status_lbl.config(text="查詢中，請稍候（每筆物件都要開新分頁抓資料，會花一點時間）...", fg=WARN_COLOR)

        thread = threading.Thread(target=self._worker, args=(args,), daemon=True)
        thread.start()

    def _worker(self, args: Namespace):
        writer = QueueWriter(self.log_queue)
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = writer
        sys.stderr = writer
        ok = True
        err_msg = ""
        try:
            asyncio.run(buyer_match.run(args))
        except SystemExit:
            ok = False
            err_msg = "連不到 Chrome。請先按上面「啟動 Chrome」按鈕，並在跳出的視窗登入 i智慧。"
        except Exception as e:
            ok = False
            err_msg = f"{e}"
            traceback.print_exc()
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
        self.root.after(0, self._on_worker_done, ok, err_msg)

    def _on_worker_done(self, ok: bool, err_msg: str):
        self.running = False
        self.run_btn.config(state="normal", text="開始查詢")
        if ok:
            self.status_lbl.config(text="完成！結果已複製到剪貼簿，可直接貼給客戶。", fg=OK_COLOR)
        else:
            self.status_lbl.config(text=f"失敗：{err_msg}", fg=ERR_COLOR)

    def _on_copy(self):
        try:
            import pyperclip

            pyperclip.copy(self.log_text.get("1.0", "end"))
            self.status_lbl.config(text="已把畫面上的內容複製到剪貼簿", fg=OK_COLOR)
        except Exception as e:
            messagebox.showerror("複製失敗", str(e))


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
