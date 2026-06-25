"""用 playwright 截屏 streamlit 看板。"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, r'D:\aiCode\Hermes\aiTest\ai-agent-governance\tokenkeeper')

# 设置 DB 路径
os.environ['TOKENKEEPER_DB'] = r'D:\aiCode\Hermes\aiTest\ai-agent-governance\tokenkeeper\examples\demo.db'

from playwright.sync_api import sync_playwright


def main():
    """启动 streamlit 并截图。"""
    print("=" * 70)
    print("🪶 截屏 tokenkeeper 看板")
    print("=" * 70)

    streamlit_url = "http://localhost:8501"
    out_dir = r'D:\aiCode\Hermes\aiTest\ai-agent-governance\docs\screenshots'
    os.makedirs(out_dir, exist_ok=True)

    with sync_playwright() as p:
        # 用您本机已有的 chromium-1228
        chromium_exe = r"C:\Users\GALAXY\AppData\Local\ms-playwright\chromium-1228\chrome-win64\chrome.exe"
        if os.path.exists(chromium_exe):
            browser = p.chromium.launch(headless=True, executable_path=chromium_exe)
        else:
            browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 1000})

        print(f"[1] 访问 {streamlit_url}")
        try:
            page.goto(streamlit_url, wait_until="networkidle", timeout=30000)
        except Exception as e:
            print(f"  networkidle 超时，尝试 domcontentloaded: {e}")
            page.goto(streamlit_url, wait_until="domcontentloaded", timeout=30000)

        # 等 streamlit 渲染
        print("[2] 等待 streamlit 渲染...")
        time.sleep(5)

        # 截全页
        full_path = os.path.join(out_dir, "01_dashboard_full.png")
        page.screenshot(path=full_path, full_page=True)
        print(f"  ✅ 全页截图: {full_path}")

        # 截首屏
        viewport_path = os.path.join(out_dir, "02_dashboard_viewport.png")
        page.screenshot(path=viewport_path, full_page=False)
        print(f"  ✅ 首屏截图: {viewport_path}")

        # 滚到中段
        page.evaluate("window.scrollTo(0, 600)")
        time.sleep(1)
        mid_path = os.path.join(out_dir, "03_dashboard_mid.png")
        page.screenshot(path=mid_path, full_page=False)
        print(f"  ✅ 中段截图: {mid_path}")

        # 滚到底部
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1)
        bottom_path = os.path.join(out_dir, "04_dashboard_bottom.png")
        page.screenshot(path=bottom_path, full_page=False)
        print(f"  ✅ 底部截图: {bottom_path}")

        # 互动：调整时间范围到 30 天
        print("[3] 互动：调时间范围到 30 天...")
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(1)
        try:
            slider = page.locator('[data-testid="stSlider"]').first
            slider.click()
            # 用键盘调整
            for _ in range(23):  # 7 → 30
                page.keyboard.press("ArrowRight")
            time.sleep(2)
            interactive_path = os.path.join(out_dir, "05_dashboard_30days.png")
            page.screenshot(path=interactive_path, full_page=True)
            print(f"  ✅ 30 天视图: {interactive_path}")
        except Exception as e:
            print(f"  ⚠️ 互动操作失败: {e}")

        browser.close()

    print()
    print("=" * 70)
    print("✅ 截图完成")
    print(f"   输出目录: {out_dir}")
    print("=" * 70)


if __name__ == "__main__":
    main()