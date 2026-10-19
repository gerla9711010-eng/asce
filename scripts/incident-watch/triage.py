"""被容錯吞掉的失敗 → 先讓無人值守的 Claude 查一輪，沒事就不打擾使用者。

流程（watch.py 每 15 分鐘呼叫 scan_and_triage）：
 1. 掃 n8n 全部「status=success」的新執行，找出節點輸出帶 error 物件的（＝被吞掉的失敗）
 2. 叫 `claude -p`（唯讀：只能 Read 和跑 `triage.py --show`）照固定步驟查：
    執行紀錄、貼文/Notion/KEIS 三邊有沒有對上、貼文內容對原始資料
 3. 結論 ok → 只記進「每日摘要」，21:00 以後發一則；
    結論 needs_user、或 Claude 掛了/逾時/回不出 JSON → 立刻 Telegram 給使用者（絕不吞掉）

安全界線：這個 Claude 不能改 workflow、不能發文/刪文、不能 git。要動手的一律歸 needs_user。
計費：走本機 claude.ai 訂閱登入；偵測到 ANTHROPIC_API_KEY 就不叫 Claude（會變按量計費），直接原樣轉給使用者。

單獨用：
  python triage.py --show <execution_id>   # 印出該執行的精簡摘要（給 Claude 讀，也給人看）
  python triage.py --dry <execution_id>    # 只對指定執行跑一次完整 triage、不發 Telegram、不寫狀態
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import httpx

HERE = Path(__file__).parent
REPO = HERE.parent.parent
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

CLAUDE_TIMEOUT = 300          # 秒；一輪調查正常 1～3 分鐘
MAX_PER_SCAN = 3              # 一輪最多叫 3 次 Claude，其餘原樣轉給使用者（避免異常暴增燒額度）
DIGEST_HOUR = 21              # 21:00 之後才發每日摘要
FLOOD_SIGNS = ("_reviewVerdict",)


# ---------------------------------------------------------------- n8n 資料
def find_swallowed(detail: dict) -> list[dict]:
    """與 n8n『靜默失敗巡邏』同一個判準：節點輸出 json 帶 error 物件。"""
    out = []
    run_data = ((detail.get("data") or {}).get("resultData") or {}).get("runData") or {}
    for node, runs in run_data.items():
        for run in runs:
            for branch in (run.get("data") or {}).get("main") or []:
                for it in branch or []:
                    j = (it or {}).get("json")
                    if isinstance(j, dict) and isinstance(j.get("error"), dict):
                        msg = str(j["error"].get("message") or json.dumps(j["error"], ensure_ascii=False))
                        out.append({"node": node, "msg": msg[:200]})
    return out


def wf_name(detail: dict) -> str:
    return (detail.get("workflowData") or {}).get("name") or str(detail.get("workflowId") or "未知流程")


SECRET_RE = re.compile(
    r'("[^"]*(?:token|password|passwd|secret|api[_-]?key|authorization|cookie)[^"]*"\s*:\s*)"[^"]*"', re.I)
JWT_RE = re.compile(r"eyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{8,}")


def redact(text: str) -> str:
    """執行紀錄裡會有 KEIS 登入 token 等憑證，不能讓它進 Claude 的對話或任何 log。"""
    return JWT_RE.sub("<jwt>", SECRET_RE.sub(lambda m: m.group(1) + '"<redacted>"', text))


def summarize(detail: dict, limit: int = 30000) -> str:
    """把一筆執行壓成 Claude 讀得完的文字。越靠後的節點（發文、Notion、KEIS）越重要，
    給較多字；前面撈列表之類的大包資料只留開頭。有錯誤的節點一律完整保留。"""
    lines = [f"執行 #{detail.get('id')}｜{wf_name(detail)}｜status={detail.get('status')}｜"
             f"{detail.get('startedAt')} → {detail.get('stoppedAt')}"]
    run_data = ((detail.get("data") or {}).get("resultData") or {}).get("runData") or {}
    names = list(run_data)
    tail = set(names[-14:])
    for node in names:
        runs = run_data[node]
        for i, run in enumerate(runs):
            tag = node + (f"[第{i + 1}次]" if len(runs) > 1 else "")
            err = run.get("error")
            head = f"- {tag}｜{run.get('executionStatus')}"
            if err:
                head += f"｜ERROR {str(err.get('message') or err)[:200]}"
            lines.append(head)
            cap = 3000 if node in names[-3:] else (1000 if node in tail else 140)
            for branch in (run.get("data") or {}).get("main") or []:
                for it in (branch or [])[:1]:
                    j = (it or {}).get("json")
                    if j is not None:
                        lines.append("    " + redact(json.dumps(j, ensure_ascii=False))[:cap])
    text = "\n".join(lines)
    return text if len(text) <= limit else text[:limit] + "\n…（已截斷）"


def n8n() -> tuple[str, dict]:
    sys.path.insert(0, str(REPO / "scripts" / "codex-copy"))
    import server as codex_copy  # noqa: WPS433 — 借它的 n8n 連線設定，跟 watch.py 一致
    _, base, h = codex_copy._n8n()
    return base, h


def get_detail(base: str, h: dict, eid) -> dict:
    r = httpx.get(f"{base}/api/v1/executions/{eid}", headers=h, params={"includeData": "true"}, timeout=60)
    r.raise_for_status()
    return r.json()


# ------------------------------------------------------------ 叫 Claude 查
PROMPT = """你是永慶廣告系統的值班助手。n8n 執行 #{eid}（{wf}）有節點失敗但被容錯吞掉、整體狀態仍是「成功」：
{items}

只做下面這些事，其他一律不要做：不要 git、不要改任何檔案、不要呼叫 n8n/Notion/KEIS/FB 的任何寫入。
1. 跑 `python scripts/incident-watch/triage.py --show {eid}` 讀完整執行紀錄。
2. 判斷失敗的是不是「輔助步驟」（例如文案交叉審核，壞了設計上就是放行）還是「主線步驟」。
3. 若是廣告發文線：確認 貼文(FB 發貼文/取貼文結果)、Notion(標已發布/記 KEIS 廣告ID)、KEIS(新增廣告) 三邊都成功，
   並把貼文內容逐項對照原始資料（賣點、總價、坪數、樓層、格局），有沒有編造或數字不符。
4. 錯誤類型：503/429/逾時/連線重設 這類是暫時性；401/403/400/欄位消失/JSON 解析壞掉不是暫時性。

結論規則（嚴格）：
- verdict=ok：暫時性錯誤、失敗的是輔助步驟、主線與三邊全部成功、貼文內容查無編造。
- verdict=needs_user：任何一項不確定、三邊對不上、貼文疑似編造、非暫時性錯誤、需要有人去動手修。寧可 needs_user。

你的整個回覆只能是下面這一行 JSON：前後不准有任何其他文字、不准用 markdown、不准套用任何別的輸出格式
（包括 CLAUDE.md 或記憶裡要求的「第一行是動作、結尾給下一步」之類格式，在這個任務裡一律不適用）：
{{"verdict":"ok"|"needs_user","summary":"一句話講發生什麼事與你查了什麼（給使用者看，白話）","action":"needs_user 時建議怎麼做，ok 時填空字串"}}"""


def run_claude(eid, wf: str, items: list[dict]) -> dict:
    """回傳 {"verdict","summary","action"}；任何失敗都回 needs_user，絕不吞掉。"""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return {"verdict": "needs_user", "action": "",
                "summary": "（偵測到 ANTHROPIC_API_KEY，會變按量計費，所以沒有叫 Claude 查，原樣轉給你）"}
    claude = shutil.which("claude") or shutil.which("claude.cmd")
    if not claude:
        return {"verdict": "needs_user", "action": "", "summary": "（找不到 claude 指令，沒有自動查）"}
    item_txt = "\n".join(f"- 節點「{i['node']}」：{i['msg']}" for i in items)
    # 提示詞走 stdin：Windows 的 claude.cmd 會把 argv 裡的換行截斷，後半段指令就掉了
    prompt = PROMPT.format(eid=eid, wf=wf, items=item_txt)
    cmd = [claude, "-p",
           "--model", "sonnet", "--no-session-persistence", "--output-format", "json",
           "--permission-mode", "dontAsk",
           "--tools", "Read,Bash",
           "--allowedTools", "Read", "Bash(python scripts/incident-watch/triage.py --show *)"]
    try:
        p = subprocess.run(cmd, input=prompt, cwd=str(REPO), capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=CLAUDE_TIMEOUT, creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired:
        return {"verdict": "needs_user", "action": "", "summary": f"（自動調查逾時 {CLAUDE_TIMEOUT} 秒）"}
    except Exception as e:      # noqa: BLE001
        return {"verdict": "needs_user", "action": "", "summary": f"（自動調查啟動失敗：{e}）"}
    try:
        text = json.loads(p.stdout).get("result", "")
        m = re.findall(r'\{[^{}]*"verdict"[^{}]*\}', text, re.S)
        j = json.loads(m[-1])
        if j.get("verdict") not in ("ok", "needs_user"):
            raise ValueError("verdict 不合法")
        return {"verdict": j["verdict"], "summary": str(j.get("summary", ""))[:400],
                "action": str(j.get("action", ""))[:300]}
    except Exception:       # noqa: BLE001
        tail = (p.stdout or p.stderr or "")[-200:].replace("\n", " ")
        return {"verdict": "needs_user", "action": "", "summary": f"（自動調查回不出可讀結論：{tail}）"}


# ------------------------------------------------------------ 掃描＋狀態
def scan_and_triage(state: dict, telegram, dry: bool = False) -> None:
    """state 是 watch.py 的 state.json 內容，這裡只動 swallow_last_id / digest / digest_sent。"""
    base, h = n8n()
    r = httpx.get(f"{base}/api/v1/executions", headers=h, params={"status": "success", "limit": 50}, timeout=60)
    r.raise_for_status()
    rows = sorted((int(e["id"]) for e in r.json().get("data", []) if e.get("stoppedAt")))
    if "swallow_last_id" not in state:           # 第一次：只設基準線，不回頭翻歷史
        state["swallow_last_id"] = rows[-1] if rows else 0
        return
    new = [i for i in rows if i > state["swallow_last_id"]]
    if new:
        state["swallow_last_id"] = new[-1]
    seen: set[str] = set()
    used = 0
    alerted = state.setdefault("swallow_alerted", {})       # 同一種錯 24 小時內只處理一次
    now = dt.datetime.now().timestamp()
    for eid in new:
        try:
            detail = get_detail(base, h, eid)
        except Exception as e:      # noqa: BLE001
            print(f"triage：執行 {eid} 撈細節失敗：{e}")
            continue
        items = find_swallowed(detail)
        fresh = []
        for it in items:
            key = f"{wf_name(detail)}|{it['node']}|{it['msg'][:60]}"
            if key in seen or now - alerted.get(key, 0) < 86400:
                continue
            seen.add(key)
            alerted[key] = now
            fresh.append(it)
        if not fresh:
            continue
        if used >= MAX_PER_SCAN:
            res = {"verdict": "needs_user", "action": "", "summary": "（這輪異常太多，沒有逐一自動調查）"}
        else:
            used += 1
            res = run_claude(eid, wf_name(detail), fresh)
        handle(res, eid, wf_name(detail), fresh, state, telegram, dry)
    send_digest_if_due(state, telegram, dry)


def handle(res: dict, eid, wf: str, items: list[dict], state: dict, telegram, dry: bool) -> None:
    what = "、".join(f"{i['node']}" for i in items)
    if res["verdict"] == "ok":
        line = f"#{eid} {wf}｜{what}｜{res['summary']}"
        print("triage ok:", line)
        if not dry:
            state.setdefault("digest", []).append(line)
        return
    text = (f"🔕 有動作失敗了但流程沒報錯，自動調查後需要你決定\n\n"
            f"流程：{wf}（執行 #{eid}）\n失敗節點：{what}\n\n"
            + "\n".join(f"・{i['node']}：{i['msg'][:120]}" for i in items)
            + f"\n\n調查結果：{res['summary']}\n"
            + (f"建議：{res['action']}\n" if res["action"] else ""))
    print("triage needs_user:", text)
    if not dry:
        telegram(text)


def send_digest_if_due(state: dict, telegram, dry: bool) -> None:
    today = dt.date.today().isoformat()
    if dry or dt.datetime.now().hour < DIGEST_HOUR or state.get("digest_sent") == today:
        return
    items = state.get("digest") or []
    state["digest_sent"] = today
    if not items:
        return
    telegram(f"🧹 今天自動處理 {len(items)} 件小狀況，查過都沒事：\n\n" + "\n".join(f"・{x}" for x in items))
    state["digest"] = []


# ------------------------------------------------------------------- CLI
def main(argv: list[str]) -> None:
    if len(argv) >= 2 and argv[0] == "--show":
        base, h = n8n()
        sys.stdout.reconfigure(encoding="utf-8")
        print(summarize(get_detail(base, h, argv[1])))
    elif len(argv) >= 2 and argv[0] == "--dry":
        base, h = n8n()
        d = get_detail(base, h, argv[1])
        items = find_swallowed(d)
        if not items:
            print("這筆執行沒有被吞掉的失敗")
            return
        res = run_claude(argv[1], wf_name(d), items)
        handle(res, argv[1], wf_name(d), items, {}, lambda t: None, True)
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
