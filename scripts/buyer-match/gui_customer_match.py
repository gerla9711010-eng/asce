"""
房地/i智慧配案（房地客需 → i智慧即時案源）— Tkinter GUI

雙擊 房地i智慧配案.vbs 開沒有黑窗，群組／客戶／客需三個下拉點一點按鈕就查，
結果直接複製到剪貼簿。跟 gui_main.py（單獨查 i智慧）同一套黑底風格，差別是這支
先讀房地那邊存好的客需條件，再回頭去 i智慧 現查。

三個下拉的清單是開工具時直接從房地讀回來的（2026-07-30 改；之前要手打客戶名字，
名字很長又會打錯）。四種範圍：
  群組＝「★ 全部群組」          → A買/B買/C買… 全部依序跑完（2026-08-04 加）
  客戶＝「全部客戶」            → 整組跑
  客戶＝某人、客需＝「全部客需」  → 只跑這位客戶所有條件
  客戶＝某人、客需＝某個條件      → 單查一條

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

from playwright.async_api import async_playwright

import buyer_match
import foundi_need
import run_customer_match
import run_group_match
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

ALL_GROUPS = "（★ 全部群組：一組一組依序跑完）"
ALL_CUSTOMERS = "（整組跑：全部客戶）"
ALL_NEEDS = "（這位客戶的全部客需）"

# 整組實測時間：2026-07-30 A買 7 位客戶 14 個客需約 46 分鐘 → 抓每組 45 分鐘估
MINUTES_PER_GROUP = 45


async def fetch_foundi_tree() -> dict[str, list[tuple[str, list[str]]]]:
    """連上 CDP Chrome，把房地「客需條件」整棵樹讀回來給下拉用。"""
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(buyer_match.CDP_URL)
        ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = await foundi_need.get_or_open_foundi_page(ctx)
        await foundi_need.ensure_logged_in(page)
        return await foundi_need.read_all_groups(page)


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("房地/i智慧配案")
        self.root.configure(bg=BG)
        self.root.geometry("720x760")

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.running = False
        self.loading_tree = False
        self.tree: dict[str, list[tuple[str, list[str]]]] = {}

        self._build_ui()
        self._poll_log_queue()
        self._refresh_chrome_status()
        # Chrome 已經開著就直接把客戶清單讀進來，不用使用者多按一顆鈕
        self.root.after(800, self._auto_load_tree)

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

        def add_combo(r, label, var, width=38):
            tk.Label(form, text=label, bg=BG, fg=FG, font=("Microsoft JhengHei", 10)).grid(
                row=r, column=0, sticky="w", pady=4
            )
            cb = ttk.Combobox(
                form, textvariable=var, state="readonly", width=width,
                font=("Microsoft JhengHei", 10),
            )
            cb.grid(row=r, column=1, sticky="w", padx=8, pady=4)
            return cb

        form.grid_columnconfigure(1, weight=1)

        # 群組／客戶／客需三層下拉：清單直接從房地讀出來點選，不用手打
        # （客戶名字很長又常打錯，2026-07-29 使用者明講手打「不人性化」）
        self.group_var = tk.StringVar()
        self.customer_var = tk.StringVar()
        self.need_var = tk.StringVar()

        self.group_cb = add_combo(0, "群組", self.group_var)
        self.customer_cb = add_combo(1, "客戶", self.customer_var)
        self.need_cb = add_combo(2, "客需（子條件）", self.need_var)
        self.group_cb.bind("<<ComboboxSelected>>", self._on_group_selected)
        self.customer_cb.bind("<<ComboboxSelected>>", self._on_customer_selected)

        self.price_min_entry = add_row(3, "總價下限（萬，可留空＝用房地讀到的）")
        self.price_max_entry = add_row(4, "總價上限（萬，可留空＝用房地讀到的）")
        self.rooms_entry = add_row(5, "至少幾房（可留空＝用房地讀到的）")
        self.usage_entry = add_row(6, "用途關鍵字（可留空＝用房地讀到的，例：住宅）")
        self.limit_entry = add_row(7, "i智慧最多處理幾筆（預設 15）")
        self.limit_entry.insert(0, "15")
        self.limit_areas_entry = add_row(8, "只用前 N 個關鍵字（可留空＝全部，先試跑用）")

        tree_row = tk.Frame(form, bg=BG)
        tree_row.grid(row=9, column=0, columnspan=2, sticky="w", pady=(2, 0))

        self.reload_btn = tk.Button(
            tree_row, text="從房地重新讀客戶清單", command=self._on_load_tree,
            bg=BTN_BG, fg=FG, activebackground=BTN_HOVER, relief="flat", padx=10, pady=3,
        )
        self.reload_btn.pack(side="left")

        self.tree_status_lbl = tk.Label(
            tree_row, text="尚未讀取客戶清單", bg=BG, fg=DIM, font=("Microsoft JhengHei", 9)
        )
        self.tree_status_lbl.pack(side="left", padx=8)

        self.dry_run_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            form, text="只抓專員資訊，不點分享連結（除錯用，先確認條件抓得對不對）",
            variable=self.dry_run_var, bg=BG, fg=FG, selectcolor=BG,
            activebackground=BG, activeforeground=FG,
        ).grid(row=10, column=0, columnspan=2, sticky="w", pady=(4, 0))

        self.newest_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            form, text="優先看新案（i智慧排序改「上架：新>舊」，新案會標 🆕）",
            variable=self.newest_var, bg=BG, fg=FG, selectcolor=BG,
            activebackground=BG, activeforeground=FG,
        ).grid(row=11, column=0, columnspan=2, sticky="w", pady=(4, 0))

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
            # Chrome 起來要幾秒，之後自己把客戶清單讀進來（沒登入會在狀態列講）
            self.root.after(10000, self._auto_load_tree)
            messagebox.showinfo(
                "Chrome 啟動中",
                "Chrome 開好後，請在跳出的視窗登入 i智慧（is.ycut.com.tw）跟房地\n"
                "（agent.foundi.info）兩個分頁都要登。登入一次之後，之後開這個工具\n"
                "都不用再登，除非過期。",
            )
        else:
            messagebox.showerror("啟動失敗", msg)

    # ── 三層下拉（群組／客戶／客需）────────────────────────

    def _auto_load_tree(self):
        if cdp_alive() and not self.tree:
            self._on_load_tree()

    def _on_load_tree(self):
        if self.loading_tree:
            return
        if not cdp_alive():
            messagebox.showwarning(
                "Chrome 還沒開",
                "要先按右上角「啟動 Chrome」把配案用的視窗開起來（並登入房地），\n"
                "才能把客戶清單讀出來。",
            )
            return
        self.loading_tree = True
        self.reload_btn.config(state="disabled", text="讀取中...")
        self.tree_status_lbl.config(text="正在從房地讀客戶清單...", fg=WARN_COLOR)
        threading.Thread(target=self._load_tree_worker, daemon=True).start()

    def _load_tree_worker(self):
        tree, err = None, ""
        try:
            tree = asyncio.run(fetch_foundi_tree())
        except foundi_need.FoundiNotLoggedIn as e:
            err = f"房地要重新登入：{e}"
        except Exception as e:
            err = str(e)
        self.root.after(0, self._on_tree_loaded, tree, err)

    def _on_tree_loaded(self, tree, err: str):
        self.loading_tree = False
        self.reload_btn.config(state="normal", text="從房地重新讀客戶清單")
        if not tree:
            self.tree_status_lbl.config(text=f"讀不到清單：{err}", fg=ERR_COLOR)
            # 讀不到就把三個下拉解鎖成可打字，不要讓人卡在這裡什麼都做不了
            for cb in (self.group_cb, self.customer_cb, self.need_cb):
                cb.config(state="normal")
            return

        self.tree = tree
        groups = list(tree.keys())
        self.group_cb.config(state="readonly", values=[ALL_GROUPS] + groups)
        total_customers = sum(len(v) for v in tree.values())
        self.tree_status_lbl.config(
            text=f"已讀到 {len(groups)} 個群組、{total_customers} 位客戶", fg=OK_COLOR
        )
        # 預設停在 A買（每天 08:10 排程跑的那組），沒有就用第一個
        self.group_var.set("A買" if "A買" in groups else (groups[0] if groups else ""))
        self._on_group_selected()

    def _on_group_selected(self, _event=None):
        if self.group_var.get() == ALL_GROUPS:
            # 全部群組：底下每一組的每位客戶、每個客需都會跑，兩個下拉都沒有意義
            self.customer_cb.config(values=[], state="disabled")
            self.customer_var.set("")
            self.need_cb.config(values=[], state="disabled")
            self.need_var.set("")
            return
        customers = [name for name, _ in self.tree.get(self.group_var.get(), [])]
        values = [ALL_CUSTOMERS] + customers
        self.customer_cb.config(state="readonly", values=values)
        self.customer_var.set(ALL_CUSTOMERS)
        self._on_customer_selected()

    def _on_customer_selected(self, _event=None):
        customer = self.customer_var.get()
        if customer == ALL_CUSTOMERS:
            # 整組跑：每位客戶的每個客需都會跑，這個下拉沒有意義
            self.need_cb.config(values=[], state="disabled")
            self.need_var.set("")
            return
        needs = next(
            (nl for name, nl in self.tree.get(self.group_var.get(), []) if name == customer), []
        )
        values = [ALL_NEEDS] + needs
        self.need_cb.config(state="readonly", values=values)
        # 預設點第一個實際客需（單查一個條件是最常見用法），要全部跑再自己選上面那項
        self.need_var.set(needs[0] if needs else ALL_NEEDS)

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

        group = self.group_var.get().strip()
        customer = self.customer_var.get().strip()
        need = self.need_var.get().strip()

        if not group:
            messagebox.showwarning(
                "還沒選群組", "先按「從房地重新讀客戶清單」把清單讀進來，再選群組／客戶。"
            )
            return

        # 四種模式：
        #   群組＝全部群組         → 每一組依序整組跑（run_group_match.run_all）
        #   客戶＝全部            → 整組跑（每位客戶的每個客需）
        #   客戶＝某人、客需＝全部  → 只跑這位客戶的全部客需（也是走 run_group_match）
        #   客戶＝某人、客需＝某條件 → 單一查詢（run_customer_match）
        all_groups = group == ALL_GROUPS
        all_customers = all_groups or customer in ("", ALL_CUSTOMERS)
        group_mode = all_customers or need in ("", ALL_NEEDS)

        groups = list(self.tree.keys()) if all_groups else []
        if all_groups and not groups:
            messagebox.showwarning(
                "沒有群組可跑", "客戶清單是空的，先按「從房地重新讀客戶清單」再試。"
            )
            return

        def to_int(entry):
            v = entry.get().strip()
            return int(v) if v else None

        try:
            if group_mode:
                args = Namespace(
                    group=None if all_groups else group,
                    customer=None if all_customers else customer,
                    limit=to_int(self.limit_entry) or 15,
                    dry_run=self.dry_run_var.get(),
                    newest=self.newest_var.get(),
                )
            else:
                args = Namespace(
                    customer=customer,
                    need=need,
                    group=group,
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

        if group_mode:
            if all_groups:
                scope = f"全部 {len(groups)} 個群組（{'、'.join(groups)}）底下所有客戶的所有客需"
            elif all_customers:
                scope = f"「{group}」底下全部客戶的全部客需"
            else:
                scope = f"客戶「{customer}」的全部客需"
            hours = len(groups) * MINUTES_PER_GROUP / 60
            est = (
                f"⚠️ 全部群組要一組一組跑，粗估 {hours:.1f} 小時（每組約 {MINUTES_PER_GROUP} 分鐘）。\n"
                "期間電腦不能關、Chrome 視窗不能動。\n"
                if all_groups
                else "⚠️ 整組可能要幾十分鐘（2026-07-30 實測 A買 7 位客戶 14 個客需約 46 分鐘）。\n"
                if all_customers
                else "⚠️ 一位客戶的全部客需通常幾分鐘。\n"
            )
            if not messagebox.askokcancel(
                "確認範圍",
                f"會跑 {scope}。\n每個客需各自存一個檔，跑完印總表。\n\n"
                f"{est}期間請不要動那個 Chrome 視窗。要開始嗎？",
            ):
                return

        self.log_text.delete("1.0", "end")
        self.running = True
        self.run_btn.config(state="disabled", text="查詢中...")
        self.status_lbl.config(
            text=(
                f"全部群組查詢中（{'、'.join(groups)}），請稍候，這會花好幾小時..."
                if all_groups
                else f"整組查詢中（{group}），請稍候，這會花幾十分鐘..."
                if group_mode and all_customers
                else f"查詢中（{customer}），請稍候（先讀房地客需，再逐關鍵字查 i智慧）..."
            ),
            fg=WARN_COLOR,
        )

        thread = threading.Thread(
            target=self._worker, args=(args, group_mode, groups), daemon=True
        )
        thread.start()

    def _worker(self, args: Namespace, group_mode: bool = False, groups: list[str] | None = None):
        writer = QueueWriter(self.log_queue)
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = writer
        sys.stderr = writer
        ok = True
        err_msg = ""
        try:
            if groups:
                asyncio.run(run_group_match.run_all(args, groups))
            elif group_mode:
                asyncio.run(run_group_match.run(args))
            else:
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
