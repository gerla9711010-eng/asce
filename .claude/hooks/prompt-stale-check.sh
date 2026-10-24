#!/bin/bash
# UserPromptSubmit：使用者每傳一則訊息，檢查本機分支有沒有落後 origin/main，落後就把警告塞進 Claude 的上下文。
# 開場檢查（stale-check.sh）只跑一次；3 個視窗長開，中途別的視窗合 PR 就落後了（10-24 一天兩次拿舊程式回答）。
#
# 規矩：永遠 exit 0、不擋訊息；fetch 3 個視窗共用、10 分鐘最多一次、5 秒逾時，失敗也算一次（網路不穩不會每則都卡）。
# 沒落後就什麼都不印。
cd "${CLAUDE_PROJECT_DIR:-.}" 2>/dev/null || exit 0

CACHE_DIR="$HOME/.claude/cache"
STAMP="$CACHE_DIR/prompt_fetch.stamp"
LOCK="$CACHE_DIR/prompt_fetch.lock"
mkdir -p "$CACHE_DIR" 2>/dev/null

age_of() { [ -e "$1" ] && echo $(( $(date +%s) - $(stat -c %Y "$1") )) || echo 999999; }

# 當掉留下的鎖超過 1 分鐘就清掉
[ -d "$LOCK" ] && [ "$(age_of "$LOCK")" -gt 60 ] && rmdir "$LOCK" 2>/dev/null

if [ "$(age_of "$STAMP")" -ge 600 ] && mkdir "$LOCK" 2>/dev/null; then
  touch "$STAMP"
  timeout 5 git fetch -q origin main >/dev/null 2>&1
  rmdir "$LOCK" 2>/dev/null
fi

N=$(git rev-list --count HEAD..origin/main 2>/dev/null || echo 0)
if [ "${N:-0}" -gt 0 ] 2>/dev/null; then
  echo "⚠️ 本機分支落後 origin/main ${N} 個 commit（別的視窗合了 PR）。回答前："
  echo "1. 查程式／文件一律讀最新版：git show origin/main:<路徑>，不要讀工作區的檔案"
  echo "2. 要改東西先開 worktree 從 origin/main 起分支（工作區常有別的視窗未提交的改動，別直接 rebase）"
  echo "3. 回答講清楚是「main 的版本」還是「這台電腦正在跑的版本」"
fi
exit 0
