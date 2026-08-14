#!/bin/bash
set -uo pipefail

# Stop hook：docs/STATUS.md 超過 150 行就擋下收工，逼當場瘦身。
# 只在超過時才動作；每個 session 只擋一次（用 session_id 存 marker），
# 避免同一 session 裡每輪回話都被擋。

INPUT=$(cat)

SESSION_ID=$(printf '%s' "$INPUT" | python -c "
import json, sys
try:
    print(json.load(sys.stdin).get('session_id', 'unknown'))
except Exception:
    print('unknown')
" 2>/dev/null)
[ -n "$SESSION_ID" ] || SESSION_ID="unknown"

ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
STATUS_FILE="$ROOT/docs/STATUS.md"
[ -f "$STATUS_FILE" ] || exit 0

LINES=$(wc -l < "$STATUS_FILE" | tr -d ' ')
[ "$LINES" -gt 150 ] || exit 0

MARKER_DIR="${TMPDIR:-/tmp}/claude-stop-status-check"
mkdir -p "$MARKER_DIR" 2>/dev/null
MARKER="$MARKER_DIR/${SESSION_ID}.done"
[ -f "$MARKER" ] && exit 0
touch "$MARKER" 2>/dev/null

cat >&2 <<EOF
docs/STATUS.md 已經 $LINES 行，超過 150 上限，收工前要瘦身到 ~120 行：
1. 事故經過搬去 docs/incidents.md（新的加最上面）
2. 查表類搬去 docs/reference.md
3. 已完成的項目直接刪掉
STATUS.md 只留「現在的狀態」和「接下來要做的事」，搬完再結束這輪。
EOF
exit 2
