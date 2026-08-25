# -*- coding: utf-8 -*-
"""補回「發文預告」和「發文成功」兩個主動推播（Telegram）。

背景：2026-08-14 為省 LINE 配額，把 11 個主動推播全拔了；08-19 PR #220 改推 Telegram 時
只補回了「失敗類」的三個（發文失敗／體檢告警／跳過摘要），漏掉這兩個「正常流程」的推播：

  1. 線A `組預告` 明明有算出 pushText，但沒有任何節點讀它 → 煞車 10 分鐘變成沒人知道的空等
  2. 線A `Notion 記 KEIS 廣告ID`（成功終點）後面直接斷掉 → 發成功了也沒人知道
  3. 線C `Notion 更新重發` 之後同樣沒有任何推播 → 重發到粉專也是靜悄悄

做法沿用 scripts/n8n_add_telegram_push.py：從既有節點多接一條並聯出去，不動原本的主線。

用法：
    python scripts/n8n_restore_publish_push.py --dry-run
    python scripts/n8n_restore_publish_push.py
"""
import json
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

CRED = {"id": "yBF20qXez1b7FLFI", "name": "Telegram 業務助理 Bot"}
CHAT_ID = "1890720012"
DRY = "--dry-run" in sys.argv

env = {}
for line in open(".env", encoding="utf-8"):
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        env[k] = v.strip()
BASE = env["N8N_URL"].rstrip("/")
HEADERS = {"X-N8N-API-KEY": env["N8N_API_KEY"], "Content-Type": "application/json"}

# 發成功通知的文字：沿用 2026-08-14 被拔掉的「LINE 發布通知」原文，只換推播管道
PUBLISH_MSG = (
    "const p = $('取貼文結果').first().json;\n"
    "const k = $('取 KEIS 廣告ID').first().json;\n"
    "const text = `✅ 已發布 ${p.contract_no}\\n"
    "${p.permalink || '（連結未取得，請到粉專確認）'}\\n\\n`\n"
    "  + `━ 社團版（複製貼原生文）━\\n${p['社團文案'] || ''}\\n\\n"
    "撒網社團按這篇的「分享」即可。\\n\\n`\n"
    "  + `\U0001F4CA KEIS 廣告追蹤：${k.keisNote || '未執行'}${k.skipNote || ''}`;\n"
    "return [{ json: { text } }];\n"
)

REPOST_MSG = (
    "const p = $('取貼文結果').first().json;\n"
    "const o = $('挑一件重發').first().json;\n"
    "const text = `\U0001F501 已重發 ${p.contract_no}\\n"
    "${p.permalink || '（連結未取得，請到粉專確認）'}\\n\\n`\n"
    "  + (o.oldPermalink ? `舊貼文已刪：${o.oldPermalink}\\n\\n` : '')\n"
    "  + `━ 社團版（複製貼原生文）━\\n${p['社團文案'] || ''}`;\n"
    "return [{ json: { text } }];\n"
)

# 預告這則要「插」在 組預告 → 煞車 10 分鐘 中間，不能並聯：並聯的話 Wait 節點一停，
# 推播可能排在 10 分鐘之後才送出，那預告就失去意義了。下游的 重查狀態／判斷是否被停
# 都是用 $('組預告') 取值、照片是 被停? 之後才下載的，所以中間插一個節點不影響資料流。
INLINE = ("yc-v3-scan-publish.json", "組預告", "煞車 10 分鐘",
          "Telegram 預告", "={{ $json.pushText }}")

# (檔名, 來源節點, branch, [中間 code 節點名, jsCode] 或 None, telegram 節點名, text 表達式)
JOBS = [
    ("yc-v3-scan-publish.json", "Notion 記 KEIS 廣告ID", 0,
     ["組發布通知", PUBLISH_MSG], "Telegram 發布通知", "={{ $json.text }}"),
    ("yc-v3-repost.json", "Notion 更新重發", 0,
     ["組重發通知", REPOST_MSG], "Telegram 重發通知", "={{ $json.text }}"),
]

# 預告文字原本寫「回『停 XXX』」，那是 LINE 指令分流器在收；Telegram 沒有 trigger，
# 在 Telegram 回「停」不會有任何作用。推播管道換掉了，指示也要一起改，否則等於給假的煞車。
STOP_TEXT_OLD = "不想發這件 → 回「停 ${src.contract_no}」或「停」"
STOP_TEXT_NEW = "不想發這件 → 到 LINE 回「停 ${src.contract_no}」或「停」（Telegram 回沒用）"


def req(path, data=None, method=None):
    r = urllib.request.Request(
        BASE + path,
        data=json.dumps(data).encode() if data is not None else None,
        headers=HEADERS,
        method=method,
    )
    try:
        return json.load(urllib.request.urlopen(r))
    except urllib.error.HTTPError as e:
        return {"ERR": e.code, "body": e.read().decode()[:400]}


def make_telegram_node(name, position, text_expr):
    return {
        "parameters": {
            "chatId": CHAT_ID,
            "text": text_expr,
            "additionalFields": {"appendAttribution": False},
        },
        "type": "n8n-nodes-base.telegram",
        "typeVersion": 1.2,
        "position": position,
        "name": name,
        "credentials": {"telegramApi": CRED},
        # 推播掛掉不該連累發文本身（預告那條是並聯在煞車旁邊的）
        "onError": "continueRegularOutput",
    }


def make_code_node(name, position, js):
    return {
        "parameters": {"jsCode": js, "mode": "runOnceForAllItems"},
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": position,
        "name": name,
    }


def main():
    all_wf = req("/api/v1/workflows?limit=250")["data"]
    by_name = {w["name"]: w for w in all_wf}

    jobs_by_file = {}
    for job in JOBS:
        jobs_by_file.setdefault(job[0], []).append(job[1:])

    touched = []
    for fname, jobs in jobs_by_file.items():
        wf_name = json.load(open("workflows/" + fname, encoding="utf-8"))["name"]
        remote = by_name.get(wf_name)
        if not remote:
            print("找不到對應的 n8n workflow：", wf_name)
            continue
        wf = req("/api/v1/workflows/" + remote["id"])
        node_by_name = {n["name"]: n for n in wf["nodes"]}
        changed = False

        # 順手把預告的煞車指示改成指向 LINE
        pre = node_by_name.get("組預告")
        if pre and STOP_TEXT_OLD in pre["parameters"]["jsCode"]:
            pre["parameters"]["jsCode"] = pre["parameters"]["jsCode"].replace(
                STOP_TEXT_OLD, STOP_TEXT_NEW)
            changed = True
            print("  %s：組預告 煞車指示改成「到 LINE 回停」" % wf_name)

        # 串接式：src -> 新 Telegram -> 原本的下游
        if fname == INLINE[0]:
            _, src, downstream, tg_name, text_expr = INLINE
            if tg_name in node_by_name:
                print("  %s：%s 已存在，跳過" % (wf_name, tg_name))
            elif src not in node_by_name:
                print("  [找不到來源節點] %s：%s" % (wf_name, src))
            else:
                x, y = node_by_name[src]["position"]
                tg_node = make_telegram_node(tg_name, [x + 180, y + 160], text_expr)
                wf["nodes"].append(tg_node)
                node_by_name[tg_name] = tg_node
                wf["connections"][src]["main"][0] = [
                    {"node": tg_name, "type": "main", "index": 0}]
                wf["connections"].setdefault(tg_name, {})["main"] = [
                    [{"node": downstream, "type": "main", "index": 0}]]
                changed = True
                print("  %s：%s -> %s -> %s（串接）"
                      % (wf_name, src, tg_name, downstream))

        for src, branch, mid, tg_name, text_expr in jobs:
            if tg_name in node_by_name:
                print("  %s：%s 已存在，跳過" % (wf_name, tg_name))
                continue
            src_node = node_by_name.get(src)
            if not src_node:
                print("  [找不到來源節點] %s：%s" % (wf_name, src))
                continue
            x, y = src_node["position"]
            head = tg_name
            if mid:
                mid_name, js = mid
                mid_node = make_code_node(mid_name, [x + 200, y + 200], js)
                wf["nodes"].append(mid_node)
                node_by_name[mid_name] = mid_node
                wf["connections"].setdefault(mid_name, {}).setdefault(
                    "main", [[]])[0].append(
                    {"node": tg_name, "type": "main", "index": 0})
                head = mid_name
                tg_pos = [x + 400, y + 200]
            else:
                tg_pos = [x + 200, y + 200]
            tg_node = make_telegram_node(tg_name, tg_pos, text_expr)
            wf["nodes"].append(tg_node)
            node_by_name[tg_name] = tg_node
            conns = wf["connections"].setdefault(src, {}).setdefault("main", [])
            while len(conns) <= branch:
                conns.append([])
            conns[branch].append({"node": head, "type": "main", "index": 0})
            changed = True
            print("  %s：%s --(branch %d)--> %s%s"
                  % (wf_name, src, branch,
                     (head + " -> ") if mid else "", tg_name))

        if not changed:
            continue
        if DRY:
            print("  → --dry-run，沒有寫回")
            continue
        settings = dict(wf.get("settings", {}))
        settings.pop("binaryMode", None)
        settings.pop("availableInMCP", None)
        res = req("/api/v1/workflows/" + remote["id"], {
            "name": wf["name"],
            "nodes": wf["nodes"],
            "connections": wf["connections"],
            "settings": settings,
        }, "PUT")
        print("  → 寫回", "成功" if "ERR" not in res else res)
        if "ERR" not in res:
            touched.append((remote["id"], wf_name, remote.get("active")))

    if DRY or not touched:
        return

    print("\n改完的 active workflow 重新 deactivate+activate：")
    for wid, name, was_active in touched:
        if not was_active:
            print("  %s：本來就沒 active，跳過" % name)
            continue
        r1 = req("/api/v1/workflows/%s/deactivate" % wid, method="POST")
        r2 = req("/api/v1/workflows/%s/activate" % wid, method="POST")
        now = req("/api/v1/workflows/%s" % wid)
        print("  %s：deactivate=%s activate=%s → 目前 active=%s"
              % (name,
                 "OK" if "ERR" not in r1 else r1,
                 "OK" if "ERR" not in r2 else r2,
                 now.get("active")))


if __name__ == "__main__":
    main()
