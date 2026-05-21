#!/usr/bin/env python3
"""
KEIS 廣告上架自動化腳本

用法:
    python publish.py YC1868650
    python publish.py YC1868650 --headed   # 看瀏覽器跑（debug 用）

流程:
    1. 用 案件編號 從 Notion 撈：來源連結 + 粉專貼文連結
    2. Playwright 開 KEIS → 登入 → 新增廣告 → 填表 → 送出
    3. 成功 → PATCH Notion KEIS同步 = 已同步
    4. 失敗 → 列印錯誤訊息，不動 Notion

環境變數（.env）:
    NOTION_TOKEN
    NOTION_DATA_SOURCE_ID
    KEIS_USERNAME
    KEIS_PASSWORD
"""

import argparse
import os
import sys
from dataclasses import dataclass

import httpx
from dotenv import load_dotenv
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout, sync_playwright

load_dotenv()

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DATA_SOURCE_ID = os.environ["NOTION_DATA_SOURCE_ID"]
KEIS_USERNAME = os.environ["KEIS_USERNAME"]
KEIS_PASSWORD = os.environ["KEIS_PASSWORD"]

KEIS_LOGIN_URL = "https://keis.kshouse.com.tw/"
KEIS_AD_TRACKER_URL = "https://keis.kshouse.com.tw/ad-tracker"

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


@dataclass
class PropertyData:
    page_id: str
    yc_id: str
    yungching_url: str
    facebook_url: str


def fetch_property(yc_id: str) -> PropertyData:
    """從 Notion 撈該物件的來源連結 + 粉專貼文連結"""
    resp = httpx.post(
        f"{NOTION_API}/data_sources/{NOTION_DATA_SOURCE_ID}/query",
        headers={
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
        json={
            "filter": {
                "property": "案件編號",
                "rich_text": {"equals": yc_id},
            }
        },
        timeout=30,
    )
    resp.raise_for_status()
    results = resp.json()["results"]
    if not results:
        raise SystemExit(f"❌ Notion 找不到 {yc_id}")

    page = results[0]
    props = page["properties"]

    yungching = props["來源連結"]["url"]
    fb_url = props["粉專貼文連結"]["url"]

    if not yungching:
        raise SystemExit(f"❌ {yc_id} 沒有「來源連結」")
    if not fb_url:
        raise SystemExit(f"❌ {yc_id} 沒有「粉專貼文連結」— 先發粉專、回報連結再來上架")

    return PropertyData(
        page_id=page["id"],
        yc_id=yc_id,
        yungching_url=yungching,
        facebook_url=fb_url,
    )


def mark_keis_synced(page_id: str) -> None:
    """PATCH Notion KEIS同步 = 已同步"""
    resp = httpx.patch(
        f"{NOTION_API}/pages/{page_id}",
        headers={
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
        json={"properties": {"KEIS同步": {"select": {"name": "已同步"}}}},
        timeout=30,
    )
    resp.raise_for_status()


def keis_login(page: Page) -> None:
    """登入 KEIS。首次跑會卡 captcha / 2FA 的話這裡會 fail，要使用者手動跑一次。"""
    page.goto(KEIS_LOGIN_URL)
    # 用 placeholder / label 找帳密欄位 — 實際 KEIS 欄位 selector 跑起來不對再調
    page.get_by_label("帳號").fill(KEIS_USERNAME)
    page.get_by_label("密碼").fill(KEIS_PASSWORD)
    page.get_by_role("button", name="登入").click()
    page.wait_for_load_state("networkidle")


def keis_publish_ad(page: Page, data: PropertyData) -> None:
    """填單送出。整段失敗就 raise，呼叫端 catch"""
    page.goto(KEIS_AD_TRACKER_URL)

    page.get_by_role("button", name="+ 新增廣告").click()
    page.get_by_label("官網連結").fill(data.yungching_url)
    page.get_by_role("button", name="自動填入").click()
    page.wait_for_timeout(3000)

    # 檢查重複
    if page.get_by_text("已新增過此連結").is_visible(timeout=1000):
        raise RuntimeError(f"KEIS 已存在 {data.yc_id}，跳過上架（Notion 仍標已同步）")

    # 廣告平台勾臉書
    page.get_by_label("臉書").check()
    page.get_by_label("臉書連結").fill(data.facebook_url)
    page.get_by_label("備忘錄").fill(data.yc_id)
    page.get_by_role("button", name="確定新增").click()

    # 確認列表出現「新上架」標籤
    page.get_by_text("新上架").wait_for(timeout=10000)


def main() -> int:
    parser = argparse.ArgumentParser(description="KEIS 廣告上架自動化")
    parser.add_argument("yc_id", help="案件編號，例如 YC1868650")
    parser.add_argument("--headed", action="store_true", help="顯示瀏覽器（debug 用）")
    args = parser.parse_args()

    print(f"🔍 撈 Notion {args.yc_id}...")
    data = fetch_property(args.yc_id)
    print(f"  ✓ 來源連結: {data.yungching_url}")
    print(f"  ✓ 粉專連結: {data.facebook_url}")

    duplicate_skip = False
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        context = browser.new_context()
        page = context.new_page()

        try:
            print("🔑 登入 KEIS...")
            keis_login(page)

            print("📤 送出新廣告...")
            try:
                keis_publish_ad(page, data)
                print("  ✓ KEIS 新增廣告成功")
            except RuntimeError as e:
                if "已存在" in str(e):
                    duplicate_skip = True
                    print(f"  ⚠ {e}")
                else:
                    raise

        except (PlaywrightTimeout, Exception) as e:
            print(f"❌ KEIS 操作失敗: {type(e).__name__}: {e}")
            page.screenshot(path=f"keis_error_{args.yc_id}.png")
            print(f"   截圖存 keis_error_{args.yc_id}.png")
            return 1
        finally:
            browser.close()

    print("📝 PATCH Notion KEIS同步 = 已同步...")
    mark_keis_synced(data.page_id)
    if duplicate_skip:
        print("✅ 完成（KEIS 既有那筆已標已同步）")
    else:
        print("✅ 完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
