#!/bin/bash
set -uo pipefail

# 雲端環境：同步到最新的 main，確保每次 session 都從正確的起點開始
# （本機環境不做這步：本機就是原點，rebase 反而有夾到其他平行 session 未提交改動的風險）
if [ "${CLAUDE_CODE_REMOTE:-}" = "true" ]; then
  git fetch origin main || echo "⚠️ git fetch 失敗（GitHub 帳號停權中會這樣，正常現象，略過）"
  git rebase origin/main || echo "⚠️ git rebase 失敗，需要手動處理衝突"
fi

# 每次 session 開場都自動跑一次分岔檢查，不用再靠人記得
if command -v python >/dev/null 2>&1 && [ -f scripts/n8n_sync.py ]; then
  echo "=== n8n_sync.py --check ==="
  python scripts/n8n_sync.py --check || echo "⚠️ n8n_sync.py --check 執行失敗，稍後手動確認"
fi

# === 長度體檢 ===
# 對象是「每次 session 都會被整份載入」的三份檔案。它們越長，Claude 對裡面每一條
# 規則的遵從率就越差——而且不是只忽略多出來那幾條，是整份一起垮。
#
# CLAUDE.md 裡「不要讓它越來越長」這條規則本來就有，但 STATUS.md 還是長到 627 行
# 才被發現（2026-08-04 拆掉）。規則沒人看，數字每次跳出來才有用。
#
# 警戒線都留了兩成緩衝（STATUS.md 目標 ~120 但線設 150），因為
# 一個永遠亮著的警告等於沒有警告。平常只印現況，撞線才展開處置說明。

MEM_DIR="$HOME/.claude/projects/C--Users-user-asce/memory"
WARN=""

lines_of() { [ -f "$1" ] && wc -l < "$1" | tr -d ' ' || echo 0; }

C_L=$(lines_of CLAUDE.md)
S_L=$(lines_of docs/STATUS.md)
M_L=$(lines_of "$MEM_DIR/MEMORY.md")
M_N=$(ls "$MEM_DIR"/*.md 2>/dev/null | grep -vc 'MEMORY\.md$' || echo 0)

echo ""
echo "📏 體檢｜CLAUDE.md $C_L/60 ｜ STATUS.md $S_L/150 ｜ MEMORY.md $M_L/45（$M_N/45 檔）"

[ "$C_L" -gt 60 ] && WARN="$WARN
⚠️ CLAUDE.md 已經 $C_L 行——查表類搬去 docs/reference.md，只留「每次都要遵守的規則」"

[ "$S_L" -gt 150 ] && WARN="$WARN
⚠️ docs/STATUS.md 已經 $S_L 行（目標 ~120）——這次 session 結束前要瘦身：
   事故經過 → docs/incidents.md（新的加最上面）｜查表類 → docs/reference.md
   STATUS.md 只留「現在的狀態」和「接下來要做的事」，完成的直接刪掉"

{ [ "$M_L" -gt 45 ] || [ "$M_N" -gt 45 ]; } && WARN="$WARN
⚠️ 記憶檔 $M_N 個 / MEMORY.md $M_L 行——清一輪：寫著「完結/無待辦」的直接刪、
   已死的服務縮成一行、同一件事存兩份的合併掉（2026-08-05 就抓到兩份 ADHD 記憶）"

[ -n "$WARN" ] && echo "$WARN"

echo ""
echo "📋 開工提醒：以 docs/n8n-live.md（線上真相）為準，docs/STATUS.md 是待辦清單"

exit 0
