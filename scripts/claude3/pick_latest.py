"""挑出某個 Claude 視窗(assistant1/2/3)目前最新的一份對話檔。

用法:  python pick_latest.py <bridgeSessionId> <備援jsonl路徑>
輸出:  一行絕對路徑（永遠會印一行，失敗就印備援路徑）

為什麼需要這支
--------------
啟動三視窗.bat 原本每個視窗釘死一份 jsonl。但按 /clear 會另開一份新檔，
釘死的那份就停在 /clear 之前 —— 隔天開機看到的是「清空前」的舊對話，
當天談的事全都翻不到。2026-09-02 assistant2 就這樣斷過一次。

族譜 key 用 bridgeSessionId
--------------------------
同一個視窗歷次 /clear 產生的所有 jsonl，都帶同一個 bridgeSessionId
（就是手機端那個固定不變的標籤，在視窗第一次註冊時決定）。用它認親最準。

不用 agentName：會被自動標題蓋掉（實際看過 assistant2 變成 "notion"、
assistant3 變成 "ad review cross-check failure"）。
不用檔案 mtime：resume 時只改 metadata 也會更新 mtime，
a475df8e 最後一則是 9/1 但 mtime 是 9/3。所以排序一律看「最後一則訊息時間」。
"""
import os
import re
import sys

PROJECT_DIR = os.path.join(
    os.path.expanduser("~"), ".claude", "projects", "C--Users-user-asce"
)

# bridge-session 通常在前幾行；設上限免得掃到 16MB 的大檔還在讀
HEAD_LINES = 100
HEAD_BYTES = 256 * 1024
TAIL_BYTES = 256 * 1024

BRIDGE_RE = re.compile(r'"bridgeSessionId"\s*:\s*"([^"]+)"')
TS_RE = re.compile(r'"timestamp"\s*:\s*"(20\d\d-\d\d-\d\dT[^"]+)"')


def bridge_of(path):
    """讀開頭找 bridgeSessionId，找不到回 None。"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            read = 0
            for i, line in enumerate(fh):
                read += len(line)
                if i >= HEAD_LINES or read > HEAD_BYTES:
                    break
                if '"bridge-session"' in line:
                    m = BRIDGE_RE.search(line)
                    if m:
                        return m.group(1)
    except OSError:
        pass
    return None


def last_ts(path):
    """讀檔尾抓最後一個 timestamp，當作這份對話的活動時間。"""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size > TAIL_BYTES:
                fh.seek(size - TAIL_BYTES)
            blob = fh.read().decode("utf-8", errors="replace")
        found = TS_RE.findall(blob)
        return max(found) if found else ""
    except OSError:
        return ""


def main():
    if len(sys.argv) < 3:
        sys.exit(2)
    bridge, fallback = sys.argv[1], sys.argv[2]

    best, best_ts = None, ""
    try:
        names = os.listdir(PROJECT_DIR)
    except OSError as e:
        print(fallback)
        print("pick_latest: 讀不到 %s (%s)，用備援" % (PROJECT_DIR, e), file=sys.stderr)
        return

    for name in names:
        if not name.endswith(".jsonl") or ".orphaned-" in name:
            continue
        path = os.path.join(PROJECT_DIR, name)
        if bridge_of(path) != bridge:
            continue
        ts = last_ts(path)
        if ts > best_ts:          # 空字串(完全沒訊息的空檔)永遠贏不了
            best, best_ts = path, ts

    if best and os.path.getsize(best) > 0:
        print(best)
    else:
        print(fallback)
        print("pick_latest: %s 找不到對話檔，用備援" % bridge, file=sys.stderr)


if __name__ == "__main__":
    main()
