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

# STATUS.md 體檢：CLAUDE.md 裡「不要讓它越來越長」這條規則本來就有，
# 但它還是長到 627 行才被發現（2026-08-04 拆掉）。規則沒人看，數字每次跳出來才有用。
if [ -f docs/STATUS.md ]; then
  # 警戒線 150 不是 120：目標是 ~120，但留兩成緩衝才不會天天叫。
  # 一個永遠亮著的警告等於沒有警告。
  L=$(wc -l < docs/STATUS.md | tr -d ' ')
  if [ "$L" -gt 150 ]; then
    echo ""
    echo "⚠️ docs/STATUS.md 已經 $L 行（目標 ~120）——這次 session 結束前要瘦身："
    echo "   事故經過 → docs/incidents.md（新的加最上面）｜查表類 → docs/reference.md"
    echo "   STATUS.md 只留「現在的狀態」和「接下來要做的事」，完成的直接刪掉"
  fi
fi

echo ""
echo "📋 開工提醒：以 docs/n8n-live.md（線上真相）為準，docs/STATUS.md 是待辦清單"
