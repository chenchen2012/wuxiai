#!/usr/bin/env python3
import hashlib
import html
import json
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUTPUT_PATH = os.path.join(ROOT_DIR, "index.html")
DATA_PATH = os.path.join(ROOT_DIR, "data.json")
ROBOTS_PATH = os.path.join(ROOT_DIR, "robots.txt")
SITEMAP_PATH = os.path.join(ROOT_DIR, "sitemap.xml")

CST = timezone(timedelta(hours=8))
USER_AGENT = "Mozilla/5.0 (compatible; WuxiAINewsBot/2.0; +https://wuxiai.com/)"
FETCH_TIMEOUT_SECONDS = 10
MAX_WORKERS = 8
MAX_ITEMS = 12
MAX_PER_SOURCE_ON_PAGE = 3
MAX_PER_FEED = 20
CACHE_LIMIT = 120

KEYWORDS = [
    "无锡 人工智能",
    "无锡 AI",
    "无锡AI",
    "Wuxi AI",
    "无锡 大模型",
]

TRUSTED_DOMAINS = [
    "xinhuanet.com",
    "chinanews.com.cn",
    "thepaper.cn",
    "people.com.cn",
    "xhby.net",
    "cctv.com",
    "yzwb.net",
    "wuxi.gov.cn",
    "jiangsu.gov.cn",
    "news.jiangnan.edu.cn",
]

PRIORITY_SITE_FILTERS = [
    "xinhuanet.com",
    "chinanews.com.cn",
    "thepaper.cn",
    "people.com.cn",
    "xhby.net",
    "yzwb.net",
]

BLOCKED_DOMAINS = [
    "news.google.com",
    "bing.com",
    "toutiao.com",
    "sohu.com",
    "163.com",
]

TRUSTED_SOURCE_KEYWORDS = [
    "新华网",
    "人民网",
    "中国新闻网",
    "澎湃",
    "新华报业网",
    "紫牛新闻",
    "江南大学新闻网",
    "央视网",
]

BLOCKED_SOURCE_KEYWORDS = [
    "广告",
    "推广",
    "赞助",
    "营销",
    "百家号",
    "搜狐号",
]

AD_KEYWORDS = [
    "广告",
    "推广",
    "赞助",
    "招商",
    "代理",
    "课程报名",
    "优惠",
    "折扣",
    "限时",
    "团购",
    "邀请码",
    "加微信",
    "vx",
]

RELEVANCE_KEYWORDS = [
    "无锡",
    "wuxi",
    "江阴",
    "宜兴",
    "江苏",
    "jiangsu",
    "江南大学",
]

LOCATION_KEYWORDS = [
    "无锡",
    "wuxi",
    "江阴",
    "宜兴",
]

AI_TOPIC_KEYWORDS = [
    "人工智能",
    "大模型",
    "算力",
    "机器人",
    "机器学习",
    "智能体",
    "aigc",
    "算法",
]


def build_bing_rss_url(keyword: str) -> str:
    encoded = urllib.parse.quote(keyword)
    return f"https://www.bing.com/news/search?q={encoded}&format=RSS&setlang=zh-hans"


FEED_SOURCES = []
for kw in KEYWORDS:
    FEED_SOURCES.append((f"bing:{kw}", build_bing_rss_url(kw)))
    for site in PRIORITY_SITE_FILTERS:
        scoped_kw = f"{kw} site:{site}"
        FEED_SOURCES.append((f"bing:{kw}:{site}", build_bing_rss_url(scoped_kw)))


def fetch_url(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SECONDS) as resp:
        return resp.read()


def normalize_domain(url: str) -> str:
    try:
        netloc = urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return ""
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def domain_matches(domain: str, pattern: str) -> bool:
    return domain == pattern or domain.endswith("." + pattern)


def is_trusted_domain(domain: str) -> bool:
    return any(domain_matches(domain, pattern) for pattern in TRUSTED_DOMAINS)


def is_blocked_domain(domain: str) -> bool:
    return any(domain_matches(domain, pattern) for pattern in BLOCKED_DOMAINS)


def is_ad_title(title: str) -> bool:
    lt = (title or "").strip().lower()
    return any(k in lt for k in AD_KEYWORDS)


def is_trusted_source(source: str) -> bool:
    s = (source or "").strip()
    return any(k in s for k in TRUSTED_SOURCE_KEYWORDS)


def is_blocked_source(source: str) -> bool:
    s = (source or "").strip()
    return any(k in s for k in BLOCKED_SOURCE_KEYWORDS)


def is_relevant(item: dict) -> bool:
    text = " ".join(
        [
            str(item.get("title", "")),
            str(item.get("url", "")),
            str(item.get("source", "")),
        ]
    ).lower()
    return any(k in text for k in RELEVANCE_KEYWORDS)


def is_wuxi_ai_topic(item: dict) -> bool:
    text = str(item.get("title", "")).lower()
    has_location = any(k in text for k in LOCATION_KEYWORDS)
    has_ai_topic = any(k in text for k in AI_TOPIC_KEYWORDS) or bool(
        re.search(r"(?<![a-z0-9])ai(?![a-z0-9])", text)
    )
    return has_location and has_ai_topic


def clean_url(url: str) -> str:
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return url.strip()
    if not parsed.scheme or not parsed.netloc:
        return url.strip()

    query_items = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    kept = []
    for k, v in query_items:
        lk = k.lower()
        if lk.startswith("utm_") or lk in {"spm", "from", "ref", "source", "cmpid"}:
            continue
        kept.append((k, v))

    return urllib.parse.urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path,
            parsed.params,
            urllib.parse.urlencode(kept, doseq=True),
            "",
        )
    )


def parse_time_to_iso(pub_date: str) -> str:
    if not pub_date:
        return ""
    try:
        dt = parsedate_to_datetime(pub_date)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(CST).isoformat()
    except Exception:
        return ""


def format_cst_time(iso_time: str) -> str:
    if not iso_time:
        return "时间未知"
    try:
        dt = datetime.fromisoformat(iso_time)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=CST)
        return dt.astimezone(CST).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "时间未知"


def normalize_title(title: str) -> str:
    t = html.unescape(title or "").strip().lower()
    t = re.sub(r"\s+", " ", t)
    if " - " in t:
        parts = t.split(" - ")
        if len(parts[-1]) <= 12:
            t = " - ".join(parts[:-1])
    t = re.sub(r"[^\w\u4e00-\u9fff]+", "", t)
    return t


def item_fingerprint(title: str, url: str) -> str:
    t = normalize_title(title)
    domain = normalize_domain(url)
    return hashlib.sha1(f"{t}|{domain}".encode("utf-8")).hexdigest()


def extract_direct_url(link: str) -> str:
    parsed = urllib.parse.urlparse(link)
    domain = normalize_domain(link)
    if domain == "bing.com" and parsed.path.endswith("/news/apiclick.aspx"):
        qs = urllib.parse.parse_qs(parsed.query)
        direct = (qs.get("url") or [""])[0].strip()
        if direct.startswith("http://") or direct.startswith("https://"):
            return clean_url(direct)
    return clean_url(link)


def parse_feed(feed_name: str, xml_bytes: bytes) -> list[dict]:
    items = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return items

    channel = root.find("channel")
    if channel is None:
        return items

    for item in channel.findall("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        direct_url = extract_direct_url(link)
        source = ""

        source_el = item.find("source")
        if source_el is not None and source_el.text:
            source = source_el.text.strip()

        if not source:
            source = normalize_domain(direct_url) or feed_name

        pub_date = (item.findtext("pubDate") or "").strip()
        published_at = parse_time_to_iso(pub_date)

        if not title or not link:
            continue

        items.append(
            {
                "title": title,
                "url": direct_url,
                "source": source,
                "published_at": published_at,
                "feed": feed_name,
            }
        )
        if len(items) >= MAX_PER_FEED:
            break

    return items


def load_existing_items() -> list[dict]:
    if not os.path.exists(DATA_PATH):
        return []
    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    items = data.get("items")
    return items if isinstance(items, list) else []


def dedupe_items(items: list[dict]) -> list[dict]:
    by_fp = {}
    seen_urls = set()

    for item in items:
        title = str(item.get("title", "")).strip()
        url = clean_url(str(item.get("url", "")).strip())
        domain = normalize_domain(url)
        source = str(item.get("source", "")).strip()
        if not title or not (url.startswith("http://") or url.startswith("https://")):
            continue
        if not domain or is_blocked_domain(domain) or is_blocked_source(source):
            continue
        if is_ad_title(title):
            continue
        if not is_relevant(item):
            continue
        if not is_wuxi_ai_topic(item):
            continue

        fp = item_fingerprint(title, url)
        item["fingerprint"] = fp
        item["url"] = url
        item["domain"] = domain
        item["trusted"] = is_trusted_domain(domain) or is_trusted_source(source)

        if url in seen_urls:
            continue
        seen_urls.add(url)

        prev = by_fp.get(fp)
        if prev is None:
            by_fp[fp] = item
            continue

        prev_time = prev.get("published_at", "")
        cur_time = item.get("published_at", "")
        if cur_time and (not prev_time or cur_time > prev_time):
            by_fp[fp] = item

    deduped = list(by_fp.values())
    deduped.sort(
        key=lambda x: (1 if x.get("trusted") else 0, x.get("published_at", "")),
        reverse=True,
    )
    return deduped


def write_data_json(items: list[dict]) -> None:
    payload = {
        "updated_at": datetime.now(CST).isoformat(),
        "item_count": len(items),
        "items": items,
    }
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def write_seo_files(updated_iso: str) -> None:
    updated_date = updated_iso[:10] if updated_iso else datetime.now(CST).strftime("%Y-%m-%d")
    robots = "\n".join(
        [
            "User-agent: *",
            "Allow: /",
            "",
            "Sitemap: https://wuxiai.com/sitemap.xml",
            "",
        ]
    )
    sitemap = "\n".join(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
            "  <url>",
            "    <loc>https://wuxiai.com/</loc>",
            f"    <lastmod>{updated_date}</lastmod>",
            "    <changefreq>hourly</changefreq>",
            "    <priority>1.0</priority>",
            "  </url>",
            "  <url>",
            "    <loc>https://wuxiai.com/contact.html</loc>",
            f"    <lastmod>{updated_date}</lastmod>",
            "    <changefreq>monthly</changefreq>",
            "    <priority>0.6</priority>",
            "  </url>",
            "</urlset>",
            "",
        ]
    )
    with open(ROBOTS_PATH, "w", encoding="utf-8") as f:
        f.write(robots)
    with open(SITEMAP_PATH, "w", encoding="utf-8") as f:
        f.write(sitemap)


def build_html(items: list[dict]) -> str:
    now_iso = datetime.now(CST).isoformat()
    seo_json_ld = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "CollectionPage",
            "name": "无锡AI",
            "url": "https://wuxiai.com/",
            "inLanguage": "zh-CN",
            "description": "无锡AI新闻与无锡人工智能新闻聚合，聚焦无锡与人工智能相关资讯。",
            "isPartOf": {
                "@type": "WebSite",
                "name": "无锡AI",
                "url": "https://wuxiai.com/",
            },
        },
        ensure_ascii=False,
    )
    display_items = []
    source_counts = {}
    for item in items:
        src = str(item.get("source", "未知来源")).strip() or "未知来源"
        if source_counts.get(src, 0) >= MAX_PER_SOURCE_ON_PAGE:
            continue
        source_counts[src] = source_counts.get(src, 0) + 1
        display_items.append(item)
        if len(display_items) >= MAX_ITEMS:
            break

    lines = [
        "<!doctype html>",
        '<html lang="zh-CN">',
        "<head>",
        '  <meta charset="utf-8">',
        '  <meta name="viewport" content="width=device-width, initial-scale=1">',
        '  <meta name="description" content="无锡AI新闻与无锡人工智能新闻聚合，聚焦无锡与人工智能相关资讯。">',
        '  <meta name="keywords" content="无锡AI新闻, 无锡人工智能新闻, 无锡AI, 无锡人工智能">',
        '  <meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1,max-video-preview:-1">',
        '  <meta name="applicable-device" content="pc,mobile">',
        '  <meta name="renderer" content="webkit">',
        '  <link rel="canonical" href="https://wuxiai.com/">',
        '  <meta property="og:type" content="website">',
        '  <meta property="og:locale" content="zh_CN">',
        '  <meta property="og:site_name" content="无锡AI">',
        '  <meta property="og:title" content="无锡AI">',
        '  <meta property="og:description" content="无锡AI新闻与无锡人工智能新闻聚合，聚焦无锡与人工智能相关资讯。">',
        '  <meta property="og:url" content="https://wuxiai.com/">',
        '  <meta name="twitter:card" content="summary">',
        '  <meta name="twitter:title" content="无锡AI">',
        '  <meta name="twitter:description" content="无锡AI新闻与无锡人工智能新闻聚合，聚焦无锡与人工智能相关资讯。">',
        f'  <meta property="article:modified_time" content="{html.escape(now_iso)}">',
        "  <title>无锡AI</title>",
        f'  <script type="application/ld+json">{seo_json_ld}</script>',
        "  <style>",
        "    :root { --bg: #f5f7fb; --paper: #ffffff; --text: #1f2937; --muted: #6b7280; --line: #e5e7eb; --brand: #1d4ed8; }",
        "    * { box-sizing: border-box; }",
        "    body { margin: 0; background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', sans-serif; line-height: 1.7; }",
        "    main { max-width: 920px; margin: 28px auto; padding: 0 16px; }",
        "    .card { background: var(--paper); border: 1px solid var(--line); border-radius: 14px; padding: 22px 22px 16px; box-shadow: 0 8px 24px rgba(16, 24, 40, 0.04); }",
        "    h1 { margin: 0; font-size: 30px; letter-spacing: 0.2px; }",
        "    .meta { color: var(--muted); margin: 8px 0 16px; font-size: 14px; }",
        "    .intro { margin: 0 0 18px; color: #374151; font-size: 15px; }",
        "    ul { margin: 0; padding-left: 18px; }",
        "    li { margin: 11px 0; }",
        "    a { color: var(--brand); text-decoration: none; }",
        "    a:hover { text-decoration: underline; }",
        "    .src { color: var(--muted); font-size: 13px; }",
        "    .contact { margin-top: 18px; padding-top: 14px; border-top: 1px solid var(--line); color: #4b5563; font-size: 14px; }",
        "    .footer-nav { display: flex; flex-wrap: wrap; gap: 12px 20px; align-items: center; }",
        "    .footer-label { color: #6b7280; margin-right: 6px; }",
        "    .friend-links { display: inline-flex; gap: 10px; }",
        "  </style>",
        "</head>",
        "<body>",
        "  <main>",
        '  <section class="card">',
        "  <h1>无锡AI</h1>",
        '  <p class="meta">自动更新，仅提供标题与原文链接。</p>',
        '  <p class="intro">聚合无锡AI新闻、无锡人工智能新闻，重点关注无锡本地人工智能产业、技术与应用动态。</p>',
    ]

    if not items:
        lines.append("  <p>暂无可展示的新闻，请稍后再试。</p>")
    else:
        lines.append("  <ul>")
        for news in display_items:
            title = html.escape(str(news.get("title", "")))
            source = html.escape(str(news.get("source", "未知来源")))
            pub_date = html.escape(format_cst_time(str(news.get("published_at", ""))))
            url = html.escape(str(news.get("url", "")), quote=True)
            lines.append(
                f'    <li><a href="{url}" target="_blank" rel="noopener noreferrer">{title}</a><br><span class="src">{source} | {pub_date}</span></li>'
            )
        lines.append("  </ul>")

    lines.extend(
        [
            '  <div class="contact">',
            '    <div class="footer-nav"><span><span class="footer-label">联系</span><a href="/contact.html">联系方式</a></span><span><span class="footer-label">友情链接</span><span class="friend-links"><a href="https://robot.tv" target="_blank" rel="noopener noreferrer">robot.tv</a><a href="https://aild.org" target="_blank" rel="noopener noreferrer">aild.org</a></span></span></div>',
            "  </div>",
            "  </section>",
            "  </main>",
            "</body>",
            "</html>",
            "",
        ]
    )
    return "\n".join(lines)


def collect_items() -> list[dict]:
    raw_items = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(fetch_url, url): (name, url)
            for name, url in FEED_SOURCES
        }
        for future in as_completed(futures):
            name, _ = futures[future]
            try:
                xml_bytes = future.result()
            except Exception:
                continue
            raw_items.extend(parse_feed(name, xml_bytes))

    existing = load_existing_items()
    merged = dedupe_items(raw_items + existing)
    return merged[:CACHE_LIMIT]


def main():
    items = collect_items()
    updated_iso = datetime.now(CST).isoformat()
    write_data_json(items)
    write_seo_files(updated_iso)
    html_content = build_html(items)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html_content)


if __name__ == "__main__":
    main()
