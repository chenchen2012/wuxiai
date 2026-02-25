#!/usr/bin/env python3
import html
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUTPUT_PATH = os.path.join(ROOT_DIR, "index.html")
RSS_URL = (
    "https://news.google.com/rss/search"
    "?q=%E6%97%A0%E9%94%A1+%E4%BA%BA%E5%B7%A5%E6%99%BA%E8%83%BD"
    "&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
)
MAX_ITEMS = 8
MAX_CANDIDATES = 8
FETCH_TIMEOUT_SECONDS = 12
DECODE_TIMEOUT_SECONDS = 6

CST = timezone(timedelta(hours=8))


def fetch_url(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; WuxiAINewsBot/1.0; +https://github.com/)"
        },
    )
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SECONDS) as resp:
        return resp.read()


def resolve_final_url(link: str) -> str:
    code = (
        "from googlenewsdecoder import new_decoderv1; import json,sys; "
        "u=sys.argv[1]; "
        "r=new_decoderv1(u, interval=0); "
        "print(json.dumps(r, ensure_ascii=False))"
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code, link],
            capture_output=True,
            text=True,
            timeout=DECODE_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return ""
    if proc.returncode != 0 or not proc.stdout.strip():
        return ""
    try:
        decoded = json.loads(proc.stdout.strip())
    except json.JSONDecodeError:
        return ""
    final_url = str((decoded or {}).get("decoded_url", "")).strip()
    return final_url


def is_google_domain(url: str) -> bool:
    netloc = urllib.parse.urlparse(url).netloc.lower()
    return (
        netloc.endswith("google.com")
        or netloc.endswith("google.com.hk")
        or netloc.endswith("news.google.com")
        or netloc.endswith("googleusercontent.com")
    )


def to_local_time(pub_date: str) -> str:
    if not pub_date:
        return ""
    try:
        dt = parsedate_to_datetime(pub_date)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(CST).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return pub_date


def parse_rss(rss_xml: bytes):
    root = ET.fromstring(rss_xml)
    channel = root.find("channel")
    if channel is None:
        return []

    candidates = []
    seen = set()

    for item in channel.findall("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        source = ""
        source_el = item.find("source")
        if source_el is not None and source_el.text:
            source = source_el.text.strip()
        pub_date = (item.findtext("pubDate") or "").strip()

        if not title or not link:
            continue

        candidates.append(
            {
                "title": title,
                "link": link,
                "source": source or "未知来源",
                "pub_date": to_local_time(pub_date),
            }
        )
        if len(candidates) >= MAX_CANDIDATES:
            break

    items = []
    for candidate in candidates:
        try:
            final_url = resolve_final_url(candidate["link"])
        except Exception:
            continue
        if not (final_url.startswith("http://") or final_url.startswith("https://")):
            continue
        if is_google_domain(final_url):
            continue
        if final_url in seen:
            continue
        seen.add(final_url)
        items.append(
            {
                "title": candidate["title"],
                "source": candidate["source"],
                "pub_date": candidate["pub_date"],
                "url": final_url,
            }
        )
        if len(items) >= MAX_ITEMS:
            break

    return items


def build_html(items):
    now_text = datetime.now(CST).strftime("%Y-%m-%d %H:%M")

    lines = [
        "<!doctype html>",
        '<html lang="zh-CN">',
        "<head>",
        '  <meta charset="utf-8">',
        '  <meta name="viewport" content="width=device-width, initial-scale=1">',
        "  <title>无锡人工智能新闻</title>",
        "  <style>",
        "    body { font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', sans-serif; max-width: 900px; margin: 24px auto; padding: 0 16px; line-height: 1.7; color: #111; }",
        "    h1 { margin: 0 0 8px; font-size: 28px; }",
        "    .meta { color: #666; margin: 0 0 20px; font-size: 14px; }",
        "    ul { padding-left: 18px; }",
        "    li { margin: 10px 0; }",
        "    a { color: #0b57d0; text-decoration: none; }",
        "    a:hover { text-decoration: underline; }",
        "    .src { color: #666; font-size: 14px; }",
        "    .contact { margin-top: 24px; padding-top: 12px; border-top: 1px solid #ddd; color: #444; font-size: 14px; }",
        "  </style>",
        "</head>",
        "<body>",
        "  <h1>无锡人工智能新闻</h1>",
        f"  <p class=\"meta\">定时更新，仅提供标题与原文链接。最后更新：{html.escape(now_text)}（北京时间）</p>",
    ]

    if not items:
        lines.append("  <p>暂无可展示的新闻，请稍后再试。</p>")
    else:
        lines.append("  <ul>")
        for news in items:
            title = html.escape(news["title"])
            source = html.escape(news["source"])
            pub_date = html.escape(news["pub_date"])
            url = html.escape(news["url"], quote=True)
            lines.append(
                f'    <li><a href="{url}" target="_blank" rel="noopener noreferrer">{title}</a><br><span class="src">{source} | {pub_date}</span></li>'
            )
        lines.append("  </ul>")

    lines.extend(
        [
            '  <div class="contact">',
            '    联系方式：chenchen2012 [at] hotmail.com | 微信：359959667（请注明来源） | <a href="/contact.html">联系页面</a> | 友情链接：<a href="https://robot.tv" target="_blank" rel="noopener noreferrer">robot.tv</a>、<a href="https://aild.org" target="_blank" rel="noopener noreferrer">aild.org</a>',
            "  </div>",
        ]
    )

    lines.extend(
        [
            "</body>",
            "</html>",
            "",
        ]
    )
    return "\n".join(lines)


def main():
    rss = fetch_url(RSS_URL)
    items = parse_rss(rss)
    html_content = build_html(items)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html_content)


if __name__ == "__main__":
    main()
