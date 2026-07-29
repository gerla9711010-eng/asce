"""CDP Chrome（port 9223）的啟動／偵測，GUI 跟排程都用這一份。

原本這幾支只寫在 gui_main.py 裡，但 daily_run.py（每天 08:10 排程）也要用，
而排程跑的是無介面環境，不該為了兩個函式去 import tkinter——所以抽出來放這裡，
gui_main 改成從這裡 import（名字沒變，GUI 那邊的呼叫方式完全不動）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import buyer_match

SCRIPT_DIR = Path(__file__).resolve().parent
CDP_URL = f"http://localhost:{buyer_match.CDP_PORT}/json/version"
CDP_TIMEOUT_SEC = 1.5

CHROME_EXE_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

FOUNDI_URL = "https://agent.foundi.info/tool/property/map"


def find_chrome_exe():
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
        req = urllib.request.Request(CDP_URL, headers={"User-Agent": "buyer-match"})
        with urllib.request.urlopen(req, timeout=CDP_TIMEOUT_SEC) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return bool(data.get("Browser"))
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError):
        return False


def launch_chrome(with_foundi: bool = False) -> tuple[bool, str]:
    """用專屬 profile 開一個帶 CDP port 的 Chrome。

    ⚠️ 如果系統上已經有別的 chrome.exe 開著（同一個 user），Windows 的 ProcessSingleton
    會把這次啟動併進既有那個 process，9223 就不會生效——這是 open_real_chrome.bat 早就
    寫在警語裡的老問題，排程跑的時候一樣適用（見 daily_run.py 的處理）。
    """
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
    if with_foundi:
        args.append(FOUNDI_URL)
    try:
        subprocess.Popen(args, creationflags=_no_window_flags())
        return True, "Chrome 啟動中..."
    except Exception as e:
        return False, f"啟動失敗：{e}"


def ensure_cdp(timeout_sec: int = 60, with_foundi: bool = True) -> tuple[bool, str]:
    """給無人值守用：CDP 沒開就自己開一個，等到 port 活過來為止。
    回傳 (成功與否, 說明)。已經活著就直接回 True，不會重開。"""
    if cdp_alive():
        return True, "CDP Chrome 已在執行"
    ok, msg = launch_chrome(with_foundi=with_foundi)
    if not ok:
        return False, msg
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        time.sleep(2)
        if cdp_alive():
            return True, "已自動啟動 CDP Chrome"
    return False, (
        f"啟動 Chrome 後 {timeout_sec} 秒內連不到 port {buyer_match.CDP_PORT}"
        "（多半是已經有別的 Chrome 開著，把 CDP 參數吃掉了）"
    )
