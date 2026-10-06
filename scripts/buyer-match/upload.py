# -*- coding: utf-8 -*-
"""把產好的買方配案頁上傳到 n8n「買方配案手機頁」，手機開 BUYER_MATCH_URL 就是最新版。

帳密在 repo 根目錄 .env（BUYER_MATCH_URL / USER / PASS），repo 是公開的所以不寫進程式。
用法：python upload.py [html路徑]   （不給就傳同資料夾的 buyer-match.html）
worker.py 跑完會自動叫 upload()；上傳失敗不影響桌面那份。
"""
import sys
from pathlib import Path

import httpx

BASE = Path(__file__).resolve().parent
ENV_FILE = BASE.parent.parent / ".env"


def load_env():
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def upload(html_path):
    """成功回網址，失敗丟例外。"""
    env = load_env()
    url, user, pw = env.get("BUYER_MATCH_URL"), env.get("BUYER_MATCH_USER"), env.get("BUYER_MATCH_PASS")
    if not (url and user and pw):
        raise RuntimeError(".env 缺 BUYER_MATCH_URL / USER / PASS")
    html = Path(html_path).read_text(encoding="utf-8")
    r = httpx.post(url + "-upload", json={"html": html}, auth=(user, pw), timeout=120)
    r.raise_for_status()
    return url


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print("已上傳：" + upload(sys.argv[1] if len(sys.argv) > 1 else BASE / "buyer-match.html"))
