# -*- coding: utf-8 -*-
"""
買方配案系統 — 雙擊啟動視窗。按「開始更新」就會自動跑完
collect.js → 產頁面 → 發布到 https://yc-buyer-match.pages.dev/，不用再叫 Claude。
"""
import subprocess
import sys
import queue
import threading
import tkinter as tk
from tkinter import scrolledtext, messagebox
from pathlib import Path

BASE = Path(__file__).resolve().parent
REPO = BASE.parent.parent
PYTHON = sys.executable
FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def self_update():
    """跑之前把程式更新成 GitHub main 版。家裡/公司兩台共用 OneDrive 記錄、程式卻各自一份，
    舊程式跑一次就會把共用記錄寫壞（2026-10-19 公司那台）。
    先試快轉（分支已併進 main 時 git 狀態保持乾淨）；不行才只覆蓋這個資料夾（run.bat 除外）。
    本機有改到一半的程式就不動；沒網路就用現有版本。放在 GUI 不放 run.bat：執行中改 .bat 會壞。"""
    def git(*a):
        try:
            return subprocess.run(["git", *a], cwd=str(REPO), capture_output=True, text=True,
                                  timeout=60, creationflags=FLAGS).returncode
        except Exception:
            return -1
    here = "scripts/buyer-match"
    if git("fetch", "-q", "origin", "main") != 0:
        return "⚠️ 連不到 GitHub，用目前這台的程式版本跑"
    if git("diff", "--quiet", "HEAD", "origin/main", "--", here) == 0:
        return "程式已是最新版"
    if git("merge", "-q", "--ff-only", "origin/main") == 0:
        if git("diff", "--quiet", "HEAD", "origin/main", "--", here) != 0:
            return "這台的程式比 GitHub main 還新（開發中），照用"
        return "程式已自動更新到最新版"
    if git("diff", "--quiet", "--", here) != 0:
        return "⚠️ 這台有改到一半的買方配案程式，沒有自動更新（請找 Claude 處理）"
    if git("checkout", "origin/main", "--", here, ":!" + here + "/run.bat") == 0:
        return "程式已自動更新到最新版（只更新買方配案資料夾）"
    return "⚠️ 自動更新失敗，用目前版本跑"


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
        threading.Thread(target=self.read_output, args=(self.full_var.get(),), daemon=True).start()

    def read_output(self, full):
        self.q.put("檢查程式版本…")
        self.q.put(self_update())
        args = [PYTHON, str(BASE / "worker.py")]  # 更新完才啟動，worker.py／collect.js 讀到的是新版
        if full:
            args.append("--full")
        self.proc = subprocess.Popen(
            args, cwd=str(BASE), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", bufsize=1, creationflags=FLAGS,
        )
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
            self.append(f"進度 {done}/{total}，已存 {saved} 個客需，已處理 {cards} 張卡")  # 10-19 起卡片不點開，舊字「展開」會誤導
        elif line.startswith("DONE|"):
            import json
            d = json.loads(line.split("|", 1)[1])
            msg = f"完成！{d['demands']} 個客需、{d['items']} 筆連結，網址已更新：{d.get('url', '')}"
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
