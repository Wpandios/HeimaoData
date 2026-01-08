import argparse
import csv
import datetime
import json
import logging
import os
import re
import time
import urllib.parse
import threading
import asyncio
from typing import List, Dict, Any, Tuple, Optional

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError, Page, Browser, BrowserContext, Playwright

START_URL = "https://tousu.sina.com.cn/"
DEFAULT_CONFIG_PATH = "config/sina_crawl.json"
STORAGE_PATH = "data/sina_storage_state.json"
DEFAULT_OUT_DIR = "data"
LOG_PATH = "output/sina_crawl.log"
SERVER_PORT = 8765

# Global Event Loop for Server Mode
LOOP = None

def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def now_ts():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def write_json(path: str, data: Any):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def write_csv(path: str, rows: List[Dict[str, Any]]):
    if not rows:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write("")
        return
    headers = list(rows[0].keys())
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def load_config(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def retry(fn, tries=3, delay=1.5):
    for i in range(tries):
        try:
            return fn()
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(delay)

async def async_retry(fn, tries=3, delay=1.5):
    for i in range(tries):
        try:
            return await fn()
        except Exception:
            if i == tries - 1:
                raise
            await asyncio.sleep(delay)


def save_outputs(data: List[Dict[str, Any]], keyword: str, fmt: str, out_dir: str) -> Tuple[str, str]:
    ensure_dir(out_dir)
    base = f"{keyword}_{now_ts()}"
    json_path = ""
    csv_path = ""
    if fmt in ("json", "both"):
        json_path = os.path.join(out_dir, f"{base}.json")
        write_json(json_path, data)
    if fmt in ("csv", "both"):
        cleaned = []
        for it in data:
            cleaned.append({
                "title": (it.get("title") or "").strip(),
                "content": (it.get("content") or "").strip(),
                "time": (it.get("time") or "").strip(),
                "href": (it.get("href") or "").strip(),
                "keyword": keyword,
            })
        csv_path = os.path.join(out_dir, f"{base}.csv")
        write_csv(csv_path, cleaned)
    return json_path, csv_path

def _normalize_href(h: str) -> str:
    s = (h or "").strip()
    if not s:
        return ""
    if s.startswith("//"):
        return "https:" + s
    if s.startswith("/"):
        return urllib.parse.urljoin("https://tousu.sina.com.cn", s)
    return s

def transform_structured(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for it in items:
        t = (it.get("title") or "").strip()
        # c = (it.get("content") or "").strip()
        href = _normalize_href(it.get("href") or "")
        tm = (it.get("time") or "").strip()
        m = re.search(r"(\d{4}-\d{2}-\d{2})", t)
        date = m.group(1) if m else tm
        t2 = t.replace("于黑猫投诉平台发起", "").strip()
        t2 = re.sub(r"^\s*\d{4}-\d{2}-\d{2}\s*", "", t2)
        lines = [x.strip() for x in t2.split("\n") if x.strip()]
        obj = ""
        demands = ""
        for ln in lines:
            mo = re.match(r"\[投诉对象\](.*)", ln)
            if mo:
                obj = mo.group(1).strip()
            md = re.match(r"\[投诉要求\](.*)", ln)
            if md:
                demands = md.group(1).strip()
        body = [ln for ln in lines if not ln.startswith("[投诉对象]") and not ln.startswith("[投诉要求]")]
        title_main = body[0] if body else ""
        summary = ""
        if len(body) > 1:
            summary = " ".join(body[1:])
        out.append({
            "date": (date or "").strip(),
            "title": title_main,
            "summary": summary,
            "object": obj,
            "demands": demands,
            # "content": c,
            "href": href,
        })
    return out

def save_structured(items: List[Dict[str, Any]], tag: str, fmt: str, out_dir: str) -> Tuple[str, str]:
    ensure_dir(out_dir)
    base = f"{tag}_structured_{now_ts()}"
    jpath = ""
    cpath = ""
    if fmt in ("json", "both"):
        jpath = os.path.join(out_dir, f"{base}.json")
        write_json(jpath, items)
    if fmt in ("csv", "both"):
        cpath = os.path.join(out_dir, f"{base}.csv")
        write_csv(cpath, items)
    return jpath, cpath

def filter_invalid(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    res = []
    seen = set()
    for it in items:
        href = _normalize_href(it.get("href") or "")
        title = (it.get("title") or "").strip()
        content = (it.get("content") or "").strip()
        if not href or not title:
            continue
        if ("tousu.sina.com.cn/complaint/view/" not in href):
            continue
        key = href
        if key in seen:
            continue
        seen.add(key)
        res.append({"title": title, "content": content, "time": (it.get("time") or "").strip(), "href": href})
    return res

class StreamSaver:
    def __init__(self, tag: str, fmt: str, out_dir: str):
        ensure_dir(out_dir)
        base = f"{tag}_{now_ts()}"
        self.csv_path = os.path.join(out_dir, f"{base}.csv") if fmt in ("csv", "both") else ""
        self.ndjson_path = os.path.join(out_dir, f"{base}.ndjson") if fmt in ("json", "both") else ""
        self.json_path = os.path.join(out_dir, f"{base}.json") if fmt in ("json", "both") else ""
        self.fmt = fmt
        self._csv_header_written = False
        self._csv_headers = ["title", "content", "time", "href", "keyword"]
        if self.csv_path:
            if not os.path.exists(self.csv_path):
                with open(self.csv_path, "w", encoding="utf-8", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=self._csv_headers)
                    w.writeheader()
                self._csv_header_written = True
            else:
                self._csv_header_written = True
        if self.ndjson_path:
            ensure_dir(os.path.dirname(self.ndjson_path))
            if not os.path.exists(self.ndjson_path):
                with open(self.ndjson_path, "w", encoding="utf-8") as f:
                    f.write("")
    def append(self, items: List[Dict[str, Any]], keyword: str):
        if not items:
            return
        if self.csv_path:
            with open(self.csv_path, "a", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=self._csv_headers)
                for it in items:
                    w.writerow({
                        "title": (it.get("title") or "").strip(),
                        "content": (it.get("content") or "").strip(),
                        "time": (it.get("time") or "").strip(),
                        "href": (it.get("href") or "").strip(),
                        "keyword": keyword,
                    })
        if self.ndjson_path:
            with open(self.ndjson_path, "a", encoding="utf-8") as f:
                for it in items:
                    f.write(json.dumps({
                        "title": (it.get("title") or "").strip(),
                        "content": (it.get("content") or "").strip(),
                        "time": (it.get("time") or "").strip(),
                        "href": (it.get("href") or "").strip(),
                        "keyword": keyword,
                    }, ensure_ascii=False) + "\n")
    def finalize(self):
        if self.ndjson_path and self.json_path:
            try:
                arr = []
                with open(self.ndjson_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        arr.append(json.loads(line))
                write_json(self.json_path, arr)
            except Exception:
                pass
        return (self.json_path if self.json_path else ""), (self.csv_path if self.csv_path else "")


def build_html() -> str:
    return (
        "<!doctype html>"
        "<html lang=\"zh\">"
        "<meta charset=\"utf-8\">"
        "<title>新浪投诉爬取工具</title>"
        "<style>"
        "body{font-family:sans-serif;margin:20px;max-width:900px}"
        ".row{display:flex;gap:10px;align-items:center;margin:6px 0}"
        "label{display:inline-block;min-width:120px;color:#333}"
        "input,select{padding:6px 8px;border:1px solid #ccc;border-radius:4px}"
        "button{margin-right:8px;padding:6px 12px;border:1px solid #0b79d0;background:#0b79d0;color:#fff;border-radius:4px}"
        "button.secondary{border-color:#777;background:#fff;color:#333}"
        "#status{margin-top:12px;color:#333;background:#f7f7f9;border:1px solid #eee;padding:8px;border-radius:4px}"
        ".mode{display:flex;gap:16px;align-items:center}"
        "</style>"
        "<body>"
        "<h3>新浪投诉爬取工具</h3>"
        "<div class=\"row mode\">"
        "  <label>模式</label>"
        "  <label><input type=\"radio\" name=\"mode\" id=\"mode_kw\" checked/> 关键词（支持多关键词）</label>"
        "  <label><input type=\"radio\" name=\"mode\" id=\"mode_url\"/> 指定链接</label>"
        "</div>"
        "<div class=\"row\" id=\"row_kw\"><label>关键词（逗号分隔）</label><input id=\"kw\" placeholder=\"示例：嗨麦科技, 众花, 马上消费金融\" value=\"\" style=\"width:420px\"/></div>"
        "<div class=\"row\" id=\"row_t\"><label>类型参数 t</label><input id=\"t\" value=\"1\" style=\"width:80px\"/></div>"
        "<div class=\"row\" id=\"row_url\" style=\"display:none\"><label>指定链接</label><input id=\"link\" placeholder=\"示例：https://tousu.sina.com.cn/company/index\" value=\"\" style=\"width:420px\"/></div>"
        "<div class=\"row\"><label>无头模式</label><input type=\"checkbox\" id=\"headless\" checked/></div>"
        "<div class=\"row\"><label>滚动间隔(秒)</label><input id=\"interval\" value=\"2.5\" style=\"width:80px\"/>"
        "  <span style=\"color:#666;margin-left:8px\">数值越大越完整，越小越快</span></div>"
        "<div class=\"row\"><label>速度优先</label><input type=\"checkbox\" id=\"fast\"/>"
        "  <span style=\"color:#666;margin-left:8px\">勾选后更快但可能略降覆盖</span></div>"
        "<div class=\"row\"><label>输出格式</label>"
        "  <select id=\"fmt\">"
        "    <option value=\"both\">both</option>"
        "    <option value=\"json\">json</option>"
        "    <option value=\"csv\">csv</option>"
        "  </select>"
        "</div>"
        "<div class=\"row\">"
        "  <button onclick=\"openLogin()\" class=\"secondary\">打开登录页面</button>"
        "  <button onclick=\"saveLogin()\" class=\"secondary\">保存登录状态</button>"
        "  <button onclick=\"startCrawl()\">开始爬取</button>"
        "  <button onclick=\"stopCrawl()\" class=\"secondary\">停止爬取</button>"
        "</div>"
        "<div id=\"status\">请先登录以保存会话状态</div>"
        "<div class=\"row\"><label>当前任务</label><span id=\"current\">-</span></div>"
        "<div class=\"row\"><label>任务进度</label><span id=\"done\">0</span>/<span id=\"total\">0</span></div>"
        "<div>当前已滑动次数：<span id=\"count\">0</span></div>"
        "<script>"
        "function init(){"
        "  fetch('/has_login').then(r=>r.json()).then(j=>{"
        "    if(j.ok && j.has){"
        "      document.getElementById('status').innerText = '已检测到登录状态：'+(j.path||'');"
        "    }else{"
        "      document.getElementById('status').innerText = '未检测到登录状态，请先登录';"
        "    }"
        "  }).catch(()=>{});"
        "}"
        "function switchMode(){"
        "  const kwMode = document.getElementById('mode_kw').checked;"
        "  document.getElementById('row_kw').style.display = kwMode ? 'flex':'none';"
        "  document.getElementById('row_t').style.display = kwMode ? 'flex':'none';"
        "  document.getElementById('row_url').style.display = kwMode ? 'none':'flex';"
        "}"
        "document.getElementById('mode_kw').addEventListener('change', switchMode);"
        "document.getElementById('mode_url').addEventListener('change', switchMode);"
        "switchMode();"
        "window.addEventListener('load', init);"
        "function openLogin(){"
        "  fetch('/open_login').then(r=>r.json()).then(j=>{"
        "    if(j.ok){"
        "      if(j.has){"
        "        document.getElementById('status').innerText = '已检测到登录状态：'+(j.path||'');"
        "      }else{"
        "        document.getElementById('status').innerText = '已打开登录页面，请在弹出的浏览器中完成登录，然后点击“保存登录状态”';"
        "      }"
        "    }else{"
        "      document.getElementById('status').innerText = '失败：'+j.err;"
        "    }"
        "  }).catch(e=>document.getElementById('status').innerText='失败：'+e);"
        "}"
        "function saveLogin(){"
        "  fetch('/save_login').then(r=>r.json()).then(j=>{"
        "    document.getElementById('status').innerText = j.ok ? ('登录状态已保存：'+j.path) : ('失败：'+j.err);"
        "  }).catch(e=>document.getElementById('status').innerText='失败：'+e);"
        "}"
        "let timer=null;"
        "function poll(){"
        "  if(timer) return;"
        "  timer = setInterval(()=>{"
        "    fetch('/progress').then(r=>r.json()).then(j=>{"
        "      if(j.count!==undefined) document.getElementById('count').innerText = j.count;"
        "      if(j.current!==undefined) document.getElementById('current').innerText = j.current || '-';"
        "      if(j.total!==undefined) document.getElementById('total').innerText = j.total || 0;"
        "      if(j.done!==undefined) document.getElementById('done').innerText = j.done || 0;"
        "      if(!j.running){"
        "        if(timer){ clearInterval(timer); timer=null; }"
        "        if(j.ok){"
        "          let s = '完成：';"
        "          if(j.csv) s += j.csv + ' ';"
        "          if(j.json) s += j.json;"
        "          document.getElementById('status').innerText = s;"
        "        }"
        "      }"
        "    }).catch(()=>{});"
        "  }, 1000);"
        "}"
        "function startCrawl(){"
        "  const kwMode = document.getElementById('mode_kw').checked;"
        "  const headless = document.getElementById('headless').checked ? '1':'0';"
        "  const interval = document.getElementById('interval').value;"
        "  const fmt = document.getElementById('fmt').value;"
        "  document.getElementById('status').innerText = '正在爬取...';"
        "  const fast = document.getElementById('fast').checked ? '1':'0';"
        "  if(kwMode){"
        "  const kw = document.getElementById('kw').value;"
        "  const t = document.getElementById('t').value;"
        "  fetch('/crawl?kw='+encodeURIComponent(kw)+'&t='+encodeURIComponent(t)+'&headless='+headless+'&interval='+encodeURIComponent(interval)+'&fmt='+encodeURIComponent(fmt)+'&fast='+fast)"
        "    .then(r=>r.json()).then(j=>{"
        "      if(j.ok){"
        "        poll();"
        "      }else{"
        "        document.getElementById('status').innerText = '失败：'+j.err;"
        "      }"
        "    }).catch(e=>document.getElementById('status').innerText='失败：'+e);"
        "  }else{"
        "    const url = document.getElementById('link').value;"
        "    if(!url){ document.getElementById('status').innerText='请填写指定链接'; return; }"
        "    fetch('/crawl_url?url='+encodeURIComponent(url)+'&headless='+headless+'&interval='+encodeURIComponent(interval)+'&fmt='+encodeURIComponent(fmt)+'&fast='+fast)"
        "      .then(r=>r.json()).then(j=>{"
        "        if(j.ok){"
        "          poll();"
        "        }else{"
        "          document.getElementById('status').innerText = '失败：'+j.err;"
        "        }"
        "      }).catch(e=>document.getElementById('status').innerText='失败：'+e);"
        "  }"
        "}"
        "function stopCrawl(){"
        "  fetch('/stop').then(r=>r.json()).then(j=>{"
        "    if(j.ok){"
        "      document.getElementById('status').innerText = '已请求停止，正在保存数据...';"
        "    }else{"
        "      document.getElementById('status').innerText = '失败：'+j.err;"
        "    }"
        "  }).catch(e=>document.getElementById('status').innerText='失败：'+e);"
        "}"
        "</script>"
        "</body>"
        "</html>"
    )


class SinaTousuCrawler:
    def __init__(self, storage_state_path: str, headless: bool, scroll_interval: float, log_path: str):
        self.storage_state_path = storage_state_path
        self.headless = headless
        self.scroll_interval = scroll_interval
        ensure_dir(os.path.dirname(log_path))
        logging.basicConfig(filename=log_path, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    async def _launch(self, persistent: bool = False, block_resources: bool = True):
        p = await async_playwright().start()
        if persistent:
            ensure_dir(os.path.dirname(self.storage_state_path))
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context()
        else:
            if os.path.exists(self.storage_state_path):
                browser = await p.chromium.launch(headless=self.headless, args=["--disable-blink-features=AutomationControlled"])
                context = await browser.new_context(storage_state=self.storage_state_path)
            else:
                browser = await p.chromium.launch(headless=self.headless, args=["--disable-blink-features=AutomationControlled"])
                context = await browser.new_context()
        if block_resources:
            try:
                async def _route_handler(route):
                    rt = route.request.resource_type
                    if rt in ("image", "font", "media"):
                        await route.abort()
                    else:
                        await route.continue_()
                await context.route("**/*", _route_handler)
            except Exception:
                pass
        return p, browser, context

    async def login_capture(self, start_url: str):
        p, browser, context = await self._launch(persistent=True, block_resources=False)
        page = await context.new_page()
        await async_retry(lambda: page.goto(start_url, timeout=60000))
        print("请在打开的浏览器页面中完成登录，然后返回终端按回车继续。")
        # Use asyncio.to_thread for input to avoid blocking if possible, but for CLI it's fine.
        await asyncio.to_thread(input)
        await context.storage_state(path=self.storage_state_path)
        await browser.close()
        await p.stop()
        print(self.storage_state_path)

    async def login_open(self, start_url: str):
        p, browser, context = await self._launch(persistent=True, block_resources=False)
        page = await context.new_page()
        await async_retry(lambda: page.goto(start_url, timeout=60000))
        return p, browser, context

    async def login_save(self, p, browser, context):
        await context.storage_state(path=self.storage_state_path)
        await browser.close()
        await p.stop()

    async def _detect_captcha(self, page) -> bool:
        try:
            if await page.locator("text=验证码").count() > 0:
                return True
            if await page.locator("iframe[src*='captcha']").count() > 0:
                return True
            if await page.locator("[class*='geetest'], [id*='geetest']").count() > 0:
                return True
        except Exception:
            return False
        return False

    async def _collect_items(self, page) -> List[Dict[str, Any]]:
        items = []
        candidates = [
            "div.search-list div.item",
            "ul.search-list li",
            "div.list-item",
            "div.item",
            "li.item",
            "div.company-list li",
            "ul.company-list li",
            "[class*='company'] li",
            "[class*='company'] .item",
        ]
        locator = None
        for sel in candidates:
            if await page.locator(sel).count() > 0:
                locator = page.locator(sel)
                break
        if locator is None:
            anchors = page.locator("a[href*='/index/'], a[href*='complaint'], a[href*='view'], a[href*='/company']")
            count = await anchors.count()
            for i in range(count):
                a = anchors.nth(i)
                href = ""
                title = ""
                try:
                    href = await a.get_attribute("href") or ""
                    title = (await a.inner_text()).strip()
                except Exception:
                    pass
                if href and title:
                    parent = a.locator("xpath=..")
                    desc = ""
                    ts = ""
                    try:
                        ptag = parent.locator("p")
                        if await ptag.count() > 0:
                            desc = (await ptag.nth(0).inner_text()).strip()
                        stime = parent.locator("text=时间, span.time, div.time, .time")
                        if await stime.count() > 0:
                            ts = (await stime.nth(0).inner_text()).strip()
                    except Exception:
                        pass
                    items.append({"title": title, "content": desc, "time": ts, "href": href})
            return items
        count = await locator.count()
        for i in range(count):
            el = locator.nth(i)
            title = ""
            desc = ""
            ts = ""
            href = ""
            try:
                t_anchor = el.locator("a")
                if await t_anchor.count() > 0:
                    href = await t_anchor.nth(0).get_attribute("href") or ""
                    title = ((await t_anchor.nth(0).text_content()) or "").strip()
                if not title:
                    t_title = el.locator("[class*='title']")
                    if await t_title.count() > 0:
                        title = ((await t_title.nth(0).text_content()) or "").strip()
                p_sel = el.locator("p, [class*='content'], [class*='cont']")
                if await p_sel.count() > 0:
                    desc = ((await p_sel.nth(0).text_content()) or "").strip()
                tt = el.locator("span.time, .time, div.time")
                if await tt.count() > 0:
                    ts = ((await tt.nth(0).text_content()) or "").strip()
            except Exception:
                pass
            if title or desc:
                items.append({"title": title, "content": desc, "time": ts, "href": href})
        return items

    async def _collect_items_fast(self, page) -> List[Dict[str, Any]]:
        try:
            return await page.evaluate("""
            (function(){
              var sels = ["div.search-list div.item","ul.search-list li","div.list-item","div.item","li.item","div.company-list li","ul.company-list li","[class*='company'] li","[class*='company'] .item"];
              var nodes = [];
              for(var i=0;i<sels.length;i++){
                var list = document.querySelectorAll(sels[i]);
                if(list && list.length){ nodes = list; break; }
              }
              var items = [];
              if(nodes && nodes.length){
                nodes.forEach(function(el){
                  var a = el.querySelector("a");
                  var href = a ? (a.href || a.getAttribute("href") || "") : "";
                  var title = a ? ((a.innerText||a.textContent)||"").trim() : ((el.innerText||el.textContent)||"").trim();
                  var p = el.querySelector("p, [class*='content'], [class*='cont']");
                  var desc = p ? ((p.innerText||p.textContent)||"").trim() : "";
                  var tt = el.querySelector("span.time, .time, div.time, [data-time]");
                  var ts = tt ? ((tt.innerText||tt.textContent)||"").trim() : "";
                  if(title || desc){
                    items.push({title:title, content:desc, time:ts, href:href});
                  }
                });
                return items;
              }
              var anchors = Array.from(document.querySelectorAll("a[href*='/index/'], a[href*='complaint'], a[href*='view'], a[href*='/company']"));
              return anchors.map(function(a){
                var href = a.href || a.getAttribute("href") || "";
                var title = ((a.innerText||a.textContent)||"").trim();
                var parent = a.parentElement;
                var desc = "";
                var ts = "";
                if(parent){
                  var p = parent.querySelector("p");
                  if(p){ desc = ((p.innerText||p.textContent)||"").trim(); }
                  var tt = parent.querySelector("span.time, .time, div.time, .time");
                  if(tt){ ts = ((tt.innerText||tt.textContent)||"").trim(); }
                }
                return {title:title, content:desc, time:ts, href:href};
              }).filter(function(x){ return x.title && (x.href || x.content); });
            })()
            """)
        except Exception:
            return await self._collect_items(page)

    async def crawl_keyword(self, keyword: str, t: int, out_dir: str, on_progress=None, should_stop=None, on_items=None, fast_mode: bool = False):
        ensure_dir(out_dir)
        ensure_dir("data")
        p, browser, context = await self._launch(persistent=False, block_resources=fast_mode)
        page = await context.new_page()
        url = f"https://tousu.sina.com.cn/index/search/?keywords={urllib.parse.quote(keyword)}&t={t}"
        await async_retry(lambda: page.goto(url, timeout=60000))
        if await self._detect_captcha(page):
            print("检测到验证码或反爬，请在打开的页面中完成验证后按回车继续。")
            await asyncio.to_thread(input)
        prev = -1
        stagnant = 0
        latest_items = []
        seen = set()
        loops = 0
        while True:
            items = await self._collect_items_fast(page)
            cur = len(items)
            latest_items = items
            new_items = []
            for it in items:
                key = (it.get("href") or "") or ((it.get("title") or "") + "|" + (it.get("time") or ""))
                if key and key not in seen:
                    seen.add(key)
                    new_items.append(it)
            logging.info("progress loads=%d count=%d keyword=%s fast=%s", loops, cur, keyword, "1" if fast_mode else "0")
            if on_progress:
                try:
                    on_progress(loops)
                except Exception:
                    pass
            # on_preview removed/ignored as it's not defined
            if should_stop and should_stop():
                break
            if cur == prev:
                stagnant += 1
            else:
                stagnant = 0
            prev = cur
            try:
                more_btn = page.locator("text=加载更多, text=加载, text=更多, [data-action='more']")
                if await more_btn.count() > 0:
                    try:
                        await more_btn.nth(0).click(timeout=3000)
                        await asyncio.sleep(self.scroll_interval)
                    except PlaywrightTimeoutError:
                        pass
            except Exception:
                pass
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(self.scroll_interval * (0.8 if fast_mode else 1.2))
            loops += 1
            if stagnant >= 2:
                break
        data = await self._collect_items(page)
        if data and on_items:
            try:
                on_items(data)
            except Exception:
                pass
        await browser.close()
        await p.stop()
        return data

    async def _extract_detail(self, page) -> Dict[str, Any]:
        title = ""
        content = ""
        ts = ""
        try:
            for sel in ["h1", "[class*='title']", ".detail-title", "header h1"]:
                loc = page.locator(sel)
                if await loc.count() > 0:
                    title = (await loc.nth(0).inner_text()).strip()
                    if title:
                        break
        except Exception:
            pass
        try:
            for sel in ["[class*='content']", "[class*='cont']", "article", ".detail-content", "div.content"]:
                loc = page.locator(sel)
                if await loc.count() > 0:
                    content = (await loc.nth(0).inner_text()).strip()
                    if content:
                        break
        except Exception:
            pass
        try:
            for sel in ["span.time", ".time", "div.time", "[data-time]"]:
                loc = page.locator(sel)
                if await loc.count() > 0:
                    ts = (await loc.nth(0).inner_text()).strip()
                    if ts:
                        break
        except Exception:
            pass
        return {"title": title, "content": content, "time": ts, "href": page.url}

    async def crawl_url(self, url: str, out_dir: str, on_progress=None, should_stop=None, on_items=None, fast_mode: bool = False):
        ensure_dir(out_dir)
        p, browser, context = await self._launch(persistent=False, block_resources=fast_mode)
        page = await context.new_page()
        await async_retry(lambda: page.goto(url, timeout=60000))
        if await self._detect_captcha(page):
            print("检测到验证码或反爬，请在打开的页面中完成验证后按回车继续。")
            await asyncio.to_thread(input)
        prev = -1
        stagnant = 0
        latest_items = []
        seen = set()
        loops = 0
        while True:
            items = await self._collect_items_fast(page)
            cur = len(items)
            if items:
                latest_items = items
            new_items = []
            for it in items:
                key = (it.get("href") or "") or ((it.get("title") or "") + "|" + (it.get("time") or ""))
                if key and key not in seen:
                    seen.add(key)
                    new_items.append(it)
            logging.info("progress loads=%d count=%d url=%s fast=%s", loops, cur, url, "1" if fast_mode else "0")
            if on_progress:
                try:
                    on_progress(loops)
                except Exception:
                    pass
            if should_stop and should_stop():
                break
            if cur == prev:
                stagnant += 1
            else:
                stagnant = 0
            prev = cur
            try:
                more_btn = page.locator("text=加载更多, text=更多, [data-action='more']")
                if await more_btn.count() > 0:
                    try:
                        await more_btn.nth(0).click(timeout=3000)
                        await asyncio.sleep(self.scroll_interval)
                    except PlaywrightTimeoutError:
                        pass
            except Exception:
                pass
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(self.scroll_interval * (0.8 if fast_mode else 1.2))
            loops += 1
            if stagnant >= 2:
                break
            if not items and stagnant >= 1:
                break
        data = latest_items if latest_items else [await self._extract_detail(page)]
        if data and on_items:
            try:
                on_items(data)
            except Exception:
                pass
        await browser.close()
        await p.stop()
        return data


def run_gui():
    # GUI implementation is not updated for Async support.
    # It requires a separate thread for the loop and complex state management.
    # Disabling for now to focus on Server.
    print("GUI mode not supported in Async version yet. Please use Server mode (no arguments).")
    pass

class AppState:
    def __init__(self):
        self.running = False
        self.count = 0
        self.finished = False
        self.stop = False
        self.csv = None
        self.json = None
        self.current = ""
        self.done = 0
        self.total = 0

def make_handler(state: AppState):
    from http.server import BaseHTTPRequestHandler
    crawler_ref = {"crawler": None, "p": None, "browser": None, "context": None}
    class Handler(BaseHTTPRequestHandler):
        def _json(self, obj: Any):
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(obj).encode("utf-8"))
        def _html(self, html: str):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
        def do_GET(self):
            from urllib.parse import urlparse, parse_qs
            u = urlparse(self.path)
            if u.path == "/":
                try:
                    index_path = os.path.join("web", "index.html")
                    if os.path.exists(index_path):
                        with open(index_path, "r", encoding="utf-8") as f:
                            html = f.read()
                        self._html(html)
                    else:
                        self._html(build_html())
                except Exception:
                    self._html(build_html())
                return
            if u.path == "/open_login":
                try:
                    if os.path.exists(STORAGE_PATH):
                        self._json({"ok": True, "has": True, "path": STORAGE_PATH})
                    else:
                        crawler = SinaTousuCrawler(STORAGE_PATH, False, 2.5, LOG_PATH)
                        # Run async login_open in the global loop
                        future = asyncio.run_coroutine_threadsafe(crawler.login_open(START_URL), LOOP)
                        p, browser, context = future.result()
                        crawler_ref["crawler"] = crawler
                        crawler_ref["p"], crawler_ref["browser"], crawler_ref["context"] = p, browser, context
                        self._json({"ok": True, "has": False})
                except Exception as e:
                    self._json({"ok": False, "err": str(e)})
                return
            if u.path == "/has_login":
                try:
                    h = os.path.exists(STORAGE_PATH)
                    res = {"ok": True, "has": h}
                    if h:
                        res["path"] = STORAGE_PATH
                    self._json(res)
                except Exception as e:
                    self._json({"ok": False, "err": str(e)})
                return
            if u.path == "/save_login":
                try:
                    c = crawler_ref["crawler"] or SinaTousuCrawler(STORAGE_PATH, False, 2.5, LOG_PATH)
                    # Run async login_save in the global loop
                    future = asyncio.run_coroutine_threadsafe(
                        c.login_save(crawler_ref["p"], crawler_ref["browser"], crawler_ref["context"]), 
                        LOOP
                    )
                    future.result()
                    crawler_ref["p"], crawler_ref["browser"], crawler_ref["context"] = None, None, None
                    self._json({"ok": True, "path": STORAGE_PATH})
                except Exception as e:
                    self._json({"ok": False, "err": str(e)})
                return
            if u.path == "/progress":
                res = {"running": state.running, "count": state.count}
                if state.finished:
                    res["ok"] = True
                    if state.csv: res["csv"] = state.csv
                    if state.json: res["json"] = state.json
                if state.current:
                    res["current"] = state.current
                if state.total:
                    res["total"] = state.total
                res["done"] = state.done
                self._json(res)
                return
            if u.path == "/stop":
                state.stop = True
                self._json({"ok": True})
                return
            if u.path == "/crawl":
                try:
                    qs = parse_qs(u.query)
                    kw_raw = (qs.get("kw", [""])[0] or "").strip()
                    kws = [x.strip() for x in re.split(r"[,;\uFF0C\u3001\\s]+", kw_raw) if x.strip()]
                    t = int(qs.get("t", ["1"])[0] or "1")
                    headless = qs.get("headless", ["1"])[0] == "1"
                    interval = float(qs.get("interval", ["2.5"])[0] or "2.5")
                    fmt = qs.get("fmt", ["both"])[0]
                    fast = qs.get("fast", ["1"])[0] == "1"
                    state.running = True
                    state.count = 0
                    state.finished = False
                    state.stop = False
                    state.csv = None
                    state.json = None
                    state.done = 0
                    state.total = len(kws) if kws else (1 if kw_raw else 0)
                    state.current = ""
                    c = SinaTousuCrawler(STORAGE_PATH, headless, interval, LOG_PATH)
                    def on_progress(n):
                        state.count = n
                    def should_stop():
                        return bool(state.stop)
                    
                    async def async_worker():
                        try:
                            csvs = []
                            jsons = []
                            targets = kws if kws else [kw_raw]
                            for kw in targets:
                                state.current = kw
                                saver = StreamSaver(tag=kw or "keyword", fmt="json", out_dir=DEFAULT_OUT_DIR)
                                state.csv = saver.csv_path or None
                                state.json = saver.json_path or None
                                def on_items(items):
                                    pass
                                data = await c.crawl_keyword(keyword=kw, t=t, out_dir=DEFAULT_OUT_DIR, on_progress=on_progress, should_stop=should_stop, on_items=on_items, fast_mode=fast)
                                data = filter_invalid(data or [])
                                saver.append(data, kw)
                                jpath, cpath = saver.finalize()
                                # 自动结构化解析
                                items = transform_structured(data)
                                js, cs = save_structured(items, kw, "csv", DEFAULT_OUT_DIR)
                                entries = []
                                if cpath: entries.append(cpath)
                                if cs: entries.append(cs)
                                if entries: csvs.append(" ".join(entries))
                                entries = []
                                if jpath: entries.append(jpath)
                                if js: entries.append(js)
                                if entries: jsons.append(" ".join(entries))
                                state.done += 1
                            if csvs: state.csv = "\n".join(csvs)
                            if jsons: state.json = "\n".join(jsons)
                            state.finished = True
                        except Exception as e:
                            logging.error(f"Crawl error: {e}")
                            state.finished = True
                        finally:
                            state.running = False

                    def worker():
                        future = asyncio.run_coroutine_threadsafe(async_worker(), LOOP)
                        try:
                            future.result()
                        except Exception as e:
                            logging.error(f"Worker thread error: {e}")

                    threading.Thread(target=worker, daemon=True).start()
                    self._json({"ok": True})
                except Exception as e:
                    self._json({"ok": False, "err": str(e)})
                return
            if u.path == "/crawl_url":
                try:
                    qs = parse_qs(u.query)
                    url = (qs.get("url", [""])[0] or "").strip()
                    if not url:
                        self._json({"ok": False, "err": "缺少参数 url"})
                        return
                    headless = qs.get("headless", ["1"])[0] == "1"
                    interval = float(qs.get("interval", ["2.5"])[0] or "2.5")
                    fmt = qs.get("fmt", ["both"])[0]
                    fast = qs.get("fast", ["1"])[0] == "1"
                    state.running = True
                    state.count = 0
                    state.finished = False
                    state.stop = False
                    state.csv = None
                    state.json = None
                    c = SinaTousuCrawler(STORAGE_PATH, headless, interval, LOG_PATH)
                    def on_progress(n):
                        state.count = n
                    def should_stop():
                        return bool(state.stop)
                    saver = StreamSaver(tag="page", fmt="json", out_dir=DEFAULT_OUT_DIR)
                    state.csv = saver.csv_path or None
                    state.json = saver.json_path or None
                    
                    async def async_worker():
                        try:
                            def on_items(items):
                                saver.append(items, "page")
                            data = await c.crawl_url(url=url, out_dir=DEFAULT_OUT_DIR, on_progress=on_progress, should_stop=should_stop, on_items=on_items, fast_mode=fast)
                            # 使用 url 的主机或路径片段作为 keyword
                            from urllib.parse import urlparse
                            up = urlparse(url)
                            kw = (up.path.strip("/").split("/")[0] or up.netloc or "page")
                            # 将最终tag与keyword统一
                            saver_final = StreamSaver(tag=kw, fmt="json", out_dir=DEFAULT_OUT_DIR)
                            saver_final.append(data, kw)
                            jpath, cpath = saver_final.finalize()
                            # 自动结构化解析（单页）
                            items = transform_structured(data)
                            js, cs = save_structured(items, kw, "csv", DEFAULT_OUT_DIR)
                            state.json = jpath or state.json
                            state.csv = ((" ".join([x for x in [cpath, cs] if x])) or state.csv)
                            state.finished = True
                        except Exception as e:
                            logging.error(f"Crawl error: {e}")
                            state.finished = True
                        finally:
                            state.running = False
                            
                    def worker():
                        future = asyncio.run_coroutine_threadsafe(async_worker(), LOOP)
                        try:
                            future.result()
                        except Exception as e:
                            logging.error(f"Worker thread error: {e}")

                    threading.Thread(target=worker, daemon=True).start()
                    self._json({"ok": True})
                except Exception as e:
                    self._json({"ok": False, "err": str(e)})
                return
            if u.path == "/transform":
                try:
                    qs = parse_qs(u.query)
                    path = (qs.get("path", [""])[0] or "").strip()
                    fmt = qs.get("fmt", ["both"])[0]
                    out_dir = qs.get("out_dir", [DEFAULT_OUT_DIR])[0]
                    if not path or not os.path.exists(path):
                        self._json({"ok": False, "err": "文件不存在"})
                        return
                    with open(path, "r", encoding="utf-8") as f:
                        arr = json.load(f)
                    if not isinstance(arr, list):
                        self._json({"ok": False, "err": "数据格式错误"})
                        return
                    items = transform_structured(arr)
                    base_tag = os.path.splitext(os.path.basename(path))[0]
                    jpath, cpath = save_structured(items, base_tag, fmt, out_dir)
                    self._json({"ok": True, "json": jpath, "csv": cpath})
                except Exception as e:
                    self._json({"ok": False, "err": str(e)})
                return
            self.send_response(404)
            self.end_headers()
    return Handler

def run_server():
    from http.server import HTTPServer
    import webbrowser
    ensure_dir(DEFAULT_OUT_DIR)
    ensure_dir(os.path.dirname(LOG_PATH))
    
    # Initialize global loop
    global LOOP
    LOOP = asyncio.new_event_loop()
    def loop_runner():
        asyncio.set_event_loop(LOOP)
        LOOP.run_forever()
    threading.Thread(target=loop_runner, daemon=True).start()
    
    state = AppState()
    server = HTTPServer(("127.0.0.1", SERVER_PORT), make_handler(state))
    url = f"http://127.0.0.1:{SERVER_PORT}/"
    print(url)
    try:
        webbrowser.open(url)
    except Exception:
        pass
    server.serve_forever()

async def async_main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["login", "crawl"], default="crawl")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--keyword", default="")
    parser.add_argument("--t", type=int, default=1)
    parser.add_argument("--format", choices=["json", "csv", "both"], default="both")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--scroll_interval", type=float, default=2.5)
    parser.add_argument("--storage_state", default=STORAGE_PATH)
    parser.add_argument("--out_dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--log_path", default=LOG_PATH)
    args = parser.parse_args()

    cfg = load_config(args.config)
    keyword = args.keyword or (cfg.get("keywords", [""])[0] if cfg.get("keywords") else "")
    headless = args.headless or bool(cfg.get("headless", True))
    crawler = SinaTousuCrawler(storage_state_path=args.storage_state, headless=headless, scroll_interval=args.scroll_interval, log_path=args.log_path)

    if args.mode == "login":
        await crawler.login_capture(START_URL)
        return
    if not os.path.exists(args.storage_state):
        print("未发现已登录的会话状态文件，先执行登录流程。")
        await crawler.login_capture(START_URL)
    data = await crawler.crawl_keyword(keyword=keyword or "", t=args.t, out_dir=args.out_dir)
    jpath, cpath = save_outputs(data, keyword or "", args.format, args.out_dir)
    if args.format == "json":
        print(jpath)
    elif args.format == "csv":
        print(cpath)
    else:
        print(f"{jpath} {cpath}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        asyncio.run(async_main())
    else:
        run_server()
