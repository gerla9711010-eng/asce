"""
房地/i智慧配案（房地客需 → i智慧即時案源）— Tkinter GUI

雙擊 房地i智慧配案.vbs 開沒有黑窗，填客戶名字（+可選子條件名）按一顆鈕就查，
結果直接複製到剪貼簿。跟 gui_main.py（單獨查 i智慧）同一套黑底風格，差別是這支
先讀房地那邊存好的客需條件，再回頭去 i智慧 現查。

啟動：
  雙擊 房地i智慧配案.vbs（pythonw、無 console 黑窗）
  或   python gui_customer_match.py
"""
from __future__ import annotations

import asyncio
import queue
import sys
import threading
import traceback
from argparse import Namespace

import tkinter as tk
from tkinter import messagebox, ttk

import buyer_match
import foundi_need
import run_customer_match
from gui_main import (  # 沿用同一套配色與 Chrome 啟動/狀態邏輯，不重複寫
    ACCENT,
    BG,
    BTN_BG,
    BTN_HOVER,
    DIM,
    ERR_COLOR,
    FG,
    OK_COLOR,
    QueueWriter,
    WARN_COLOR,
    cdp_alive,
    launch_chrome,
)


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("房地/i智慧配案")
        self.root.configure(bg=BG)
        self.root.geometry("720x760")

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
            top, text="啟動 Chrome（第一次要手動登入 i智慧＋房地）", command=self._on_launch_chrome,
            bg=BTN_BG, fg=FG, activebackground=BTN_HOVER, relief="flat", padx=10, pady=4,
        )
        self.chrome_btn.pack(side="right")

        form = tk.Frame(self.root, bg=BG)
        form.pack(fill="x", **pad)

        def add_row(r, label, width=30):
            tk.Label(form, text=label, bg=BG, fg=FG, font=("Microsoft JhengHei", 10)).grid(
                row=r, column=0, sticky="w", pady=4
            )
            e = tk.Entry(form, bg="#2d2d2d", fg=FG, insertbackground=FG, relief="flat", width=width)
            e.grid(row=r, column=1, sticky="w", padx=8, pady=4)
            return e

        form.grid_columnconfigure(1, weight=1)

        self.customer_entry = add_row(0, "客戶名字（房地「客需條件」裡的名字，例：采儒）")
        self.need_entry = add_row(1, "子條件名稱（可留空，不填就用第一個，例：文化中心周圍）")
        self.price_min_entry = add_row(2, "總價下限（萬，可留空＝用房地讀到的）")
        self.price_max_entry = add_row(3, "總價上限（萬，可留空＝用房地讀到的）")
        self.rooms_entry = add_row(4, "至少幾房（可留空＝用房地讀到的）")
        self.usage_entry = add_row(5, "用途關鍵字（可留空＝用房地讀到的，例：住宅）")
        self.limit_entry = add_row(6, "i智慧最多處理幾筆（預設 15）")
        self.limit_entry.insert(0, "15")
        self.limit_areas_entry = add_row(7, "只用前 N 個關鍵字（可留空＝全部，先試跑用）")

        self.dry_run_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            form, text="只抓專員資訊，不點分享連結（除錯用，先確認條件抓得對不對）",
            variable=self.dry_run_var, bg=BG, fg=FG, selectcolor=BG,
            activebackground=BG, activeforeground=FG,
        ).grid(row=8, column=0, columnspan=2, sticky="w", pady=(4, 0))

        self.newest_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            form, text="優先看新案（i智慧排序改「上架：新>舊」，新案會標 🆕）",
            variable=self.newest_var, bg=BG, fg=FG, selectcolor=BG,
            activebackground=BG, activeforeground=FG,
        ).grid(row=9, column=0, columnspan=2, sticky="w", pady=(4, 0))

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
                "Chrome 開好後，請在跳出的視窗登入 i智慧（is.ycut.com.tw）跟房地\n"
                "（agent.foundi.info）兩個分頁都要登。登入一次之後，之後開這個工具\n"
                "都不用再登，除非過期。",
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

        customer = self.customer_entry.get().strip()
        if not customer:
            messagebox.showwarning("缺條件", "客戶名字要填（房地「客需條件」裡的名字）")
            return

        def to_int(entry):
            v = entry.get().strip()
            return int(v) if v else None

        try:
            args = Namespace(
                customer=customer,
                need=(self.need_entry.get().strip() or None),
                price_min=to_int(self.price_min_entry),
                price_max=to_int(self.price_max_entry),
                rooms_min=to_int(self.rooms_entry),
                usage=(self.usage_entry.get().strip() or None),
                limit=to_int(self.limit_entry) or 15,
                limit_areas=to_int(self.limit_areas_entry),
                dry_run=self.dry_run_var.get(),
                newest=self.newest_var.get(),
            )
        except ValueError:
            messagebox.showwarning("輸入錯誤", "總價/房數/筆數請填數字")
            return

        self.log_text.delete("1.0", "end")
        self.running = True
        self.run_btn.config(state="disabled", text="查詢中...")
        self.status_lbl.config(
            text="查詢中，請稍候（先讀房地客需，再逐關鍵字查 i智慧，會花一點時間）...",
            fg=WARN_COLOR,
        )

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
            asyncio.run(run_customer_match.run(args))
        except SystemExit:
            ok = False
            err_msg = "連不到 Chrome。請先按上面「啟動 Chrome」按鈕，並登入 i智慧＋房地。"
        except RuntimeError as e:
            ok = False
            err_msg = str(e)
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
