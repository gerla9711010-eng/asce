"""CDP Chrome（port 9223）的啟動／偵測——房地登入態要靠真的、看得到的 Chrome 視窗
手動登入過一次，Playwright 自己 launch 的無痕瀏覽器沒有這份登入態。

⚠️ 2026-08-14 拿掉 i智慧 那條主流程後，這支原本是從 `buyer_match.py`（已刪除）借
CDP_PORT／ISMART_SEARCH_URL，現在改成自己帶常數、只開房地——不用再管 i智慧 登入。
舊版邏輯／i智慧 的部分見 `git show 8fb431cff99ccd55081c685c6d29213cbd87c541^:scripts/buyer-match/chrome_cdp.py`。
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

SCRIPT_DIR = Path(__file__).resolve().parent

CDP_PORT = 9223
CDP_URL = f"http://localhost:{CDP_PORT}"
_CDP_VERSION_URL = f"{CDP_URL}/json/version"
CDP_TIMEOUT_SEC = 1.5

CHROME_EXE_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

FOUNDI_URL = "https://agent.foundi.info/tool/property/map"


def profile_dir() -> Path:
    """CDP Chrome 的 user-data-dir。

    ⚠️ **絕對不要放在工具資料夾裡**（桌面那份在 OneDrive 底下）。2026-07-30 查出來：
    profile 放在 `桌面\\工具\\買方配案\\chrome_profile` 時，OneDrive 會同步整個 Chrome
    profile（實測 5943 個檔、4.75 GB），連 `Default\\Network\\Cookies` 都被變成雲端
    佔位檔（ReparsePoint）。Chrome 關著的時候 OneDrive 只要把它變成「線上檔案」，
    下次開起來就等於被登出——這很可能就是「莫名其妙被登出」的真兇（同一個坑在
    KEIS 的 CSV 上踩過一次，見 scripts/keis 的 README）。

    預設放 `%LOCALAPPDATA%\\buyer-match-chrome`（不會被雲端同步、不用管理員權限）。
    要改位置設環境變數 `BUYER_MATCH_PROFILE_DIR`。
    """
    override = os.environ.get("BUYER_MATCH_PROFILE_DIR")
    if override:
        return Path(override)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "buyer-match-chrome"
    return SCRIPT_DIR / "chrome_profile"  # 最後退路（非 Windows / 環境變數壞掉）


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
        req = urllib.request.Request(_CDP_VERSION_URL, headers={"User-Agent": "buyer-match"})
        with urllib.request.urlopen(req, timeout=CDP_TIMEOUT_SEC) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return bool(data.get("Browser"))
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError):
        return False


def launch_chrome() -> tuple[bool, str]:
    """用專屬 profile 開一個帶 CDP port 的 Chrome，開好直接進房地物件地圖頁。

    ⚠️ 如果系統上已經有別的 chrome.exe 開著（同一個 user），Windows 的 ProcessSingleton
    會把這次啟動併進既有那個 process，9223 就不會生效——這是舊版 `open_real_chrome.bat`
    早就寫在警語裡的老問題，排程跑的時候一樣適用。
    """
    exe = find_chrome_exe()
    if not exe:
        return False, "找不到 chrome.exe，請確認 Chrome 有裝在預設路徑"
    args = [
        exe,
        f"--remote-debugging-port={CDP_PORT}",
        "--remote-allow-origins=*",
        f"--user-data-dir={profile_dir()}",
        FOUNDI_URL,
    ]
    try:
        subprocess.Popen(args, creationflags=_no_window_flags())
        return True, "Chrome 啟動中..."
    except Exception as e:
        return False, f"啟動失敗：{e}"


def ensure_cdp(timeout_sec: int = 60) -> tuple[bool, str]:
    """給無人值守用：CDP 沒開就自己開一個，等到 port 活過來為止。
    回傳 (成功與否, 說明)。已經活著就直接回 True，不會重開。"""
    if cdp_alive():
        return True, "CDP Chrome 已在執行"
    ok, msg = launch_chrome()
    if not ok:
        return False, msg
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        time.sleep(2)
        if cdp_alive():
            return True, "已自動啟動 CDP Chrome"
    return False, (
        f"啟動 Chrome 後 {timeout_sec} 秒內連不到 port {CDP_PORT}"
        "（多半是已經有別的 Chrome 開著，把 CDP 參數吃掉了）"
    )
