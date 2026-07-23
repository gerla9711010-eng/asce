# n8n 線上現況（2026-07-23 23:53 自動產生）

> 這份是 `python scripts/n8n_sync.py` 產的，**不要手改**。
> 它反映的是 n8n 上真正在跑的東西，跟 STATUS.md 的說法對不上時，以這份為準。

## Workflow

| 狀態 | 名稱 | 檔案 | 節點 | 最近執行 |
|---|---|---|---|---|
| 🟢 | KEIS 待聯絡提醒 | `keis-contact-reminder.json` | 4 | 2026-07-23T01:00 success |
| 🟢 | KEIS 心跳檢查 | `keis-heartbeat-check.json` | 5 | 2026-07-23T15:48 success |
| 🟢 | KEIS 戰果查詢 | `keis-battle-report.json` | 5 | 2026-07-23T00:05 success |
| 🟢 | KEIS 搶單 LINE 通知 | `keis-grab-notify.json` | 3 | 2026-07-23T03:47 success |
| 🟢 | LINE 指令分流器 v3 | `line-command-router.json` | 14 | 2026-07-23T00:05 success |
| 🟢 | 圖片分流器（LINE 傳圖自動分類） | `line-image-dispatcher.json` | 9 | 2026-07-22T15:06 success |
| 🟢 | 客戶建檔器 | `line-customer-create.json` | 13 | 2026-07-16T10:15 success |
| 🟢 | 市場週報 LINE 通知 | `market-report-notify.json` | 3 | 2026-07-21T11:00 success |
| 🟢 | 廣告v3 下架偵測線 | `yc-v3-removal.json` | 21 | 2026-07-23T00:00 success |
| 🟢 | 廣告v3 掃描發文線 | `yc-v3-scan-publish.json` | 41 | 2026-07-23T11:52 success |
| 🟢 | 廣告v3 煞車（停） | `yc-v3-stop.json` | 9 | 2026-07-22T14:02 success |
| 🟢 | 廣告v3 重發輪替線 | `yc-v3-repost.json` | 23 | 2026-07-23T11:30 success |
| 🟢 | 自動簽到 LINE 通知 | `clockin-notify.json` | 3 | 2026-07-23T01:51 success |
| 🟢 | 行事曆建立器 | `line-calendar-create.json` | 13 | 2026-07-22T15:06 success |
| ⚪ | LINE 新聞推播 | `line-news-push.json` | 6 | — |
| ⚪ | YC 建檔器 v2（抓真物編productID） | `yc-property-create.json` | 13 | 2026-07-20T15:15 success |
| ⚪ | YC 建檔器 v3（鎖物編+總價） | `yc-property-create-v3.json` | 13 | — |
| ⚪ | YC 發文線（發 YCxxx） | `yc-fb-publish.json` | 24 | 2026-07-20T12:44 success |
| ⚪ | 文案重產器 | `yc-rewrite-copy.json` | 10 | — |

## 廣告 DB 欄位｜誰在寫

| 欄位 | workflow |
|---|---|
| KEIS同步 | （停用）YC 發文線（發 YCxxx）、廣告v3 掃描發文線 |
| KEIS廣告ID | 廣告v3 下架偵測線、廣告v3 掃描發文線 |
| KEIS物件ID | 廣告v3 重發輪替線、廣告v3 掃描發文線 |
| 下架偵測時間 | 廣告v3 下架偵測線 |
| 主建物坪數 | （停用）YC 建檔器 v3（鎖物編+總價）、（停用）YC 發文線（發 YCxxx）、（停用）文案重產器、（停用）YC 建檔器 v2（抓真物編productID）、廣告v3 掃描發文線 |
| 來源連結 | 廣告v3 重發輪替線、（停用）YC 建檔器 v3（鎖物編+總價）、（停用）YC 發文線（發 YCxxx）、（停用）YC 建檔器 v2（抓真物編productID）、廣告v3 下架偵測線、廣告v3 掃描發文線 |
| 地址 | 廣告v3 重發輪替線、（停用）YC 建檔器 v3（鎖物編+總價）、（停用）YC 發文線（發 YCxxx）、（停用）文案重產器、（停用）YC 建檔器 v2（抓真物編productID）、客戶建檔器、廣告v3 掃描發文線 |
| 專員 | 廣告v3 掃描發文線 |
| 專員電話 | ⚠️ 沒有任何 workflow |
| 屋齡 | 廣告v3 重發輪替線、（停用）YC 建檔器 v3（鎖物編+總價）、（停用）YC 發文線（發 YCxxx）、（停用）文案重產器、（停用）YC 建檔器 v2（抓真物編productID）、廣告v3 掃描發文線 |
| 已撤除確認 | —（手動勾選） |
| 廣告貼文紀錄 | —（桌面 /yc-ad skill append） |
| 建物坪數 | （停用）YC 建檔器 v3（鎖物編+總價）、（停用）YC 發文線（發 YCxxx）、（停用）文案重產器、（停用）YC 建檔器 v2（抓真物編productID）、廣告v3 掃描發文線 |
| 建物類型 | 廣告v3 重發輪替線、（停用）YC 建檔器 v3（鎖物編+總價）、（停用）YC 發文線（發 YCxxx）、（停用）文案重產器、（停用）YC 建檔器 v2（抓真物編productID）、廣告v3 掃描發文線 |
| 建立日期 | —（Notion 自動（created_time）） |
| 所屬門市 | 廣告v3 掃描發文線 |
| 文案版本 | 廣告v3 重發輪替線、（停用）YC 建檔器 v3（鎖物編+總價）、（停用）YC 發文線（發 YCxxx）、（停用）文案重產器、（停用）YC 建檔器 v2（抓真物編productID） |
| 最後重發時間 | 廣告v3 重發輪替線 |
| 格局 | 廣告v3 重發輪替線、（停用）YC 建檔器 v3（鎖物編+總價）、（停用）YC 發文線（發 YCxxx）、（停用）文案重產器、（停用）YC 建檔器 v2（抓真物編productID）、廣告v3 掃描發文線 |
| 案件編號 | 廣告v3 重發輪替線、廣告v3 煞車（停）、（停用）YC 建檔器 v3（鎖物編+總價）、（停用）YC 發文線（發 YCxxx）、（停用）文案重產器、（停用）YC 建檔器 v2（抓真物編productID）、廣告v3 下架偵測線、廣告v3 掃描發文線 |
| 案名 | 廣告v3 重發輪替線、廣告v3 煞車（停）、（停用）YC 建檔器 v3（鎖物編+總價）、（停用）YC 發文線（發 YCxxx）、（停用）文案重產器、（停用）YC 建檔器 v2（抓真物編productID）、廣告v3 下架偵測線、廣告v3 掃描發文線 |
| 樓層 | 廣告v3 重發輪替線、（停用）YC 建檔器 v3（鎖物編+總價）、（停用）YC 發文線（發 YCxxx）、（停用）文案重產器、（停用）YC 建檔器 v2（抓真物編productID）、廣告v3 掃描發文線 |
| 永慶官網連結 | 廣告v3 掃描發文線 |
| 狀態 | 廣告v3 重發輪替線、廣告v3 煞車（停）、（停用）YC 發文線（發 YCxxx）、廣告v3 下架偵測線、客戶建檔器、廣告v3 掃描發文線 |
| 社區名稱 | （停用）YC 建檔器 v3（鎖物編+總價）、（停用）YC 發文線（發 YCxxx）、（停用）文案重產器、（停用）YC 建檔器 v2（抓真物編productID）、廣告v3 掃描發文線 |
| 社團文案 | 廣告v3 重發輪替線、（停用）YC 發文線（發 YCxxx）、廣告v3 掃描發文線 |
| 粉專文案 | 廣告v3 重發輪替線、（停用）YC 發文線（發 YCxxx）、廣告v3 掃描發文線 |
| 粉專貼文連結 | 廣告v3 重發輪替線、（停用）YC 發文線（發 YCxxx）、廣告v3 下架偵測線、廣告v3 掃描發文線 |
| 總價 | （停用）YC 建檔器 v3（鎖物編+總價）、（停用）YC 發文線（發 YCxxx）、（停用）文案重產器、（停用）YC 建檔器 v2（抓真物編productID）、廣告v3 掃描發文線 |
| 要重發 | 廣告v3 重發輪替線 |
| 重發次數 | 廣告v3 重發輪替線 |

## 分岔檢查

- git 與 n8n 檔案一致
- ⚠️ **沒人寫的 Notion 欄位**（可能該刪，或有 n8n 以外的東西在寫）：專員電話
