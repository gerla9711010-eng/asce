#!/usr/bin/env bash
# PreToolUse：瀏覽器 navigate 一定要帶 tabId，沒帶就擋（exit 2）。
# 2026-10-21：navigate 沒帶 tabId，houseol 開進填好但還沒送出的 591 編輯頁分頁，整張表單被蓋掉要重填。
# 使用者要求「不要以後再發生」，靠記憶擋不住，改成 hook 硬擋。
export PYTHONIOENCODING=utf-8   # 不設的話中文訊息在 Windows 會編碼錯誤 → exit 1 → 變成沒擋
python -c "
import json, sys
d = json.load(sys.stdin)
if d.get('tool_input', {}).get('tabId') in (None, ''):
    sys.stderr.write('擋下：navigate 沒帶 tabId。先 tabs_context_mcp／tabs_create_mcp 拿自己的分頁 id 再帶上，'
                     '免得導進別的分頁、蓋掉沒送出的表單（2026-10-21 踩過）。')
    sys.exit(2)
"
