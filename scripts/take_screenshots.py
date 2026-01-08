import asyncio
from playwright.async_api import async_playwright

async def take_screenshots():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        
        # 访问主页
        await page.goto('http://127.0.0.1:8765')
        await page.wait_for_timeout(2000)
        
        # 截图1: 主页
        await page.screenshot(path='docs/screenshots/01_homepage.png', full_page=True)
        print("Screenshot 1: Homepage saved")
        
        # 点击打开登录页
        await page.click('button:has-text("打开登录页")')
        await page.wait_for_timeout(2000)
        
        # 截图2: 登录状态
        await page.screenshot(path='docs/screenshots/02_login_status.png', full_page=True)
        print("Screenshot 2: Login status saved")
        
        # 输入关键词
        await page.fill('input#kw', '信用飞')
        await page.wait_for_timeout(1000)
        
        # 截图3: 关键词输入
        await page.screenshot(path='docs/screenshots/03_keyword_input.png', full_page=False)
        print("Screenshot 3: Keyword input saved")
        
        await browser.close()
        print("All screenshots saved successfully!")

if __name__ == "__main__":
    asyncio.run(take_screenshots())
