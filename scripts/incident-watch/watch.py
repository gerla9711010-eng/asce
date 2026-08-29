"""每 15 分鐘被 /loop 呼叫一次：查 n8n 有沒有新的失敗執行，比對已知案例，符合就自動修+回報。

不符合已知案例的失敗完全不動——n8n 自己的失敗告警（Telegram）照樣會發，這支只負責
「已經抓到根因、修法固定」的那幾種，省得每次都要人回來貼錯誤訊息。

用法：python watch.py
狀態存在 state.json（記每個 workflow 查到哪個 execution id，避免同一筆重複處理）。
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import httpx
from dotenv import dotenv_values

HERE = Path(__file__).parent
REPO = HERE.parent.parent
STATE_FILE = HERE / "state.json"

CODEX_COPY_DIR = REPO / "scripts" / "codex-copy"
sys.path.insert(0, str(CODEX_COPY_DIR))
import server as codex_copy  # noqa: E402  — 借用它的 SCAN_WF/GEMINI_NODE/probe_alive/point_n8n_at

KEIS_ENV = dotenv_values(REPO / "scripts" / "keis" / ".env")
TELEGRAM_TOKEN = KEIS_ENV.get("KEIS_TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = KEIS_ENV.get("KEIS_TELEGRAM_CHAT_ID", "")


def n8n():
    httpx_mod, base, h = codex_copy._n8n()
    return base, h


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"last_seen_id": {}}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def telegram(text: str) -> None:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ 沒有 Telegram token/chat id，只印在這裡：\n" + text)
        return
    try:
        httpx.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text},
            timeout=15,
        )
    except Exception as e:      # noqa: BLE001
        print(f"⚠️ Telegram 發送失敗：{e}")


def fetch_new_error_executions(base: str, h: dict, workflow_id: str, since_id: int) -> list[dict]:
    r = httpx.get(
        f"{base}/api/v1/executions",
        headers=h,
        params={"workflowId": workflow_id, "status": "error", "limit": 20},
        timeout=60,
    )
    r.raise_for_status()
    out = []
    for e in r.json().get("data", []):
        try:
            eid = int(e["id"])
        except (KeyError, ValueError):
            continue
        if eid > since_id:
            out.append(e)
    return out


def fetch_execution_detail(base: str, h: dict, execution_id: str) -> dict:
    r = httpx.get(
        f"{base}/api/v1/executions/{execution_id}",
        headers=h,
        params={"includeData": "true"},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def extract_error_text(detail: dict) -> str:
    """從 execution detail 挖出失敗節點的錯誤訊息，格式不穩定所以放寬找。"""
    try:
        run_data = detail["data"]["resultData"]["runData"]
    except (KeyError, TypeError):
        return ""
    chunks = []
    for node_name, runs in run_data.items():
        for run in runs:
            err = run.get("error")
            if err:
                msg = err.get("message") or err.get("description") or str(err)
                chunks.append(f"{node_name}: {msg}")
    top_err = detail.get("data", {}).get("resultData", {}).get("error", {})
    if top_err:
        chunks.append(f"(top-level) {top_err.get('message', '')}")
    return "\n".join(chunks)


def is_codex_tunnel_dead(error_text: str) -> bool:
    if codex_copy.GEMINI_NODE not in error_text:
        return False
    signals = ["incorrect host", "connection cannot be established", "ECONNREFUSED", "ENOTFOUND"]
    return any(s.lower() in error_text.lower() for s in signals)


def find_codex_copy_pid() -> str | None:
    out = subprocess.run(
        ["wmic", "process", "where", "name='pythonw.exe'", "get", "ProcessId,CommandLine", "/format:csv"],
        capture_output=True, text=True, timeout=30,
    ).stdout
    for line in out.splitlines():
        if "codex-copy" in line and "server.py" in line:
            parts = [p.strip() for p in line.split(",")]
            if parts and parts[-1].isdigit():
                return parts[-1]
    return None


def fix_codex_tunnel_dead() -> str:
    """已知案例的固定修法：探測現在的通道，死了就重開服務；活著就不動。回傳給 Telegram 的說明。"""
    base, h = n8n()
    w = httpx.get(f"{base}/api/v1/workflows/{codex_copy.SCAN_WF}", headers=h, timeout=30).json()
    current_url = ""
    for n in w.get("nodes", []):
        if n["name"] == codex_copy.GEMINI_NODE:
            current_url = n["parameters"].get("url", "")
            break

    if current_url.startswith("https://") and "trycloudflare.com" in current_url:
        if codex_copy.probe_alive(current_url):
            return f"通道 {current_url} 現在探測活著，判斷已經自己恢復，沒有重開服務。"

    pid = find_codex_copy_pid()
    if pid:
        subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True, text=True, timeout=15)
        time.sleep(1)

    pythonw = sys.executable.replace("python.exe", "pythonw.exe")
    subprocess.Popen(
        [pythonw, str(CODEX_COPY_DIR / "server.py"), "--tunnel", "--port", "8787"],
        cwd=str(CODEX_COPY_DIR),
    )

    for _ in range(30):
        time.sleep(2)
        log_path = CODEX_COPY_DIR / "logs" / "codex-copy.log"
        if log_path.exists():
            tail = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-5:]
            for line in tail:
                if "已把 n8n 產文案指向" in line:
                    new_url = line.split("：")[-1].strip()
                    ok = codex_copy.probe_alive(new_url)
                    return (
                        f"通道死了（原 PID {pid or '找不到，可能行程已經不在'}），已重開服務，"
                        f"新網址 {new_url}，驗活{'成功' if ok else '失敗，需要人工再看一次'}。"
                    )
    return "重開服務已觸發，但 30 秒內沒等到新網址寫回 n8n 的紀錄，建議人工確認一次。"


KNOWN_INCIDENTS = [
    {
        "id": "codex-tunnel-dead",
        "match": is_codex_tunnel_dead,
        "fix": fix_codex_tunnel_dead,
    },
]


def sync_and_commit(summary: str) -> None:
    r = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "n8n_sync.py")],
        cwd=str(REPO), capture_output=True, text=True, timeout=120,
    )
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=str(REPO), capture_output=True, text=True, timeout=30,
    ).stdout
    if not status.strip():
        return
    subprocess.run(["git", "add", "-A", "--", "docs/n8n-live.md", "workflows/"], cwd=str(REPO), timeout=30)
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"], cwd=str(REPO), capture_output=True, text=True, timeout=30,
    ).stdout
    if not staged.strip():
        return
    subprocess.run(
        ["git", "commit", "-m", f"[自動修復] {summary}"],
        cwd=str(REPO), timeout=30,
    )


def run_once() -> None:
    state = load_state()
    base, h = n8n()
    wf_id = codex_copy.SCAN_WF
    since = state["last_seen_id"].get(wf_id, 0)

    try:
        new_errors = fetch_new_error_executions(base, h, wf_id, since)
    except Exception as e:      # noqa: BLE001
        print(f"查 n8n 執行紀錄失敗，這輪跳過：{e}")
        return

    if not new_errors:
        return

    max_id = since
    for e in sorted(new_errors, key=lambda x: int(x["id"])):
        eid = int(e["id"])
        max_id = max(max_id, eid)
        try:
            detail = fetch_execution_detail(base, h, str(eid))
        except Exception as ex:      # noqa: BLE001
            print(f"execution {eid} 撈細節失敗：{ex}")
            continue
        error_text = extract_error_text(detail)

        matched = None
        for incident in KNOWN_INCIDENTS:
            if incident["match"](error_text):
                matched = incident
                break

        if not matched:
            continue  # 交給現有的失敗告警，這支不重複發

        try:
            result = matched["fix"]()
        except Exception as ex:      # noqa: BLE001
            result = f"自動修復腳本本身出錯：{ex}"

        report = (
            f"🔧 自動修復報告\n"
            f"案例：{matched['id']}\n"
            f"execution：{eid}\n"
            f"處理結果：{result}"
        )
        telegram(report)
        sync_and_commit(f"{matched['id']}（execution {eid}）")

    state["last_seen_id"][wf_id] = max_id
    save_state(state)


if __name__ == "__main__":
    run_once()
