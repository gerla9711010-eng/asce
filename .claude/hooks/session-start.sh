#!/bin/bash
set -euo pipefail

# 只在 Claude Code web 環境執行
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

# 同步到最新的 main，確保每次 session 都從正確的起點開始
git fetch origin main
git rebase origin/main
