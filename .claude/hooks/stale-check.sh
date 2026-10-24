#!/bin/bash
# 檢查目前分支有沒有落後 origin/main。只 fetch、只比對，不動工作區。
# 落後 → 印紅字並 exit 1（skill 第 0 步用它擋住）；抓不到最新版 → 印一行略過，exit 0。
cd "${CLAUDE_PROJECT_DIR:-.}" 2>/dev/null || exit 0
if ! timeout 15 git fetch origin main -q 2>/dev/null; then
  echo "（抓不到 origin/main，略過落後檢查；帳號停權或沒網路時正常）"
  exit 0
fi
N=$(git rev-list --count HEAD..origin/main 2>/dev/null || echo 0)
if [ "$N" -gt 0 ]; then
  echo "⚠️⚠️ 本機分支落後 origin/main $N 個 commit——skill／腳本是舊版！"
  echo "   先 stash 別人的未提交改動，再 git rebase origin/main（或請 Claude 處理）。"
  exit 1
fi
echo "✓ 已是最新 main"
exit 0
