"""Codex 文案服務——把 ChatGPT 訂閱額度接進 n8n 的廣告產文案節點。

為什麼需要這支
--------------
n8n 產文案原本打 Gemini 免費版，一天每個模型只有 20 次，線 A 6 班 + 線 C 6 班 + LINE 指令共用，
本來就貼著上限在跑；2026-08-10 那天還撞到 Gemini 回 503「服務忙碌」，交叉審核直接跳過。
使用者有 ChatGPT 付費訂閱，而 Codex CLI 正是吃訂閱額度（不是 API key），一天 36 次產文案
約 16 萬 tokens，對一個本來拿來審程式碼的訂閱來說不痛不癢。

為什麼是「假裝自己是 Gemini」
--------------------------
這支刻意**收 Gemini 格式的請求、回 Gemini 格式的回應**，所以 n8n 那邊只要改一個節點的 URL，
workflow 結構完全不用動——下游 `解析文案+footer` 讀的還是 `candidates[0].content.parts[0].text`。
改壞了就把 URL 改回 Gemini，一行復原。

兩層保險
--------
1. **服務內建 Gemini 退路**：codex 逾時或吐不出 JSON 時，直接改打 Gemini 回傳，n8n 無感。
   （要設 `GEMINI_API_KEY`，沒設就只是少一層保險，不影響正常運作。）
2. **守門員仍在最後把關**：這支不做任何內容檢查，產出的文案照樣要過 `數字守門員`。
   寧可讓守門員擋下，也不要在這裡自作聰明修文案。

⚠️ 這支沒開機／店裡斷網時，那一班會失敗並觸發「系統錯誤 LINE 告警」，兩小時後的下一班會再試。
   這是刻意的：寧可少發一班並且叫出來，也不要靜靜地發出沒檢查過的東西。

用法
----
    python server.py                # 前景跑，預設 127.0.0.1:8787
    python server.py --port 8787
    python server.py --self-test    # 不開服務，只跑一次 codex 確認環境正常

需要 .env（放在這個資料夾）：
    CODEX_COPY_TOKEN   n8n 呼叫時要帶的密鑰（自己隨便設一串），避免路人燒掉訂閱額度
    GEMINI_API_KEY     可選，codex 掛掉時的退路
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).parent
load_dotenv(HERE / ".env")

# ====== 可調參數 ======
CODEX_TIMEOUT = 150       # codex 單次逾時（秒）。實測一篇約 23 秒，留足重試餘裕
MAX_PROMPT_CHARS = 20000  # 超過就拒收，避免被灌爆
# =====================

TPE = timezone(timedelta(hours=8))
LOG_FILE = HERE / "logs" / "codex-copy.log"
TOKEN = os.environ.get("CODEX_COPY_TOKEN", "").strip()
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_URL = ("https://generativelanguage.googleapis.com/v1beta/models/"
              "gemini-2.5-flash-lite:generateContent")


# Windows 主控台預設 cp950，印到 emoji 就 UnicodeEncodeError。log 掛掉會把整個服務帶走，
# 所以在這裡就把 stdout/stderr 轉成 UTF-8 且遇到印不出的字改用替代字元，絕不丟例外。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def log(msg: str) -> None:
    line = f"[{datetime.now(TPE):%Y-%m-%d %H:%M:%S}] {msg}"
    try:
        print(line, flush=True)
    except (UnicodeEncodeError, OSError):
        pass  # 印不出來就算了，下面的檔案 log 才是正式紀錄
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass  # log 寫不進去不該讓服務掛掉


def extract_prompt(body: dict) -> str:
    """從 Gemini 格式的請求裡挖出 prompt 文字。"""
    parts = (body.get("contents") or [{}])[0].get("parts") or [{}]
    return str(parts[0].get("text") or "")


def find_json(text: str) -> str | None:
    """從 codex 的輸出裡撈出文案 JSON。

    codex exec 會把整個 prompt、思考過程、token 統計一起印出來，真正的答案混在中間，
    而且結尾會重複一次。從最後往前找第一個看起來像文案的 JSON 物件。
    """
    for line in reversed(text.splitlines()):
        s = line.strip()
        if s.startswith("{") and "粉專主體" in s:
            try:
                json.loads(s)
                return s
            except json.JSONDecodeError:
                continue
    # 整行找不到時，退而求其次抓花括號區塊（codex 有可能把 JSON 換行印出來）
    m = re.search(r'\{[^{}]*"粉專主體".*?\}', text, re.S)
    if m:
        try:
            json.loads(m.group(0))
            return m.group(0)
        except json.JSONDecodeError:
            return None
    return None


def call_codex(prompt: str) -> str:
    """跑 codex exec，回傳文案 JSON 字串。失敗就丟例外，交給呼叫端決定要不要走退路。"""
    proc = subprocess.run(
        ["codex", "exec", "--skip-git-repo-check"],
        input=prompt, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        timeout=CODEX_TIMEOUT, shell=(os.name == "nt"),
    )
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    found = find_json(out)
    if not found:
        raise RuntimeError(f"codex 沒吐出可解析的文案 JSON（exit={proc.returncode}）")
    return found


def call_gemini(prompt: str) -> str:
    """退路：codex 掛掉時直接打 Gemini，回傳文案 JSON 字串。"""
    if not GEMINI_KEY:
        raise RuntimeError("沒設 GEMINI_API_KEY，沒有退路可走")
    import httpx
    r = httpx.post(
        GEMINI_URL, headers={"x-goog-api-key": GEMINI_KEY},
        json={"contents": [{"parts": [{"text": prompt}]}],
              "generationConfig": {"temperature": 0.7, "maxOutputTokens": 2048,
                                   "responseMimeType": "application/json"}},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def as_gemini_response(text: str, served_by: str) -> dict:
    """包成 Gemini 的回應格式，下游 `解析文案+footer` 才讀得懂。"""
    return {
        "candidates": [{"content": {"parts": [{"text": text}], "role": "model"},
                        "finishReason": "STOP", "index": 0}],
        "modelVersion": served_by,   # 方便事後在執行紀錄裡看是誰產的
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code: int, payload: dict) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, fmt, *args):
        pass  # 關掉 stdlib 每次請求的預設噪音，我們自己 log

    def do_GET(self):
        if self.path.rstrip("/") in ("", "/health"):
            self._send(200, {"ok": True, "service": "codex-copy"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        started = time.time()
        if TOKEN and self.headers.get("X-Codex-Token", "") != TOKEN:
            log("❌ 密鑰不符，拒收")
            self._send(401, {"error": "unauthorized"})
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            self._send(400, {"error": f"bad body: {e}"})
            return

        prompt = extract_prompt(body)
        if not prompt:
            self._send(400, {"error": "contents[0].parts[0].text 是空的"})
            return
        if len(prompt) > MAX_PROMPT_CHARS:
            self._send(413, {"error": "prompt 太長"})
            return

        try:
            text = call_codex(prompt)
            log(f"✅ codex 產文案成功（{time.time() - started:.0f} 秒）")
            self._send(200, as_gemini_response(text, "codex-cli"))
            return
        except Exception as e:      # noqa: BLE001 — 任何失敗都該走退路，不能讓那一班死掉
            log(f"⚠️ codex 失敗（{e}），改走 Gemini 退路")

        try:
            text = call_gemini(prompt)
            log(f"✅ Gemini 退路成功（{time.time() - started:.0f} 秒）")
            self._send(200, as_gemini_response(text, "gemini-fallback"))
        except Exception as e:      # noqa: BLE001
            log(f"❌ 兩條路都失敗：{e}")
            # 回 5xx 讓 n8n 那班明確失敗並觸發 LINE 告警，不要靜靜地回空文案
            self._send(502, {"error": f"codex 與 Gemini 都失敗：{e}"})


# ────────────────────────────────────────────────────────────────────────────
# Cloudflare 快速通道 + 自動把網址寫回 n8n
#
# 使用者的 Cloudflare 帳號裡沒有自己的網域（只有 pages.dev），所以開不了「具名通道」那種
# 固定網址。改用不需要網域也不需要登入的「快速通道」——代價是每次重開網址都會變，
# 所以這裡自己把新網址 PATCH 回 n8n 的產文案節點，使用者不用管。
#
# ⚠️ 收工／關機時會**自動把 n8n 改回 Gemini**，這樣電腦沒開的時段廣告線照樣發得出去。
#    只有「斷電」這種來不及善後的狀況會讓 n8n 指著死掉的通道，那一班會失敗並告警。
# ────────────────────────────────────────────────────────────────────────────
GEMINI_NODE = "Gemini 產文案"
SCAN_WF = "ooctMtxcaHtGThuV"          # 廣告v3 掃描發文線
REPO_ENV = HERE.parent.parent / ".env"  # n8n 金鑰跟 n8n_sync.py 共用同一份
# n8n 的 PUT schema 只吃這些 settings（多送 binaryMode/availableInMCP 會 400）
_WF_SETTINGS_OK = {"executionOrder", "errorWorkflow", "saveDataSuccessExecution",
                   "saveDataErrorExecution", "saveManualExecutions",
                   "saveExecutionProgress", "timezone", "executionTimeout", "callerPolicy"}


def _n8n():
    import httpx
    from dotenv import dotenv_values
    v = dotenv_values(REPO_ENV)
    url, key = (v.get("N8N_URL") or "").rstrip("/"), v.get("N8N_API_KEY")
    if not url or not key:
        raise RuntimeError(f"{REPO_ENV} 裡沒有 N8N_URL / N8N_API_KEY")
    return httpx, url, {"X-N8N-API-KEY": key, "Content-Type": "application/json"}


def point_n8n_at(target_url: str | None) -> None:
    """把產文案節點指到 target_url；傳 None 代表改回 Gemini。

    改完一定要 deactivate + activate，否則排程觸發器還在跑舊版（2026-07-25 踩過）。
    """
    httpx, base, h = _n8n()
    w = httpx.get(f"{base}/api/v1/workflows/{SCAN_WF}", headers=h, timeout=30).json()
    for n in w["nodes"]:
        if n["name"] != GEMINI_NODE:
            continue
        opts = n["parameters"].setdefault("options", {})
        hdrs = n["parameters"].setdefault("headerParameters", {}).setdefault("parameters", [])
        hdrs[:] = [x for x in hdrs if x.get("name") != "X-Codex-Token"]
        if target_url:
            n["parameters"]["url"] = target_url
            opts["timeout"] = 120000          # codex 比 Gemini 慢，60 秒不夠
            if TOKEN:
                hdrs.append({"name": "X-Codex-Token", "value": TOKEN})
        else:
            n["parameters"]["url"] = GEMINI_URL
            opts["timeout"] = 60000
        break
    else:
        raise RuntimeError(f"找不到節點「{GEMINI_NODE}」")

    payload = {"name": w["name"], "nodes": w["nodes"], "connections": w["connections"],
               "settings": {k: v for k, v in (w.get("settings") or {}).items()
                            if k in _WF_SETTINGS_OK}}
    r = httpx.put(f"{base}/api/v1/workflows/{SCAN_WF}", headers=h, json=payload, timeout=60)
    r.raise_for_status()
    for act in ("deactivate", "activate"):
        httpx.post(f"{base}/api/v1/workflows/{SCAN_WF}/{act}", headers=h, timeout=60).raise_for_status()
        time.sleep(1)
    log(f"已把 n8n 產文案指向：{target_url or 'Gemini（原廠）'}")


def start_tunnel(port: int) -> tuple[subprocess.Popen, str]:
    """開一條 Cloudflare 快速通道，回傳 (行程, 對外網址)。"""
    exe = "cloudflared"
    for cand in (r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
                 r"C:\Program Files\cloudflared\cloudflared.exe"):
        if Path(cand).exists():
            exe = cand
            break
    proc = subprocess.Popen(
        [exe, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )
    deadline = time.time() + 60
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                raise RuntimeError("cloudflared 自己結束了，通道沒開起來")
            continue
        m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
        if m:
            return proc, m.group(0)
    proc.kill()
    raise RuntimeError("等了 60 秒還拿不到通道網址")


def self_test() -> int:
    log("自我測試：跑一次 codex…")
    try:
        out = call_codex('只回傳這個 JSON，不要多餘說明：{"粉專主體":"測試","社團主體":"測試"}')
        log(f"✅ codex 正常，回傳：{out[:80]}")
        return 0
    except Exception as e:          # noqa: BLE001
        log(f"❌ codex 不能用：{e}")
        log("   檢查：1) codex --version 有沒有反應 2) 是否已登入 ChatGPT 訂閱")
        return 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--tunnel", action="store_true",
                    help="順便開 Cloudflare 通道並自動把網址寫回 n8n（正式跑就用這個）")
    ap.add_argument("--revert", action="store_true",
                    help="不開服務，只把 n8n 產文案改回 Gemini")
    args = ap.parse_args()

    if args.self_test:
        return self_test()
    if args.revert:
        point_n8n_at(None)
        return 0

    if not TOKEN:
        log("⚠️ 沒設 CODEX_COPY_TOKEN，任何人打得到這個網址就能燒你的訂閱額度")

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    import threading
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log(f"服務已啟動：http://{args.host}:{args.port}")

    tunnel = None
    if args.tunnel:
        # pythonw 沒有主控台，關機時 finally 不一定跑得到。多掛一層 atexit 與 SIGTERM，
        # 盡量讓 n8n 在這台電腦離線前改回 Gemini。真的來不及（斷電）就靠開機後重新註冊，
        # 急著救的話跑 `python server.py --revert`。
        import atexit
        import signal
        _done = {"v": False}

        def _restore(*_a):
            if _done["v"]:
                return
            _done["v"] = True
            try:
                point_n8n_at(None)
            except Exception as e:      # noqa: BLE001
                log(f"⚠️ 沒能把 n8n 改回 Gemini，請手動跑 `python server.py --revert`：{e}")

        atexit.register(_restore)
        for _sig in (getattr(signal, "SIGTERM", None), getattr(signal, "SIGBREAK", None)):
            if _sig is not None:
                try:
                    signal.signal(_sig, lambda *a: (_restore(), sys.exit(0)))
                except (ValueError, OSError):
                    pass

    try:
        if args.tunnel:
            tunnel, public = start_tunnel(args.port)
            log(f"通道已開：{public}")
            point_n8n_at(public)
        log("運作中（Ctrl+C 停止）")
        backoff = 10
        while True:
            time.sleep(5)
            if not (tunnel and tunnel.poll() is not None):
                continue
            # 門市每晚 00:00~07:22 固定斷網，通道一定會掉。這裡不能讓重連失敗把服務帶走——
            # 廣告線 09:00 才開始跑，睡一下重試就好，等網路回來自然接上。
            log("⚠️ 通道掉了，重開並重新註冊")
            try:
                tunnel, public = start_tunnel(args.port)
                log(f"通道已開：{public}")
                point_n8n_at(public)
                backoff = 10
            except Exception as e:      # noqa: BLE001
                tunnel = None
                log(f"⚠️ 重開失敗（{e}），{backoff} 秒後再試")
                time.sleep(backoff)
                backoff = min(backoff * 2, 300)
    except KeyboardInterrupt:
        log("收到中斷，收工")
    finally:
        if args.tunnel:
            _restore()          # 已做過就不會重複做（_done 旗標）
        if tunnel:
            tunnel.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
