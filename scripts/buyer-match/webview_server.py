#!/usr/bin/env python3
"""買方配案結果看板：本機網頁（http://localhost:5001），開著就能看＋複製。

只讀 output/ 和 manifest.json，不碰 Chrome、不碰 i智慧/房地，跟查詢流程完全分開跑。

**版面不在這支**（2026-08-05 整併）：每次請求都現叫 `build_static_view.render()`
產生跟桌面 `配案看板.html`、手機看板同一套的 HTML。以前這裡自己維護一份條列式版面，
結果改了那邊、這邊沒跟著改，使用者看到的還是舊樣子。以後改版面只要改
`build_static_view.py` 一個地方，三個入口一起變。
重新整理瀏覽器＝重新讀一次 output/，資料一定是當下最新的。

用法：
    python webview_server.py            # 預設 0.0.0.0:5001
    python webview_server.py --port 5002

⚠️ 只在區網內用（沒有帳密保護）。這份資料含真實客戶姓名/需求，
不要把這個 port 對外開放（路由器連接埠轉發／DDNS 之類）。
（門市的手機 WiFi 跟電腦有線網被隔開，手機連不到這個 port——
　手機要看是走另外發布的看板，見 README。）
"""

from __future__ import annotations

import argparse
import traceback
from pathlib import Path

from flask import Flask, Response

import build_static_view

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"

app = Flask(__name__)


@app.get("/")
def index():
    """每次開／重新整理都重產一次，看到的一定是 output/ 當下的內容。"""
    try:
        return Response(build_static_view.render("standalone"), mimetype="text/html")
    except Exception:
        traceback.print_exc()
        return Response(
            "<meta charset=utf-8><h2>看板產生失敗</h2>"
            "<p>通常是 output/ 或 manifest.json 有壞掉的檔案，看啟動這支程式的視窗有紅字。</p>"
            f"<pre>{traceback.format_exc()}</pre>",
            status=500, mimetype="text/html")


def main() -> None:
    ap = argparse.ArgumentParser(description="買方配案結果看板（本機網頁）")
    ap.add_argument("--port", type=int, default=5001)
    ap.add_argument("--host", default="0.0.0.0", help="預設 0.0.0.0 讓同區網連得到；只想自己電腦看就設 127.0.0.1")
    args = ap.parse_args()
    print(f"[INFO] 買方配案看板啟動：http://localhost:{args.port}（版面來自 build_static_view.py）")
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
