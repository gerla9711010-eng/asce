# rent_ad_gui.py - 租屋廣告 LINE 文案產生器
# 用法：python rent_ad_gui.py
# 功能：用表單填入物件資訊 → 一鍵產生 LINE 文案 → 一鍵複製到剪貼簿
# 只用 Python 內建的 tkinter，不需安裝任何套件。

import tkinter as tk
from tkinter import ttk, messagebox


# ─────────────────────────────────────────────────────
#  小工具：建立帶卷軸的內容區
# ─────────────────────────────────────────────────────
class ScrollFrame(ttk.Frame):
    """一個可垂直捲動的 Frame，欄位都放進 self.body。"""

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0)
        vbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vbar.set)

        vbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self.body = ttk.Frame(canvas)
        win = canvas.create_window((0, 0), window=self.body, anchor="nw")

        def _on_config(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        self.body.bind("<Configure>", _on_config)

        def _on_canvas(event):
            canvas.itemconfig(win, width=event.width)
        canvas.bind("<Configure>", _on_canvas)

        # 滑鼠滾輪
        def _wheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _wheel)            # Windows / macOS
        canvas.bind_all("<Button-4>", lambda e: canvas.yview_scroll(-1, "units"))  # Linux
        canvas.bind_all("<Button-5>", lambda e: canvas.yview_scroll(1, "units"))   # Linux


# ─────────────────────────────────────────────────────
#  主程式
# ─────────────────────────────────────────────────────
class RentAdApp:
    BUILDING_TYPES = ["透天", "公寓", "電梯大樓", "華廈", "店面"]
    FURNITURE = ["床", "沙發", "椅子", "衣櫃", "桌子"]
    EQUIPMENT = ["洗衣機", "電視", "熱水器", "冰箱", "冷氣"]
    OTHER = ["網路", "第四台", "天然瓦斯"]

    ON_BG = "#FFD400"     # 選取 = 黃色填滿
    OFF_BG = "#E8E8E8"    # 未選取 = 灰色

    def __init__(self, root):
        self.root = root
        root.title("租屋廣告 LINE 文案產生器")
        root.geometry("780x860")

        self.vars = {}   # 存放所有輸入元件的變數

        # 上：輸入表單（可捲動）  下：產生結果
        paned = ttk.PanedWindow(root, orient="vertical")
        paned.pack(fill="both", expand=True, padx=8, pady=8)

        form_wrap = ScrollFrame(paned)
        paned.add(form_wrap, weight=3)
        self._build_form(form_wrap.body)

        result_wrap = ttk.Frame(paned)
        paned.add(result_wrap, weight=2)
        self._build_result(result_wrap)

    # ── 基本版面小工具 ────────────────────────────────
    def _section(self, parent, title):
        lf = ttk.LabelFrame(parent, text=title)
        lf.pack(fill="x", padx=6, pady=5)
        return lf

    def _row(self, parent):
        f = ttk.Frame(parent)
        f.pack(fill="x", padx=8, pady=3)
        return f

    def _entry(self, parent, key, label, width=40, default=""):
        f = self._row(parent)
        ttk.Label(f, text=label, width=12, anchor="e").pack(side="left")
        v = tk.StringVar(value=default)
        self.vars[key] = v
        ttk.Entry(f, textvariable=v, width=width).pack(side="left", fill="x", expand=True)
        return v

    # ── 黃色填滿 chip ─────────────────────────────────
    def _single_chip(self, parent, var, opt, on_change=None):
        """單選 chip：選取時黃色填滿。再點一次可取消。共用同一個 StringVar。"""
        lbl = tk.Label(parent, text=opt, padx=10, pady=3, bd=1,
                       relief="groove", cursor="hand2")

        def refresh(*_):
            on = (var.get() == opt)
            lbl.config(bg=self.ON_BG if on else self.OFF_BG,
                       relief="solid" if on else "groove")

        def click(_):
            var.set("" if var.get() == opt else opt)
            if on_change:
                on_change()

        lbl.bind("<Button-1>", click)
        var.trace_add("write", refresh)
        refresh()
        lbl.pack(side="left", padx=2)
        return lbl

    def _multi_chip(self, parent, bvar, opt, on_delete=None):
        """複選 chip：選取時黃色填滿。右鍵可刪除（自訂選項用）。"""
        lbl = tk.Label(parent, text=opt, padx=10, pady=3, bd=1,
                       relief="groove", cursor="hand2")

        def refresh(*_):
            on = bvar.get()
            lbl.config(bg=self.ON_BG if on else self.OFF_BG,
                       relief="solid" if on else "groove")

        lbl.bind("<Button-1>", lambda e: bvar.set(not bvar.get()))
        if on_delete:
            lbl.bind("<Button-3>", lambda e: on_delete())
        bvar.trace_add("write", refresh)
        refresh()
        lbl.pack(side="left", padx=2)
        return lbl

    def _chip_single(self, parent, key, label, options, default="", on_change=None):
        f = self._row(parent)
        ttk.Label(f, text=label, width=12, anchor="e").pack(side="left")
        v = tk.StringVar(value=default)
        self.vars[key] = v
        for opt in options:
            self._single_chip(f, v, opt, on_change)
        return f, v

    def _checks(self, parent, key, label, options):
        """可動態新增/刪除選項的複選群組（黃色 chip）。
        self.vars[key] = {選項文字: BooleanVar}
        點一下 = 黃色選取；右鍵 = 刪除該選項；下方輸入框可新增自訂選項。
        """
        outer = ttk.Frame(parent)
        outer.pack(fill="x", padx=8, pady=3)

        top = ttk.Frame(outer)
        top.pack(fill="x")
        ttk.Label(top, text=label, width=12, anchor="e").pack(side="left")
        box = ttk.Frame(top)            # 放所有 chip 的容器
        box.pack(side="left", fill="x", expand=True)

        d = {}
        self.vars[key] = d

        def render():
            for w in box.winfo_children():
                w.destroy()
            for opt in list(d.keys()):
                self._multi_chip(box, d[opt], opt, on_delete=lambda o=opt: remove(o))

        def remove(opt):
            d.pop(opt, None)
            render()

        def add(opt):
            opt = opt.strip()
            if opt and opt not in d:
                d[opt] = tk.BooleanVar(value=False)
            render()

        for opt in options:
            d[opt] = tk.BooleanVar(value=False)
        render()

        addbar = ttk.Frame(outer)
        addbar.pack(fill="x", padx=(96, 0), pady=(2, 0))
        new_var = tk.StringVar()
        ent = ttk.Entry(addbar, textvariable=new_var, width=12)
        ent.pack(side="left")

        def do_add():
            add(new_var.get())
            new_var.set("")
            ent.focus_set()

        ent.bind("<Return>", lambda e: do_add())
        ttk.Button(addbar, text="＋新增選項", command=do_add).pack(side="left", padx=4)
        ttk.Label(addbar, text="（點一下=黃色選取，右鍵=刪除選項）",
                  foreground="#888").pack(side="left", padx=6)
        return d

    # ── 表單建立 ──────────────────────────────────────
    def _build_form(self, p):
        # 廣告/業務資訊
        s = self._section(p, "廣告資訊")
        self._entry(s, "no", "編號(#)", default="0", width=10)
        self._chip_single(s, "case_type", "案件類型", ["一般件", "社會住宅"], default="一般件")
        self._entry(s, "agent", "業務", default="薛力瑜")
        self._entry(s, "phone", "電話", default="0912877583")
        self._entry(s, "line_id", "LINE ID", default="gerla1001259")
        self._entry(s, "want_note", "想看註記", default="")

        # A 物件資訊
        s = self._section(p, "A. 物件資訊")
        self._entry(s, "addr", "物件地址", default="")
        self._entry(s, "community", "社區")
        rf = self._row(s)
        ttk.Label(rf, text="樓層", width=12, anchor="e").pack(side="left")
        self.vars["floor"] = tk.StringVar()
        ttk.Entry(rf, textvariable=self.vars["floor"], width=6).pack(side="left")
        ttk.Label(rf, text="F  /  總樓層").pack(side="left", padx=2)
        self.vars["total_floor"] = tk.StringVar()
        ttk.Entry(rf, textvariable=self.vars["total_floor"], width=6).pack(side="left")
        ttk.Label(rf, text="F").pack(side="left", padx=2)

        rf = self._row(s)
        ttk.Label(rf, text="租金 $", width=12, anchor="e").pack(side="left")
        self.vars["rent"] = tk.StringVar()
        ttk.Entry(rf, textvariable=self.vars["rent"], width=10).pack(side="left")
        self.vars["mgmt_fee_inc"] = tk.StringVar(value="含管理費")
        self._single_chip(rf, self.vars["mgmt_fee_inc"], "含管理費")
        self._single_chip(rf, self.vars["mgmt_fee_inc"], "不含")
        ttk.Label(rf, text="管理費 $").pack(side="left", padx=2)
        self.vars["mgmt_fee"] = tk.StringVar()
        ttk.Entry(rf, textvariable=self.vars["mgmt_fee"], width=8).pack(side="left")

        self._chip_single(s, "building", "建物型態", self.BUILDING_TYPES)

        rf = self._row(s)
        ttk.Label(rf, text="格局", width=12, anchor="e").pack(side="left")
        for k, suffix in [("room", "房"), ("hall", "廳"), ("bath", "衛"), ("balcony", "陽台")]:
            self.vars[k] = tk.StringVar()
            ttk.Entry(rf, textvariable=self.vars[k], width=4).pack(side="left")
            ttk.Label(rf, text=suffix).pack(side="left", padx=(0, 6))

        self._entry(s, "ping", "坪數(約)", width=10)

        # B 物件內容
        s = self._section(p, "B. 物件內容")

        # 機車位：有/無，選「有」自動展開詳細輸入欄
        mrow = self._row(s)
        ttk.Label(mrow, text="機車位", width=12, anchor="e").pack(side="left")
        self.vars["moto"] = tk.StringVar(value="無")
        self.vars["moto_detail"] = tk.StringVar()
        moto_box = ttk.Frame(mrow)
        ttk.Label(moto_box, text="詳細：").pack(side="left")
        ttk.Entry(moto_box, textvariable=self.vars["moto_detail"], width=22).pack(side="left")

        def moto_change():
            if self.vars["moto"].get() == "有":
                moto_box.pack(side="left", padx=8)
            else:
                moto_box.pack_forget()

        for opt in ["有", "無"]:
            self._single_chip(mrow, self.vars["moto"], opt, moto_change)
        moto_change()

        # 汽車位：有/無，選「有」自動展開（坡道機械／坡道平面 + 詳細）
        crow = self._row(s)
        ttk.Label(crow, text="汽車位", width=12, anchor="e").pack(side="left")
        self.vars["car"] = tk.StringVar(value="無")
        self.vars["car_type"] = tk.StringVar()
        self.vars["car_detail"] = tk.StringVar()
        car_box = ttk.Frame(crow)
        for opt in ["坡道機械", "坡道平面"]:
            self._single_chip(car_box, self.vars["car_type"], opt)
        ttk.Label(car_box, text="詳細：").pack(side="left", padx=(6, 0))
        ttk.Entry(car_box, textvariable=self.vars["car_detail"], width=18).pack(side="left")

        def car_change():
            if self.vars["car"].get() == "有":
                car_box.pack(side="left", padx=8)
            else:
                car_box.pack_forget()

        for opt in ["有", "無"]:
            self._single_chip(crow, self.vars["car"], opt, car_change)
        car_change()

        self._entry(s, "water", "水費", default="台水")
        self._entry(s, "elec", "電費", default="台電")
        self._chip_single(s, "pet", "寵物", ["可", "不可"])
        self._entry(s, "pet_note", "寵物條款")
        self._chip_single(s, "cook", "開伙", ["可", "不可"])
        self._chip_single(s, "cook_fire", "明火/暗火", ["明火", "暗火"])

        # C 物件設備
        s = self._section(p, "C. 物件設備（黃色=有，可自訂增刪）")
        self._checks(s, "furniture", "傢俱", self.FURNITURE)
        self._checks(s, "equipment", "設備", self.EQUIPMENT)
        self._checks(s, "other", "其他", self.OTHER)

        # D 案件備註
        s = self._section(p, "D. 案件備註")
        self._entry(s, "see_date", "可看房日期", default="隨時可看")
        self._entry(s, "special", "特別備註")

        # E 創意
        s = self._section(p, "E. 創意")
        self._entry(s, "title", "標題")
        rf = self._row(s)
        ttk.Label(rf, text="文案", width=12, anchor="ne").pack(side="left")
        self.vars["copy"] = tk.Text(rf, height=4, width=46, wrap="word")
        self.vars["copy"].pack(side="left", fill="x", expand=True)

    # ── 結果區建立 ────────────────────────────────────
    def _build_result(self, p):
        bar = ttk.Frame(p)
        bar.pack(fill="x", padx=6, pady=4)
        ttk.Button(bar, text="產生 LINE 文字", command=self.generate).pack(side="left")
        ttk.Button(bar, text="複製", command=self.copy).pack(side="left", padx=6)
        ttk.Button(bar, text="清空表單", command=self.clear).pack(side="left")
        self.status = ttk.Label(bar, text="")
        self.status.pack(side="left", padx=10)

        self.output = tk.Text(p, wrap="word", height=12)
        self.output.pack(fill="both", expand=True, padx=6, pady=4)

    # ── 取值小工具 ────────────────────────────────────
    def _g(self, key):
        v = self.vars.get(key)
        if isinstance(v, tk.StringVar):
            return v.get().strip()
        return ""

    def _checked(self, key):
        d = self.vars.get(key, {})
        return [opt for opt, bv in d.items() if bv.get()]

    # ── 產生文案 ──────────────────────────────────────
    def generate(self):
        L = []
        no = self._g("no")
        L.append(f"🌏廣告資訊#{no}🌏" if no else "🌏廣告資訊🌏")
        L.append("")
        if self._g("case_type"):
            L.append(f"案件類型：{self._g('case_type')}")
        if self._g("agent"):
            L.append(f"業務：{self._g('agent')}")
        if self._g("phone"):
            L.append(f"電話：{self._g('phone')}")
        if self._g("line_id"):
            note = self._g("want_note")
            line = f"LINE ID：{self._g('line_id')}"
            if note:
                line += f"（加LINE告知想看「{note}」）"
            L.append(line)
        L.append("------------------------------")

        # A
        L.append("［A.物件資訊］")
        addr = self._g("addr")
        community = self._g("community")
        if community:
            addr += f"（社區：{community}）"
        if addr:
            L.append(f"1.物件地址：{addr}")
        floor, total = self._g("floor"), self._g("total_floor")
        if floor or total:
            L.append(f"2.樓層：{floor}F／總樓層{total}F")
        rent = self._g("rent")
        if rent:
            inc = self._g("mgmt_fee_inc")
            fee = self._g("mgmt_fee")
            if inc == "含管理費":
                L.append(f"3.租金：＄{rent}（含管理費）")
            else:
                line = f"3.租金：＄{rent}（不含管理費"
                line += f"＄{fee}）" if fee else "）"
                L.append(line)
        if self._g("building"):
            L.append(f"4.建物型態：{self._g('building')}")
        layout = "".join([
            f"{self._g('room')}房" if self._g("room") else "",
            f"{self._g('hall')}廳" if self._g("hall") else "",
            f"{self._g('bath')}衛" if self._g("bath") else "",
            f"{self._g('balcony')}陽台" if self._g("balcony") else "",
        ])
        if layout:
            L.append(f"5.格局：{layout}")
        if self._g("ping"):
            L.append(f"6.坪數：約{self._g('ping')}坪")
        L.append("")

        # B
        L.append("［B.物件內容］")
        if self._g("moto") == "有":
            md = self._g("moto_detail")
            L.append(f"1.機車位：{md if md else '有'}")
        else:
            L.append("1.機車位：無")
        if self._g("car") == "有":
            val = (self._g("car_type") + self._g("car_detail")).strip() or "有"
            L.append(f"2.汽車位：{val}")
        else:
            L.append("2.汽車位：無")
        if self._g("water"):
            L.append(f"3.水費：{self._g('water')}")
        if self._g("elec"):
            L.append(f"4.電費：{self._g('elec')}")
        if self._g("pet"):
            line = f"5.寵物：{self._g('pet')}寵物"
            if self._g("pet_note"):
                line += f"（{self._g('pet_note')}）"
            L.append(line)
        if self._g("cook"):
            line = f"6.開伙：{self._g('cook')}開伙"
            if self._g("cook_fire"):
                line += f"（{self._g('cook_fire')}）"
            L.append(line)
        L.append("")

        # C
        fu = "／".join(self._checked("furniture"))
        eq = "／".join(self._checked("equipment"))
        ot = "／".join(self._checked("other"))
        if fu or eq or ot:
            L.append("［C.物件設備］")
            n = 1
            if fu:
                L.append(f"{n}.傢俱：{fu}"); n += 1
            if eq:
                L.append(f"{n}.設備：{eq}"); n += 1
            if ot:
                L.append(f"{n}.其他：{ot}"); n += 1
            L.append("")

        # D
        see = self._g("see_date")
        special = self._g("special")
        if see or special:
            L.append("［D.案件備註］")
            n = 1
            if see:
                L.append(f"{n}.可看房日期：{see}"); n += 1
            if special:
                L.append(f"{n}.特別備註：{special}"); n += 1
            L.append("")

        # E
        title = self._g("title")
        copy_text = self.vars["copy"].get("1.0", "end").strip()
        if title or copy_text:
            L.append("────────────")
            if title:
                L.append(f"【{title}】")
            if copy_text:
                L.append(copy_text)

        text = "\n".join(L).rstrip()
        self.output.delete("1.0", "end")
        self.output.insert("1.0", text)
        self.status.config(text="已產生 ✔")

    # ── 複製 ──────────────────────────────────────────
    def copy(self):
        text = self.output.get("1.0", "end").strip()
        if not text:
            self.generate()
            text = self.output.get("1.0", "end").strip()
        if not text:
            messagebox.showinfo("提示", "目前沒有可複製的內容")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update()  # 確保剪貼簿在視窗關閉後仍保留
        self.status.config(text="已複製到剪貼簿 ✔")

    # ── 清空 ──────────────────────────────────────────
    def clear(self):
        if not messagebox.askyesno("確認", "確定要清空所有欄位？"):
            return
        for key, v in self.vars.items():
            if isinstance(v, tk.StringVar):
                v.set("")
            elif isinstance(v, dict):
                for bv in v.values():
                    bv.set(False)
            elif isinstance(v, tk.Text):
                v.delete("1.0", "end")
        self.output.delete("1.0", "end")
        self.status.config(text="已清空")


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("clam")
    except tk.TclError:
        pass
    RentAdApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
