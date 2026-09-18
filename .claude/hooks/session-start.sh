#!/bin/bash
set -uo pipefail

# 雲端環境：同步到最新的 main，確保每次 session 都從正確的起點開始
# （本機環境不做這步：本機就是原點，rebase 反而有夾到其他平行 session 未提交改動的風險）
if [ "${CLAUDE_CODE_REMOTE:-}" = "true" ]; then
  git fetch origin main || echo "⚠️ git fetch 失敗（GitHub 帳號停權中會這樣，正常現象，略過）"
  git rebase origin/main || echo "⚠️ git rebase 失敗，需要手動處理衝突"
fi

# 每次 session 開場都自動跑一次分岔檢查，不用再靠人記得。
#
# 但這支要跑 ~90 秒，而開機會同時開 3 個助理視窗（assistant1/2/3），
# 三個各跑一次＝同樣的結果查三遍、三個視窗都卡著不能打字。
# 所以改成「查一次、三個共用」：結果存快取，10 分鐘內直接讀快取。
# 用 mkdir 當鎖（原子操作），同時開機時只有搶到鎖的那個真的去查，
# 另外兩個秒開、讀上一份結果並標明時間，不會出現「以為沒問題其實沒查」的假安心。
CACHE_DIR="$HOME/.claude/cache"
CACHE_FILE="$CACHE_DIR/n8n_check.txt"
LOCK_DIR="$CACHE_DIR/n8n_check.lock"
CACHE_MAX_AGE=600   # 10 分鐘
LOCK_MAX_AGE=300    # 鎖超過 5 分鐘視為當掉殘留，強制清掉

mkdir -p "$CACHE_DIR"

age_of() { [ -e "$1" ] && echo $(( $(date +%s) - $(stat -c %Y "$1") )) || echo 999999; }

if command -v python >/dev/null 2>&1 && [ -f scripts/n8n_sync.py ]; then
  echo "=== n8n_sync.py --check ==="

  # 清掉當掉留下的鎖，否則之後永遠不會重查
  [ -d "$LOCK_DIR" ] && [ "$(age_of "$LOCK_DIR")" -gt "$LOCK_MAX_AGE" ] && rmdir "$LOCK_DIR" 2>/dev/null

  CACHE_AGE=$(age_of "$CACHE_FILE")

  if [ "$CACHE_AGE" -lt "$CACHE_MAX_AGE" ]; then
    cat "$CACHE_FILE"
    echo "（$((CACHE_AGE / 60)) 分鐘前查的，三個視窗共用同一份）"
  elif mkdir "$LOCK_DIR" 2>/dev/null; then
    N8N_OUT=$(python scripts/n8n_sync.py --check 2>&1) \
      || N8N_OUT="$N8N_OUT
⚠️ n8n_sync.py --check 執行失敗，稍後手動確認"
    printf '%s\n' "$N8N_OUT" > "$CACHE_FILE"
    printf '%s\n' "$N8N_OUT"
    rmdir "$LOCK_DIR" 2>/dev/null
  elif [ -f "$CACHE_FILE" ]; then
    cat "$CACHE_FILE"
    echo "⏳ 另一個視窗正在重新檢查中；以上是 $((CACHE_AGE / 60)) 分鐘前的結果"
  else
    echo "⏳ 另一個視窗正在跑檢查，這裡先跳過。要自己看：python scripts/n8n_sync.py --check"
  fi
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
G_L=$(lines_of "$HOME/.claude/CLAUDE.md")   # 全域回覆格式，每個專案都會載入
S_L=$(lines_of docs/STATUS.md)
M_L=$(lines_of "$MEM_DIR/MEMORY.md")
M_N=$(ls "$MEM_DIR"/*.md 2>/dev/null | grep -vc 'MEMORY\.md$' || echo 0)

echo ""
echo "📏 體檢｜CLAUDE.md $C_L+$G_L/75 ｜ STATUS.md $S_L/150 ｜ MEMORY.md $M_L/45（$M_N/45 檔）"

# 兩份 CLAUDE.md 一起算：全域那份每個專案都吃，佔的是同一份注意力預算
[ "$((C_L + G_L))" -gt 75 ] && WARN="$WARN
⚠️ CLAUDE.md 合計已經 $((C_L + G_L)) 行（專案 $C_L ＋全域 $G_L）——查表類搬去
   docs/reference.md，只留「每次都要遵守的規則」"

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
