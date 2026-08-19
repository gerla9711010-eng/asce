# -*- coding: utf-8 -*-
"""直推 Telegram 的最小工具，給「n8n 掛掉也要叫得出來」的告警用。

為什麼不用 LINE：LINE 官方帳號免費方案一個月只有 200 則主動推播，那 200 則要留給
客戶群發。Telegram 機器人推播沒有則數上限，系統告警一律走這裡。

環境變數（放 scripts/keis/.env，那個檔在 .gitignore 裡）：
    KEIS_TELEGRAM_TOKEN    BotFather 給的機器人 token
    KEIS_TELEGRAM_CHAT_ID  收訊人的 chat id（跟機器人講過話才拿得到）
"""
import os

import httpx

TOKEN = os.environ.get("KEIS_TELEGRAM_TOKEN", "").strip()
CHAT_ID = os.environ.get("KEIS_TELEGRAM_CHAT_ID", "").strip()


def enabled() -> bool:
    return bool(TOKEN and CHAT_ID)


def send(text: str, timeout: float = 10) -> bool:
    """送一則純文字。回傳有沒有真的送出去——呼叫端要看回傳值，不要假設成功。"""
    if not enabled():
        return False
    try:
        r = httpx.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text[:4000]},
            timeout=timeout,
        )
        return r.status_code < 400
    except Exception:
        return False
