# -*- coding: utf-8 -*-
"""產買方配案頁，發到 Cloudflare Pages，手機開 SITE_URL 就是最新版。

為什麼不用 n8n（10-07 試過）：n8n 回 HTML 一律加 CSP sandbox，頁面變 null origin，
官網 frame-ancestors 拒絕嵌入 → 頁內預覽框「拒絕連線」。

網址是公開的。10-07 原本只發 --mask 打碼版，使用者看過名單（約 20 位是真實全名）後決定全名公開、風險自負；
要恢復打碼就在下面 build_page.js 那行加回 "--mask"。
獨立的 Pages 專案，不要發到 yc-tools：pages deploy 會整站覆蓋，/yc-calc/、/kh-market/ 會被洗掉。
第一次用要先 `npx wrangler login`（瀏覽器授權一次）。

用法：python upload.py        worker.py 跑完也會自動叫 upload()；失敗不影響桌面那份。
"""
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
DIST = BASE / "dist"
PROJECT = "yc-buyer-match"
SITE_URL = f"https://{PROJECT}.pages.dev/"


def run(cmd, timeout):
    r = subprocess.run(cmd, cwd=str(BASE), capture_output=True, text=True, timeout=timeout,
                       encoding="utf-8", errors="replace", shell=(sys.platform == "win32"))
    if r.returncode != 0:
        raise RuntimeError(((r.stderr or "") + (r.stdout or ""))[-400:])
    return r.stdout


def upload(_html_path=None):
    """成功回網址，失敗丟例外。_html_path 只為了跟舊呼叫相容，一律從 data.json 重產。"""
    DIST.mkdir(exist_ok=True)
    run(["node", "build_page.js", "data.json", str(DIST / "index.html")], 60)
    run(["npx", "--yes", "wrangler", "pages", "deploy", str(DIST),
         "--project-name", PROJECT, "--branch", "main", "--commit-dirty=true"], 300)
    return SITE_URL


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print("已發布：" + upload())
