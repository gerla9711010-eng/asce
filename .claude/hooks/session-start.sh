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

echo ""
echo "📋 開工提醒：以 docs/n8n-live.md（線上真相）為準，docs/STATUS.md 是待辦清單"
