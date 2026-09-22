# -*- coding: utf-8 -*-
"""
買方配案系統 — 雙擊啟動視窗。按「開始更新」就會自動跑完
collect.js → 產頁面 → 覆蓋桌面「買方配案.html」，不用再叫 Claude。
"""
import subprocess
import sys
import queue
import threading
import tkinter as tk
from tkinter import scrolledtext, messagebox
from pathlib import Path

BASE = Path(__file__).resolve().parent
PYTHON = sys.executable


class App:
    def __init__(self, root):
        self.root = root
        root.title("買方配案更新")
        root.geometry("560x420")

        top = tk.Frame(root, padx=12, pady=10)
        top.pack(fill="x")

        self.full_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            top, text="全部重新抓取（只有第一次或想重掃全部才勾，平常不用）",
            variable=self.full_var,
        ).pack(anchor="w")

        self.start_btn = tk.Button(
            top, text="開始更新", font=("Microsoft JhengHei", 12, "bold"),
            bg="#2e7d32", fg="white", height=2, command=self.start,
        )
        self.start_btn.pack(fill="x", pady=(8, 0))

        self.log = scrolledtext.ScrolledText(root, wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self.q = queue.Queue()
        self.proc = None
        self.root.after(150, self.poll_queue)

    def append(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def start(self):
        self.start_btn.configure(state="disabled", text="跑中…")
        self.append("=== 開始 ===")
        args = [PYTHON, str(BASE / "worker.py")]
        if self.full_var.get():
            args.append("--full")
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        self.proc = subprocess.Popen(
            args, cwd=str(BASE), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", bufsize=1, creationflags=flags,
        )
        threading.Thread(target=self.read_output, daemon=True).start()

    def read_output(self):
        for line in self.proc.stdout:
            self.q.put(line.rstrip("\n"))
        self.proc.wait()
        self.q.put("__PROC_DONE__")

    def poll_queue(self):
        try:
            while True:
                line = self.q.get_nowait()
                self.handle_line(line)
        except queue.Empty:
            pass
        self.root.after(200, self.poll_queue)

    def handle_line(self, line):
        if line == "__PROC_DONE__":
            self.start_btn.configure(state="normal", text="開始更新")
            return
        if line.startswith("STATUS|"):
            self.append(line.split("|", 1)[1])
        elif line == "NEED_LOGIN":
            self.append("⚠️ 還沒登入，請在跳出的瀏覽器視窗手動登入房地帳號（登入一次以後都記得）")
        elif line == "LOGIN_OK":
            self.append("登入確認，開始收集資料")
        elif line.startswith("PROGRESS|"):
            _, done, total, saved, cards = line.split("|")
            self.append(f"進度 {done}/{total}，已存 {saved} 個客需，累計展開 {cards} 張卡")
        elif line.startswith("DONE|"):
            import json
            d = json.loads(line.split("|", 1)[1])
            msg = f"完成！{d['demands']} 個客需、{d['items']} 筆連結，已更新桌面買方配案.html"
            if d.get("limitHit"):
                msg += "\n（這次撞到查詢上限提前停手，下次開再繼續抓沒抓到的）"
            self.append(msg)
            messagebox.showinfo("完成", msg)
        elif line.startswith("ERROR|"):
            msg = line.split("|", 1)[1]
            self.append("❌ " + msg)
            messagebox.showerror("出錯了", msg)
        else:
            self.append(line)


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
