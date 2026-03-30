#!/usr/bin/env python3
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from typing import Optional

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUTPUT_PATH = os.path.join(ROOT_DIR, "index.html")
HISTORY_PATH = os.path.join(ROOT_DIR, "history.html")
DATA_PATH = os.path.join(ROOT_DIR, "data.json")
ROBOTS_PATH = os.path.join(ROOT_DIR, "robots.txt")
SITEMAP_PATH = os.path.join(ROOT_DIR, "sitemap.xml")
HISTORY_PAGE_PREFIX = "history-page-"
COMPANY_DIR = os.path.join(ROOT_DIR, "company")
TOPIC_DIR = os.path.join(ROOT_DIR, "topic")
REGION_DIR = os.path.join(ROOT_DIR, "region")
WEEKLY_DIR = os.path.join(ROOT_DIR, "weekly")
SUBMIT_DIR = os.path.join(ROOT_DIR, "submit")

CST = timezone(timedelta(hours=8))
USER_AGENT = "Mozilla/5.0 (compatible; WuxiAINewsBot/3.0; +https://wuxiai.com/)"
FETCH_TIMEOUT_SECONDS = 12
ARTICLE_FETCH_TIMEOUT_SECONDS = 10
DECODE_TIMEOUT_SECONDS = 2.2
MAX_WORKERS = 8
ARTICLE_REVIEW_WORKERS = 4
MAX_ITEMS = 12
MAX_PER_SOURCE_ON_PAGE = 3
MAX_PER_FEED = 20
CACHE_LIMIT = 120
MAX_GOOGLE_DECODE_ITEMS = 120
MAX_CONTENT_REVIEW_ITEMS = 64
ARTICLE_CONTEXT_LIMIT = 9000


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


TITLE_SIMILARITY_THRESHOLD = env_float("WUXIAI_DUPLICATE_TITLE_SIMILARITY", 0.88)
CONTENT_SIMILARITY_THRESHOLD = env_float("WUXIAI_CONTENT_SIMILARITY_THRESHOLD", 0.82)
MIN_RELEVANCE_SCORE = env_int("WUXIAI_MIN_RELEVANCE_SCORE", 8)
MIN_EXTRACTED_CONTENT_LENGTH = env_int("WUXIAI_MIN_EXTRACTED_CONTENT_LENGTH", 180)
SUMMARY_MIN_CONTENT_LENGTH = env_int("WUXIAI_SUMMARY_MIN_CONTENT_LENGTH", 260)
SUMMARY_MAX_INPUT_CHARS = env_int("WUXIAI_SUMMARY_MAX_INPUT_CHARS", 3200)
MAX_ITEM_AGE_DAYS = env_int("WUXIAI_MAX_ITEM_AGE_DAYS", 45)
MAX_EXISTING_ITEM_AGE_DAYS = env_int("WUXIAI_MAX_EXISTING_ITEM_AGE_DAYS", 21)
STALE_WEAK_ITEM_AGE_DAYS = env_int("WUXIAI_STALE_WEAK_ITEM_AGE_DAYS", 10)
FRESHNESS_HALF_LIFE_DAYS = env_float("WUXIAI_FRESHNESS_HALF_LIFE_DAYS", 3.5)
SUMMARY_RECENT_BACKFILL_DAYS = env_int("WUXIAI_SUMMARY_BACKFILL_RECENT_DAYS", 7)
MAX_SUMMARY_ITEMS_PER_RUN = env_int("WUXIAI_MAX_SUMMARY_ITEMS_PER_RUN", 8)
SUMMARY_WORKERS = env_int("WUXIAI_SUMMARY_WORKERS", 2)
MAX_FEED_SOURCES = env_int("WUXIAI_MAX_FEED_SOURCES", 96)
SUMMARY_ENABLED = env_bool("WUXIAI_ENABLE_SUMMARY", True)
SUMMARY_NEW_ONLY = env_bool("WUXIAI_SUMMARY_ONLY_NEW", True)
SUMMARY_BULK_BACKFILL = env_bool("WUXIAI_SUMMARY_BULK_BACKFILL", False)

SUMMARY_PROVIDER = (os.getenv("WUXIAI_LLM_PROVIDER", "deepseek") or "deepseek").strip().lower()
LLM_API_KEY = os.getenv("WUXIAI_LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or ""
LLM_BASE_URL = (
    os.getenv("WUXIAI_LLM_BASE_URL")
    or os.getenv("DEEPSEEK_BASE_URL")
    or "https://api.deepseek.com"
).rstrip("/")
LLM_MODEL = (
    os.getenv("WUXIAI_LLM_MODEL")
    or os.getenv("DEEPSEEK_MODEL")
    or "deepseek-chat"
).strip()
ENTITY_EXTRACTION_ENABLED = (os.getenv("WUXIAI_ENABLE_ENTITY_EXTRACTION", "true") or "true").strip().lower() not in {"0", "false", "no", "off"}
MAX_ENTITY_EXTRACTION_ITEMS_PER_RUN = int(os.getenv("WUXIAI_MAX_ENTITY_EXTRACTION_ITEMS_PER_RUN", "6") or 6)
ENTITY_EXTRACTION_MIN_CONTENT_LENGTH = int(os.getenv("WUXIAI_ENTITY_EXTRACTION_MIN_CONTENT_LENGTH", "220") or 220)
ENTITY_EXTRACTION_RECENT_BACKFILL_DAYS = int(os.getenv("WUXIAI_ENTITY_EXTRACTION_RECENT_BACKFILL_DAYS", "30") or 30)
GITHUB_REPO = (os.getenv("WUXIAI_GITHUB_REPO") or "chenchen2012/wuxiai").strip()
GITHUB_TOKEN = os.getenv("WUXIAI_GITHUB_TOKEN") or os.getenv("GITHUB_TOKEN") or ""

CHINA_NEWS_SITE_FILTERS = [
    "news.cn",
    "people.com.cn",
    "chinanews.com.cn",
    "thepaper.cn",
    "cnr.cn",
    "xhby.net",
    "yzwb.net",
    "wxrb.com",
    "subaonet.com",
]

EXPANDED_SITE_FILTERS = [
    "xinhuanet.com",
    "jiangsu.gov.cn",
    "wuxi.gov.cn",
    "suzhou.gov.cn",
    "yangtse.com",
    "news.jiangnan.edu.cn",
    "cs.com.cn",
]

TOPIC_GROUPS = [
    {
        "name": "无锡人工智能",
        "keywords": [
            "无锡人工智能",
            "无锡 AI",
            "无锡AI",
            "无锡 机器人",
            "无锡 具身智能",
            "无锡 智能制造 AI",
            "无锡 工业AI",
            "无锡 机器视觉",
            "无锡 人形机器人",
        ],
    },
    {
        "name": "苏州人工智能",
        "keywords": [
            "苏州人工智能",
            "苏州 AI",
            "苏州AI",
            "苏州 机器人",
            "苏州 工业机器人",
            "苏州 具身智能",
            "苏州 工业AI",
            "苏州 机器视觉",
            "苏州 人形机器人",
        ],
    },
    {
        "name": "长三角人工智能",
        "keywords": [
            "长三角 人工智能",
            "长三角 AI",
            "长三角 机器人",
            "长三角 智能制造",
            "长三角 具身智能",
            "长三角 工业AI",
            "长三角 机器视觉",
            "长三角 人形机器人",
        ],
    },
]

TRUSTED_DOMAINS = [
    "xinhuanet.com",
    "news.cn",
    "chinanews.com.cn",
    "thepaper.cn",
    "people.com.cn",
    "cctv.com",
    "cnr.cn",
    "china.com.cn",
    "gmw.cn",
    "ce.cn",
    "cyol.com",
    "paper.people.com.cn",
    "xhby.net",
    "yzwb.net",
    "wuxi.gov.cn",
    "jiangsu.gov.cn",
    "suzhou.gov.cn",
    "news.jiangnan.edu.cn",
    "jschina.com.cn",
    "wxrb.com",
    "yangtse.com",
    "jstv.com",
    "china.org.cn",
    "subaonet.com",
]

BLOCKED_DOMAINS = [
    "news.google.com",
    "bing.com",
    "sohu.com",
    "163.com",
    "toutiao.com",
]

QUALIFIED_NEWS_DOMAINS = [
    "news.qq.com",
    "view.inews.qq.com",
    "finance.sina.com.cn",
    "news.sina.com.cn",
    "ifeng.com",
    "caixin.com",
    "stcn.com",
    "cls.cn",
]

TRUSTED_SOURCE_KEYWORDS = [
    "新华网",
    "中国新闻网",
    "央视网",
    "央广网",
    "光明网",
    "中国网",
    "经济日报",
    "中国青年报",
    "人民网",
    "澎湃",
    "新华报业网",
    "紫牛新闻",
    "江南大学新闻网",
    "无锡日报",
    "无锡观察",
    "苏州日报",
    "引力播",
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
    "直播带货",
]

PRIMARY_REGIONS = {
    "无锡": {
        "aliases": ["无锡", "wuxi", "江阴", "宜兴", "新吴区", "滨湖区", "梁溪区", "锡山区", "惠山区", "经开区", "江南大学"],
        "weight": 7,
        "tags": ["无锡", "无锡AI", "无锡机器人"],
    },
    "苏州": {
        "aliases": ["苏州", "suzhou", "昆山", "常熟", "张家港", "太仓", "吴江", "相城", "工业园区", "苏州工业园区"],
        "weight": 7,
        "tags": ["苏州", "苏州AI", "苏州机器人"],
    },
    "长三角": {
        "aliases": ["长三角", "yangtze river delta", "江浙沪", "沪苏浙皖", "一体化示范区"],
        "weight": 4,
        "tags": ["长三角", "区域协同"],
    },
}

AI_CORE_KEYWORDS = {
    "人工智能": 5,
    "ai": 4,
    "机器人": 5,
    "具身智能": 6,
    "大模型": 5,
    "智能体": 4,
    "算法": 2,
    "算力": 3,
    "机器学习": 4,
    "智能制造": 4,
    "工业机器人": 5,
    "人形机器人": 6,
    "自动化": 2,
    "工业ai": 5,
    "机器视觉": 5,
}

AI_CONTEXT_KEYWORDS = {
    "模型": 1,
    "训练": 1,
    "制造业": 2,
    "产业基金": 2,
    "实验室": 2,
    "智算中心": 2,
    "创新中心": 2,
    "研究院": 2,
    "政策": 2,
    "招商": -2,
    "文旅": -2,
    "医疗": 1,
    "工业": 1,
    "项目": 2,
    "落地": 2,
    "合作": 1,
    "产线": 2,
    "工厂": 2,
    "融资": 2,
    "基金": 2,
}

WEAK_RELATED_PATTERNS = [
    "课程",
    "培训班",
    "营销",
    "家电促销",
    "以旧换新",
    "短视频",
    "文旅宣传",
    "春假",
    "研学",
    "会展",
    "旅游",
    "论坛成功举办",
    "招聘",
    "筛查",
    "招募",
    "春日之约",
    "国际传播",
]

HARD_EXCLUDE_TITLE_PATTERNS = [
    "春假",
    "研学",
    "招募",
]

STRONG_RELEVANCE_KEYWORDS = {
    "政策": 3,
    "项目": 3,
    "融资": 3,
    "基金": 3,
    "合作": 2,
    "落地": 3,
    "投产": 3,
    "工厂": 3,
    "产线": 3,
    "实验室": 3,
    "研究院": 3,
    "创新中心": 3,
    "产业园": 3,
    "智算中心": 3,
    "江南大学": 2,
    "高校": 1,
}

EXPLICIT_TARGET_TOPIC_KEYWORDS = [
    "人工智能",
    "机器人",
    "智能制造",
    "工业ai",
    "机器视觉",
    "具身智能",
    "自动化",
    "工业机器人",
    "人形机器人",
    "大模型",
    "智能体",
    "算力",
]

INDUSTRIAL_SIGNAL_KEYWORDS = [
    "项目",
    "政策",
    "基金",
    "融资",
    "合作",
    "落地",
    "工厂",
    "产线",
    "园区",
    "研究院",
    "实验室",
    "创新中心",
    "智算中心",
]

SOFT_EVENT_TITLE_PATTERNS = [
    "春假",
    "研学",
    "招聘",
    "峰会",
    "论坛",
    "恳谈会",
    "展会",
    "大会",
    "国际传播",
]

ORG_SUFFIXES = [
    "股份有限公司",
    "有限公司",
    "集团",
    "公司",
    "研究院",
    "研究所",
    "实验室",
    "创新中心",
    "产业园",
    "高新区",
    "工信局",
    "人民政府",
    "管委会",
    "大学",
    "学院",
    "银行",
    "电信",
]

INSTITUTION_SUFFIXES = [
    "研究院",
    "研究所",
    "实验室",
    "创新中心",
    "产业园",
    "高新区",
    "工信局",
    "人民政府",
    "管委会",
    "大学",
    "学院",
]

ORG_STOPWORDS = {
    "人工智能",
    "机器人",
    "智能制造",
    "工业ai",
    "大模型",
    "智能体",
    "算法",
    "模型",
    "项目",
    "产业",
    "应用",
    "场景",
    "发展",
    "制造业",
    "高校联盟赛",
    "工业机器人",
    "协作机器人",
    "人形机器人",
    "中国机器人",
    "服务消费机器人",
    "影视公司",
    "有限公司",
}

ORG_BAD_FRAGMENTS = [
    "推动",
    "推进",
    "打造",
    "依托",
    "支持",
    "探索",
    "实现",
    "显示",
    "观察",
    "落户",
    "签约",
    "项目",
    "应用",
    "场景",
    "作为",
    "通过",
    "联合",
    "更是",
    "成立",
    "建设",
    "企业",
    "手把手",
    "春日之约",
    "单人成军",
    "加持",
    "大学生",
    "全国大学",
    "联盟赛",
    "机甲大师",
    "一人公司",
    "等多地",
    "本轮融资",
    "本次融资",
    "进一步",
]

ORG_HARD_BLOCKLIST = {
    "江苏省常熟职业教育中心校",
}

ORG_GENERIC_SUFFIX_BLOCKLIST = (
    "中心校",
    "开发区",
    "职业教育中心校",
)

ORG_REFERENCE_PREFIXES = ("这家", "该", "某", "一家", "这家苏州", "这家无锡")
ORG_ACTION_PREFIX_PATTERN = (
    r"^(?:他|她|其|并|并且|后|随后|曾|曾经|已|已经|正|正在|还|也|又|再|就|现|现已|目前|目前已)?"
    r"(?:入职|加入|加盟|任职于|就职于|供职于|创办|创立|成立|创设|组建)"
)

TOPIC_DEFINITIONS = {
    "robotics": {"label": "机器人", "keywords": ["机器人", "工业机器人", "人形机器人"]},
    "industrial-ai": {"label": "工业AI", "keywords": ["工业ai", "工业智能", "工业互联网ai"]},
    "machine-vision": {"label": "机器视觉", "keywords": ["机器视觉", "视觉检测"]},
    "smart-manufacturing": {"label": "智能制造", "keywords": ["智能制造", "制造业", "工厂", "产线"]},
    "embodied-ai": {"label": "具身智能", "keywords": ["具身智能"]},
    "automation": {"label": "自动化", "keywords": ["自动化"]},
    "llm": {"label": "大模型", "keywords": ["大模型", "模型", "智能体"]},
    "ai-chip": {"label": "AI芯片", "keywords": ["ai芯片", "芯片", "算力"]},
}

REGION_SLUGS = {
    "无锡": "wuxi",
    "苏州": "suzhou",
    "长三角": "yangtze-delta",
}

NON_AI_TITLE_KEYWORDS = [
    "铁路",
    "元宵",
    "街道",
    "文明城市",
    "外贸企业",
    "促消费",
    "家装",
]

AUTHORITATIVE_DOMAIN_SUFFIXES = (".gov.cn", ".edu.cn")
ARTICLE_CONTEXT_CACHE: dict[str, str] = {}


def log_event(stage: str, message: str) -> None:
    print(f"[{stage}] {message}", file=sys.stderr)


def build_bing_rss_url(keyword: str) -> str:
    encoded = urllib.parse.quote(keyword)
    return f"https://www.bing.com/news/search?q={encoded}&format=RSS&setlang=zh-hans"


def build_google_rss_url(keyword: str) -> str:
    encoded = urllib.parse.quote(keyword)
    return (
        "https://news.google.com/rss/search"
        f"?q={encoded}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    )


def feed_priority(name: str) -> tuple[int, int]:
    score = 0
    if name.startswith("google:") and name.count(":") == 1:
        score += 120
    if name.startswith("bing:") and name.count(":") == 1:
        score += 100
    if any(site in name for site in CHINA_NEWS_SITE_FILTERS):
        score += 80
    if any(site in name for site in {"wxrb.com", "yzwb.net", "xhby.net", "subaonet.com", "news.jiangnan.edu.cn"}):
        score += 20
    if "无锡" in name:
        score += 18
    elif "苏州" in name:
        score += 14
    elif "长三角" in name:
        score += 10
    if "机器人" in name or "具身智能" in name or "机器视觉" in name:
        score += 8
    if "工业AI" in name or "智能制造" in name:
        score += 6
    return (-score, len(name))


FEED_SOURCES = []
for group in TOPIC_GROUPS:
    for keyword in group["keywords"]:
        FEED_SOURCES.append((f"bing:{keyword}", build_bing_rss_url(keyword)))
        FEED_SOURCES.append((f"google:{keyword}", build_google_rss_url(keyword)))
        for site in CHINA_NEWS_SITE_FILTERS:
            scoped_keyword = f"{keyword} site:{site}"
            FEED_SOURCES.append((f"google:{keyword}:{site}", build_google_rss_url(scoped_keyword)))
        for site in EXPANDED_SITE_FILTERS:
            scoped_keyword = f"{keyword} site:{site}"
            FEED_SOURCES.append((f"bing:{keyword}:{site}", build_bing_rss_url(scoped_keyword)))

FEED_SOURCES = sorted(FEED_SOURCES, key=lambda pair: feed_priority(pair[0]))[:MAX_FEED_SOURCES]


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


def is_qualified_news_domain(domain: str) -> bool:
    return any(domain_matches(domain, pattern) for pattern in QUALIFIED_NEWS_DOMAINS)


def is_blocked_domain(domain: str) -> bool:
    return any(domain_matches(domain, pattern) for pattern in BLOCKED_DOMAINS)


def is_trusted_source(source: str) -> bool:
    source_text = (source or "").strip()
    return any(keyword in source_text for keyword in TRUSTED_SOURCE_KEYWORDS)


def is_blocked_source(source: str) -> bool:
    source_text = (source or "").strip()
    return any(keyword in source_text for keyword in BLOCKED_SOURCE_KEYWORDS)


def is_authoritative_channel(domain: str, source: str) -> bool:
    if not domain:
        return False
    if domain.endswith(AUTHORITATIVE_DOMAIN_SUFFIXES):
        return True
    return is_trusted_domain(domain) or is_trusted_source(source) or is_qualified_news_domain(domain)


def source_tier(domain: str, source: str) -> int:
    if domain.endswith(AUTHORITATIVE_DOMAIN_SUFFIXES):
        return 3
    if is_trusted_domain(domain) or is_trusted_source(source):
        return 2
    if is_qualified_news_domain(domain):
        return 1
    return 0


def clean_url(url: str) -> str:
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return url.strip()
    if not parsed.scheme or not parsed.netloc:
        return url.strip()
    query_items = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    kept = []
    for key, value in query_items:
        lowered = key.lower()
        if lowered.startswith("utm_") or lowered in {"spm", "from", "ref", "source", "cmpid"}:
            continue
        kept.append((key, value))
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


def decode_html_bytes(html_bytes: bytes, charset_hint: str = "") -> str:
    encodings = []
    if charset_hint:
        encodings.append(charset_hint)
    encodings.extend(["utf-8", "gb18030", "gbk"])
    seen = set()
    for encoding in encodings:
        if not encoding or encoding in seen:
            continue
        seen.add(encoding)
        try:
            return html_bytes.decode(encoding)
        except Exception:
            continue
    return html_bytes.decode("utf-8", errors="ignore")


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(text or "")).strip()


def strip_why_prefix(text: str) -> str:
    cleaned = normalize_whitespace(text)
    cleaned = re.sub(r"^(为什么值得关注[:：]\s*)+", "", cleaned)
    return cleaned.strip()


def slugify(text: str) -> str:
    lowered = normalize_whitespace(text).lower()
    lowered = lowered.replace("&", " and ")
    parts = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", lowered)
    slug = "-".join(parts).strip("-")
    return slug[:72] or "item"


def path_join_url(*parts: str) -> str:
    cleaned = [part.strip("/") for part in parts if part]
    return "/" + "/".join(cleaned) + "/"


def topic_slug_from_label(label: str) -> str:
    for slug, config in TOPIC_DEFINITIONS.items():
        if config["label"] == label:
            return slug
    return ""


def now_cst() -> datetime:
    return datetime.now(CST)


def parse_iso_datetime(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=CST)
    return dt.astimezone(CST)


def age_in_days(iso_time: str) -> float:
    dt = parse_iso_datetime(iso_time)
    if not dt:
        return 9999.0
    return max((now_cst() - dt).total_seconds() / 86400.0, 0.0)


def freshness_score(iso_time: str) -> tuple[int, str]:
    age_days = age_in_days(iso_time)
    if age_days <= 1:
        return 10, f"新鲜度:24h内({age_days:.1f}天)"
    if age_days <= 3:
        return 8, f"新鲜度:3天内({age_days:.1f}天)"
    if age_days <= 7:
        return 6, f"新鲜度:7天内({age_days:.1f}天)"
    if age_days <= 14:
        return 3, f"新鲜度:14天内({age_days:.1f}天)"
    if age_days <= MAX_ITEM_AGE_DAYS:
        return max(0, int(round(4 - (age_days / max(FRESHNESS_HALF_LIFE_DAYS, 1.0))))), f"新鲜度:偏旧({age_days:.1f}天)"
    return -6, f"新鲜度:过旧({age_days:.1f}天)"


def strip_html_tags(text: str) -> str:
    return normalize_whitespace(re.sub(r"<[^>]+>", " ", text or ""))


def extract_article_context(html_text: str) -> str:
    snippets = []
    meta_patterns = [
        r"<title[^>]*>(.*?)</title>",
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']',
        r'<meta[^>]+name=["\']keywords["\'][^>]+content=["\'](.*?)["\']',
    ]
    for pattern in meta_patterns:
        for match in re.findall(pattern, html_text, flags=re.IGNORECASE | re.DOTALL):
            cleaned = strip_html_tags(match)
            if cleaned:
                snippets.append(cleaned)

    paragraphs = []
    for match in re.findall(r"<p\b[^>]*>(.*?)</p>", html_text, flags=re.IGNORECASE | re.DOTALL):
        cleaned = strip_html_tags(match)
        if len(cleaned) < 28:
            continue
        if cleaned in paragraphs:
            continue
        paragraphs.append(cleaned)
        if len(paragraphs) >= 5:
            break
    if paragraphs:
        snippets.append(" ".join(paragraphs))
    return normalize_whitespace(" ".join(snippets))[:ARTICLE_CONTEXT_LIMIT]


def fetch_article_context(url: str) -> str:
    cached = ARTICLE_CONTEXT_CACHE.get(url)
    if cached is not None:
        return cached
    text = ""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=ARTICLE_FETCH_TIMEOUT_SECONDS) as resp:
            raw_bytes = resp.read()
            charset = resp.headers.get_content_charset() or ""
            text = extract_article_context(decode_html_bytes(raw_bytes, charset))
    except Exception as exc:
        log_event("extract", f"抓取正文失败: {url} | {exc}")
        text = ""
    ARTICLE_CONTEXT_CACHE[url] = text
    return text


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
    value = html.unescape(title or "").strip().lower()
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"(?:\||｜|_)+\s*[^|｜_]+$", "", value)
    if " - " in value:
        parts = value.split(" - ")
        if len(parts[-1]) <= 14:
            value = " - ".join(parts[:-1])
    value = re.sub(r"[^\w\u4e00-\u9fff]+", "", value)
    return value


def normalize_content_for_similarity(text: str) -> str:
    value = normalize_whitespace(text).lower()
    value = re.sub(r"[^\w\u4e00-\u9fff]+", "", value)
    return value


def char_shingles(text: str, size: int = 6) -> set[str]:
    if len(text) < size:
        return {text} if text else set()
    return {text[i : i + size] for i in range(0, len(text) - size + 1)}


def content_similarity(a: str, b: str) -> float:
    na = normalize_content_for_similarity(a)
    nb = normalize_content_for_similarity(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    sa = char_shingles(na)
    sb = char_shingles(nb)
    if not sa or not sb:
        return 0.0
    overlap = len(sa & sb)
    union = len(sa | sb)
    return overlap / max(union, 1)


def extract_direct_url(link: str) -> str:
    parsed = urllib.parse.urlparse(link)
    domain = normalize_domain(link)
    if domain == "bing.com" and parsed.path.endswith("/news/apiclick.aspx"):
        qs = urllib.parse.parse_qs(parsed.query)
        direct = (qs.get("url") or [""])[0].strip()
        if direct.startswith("http://") or direct.startswith("https://"):
            return clean_url(direct)
    return clean_url(link)


def is_google_news_domain(domain: str) -> bool:
    return domain == "news.google.com" or domain.endswith(".news.google.com")


def decode_google_news_url(url: str) -> str:
    code = (
        "from googlenewsdecoder import new_decoderv1; import json,sys; "
        "u=sys.argv[1]; "
        "r=new_decoderv1(u, interval=0); "
        "print(json.dumps(r, ensure_ascii=False))"
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code, url],
            capture_output=True,
            text=True,
            timeout=DECODE_TIMEOUT_SECONDS,
            check=False,
        )
    except Exception:
        return ""
    if proc.returncode != 0 or not proc.stdout.strip():
        return ""
    try:
        payload = json.loads(proc.stdout.strip())
    except json.JSONDecodeError:
        return ""
    decoded = clean_url(str((payload or {}).get("decoded_url", "")).strip())
    if decoded.startswith("http://") or decoded.startswith("https://"):
        return decoded
    return ""


def resolve_google_links(items: list[dict]) -> list[dict]:
    candidate_indexes = []
    for idx, item in enumerate(items):
        domain = normalize_domain(str(item.get("url", "")))
        if is_google_news_domain(domain):
            candidate_indexes.append(idx)
            if len(candidate_indexes) >= MAX_GOOGLE_DECODE_ITEMS:
                break
    if not candidate_indexes:
        return items
    updates = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_map = {
            executor.submit(decode_google_news_url, str(items[idx].get("url", ""))): idx
            for idx in candidate_indexes
        }
        for future in as_completed(future_map):
            idx = future_map[future]
            try:
                decoded = future.result()
            except Exception:
                continue
            if decoded:
                updates[idx] = decoded
    resolved = []
    for idx, item in enumerate(items):
        if idx not in updates:
            resolved.append(item)
            continue
        cloned = dict(item)
        cloned["url"] = updates[idx]
        if normalize_domain(str(cloned.get("source", ""))) in {"", "news.google.com"}:
            cloned["source"] = normalize_domain(updates[idx]) or cloned.get("source", "")
        resolved.append(cloned)
    return resolved


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
        title = normalize_whitespace(item.findtext("title") or "")
        link = normalize_whitespace(item.findtext("link") or "")
        if not title or not link:
            continue
        source = ""
        source_el = item.find("source")
        if source_el is not None and source_el.text:
            source = normalize_whitespace(source_el.text)
        direct_url = extract_direct_url(link)
        if not source:
            source = normalize_domain(direct_url) or feed_name
        pub_date = normalize_whitespace(item.findtext("pubDate") or "")
        description = strip_html_tags(item.findtext("description") or "")
        items.append(
            {
                "title": title,
                "url": direct_url,
                "source": source,
                "published_at": parse_time_to_iso(pub_date),
                "feed": feed_name,
                "rss_description": description[:1200],
            }
        )
        if len(items) >= MAX_PER_FEED:
            break
    return items


def load_existing_items() -> list[dict]:
    if not os.path.exists(DATA_PATH):
        return []
    try:
        with open(DATA_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return []
    items = data.get("items")
    if not isinstance(items, list):
        return []
    loaded = []
    for item in items:
        if not isinstance(item, dict):
            continue
        cloned = dict(item)
        cloned["_existing"] = True
        if age_in_days(str(cloned.get("published_at", ""))) > MAX_EXISTING_ITEM_AGE_DAYS:
            continue
        loaded.append(cloned)
    return loaded


def combine_candidate_text(item: dict) -> str:
    return " ".join(
        [
            str(item.get("title", "")),
            str(item.get("source", "")),
            str(item.get("rss_description", "")),
            str(item.get("content_text", "")),
            str(item.get("url", "")),
        ]
    )


def contains_ai_token(text: str) -> bool:
    lowered = (text or "").lower()
    if re.search(r"(?<![a-z0-9])ai(?![a-z0-9])", lowered):
        return True
    return False


def detect_regions(text: str) -> list[str]:
    lowered = (text or "").lower()
    hits = []
    for region, config in PRIMARY_REGIONS.items():
        for alias in config["aliases"]:
            if alias.lower() in lowered:
                hits.append(region)
                break
    return hits


def title_tokens(title: str) -> set[str]:
    normalized = normalize_whitespace(title)
    chinese_tokens = set(re.findall(r"[\u4e00-\u9fff]{2,6}", normalized))
    latin_tokens = set(token.lower() for token in re.findall(r"[A-Za-z0-9]{2,}", normalized))
    tokens = chinese_tokens | latin_tokens
    return {token for token in tokens if token not in {"新闻", "发布", "江苏", "中国"}}


def title_token_similarity(a: str, b: str) -> float:
    tokens_a = title_tokens(a)
    tokens_b = title_tokens(b)
    if not tokens_a or not tokens_b:
        return 0.0
    overlap = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)
    return overlap / max(union, 1)


def region_score(text: str) -> tuple[int, list[str]]:
    score = 0
    reasons = []
    lowered = (text or "").lower()
    for region, config in PRIMARY_REGIONS.items():
        hit = False
        for alias in config["aliases"]:
            if alias.lower() in lowered:
                hit = True
                break
        if hit:
            score += config["weight"]
            reasons.append(f"区域:{region}")
    return score, reasons


def ai_topic_score(text: str) -> tuple[int, list[str]]:
    score = 0
    reasons = []
    lowered = (text or "").lower()
    for keyword, weight in AI_CORE_KEYWORDS.items():
        if keyword.lower() == "ai":
            continue
        if keyword.lower() in lowered:
            score += weight
            reasons.append(f"主题:{keyword}")
    if contains_ai_token(lowered) and "主题:ai" not in reasons:
        score += 3
        reasons.append("主题:AI")
    for keyword, weight in AI_CONTEXT_KEYWORDS.items():
        if keyword.lower() in lowered:
            score += weight
    return score, reasons


def has_core_ai_topic(text: str) -> bool:
    lowered = (text or "").lower()
    if contains_ai_token(lowered):
        return True
    for keyword in AI_CORE_KEYWORDS:
        if keyword.lower() == "ai":
            continue
        if keyword.lower() in lowered:
            return True
    return False


def has_explicit_target_topic(text: str) -> bool:
    lowered = (text or "").lower()
    if contains_ai_token(lowered):
        return True
    return any(keyword in lowered for keyword in EXPLICIT_TARGET_TOPIC_KEYWORDS)


def has_industrial_signal(text: str) -> bool:
    lowered = (text or "").lower()
    return any(keyword in lowered for keyword in INDUSTRIAL_SIGNAL_KEYWORDS)


def is_obviously_non_ai_title(title: str) -> bool:
    lowered = (title or "").lower()
    if has_core_ai_topic(lowered):
        return False
    return any(keyword in lowered for keyword in NON_AI_TITLE_KEYWORDS)


def extracted_content_length(item: dict) -> int:
    return len(normalize_whitespace(str(item.get("content_text", ""))))


def relevance_score(item: dict) -> tuple[int, list[str]]:
    title = str(item.get("title", ""))
    body = combine_candidate_text(item)
    score = 0
    reasons = []

    region_points, region_reasons = region_score(body)
    score += region_points
    reasons.extend(region_reasons)

    topic_points, topic_reasons = ai_topic_score(body)
    score += topic_points
    reasons.extend(topic_reasons)

    freshness_points, freshness_reason = freshness_score(str(item.get("published_at", "")))
    score += freshness_points
    reasons.append(freshness_reason)

    title_points, title_region_reasons = region_score(title)
    score += min(title_points, 10)
    reasons.extend([f"标题命中:{reason}" for reason in title_region_reasons])
    title_topic_points, title_topic_reasons = ai_topic_score(title)
    score += min(title_topic_points, 8)
    reasons.extend([f"标题命中:{reason}" for reason in title_topic_reasons[:2]])

    if is_trusted_domain(str(item.get("domain", ""))):
        score += 2
        reasons.append("来源:可信媒体")
    if str(item.get("domain", "")).endswith(AUTHORITATIVE_DOMAIN_SUFFIXES):
        score += 2
        reasons.append("来源:官方/高校")
    if extracted_content_length(item) >= SUMMARY_MIN_CONTENT_LENGTH:
        score += 1
        reasons.append("正文:信息较完整")

    lowered = body.lower()
    for keyword, weight in STRONG_RELEVANCE_KEYWORDS.items():
        if keyword.lower() in lowered:
            score += weight
            reasons.append(f"强相关:{keyword}")

    for pattern in WEAK_RELATED_PATTERNS:
        if pattern.lower() in lowered:
            score -= 5
            reasons.append(f"弱相关:{pattern}")

    return score, reasons


def is_target_story(item: dict) -> tuple[bool, str, list[str], int]:
    title = str(item.get("title", ""))
    content_text = str(item.get("content_text", ""))
    if any(pattern in title for pattern in HARD_EXCLUDE_TITLE_PATTERNS):
        return False, "标题属于招募/研学类弱相关内容", [], 0
    if is_obviously_non_ai_title(title):
        return False, "标题明显偏离AI主题", [], 0
    combined = combine_candidate_text(item)
    regions = detect_regions(combined)
    if not regions:
        return False, "未命中无锡/苏州/长三角区域", [], 0
    if not has_core_ai_topic(combined):
        return False, "未命中人工智能/机器人核心主题", regions, 0
    if not has_explicit_target_topic(title) and not (has_explicit_target_topic(content_text) and has_industrial_signal(combined)):
        return False, "缺少明确目标技术主题", regions, 0
    if any(pattern in title for pattern in SOFT_EVENT_TITLE_PATTERNS) and not any(
        keyword in combined.lower()
        for keyword in ["机器人", "具身智能", "机器视觉", "智能制造", "工业ai", "大模型", "算力", "政策", "项目", "落地"]
    ):
        return False, "偏活动化/宣传化且产业信号不足", regions, 0
    score, reasons = relevance_score(item)
    item_age_days = age_in_days(str(item.get("published_at", "")))
    if item_age_days > MAX_ITEM_AGE_DAYS:
        return False, f"过旧({item_age_days:.1f}天>{MAX_ITEM_AGE_DAYS}天)", reasons, score
    if item_age_days > STALE_WEAK_ITEM_AGE_DAYS and score < MIN_RELEVANCE_SCORE + 8:
        return False, f"偏旧且相关性不足({item_age_days:.1f}天)", reasons, score
    if score < MIN_RELEVANCE_SCORE:
        return False, f"相关性分数过低({score}<{MIN_RELEVANCE_SCORE})", regions, score
    return True, "", reasons, score


def needs_article_review(item: dict) -> bool:
    combined = " ".join(
        [
            str(item.get("title", "")),
            str(item.get("rss_description", "")),
            str(item.get("url", "")),
        ]
    )
    regions = detect_regions(combined)
    return bool(regions) and not has_core_ai_topic(combined)


def should_fetch_context(item: dict) -> bool:
    combined = combine_candidate_text(item)
    if item.get("_existing"):
        if SUMMARY_BULK_BACKFILL and not item.get("summary"):
            return True
        if ENTITY_EXTRACTION_ENABLED and age_in_days(str(item.get("published_at", ""))) <= ENTITY_EXTRACTION_RECENT_BACKFILL_DAYS:
            title = str(item.get("title", ""))
            if any(keyword in combined for keyword in ["融资", "成立", "公司", "集团", "研究院", "实验室", "创新中心"]) or any(prefix in title for prefix in ORG_REFERENCE_PREFIXES):
                return True
        return False
    if detect_regions(combined):
        return True
    return has_core_ai_topic(combined)


def enrich_items_with_article_context(items: list[dict]) -> list[dict]:
    candidates = []
    for idx, item in enumerate(items):
        if not should_fetch_context(item):
            continue
        if item.get("content_text"):
            continue
        candidates.append((idx, str(item.get("published_at", ""))))
    if not candidates:
        return items
    candidates.sort(key=lambda pair: pair[1], reverse=True)
    candidates = candidates[:MAX_CONTENT_REVIEW_ITEMS]
    with ThreadPoolExecutor(max_workers=ARTICLE_REVIEW_WORKERS) as executor:
        future_map = {
            executor.submit(fetch_article_context, str(items[idx].get("url", ""))): idx
            for idx, _ in candidates
        }
        for future in as_completed(future_map):
            idx = future_map[future]
            try:
                context_text = future.result()
            except Exception:
                context_text = ""
            if context_text:
                items[idx]["content_text"] = context_text
    return items


def build_content_digest(item: dict) -> str:
    content = normalize_content_for_similarity(str(item.get("content_text", "")))
    if not content:
        return ""
    return hashlib.sha1(content[:1800].encode("utf-8")).hexdigest()


def clean_organization_candidate(candidate: str, suffix: str) -> str:
    cleaned = normalize_whitespace(candidate).strip("，。；：:、 “”—-()（）[]【】")
    cleaned = re.sub(r"(在(?:无锡|苏州|江阴|常熟|相城|长三角).{0,12}(?:成立|签约|落地|投用|启用).*)$", "", cleaned)
    cleaned = re.sub(r"^(由|与|和|在|对|将|把|被|让|为|向|从|以|及|并|该|本次|此次|联合|更是|围绕)", "", cleaned)
    cleaned = re.sub(ORG_ACTION_PREFIX_PATTERN, "", cleaned)
    cleaned = re.sub(r"(项目|场景|应用|平台|方案|生态|赛事|活动|发布会|论坛)$", "", cleaned)
    cleaned = cleaned.strip("，。；：:、 “”—-()（）[]【】")
    if suffix and cleaned and not cleaned.endswith(suffix) and suffix not in {"公司", "机器人"}:
        cleaned = f"{cleaned}{suffix}".strip()
    return cleaned


def is_valid_organization_candidate(candidate: str, suffix: str) -> bool:
    if not candidate:
        return False
    if candidate.startswith(ORG_REFERENCE_PREFIXES):
        return False
    if candidate in ORG_STOPWORDS:
        return False
    if len(candidate) <= len(suffix):
        return False
    if len(candidate) > 20:
        return False
    if candidate.count(" ") > 1:
        return False
    if re.search(r"[，。；：、“”‘’!?！？]", candidate):
        return False
    if candidate.startswith(("人工智能", "机器人", "智能制造", "工业AI", "AI")):
        return False
    if candidate.startswith(("是", "将", "成立", "建设", "围绕")):
        return False
    if candidate in {"苏州机器人", "无锡机器人", "苏州ai公司", "无锡ai公司"}:
        return False
    if re.fullmatch(r"(苏州|无锡|长三角)(机器人|AI|人工智能)(公司)?", candidate, flags=re.IGNORECASE):
        return False
    if candidate.startswith(("江苏省", "无锡等", "苏州等")) and candidate.endswith("机器人"):
        return False
    if any(fragment in candidate for fragment in ["全国大学", "大学生", "联盟赛", "一人公司", "机甲大师"]):
        return False
    lowered = candidate.lower()
    if any(fragment in candidate for fragment in ORG_BAD_FRAGMENTS):
        return False
    if any(fragment in lowered for fragment in ["http", ".com", "www."]):
        return False
    if suffix in {"公司", "集团", "银行", "电信", "机器人"} and len(candidate) < 4:
        return False
    return True


def looks_like_placeholder_company(name: str) -> bool:
    candidate = normalize_whitespace(name)
    if not candidate:
        return True
    if candidate.startswith(ORG_REFERENCE_PREFIXES):
        return True
    if candidate in ORG_STOPWORDS:
        return True
    if candidate in {"苏州机器人", "无锡机器人", "苏州ai公司", "无锡ai公司"}:
        return True
    if re.fullmatch(r"(苏州|无锡|长三角)(机器人|AI|人工智能)(公司)?", candidate, flags=re.IGNORECASE):
        return True
    if candidate.startswith(("观众在", "工作人员", "高可靠性", "全省", "旗下")):
        return True
    if re.match(ORG_ACTION_PREFIX_PATTERN, candidate):
        return True
    if candidate.endswith("机器人") and candidate.startswith(("苏州", "无锡", "中国")):
        return True
    if any(fragment in candidate for fragment in ORG_BAD_FRAGMENTS):
        return True
    if candidate in ORG_HARD_BLOCKLIST:
        return True
    if candidate.endswith(ORG_GENERIC_SUFFIX_BLOCKLIST):
        return True
    return False


def normalize_entity_name(name: str) -> str:
    cleaned = clean_organization_candidate(str(name), "")
    cleaned = re.sub(r"^.*旗下", "", cleaned)
    cleaned = re.sub(r"^(本轮融资(?:由)?|本次融资(?:由)?|由|其中|以及|包括|来自|作为|围绕|推动|面向|项目由)", "", cleaned)
    cleaned = re.sub(ORG_ACTION_PREFIX_PATTERN, "", cleaned)
    cleaned = re.sub(r"(将进一步.*|进一步.*)$", "", cleaned)
    return normalize_whitespace(cleaned).strip("，。；：:、 “”—-()（）[]【】")


def entity_aliases(name: str) -> list[str]:
    aliases = [normalize_whitespace(name)]
    for suffix in ["股份有限公司", "有限公司", "集团", "公司", "研究院", "研究所", "实验室", "创新中心", "银行", "电信"]:
        if aliases[0].endswith(suffix) and len(aliases[0]) > len(suffix) + 1:
            aliases.append(aliases[0][: -len(suffix)])
    deduped = []
    for alias in aliases:
        if alias and alias not in deduped:
            deduped.append(alias)
    return deduped


def is_supported_entity_name(name: str, org_type: str = "") -> bool:
    candidate = normalize_entity_name(name)
    if not candidate or looks_like_placeholder_company(candidate):
        return False
    if candidate in ORG_HARD_BLOCKLIST:
        return False
    if candidate.endswith(ORG_GENERIC_SUFFIX_BLOCKLIST):
        return False
    if org_type == "company":
        bare = candidate
        for suffix in ["股份有限公司", "有限公司", "集团", "公司", "银行", "电信"]:
            if bare.endswith(suffix) and len(bare) > len(suffix):
                bare = bare[: -len(suffix)]
                break
        if re.fullmatch(r"[\u4e00-\u9fff]{1,2}", bare):
            return False
    return True


def normalize_entity_list(values: object, limit: int = 6) -> list[str]:
    if not isinstance(values, list):
        return []
    normalized = []
    for value in values:
        cleaned = normalize_entity_name(str(value))
        if not cleaned or not is_supported_entity_name(cleaned) or cleaned in normalized:
            continue
        normalized.append(cleaned)
        if len(normalized) >= limit:
            break
    return normalized


def extract_organizations(text: str, title: str = "") -> list[str]:
    cleaned = normalize_whitespace(" ".join(part for part in [title, text] if part))
    candidates = []
    for suffix in ORG_SUFFIXES:
        pattern = rf"(?<![\u4e00-\u9fffA-Za-z0-9])([\u4e00-\u9fffA-Za-z0-9·\-]{{2,18}}{re.escape(suffix)})"
        for match in re.findall(pattern, cleaned):
            candidate = clean_organization_candidate(match, suffix)
            if is_valid_organization_candidate(candidate, suffix) and candidate not in candidates:
                candidates.append(candidate)

    title_patterns = [
        r"([\u4e00-\u9fffA-Za-z0-9·\-]{2,12})(?=在(?:无锡|苏州|江阴|常熟|相城|长三角).{0,8}(?:成立|签约|落地|投用|启用|发布))",
        r"([\u4e00-\u9fffA-Za-z0-9·\-]{2,12})(?=稳步推进)",
    ]
    for pattern in title_patterns:
        for match in re.findall(pattern, title or ""):
            candidate = clean_organization_candidate(match, "")
            if candidate in ORG_STOPWORDS:
                continue
            if len(candidate) < 3 or len(candidate) > 12:
                continue
            if any(fragment in candidate for fragment in ORG_BAD_FRAGMENTS):
                continue
            if candidate.endswith(("大学", "学院")):
                continue
            if candidate not in candidates:
                candidates.append(candidate)
    return candidates[:8]


def classify_organization(name: str) -> str:
    for suffix in INSTITUTION_SUFFIXES:
        if name.endswith(suffix):
            if suffix in {"产业园", "高新区"}:
                return "park"
            if suffix in {"工信局", "人民政府", "管委会"}:
                return "government"
            if suffix in {"大学", "学院"}:
                return "university"
            return "institute"
    return "company"


def entity_support_score(name: str, item: dict, org_type: str) -> int:
    score = 0
    title = normalize_whitespace(str(item.get("title", "")))
    text = combine_candidate_text(item)
    aliases = entity_aliases(name)
    for alias in aliases:
        if alias and alias in title:
            score += 8
            break
    for alias in aliases:
        if alias:
            count = text.count(alias)
            if count:
                score += min(count, 3)
                break
    if org_type == "company":
        score += 6
    elif org_type == "institute":
        score += 4
    elif org_type == "university":
        score += 3
    else:
        score += 1
    if any(name.endswith(suffix) for suffix in ["股份有限公司", "有限公司", "集团", "公司", "银行", "电信"]):
        score += 2
    bare = aliases[-1] if aliases else name
    if re.fullmatch(r"[\u4e00-\u9fff]{1,2}", bare):
        score -= 6
    if name.endswith(("高新区", "产业园", "管委会", "人民政府", "工信局", "开发区", "中心校")):
        score -= 4
    if name.endswith("基金"):
        score -= 5
    return score


def prioritize_entities(orgs: list[str], org_types: dict[str, str], item: dict) -> tuple[list[str], list[str]]:
    scored = []
    for name in orgs:
        org_type = org_types.get(name, classify_organization(name))
        if not is_supported_entity_name(name, org_type):
            continue
        score = entity_support_score(name, item, org_type)
        scored.append((score, name, org_type))
    scored.sort(key=lambda row: (row[0], 1 if row[2] == "company" else 0, len(row[1])), reverse=True)
    ordered = [name for score, name, _org_type in scored if score >= 2]
    companies = [name for score, name, org_type in scored if org_type == "company" and score >= 8]
    return ordered[:8], companies[:4]


def extract_topics(item: dict) -> list[dict]:
    text = combine_candidate_text(item).lower()
    found = []
    for slug, config in TOPIC_DEFINITIONS.items():
        if any(keyword in text for keyword in config["keywords"]):
            found.append({"slug": slug, "label": config["label"]})
    return found[:5]


def enrich_network_metadata(items: list[dict], provider: Optional["SummaryProvider"] = None) -> list[dict]:
    entity_calls = 0
    for item in items:
        combined = combine_candidate_text(item)
        rule_orgs = extract_organizations(combined, str(item.get("title", "")))
        seeded_orgs = normalize_entity_list(item.get("organizations") or item.get("companies"), limit=8)
        for name in seeded_orgs:
            if name not in rule_orgs:
                rule_orgs.append(name)
        llm_payload = None
        if provider is not None and entity_calls < MAX_ENTITY_EXTRACTION_ITEMS_PER_RUN and should_extract_entities(item, rule_orgs):
            llm_payload = provider.extract_entities(item)
            entity_calls += 1
            if llm_payload:
                log_event("entity", f"LLM 实体抽取: {item.get('title', '')} | confidence={llm_payload.get('entity_confidence', 'medium')}")
        orgs, company_types, llm_regions, entity_confidence = merge_llm_entities(rule_orgs, llm_payload)
        organizations, companies = prioritize_entities(orgs, company_types, item)
        regions = llm_regions or detect_regions(combined)
        topics = extract_topics(item)
        item["organizations"] = organizations
        item["companies"] = companies
        item["company_types"] = company_types
        item["regions"] = regions[:3]
        item["topics"] = topics[:5]
        item["network_density"] = len(item["organizations"]) + len(item["regions"]) + len(item["topics"])
        item["region_labels"] = [region for region in item["regions"]]
        item["entity_confidence"] = entity_confidence
    return items


def build_company_index(items: list[dict]) -> dict[str, dict]:
    index = {}
    for item in items:
        for company in item.get("companies", []):
            slug = slugify(company)
            entry = index.setdefault(
                slug,
                {
                    "slug": slug,
                    "name": company,
                    "type": item.get("company_types", {}).get(company, "company"),
                    "mention_count": 0,
                    "tags": set(),
                    "cities": set(),
                    "first_appearance": "",
                    "last_appearance": "",
                    "news": [],
                },
            )
            entry["mention_count"] += 1
            entry["news"].append(item)
            for tag in item.get("tags", []):
                entry["tags"].add(tag)
            for region in item.get("regions", []):
                entry["cities"].add(region)
            published = str(item.get("published_at", ""))
            if not entry["first_appearance"] or published < entry["first_appearance"]:
                entry["first_appearance"] = published
            if not entry["last_appearance"] or published > entry["last_appearance"]:
                entry["last_appearance"] = published
    for entry in index.values():
        entry["tags"] = sorted(entry["tags"])[:6]
        entry["cities"] = sorted(entry["cities"])[:3]
        entry["news"] = sorted(entry["news"], key=lambda item: str(item.get("published_at", "")), reverse=True)
    return dict(sorted(index.items(), key=lambda pair: (pair[1]["mention_count"], pair[1]["last_appearance"]), reverse=True))


def build_topic_index(items: list[dict]) -> dict[str, dict]:
    index = {}
    for item in items:
        for topic in item.get("topics", []):
            entry = index.setdefault(
                topic["slug"],
                {
                    "slug": topic["slug"],
                    "label": topic["label"],
                    "count": 0,
                    "news": [],
                    "companies": set(),
                },
            )
            entry["count"] += 1
            entry["news"].append(item)
            for company in item.get("companies", []):
                entry["companies"].add(company)
    for entry in index.values():
        entry["companies"] = sorted(entry["companies"])[:12]
        entry["news"] = sorted(entry["news"], key=lambda item: str(item.get("published_at", "")), reverse=True)
    return dict(sorted(index.items(), key=lambda pair: pair[1]["count"], reverse=True))


def build_region_index(items: list[dict]) -> dict[str, dict]:
    index = {}
    for item in items:
        for region in item.get("regions", []):
            slug = REGION_SLUGS.get(region, slugify(region))
            entry = index.setdefault(
                slug,
                {
                    "slug": slug,
                    "label": region,
                    "news": [],
                    "companies": set(),
                    "topics": set(),
                },
            )
            entry["news"].append(item)
            for company in item.get("companies", []):
                entry["companies"].add(company)
            for topic in item.get("topics", []):
                entry["topics"].add(topic["label"])
    for entry in index.values():
        entry["news"] = sorted(entry["news"], key=lambda item: str(item.get("published_at", "")), reverse=True)
        entry["companies"] = sorted(entry["companies"])[:12]
        entry["topics"] = sorted(entry["topics"])[:12]
    return index


def item_fingerprint(title: str) -> str:
    return hashlib.sha1(normalize_title(title).encode("utf-8")).hexdigest()


def titles_are_near_duplicate(a: str, b: str) -> bool:
    ta = normalize_title(a)
    tb = normalize_title(b)
    if not ta or not tb:
        return False
    if ta == tb:
        return True
    if ta in tb or tb in ta:
        shorter = min(len(ta), len(tb))
        longer = max(len(ta), len(tb))
        if shorter >= 10 and shorter / max(longer, 1) >= 0.74:
            return True
    ratio = SequenceMatcher(None, ta, tb).ratio()
    token_ratio = title_token_similarity(a, b)
    return ratio >= TITLE_SIMILARITY_THRESHOLD or token_ratio >= 0.78


def richer_item_score(item: dict) -> tuple:
    return (
        str(item.get("published_at", "")),
        freshness_score(str(item.get("published_at", "")))[0],
        int(item.get("relevance_score", 0)),
        int(item.get("source_tier", 0)),
        1 if item.get("trusted") else 0,
        1 if str(item.get("domain", "")).endswith(AUTHORITATIVE_DOMAIN_SUFFIXES) else 0,
        extracted_content_length(item),
        1 if item.get("summary_confidence") not in {"", "low", None} else 0,
        len(str(item.get("summary", ""))),
    )


def choose_better_item(current: dict, challenger: dict, reason: str) -> dict:
    current_score = richer_item_score(current)
    challenger_score = richer_item_score(challenger)
    if challenger_score > current_score:
        log_event(
            "dedupe",
            f"{reason}: 保留更优版本 | {challenger.get('title', '')} | {challenger.get('domain', '')}",
        )
        return challenger
    log_event(
        "dedupe",
        f"{reason}: 保留当前版本 | {current.get('title', '')} | {current.get('domain', '')}",
    )
    return current


def tag_story(item: dict) -> list[str]:
    text = combine_candidate_text(item).lower()
    tags = []
    if "无锡" in text or "wuxi" in text:
        tags.append("无锡")
    if "苏州" in text or "suzhou" in text:
        tags.append("苏州")
    if "长三角" in text or "江浙沪" in text:
        tags.append("长三角")
    if "人工智能" in text or contains_ai_token(text):
        tags.append("人工智能")
    if "机器人" in text:
        tags.append("机器人")
    if "具身智能" in text:
        tags.append("具身智能")
    if "机器视觉" in text:
        tags.append("机器视觉")
    if "大模型" in text:
        tags.append("大模型")
    if "智能制造" in text or "制造业" in text:
        tags.append("智能制造")
    if "工业ai" in text:
        tags.append("工业AI")
    if "自动化" in text:
        tags.append("自动化")
    if "产业基金" in text or "基金" in text:
        tags.append("融资")
    if "政策" in text or "方案" in text or "支持" in text:
        tags.append("政策")
    if "项目" in text:
        tags.append("项目")
    if "合作" in text:
        tags.append("合作")
    if "落地" in text or "投用" in text or "启用" in text:
        tags.append("落地")
    if "工厂" in text or "产线" in text:
        tags.append("工厂")
    if "实验室" in text or "研究院" in text or "创新中心" in text:
        tags.append("科研")
    if "论坛" in text or "大会" in text:
        tags.append("论坛")
    seen = set()
    final_tags = []
    for tag in tags:
        if tag in seen:
            continue
        seen.add(tag)
        final_tags.append(tag)
        if len(final_tags) >= 5:
            break
    return final_tags


def fallback_why_it_matters(item: dict) -> str:
    tags = item.get("tags") or []
    summary = str(item.get("summary", "")).strip()
    title = str(item.get("title", "")).strip()
    if "政策" in tags:
        return "能直接反映地方政府是否在继续加码 AI 与机器人产业支持。"
    if "融资" in tags:
        return "这类资金与基金动态通常最能提前反映区域产业布局方向。"
    if "项目" in tags or "落地" in tags:
        return "说明区域 AI/机器人项目正在从口号走向真实落地。"
    if "机器人" in tags or "具身智能" in tags:
        return "可用来观察区域机器人产业链和实际应用场景是否继续升温。"
    if "智能制造" in tags:
        return "更能体现 AI 是否真正进入制造业的一线生产和工厂流程。"
    if "科研" in tags:
        return "有助于判断本地高校和研究机构是否正在向产业侧持续输送能力。"
    if summary and len(summary) >= 30:
        return "有助于快速判断这条消息会不会转化成区域产业合作、项目或场景机会。"
    if title:
        return "值得继续跟踪它是否会带来后续的本地合作、项目或产业扩张。"
    return ""


class SummaryProvider:
    def summarize(self, item: dict) -> Optional[dict]:
        raise NotImplementedError

    def extract_entities(self, item: dict) -> Optional[dict]:
        return None


class NullSummaryProvider(SummaryProvider):
    def summarize(self, item: dict) -> Optional[dict]:
        return None


class DeepSeekSummaryProvider(SummaryProvider):
    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.model = model

    def _request_json(self, *, prompt: str, article_payload: dict, timeout: int, log_label: str, item_title: str) -> Optional[dict]:
        body = {
            "model": self.model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(article_payload, ensure_ascii=False)},
            ],
        }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "User-Agent": USER_AGENT,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="ignore")
            log_event(log_label, f"LLM 请求失败: {item_title} | HTTP {exc.code} | {raw[:300]}")
            return None
        except Exception as exc:
            log_event(log_label, f"LLM 请求失败: {item_title} | {exc}")
            return None

        try:
            content_text = payload["choices"][0]["message"]["content"]
            return json.loads(content_text)
        except Exception as exc:
            log_event(log_label, f"LLM 返回解析失败: {item_title} | {exc}")
            return None

    def summarize(self, item: dict) -> Optional[dict]:
        content = normalize_whitespace(str(item.get("content_text", "")))
        if len(content) < SUMMARY_MIN_CONTENT_LENGTH:
            log_event("summary", f"跳过摘要，正文过短: {item.get('title', '')}")
            return None

        prompt = (
            "你是中文科技新闻编辑。请根据提供的文章内容生成严格 JSON，字段包含 "
            "summary, why_it_matters, tags, confidence。"
            "要求："
            "1) summary 为 2-4 句自然中文，不能像机器翻译。"
            "2) why_it_matters 为 1 句“为什么值得关注”。"
            "3) tags 为 3-5 个中文短标签。"
            "4) 如果正文信息不足、噪音过大、无法确认细节，请返回 confidence=\"low\"，"
            "并把 summary 与 why_it_matters 设为空字符串，tags 设为空数组。"
            "5) 不要凭标题脑补，不要输出 Markdown。"
        )
        article_payload = {
            "title": str(item.get("title", "")),
            "source": str(item.get("source", "")),
            "published_at": str(item.get("published_at", "")),
            "content": content[:SUMMARY_MAX_INPUT_CHARS],
        }
        parsed = self._request_json(
            prompt=prompt,
            article_payload=article_payload,
            timeout=25,
            log_label="summary",
            item_title=str(item.get("title", "")),
        )
        if not parsed:
            return None

        summary = normalize_whitespace(str(parsed.get("summary", "")))
        why_it_matters = strip_why_prefix(str(parsed.get("why_it_matters", "")))
        tags = parsed.get("tags") if isinstance(parsed.get("tags"), list) else []
        normalized_tags = []
        for tag in tags:
            cleaned = normalize_whitespace(str(tag))
            if cleaned and cleaned not in normalized_tags:
                normalized_tags.append(cleaned)
        confidence = normalize_whitespace(str(parsed.get("confidence", ""))).lower() or "medium"
        if confidence == "low":
            log_event("summary", f"低置信度，存储但不写摘要: {item.get('title', '')}")
            return {"summary": "", "why_it_matters": "", "tags": [], "summary_confidence": "low"}
        return {
            "summary": summary,
            "why_it_matters": why_it_matters,
            "tags": normalized_tags[:5],
            "summary_confidence": confidence,
        }

    def extract_entities(self, item: dict) -> Optional[dict]:
        content = normalize_whitespace(str(item.get("content_text", "")))
        if len(content) < ENTITY_EXTRACTION_MIN_CONTENT_LENGTH:
            return None
        prompt = (
            "你是中文区域产业情报编辑。请从文章内容中提取明确出现且可命名的机构实体，"
            "严格返回 JSON，字段包含 companies, institutes, universities, government, parks, regions, confidence。"
            "要求："
            "1) 只保留明确命名实体，不要输出“这家公司”“这家苏州机器人公司”“某企业”这类指代词或泛称。"
            "2) 如果只能判断出行业或地区，不能确认真实机构名，就返回空数组。"
            "3) regions 仅限无锡、苏州、长三角。"
            "4) confidence 仅返回 high、medium、low。"
            "5) 不要输出 Markdown，不要补充解释。"
        )
        parsed = self._request_json(
            prompt=prompt,
            article_payload={
                "title": str(item.get("title", "")),
                "source": str(item.get("source", "")),
                "published_at": str(item.get("published_at", "")),
                "content": content[:SUMMARY_MAX_INPUT_CHARS],
            },
            timeout=25,
            log_label="entity",
            item_title=str(item.get("title", "")),
        )
        if not parsed:
            return None
        confidence = normalize_whitespace(str(parsed.get("confidence", ""))).lower() or "medium"
        payload = {
            "companies": normalize_entity_list(parsed.get("companies")),
            "institutes": normalize_entity_list(parsed.get("institutes")),
            "universities": normalize_entity_list(parsed.get("universities")),
            "government": normalize_entity_list(parsed.get("government")),
            "parks": normalize_entity_list(parsed.get("parks")),
            "regions": [region for region in normalize_entity_list(parsed.get("regions"), limit=3) if region in REGION_SLUGS],
            "entity_confidence": confidence,
        }
        return payload


def build_summary_provider() -> SummaryProvider:
    if not SUMMARY_ENABLED and not ENTITY_EXTRACTION_ENABLED:
        return NullSummaryProvider()
    if SUMMARY_PROVIDER == "deepseek" and LLM_API_KEY:
        return DeepSeekSummaryProvider(LLM_API_KEY, LLM_BASE_URL, LLM_MODEL)
    if (SUMMARY_ENABLED or ENTITY_EXTRACTION_ENABLED) and not LLM_API_KEY:
        log_event("summary", "未配置 LLM API Key，LLM 摘要与实体抽取功能将跳过")
    return NullSummaryProvider()


def should_summarize(item: dict) -> bool:
    if item.get("summary"):
        return False
    if SUMMARY_BULK_BACKFILL:
        return extracted_content_length(item) >= SUMMARY_MIN_CONTENT_LENGTH
    if item.get("summary_confidence") == "low":
        return False
    if SUMMARY_NEW_ONLY and item.get("_existing"):
        return age_in_days(str(item.get("published_at", ""))) <= SUMMARY_RECENT_BACKFILL_DAYS and extracted_content_length(item) >= SUMMARY_MIN_CONTENT_LENGTH
    return extracted_content_length(item) >= SUMMARY_MIN_CONTENT_LENGTH


def enrich_items_with_summaries(items: list[dict], provider: SummaryProvider) -> list[dict]:
    candidates = []
    for idx, item in enumerate(items):
        if not should_summarize(item):
            if extracted_content_length(item) < SUMMARY_MIN_CONTENT_LENGTH and not item.get("summary"):
                item.setdefault("summary_confidence", "low")
            continue
        candidates.append((idx, item))

    candidates.sort(
        key=lambda pair: (
            int(pair[1].get("relevance_score", 0)),
            freshness_score(str(pair[1].get("published_at", "")))[0],
            extracted_content_length(pair[1]),
        ),
        reverse=True,
    )
    candidates = candidates[:MAX_SUMMARY_ITEMS_PER_RUN]
    if not candidates:
        return items

    with ThreadPoolExecutor(max_workers=max(1, SUMMARY_WORKERS)) as executor:
        future_map = {executor.submit(provider.summarize, item): idx for idx, item in candidates}
        for future in as_completed(future_map):
            idx = future_map[future]
            item = items[idx]
            try:
                result = future.result()
            except Exception as exc:
                log_event("summary", f"摘要任务失败: {item.get('title', '')} | {exc}")
                result = None
            if not result:
                item.setdefault("summary_confidence", "low")
                continue
            item["summary"] = result.get("summary", "")
            item["why_it_matters"] = result.get("why_it_matters", "")
            item["summary_confidence"] = result.get("summary_confidence", "medium")
            if result.get("tags"):
                item["tags"] = result["tags"][:5]
    return items


def item_has_entity_cue(item: dict) -> bool:
    text = combine_candidate_text(item)
    return any(
        keyword in text
        for keyword in [
            "融资",
            "成立",
            "公司",
            "集团",
            "研究院",
            "实验室",
            "创新中心",
            "大学",
            "学院",
            "银行",
            "电信",
            "高新区",
            "管委会",
        ]
    )


def should_extract_entities(item: dict, orgs: list[str]) -> bool:
    if not ENTITY_EXTRACTION_ENABLED or not LLM_API_KEY:
        return False
    if extracted_content_length(item) < ENTITY_EXTRACTION_MIN_CONTENT_LENGTH:
        return False
    if item.get("_existing") and age_in_days(str(item.get("published_at", ""))) > ENTITY_EXTRACTION_RECENT_BACKFILL_DAYS:
        return False
    if any(looks_like_placeholder_company(org) for org in orgs):
        return True
    if item_has_entity_cue(item) and not orgs:
        return True
    title = str(item.get("title", ""))
    if any(prefix in title for prefix in ORG_REFERENCE_PREFIXES):
        return True
    return False


def merge_llm_entities(rule_orgs: list[str], llm_payload: Optional[dict]) -> tuple[list[str], dict[str, str], list[str], str]:
    filtered_rule_orgs = [org for org in rule_orgs if not looks_like_placeholder_company(org)]
    if not llm_payload:
        return filtered_rule_orgs[:6], {name: classify_organization(name) for name in filtered_rule_orgs[:6]}, [], "rule"
    confidence = normalize_whitespace(str(llm_payload.get("entity_confidence", ""))).lower() or "medium"
    llm_typed = []
    for field, org_type in [
        ("companies", "company"),
        ("institutes", "institute"),
        ("universities", "university"),
        ("government", "government"),
        ("parks", "park"),
    ]:
        for name in normalize_entity_list(llm_payload.get(field), limit=6):
            if looks_like_placeholder_company(name):
                continue
            if name not in [entry[0] for entry in llm_typed]:
                llm_typed.append((name, org_type))
    if confidence == "low":
        return filtered_rule_orgs[:6], {name: classify_organization(name) for name in filtered_rule_orgs[:6]}, [], "low"
    if llm_typed:
        orgs = [name for name, _ in llm_typed][:6]
        types = {name: org_type for name, org_type in llm_typed[:6]}
        regions = [region for region in normalize_entity_list(llm_payload.get("regions"), limit=3) if region in REGION_SLUGS]
        return orgs, types, regions, confidence
    return filtered_rule_orgs[:6], {name: classify_organization(name) for name in filtered_rule_orgs[:6]}, [], confidence


def dedupe_items(items: list[dict]) -> list[dict]:
    exact_url_map: dict[str, dict] = {}
    normalized_title_map: dict[str, dict] = {}
    accepted_items: list[dict] = []
    content_seen: list[dict] = []

    for raw_item in items:
        item = dict(raw_item)
        title = str(item.get("title", "")).strip()
        url = clean_url(str(item.get("url", "")).strip())
        source = str(item.get("source", "")).strip()
        domain = normalize_domain(url)
        if not title or not (url.startswith("http://") or url.startswith("https://")):
            log_event("skip", f"缺少有效标题或链接: {title or url}")
            continue
        if not domain or is_blocked_domain(domain):
            log_event("skip", f"来源域名被过滤: {title} | {domain}")
            continue
        if is_blocked_source(source):
            log_event("skip", f"来源名称被过滤: {title} | {source}")
            continue
        if any(keyword in title.lower() for keyword in AD_KEYWORDS):
            log_event("skip", f"疑似广告标题: {title}")
            continue
        if not is_authoritative_channel(domain, source):
            log_event("skip", f"来源质量不足: {title} | {domain}")
            continue

        item["url"] = url
        item["domain"] = domain
        item["trusted"] = is_trusted_domain(domain) or is_trusted_source(source)
        item["source_tier"] = source_tier(domain, source)
        item["fingerprint"] = item_fingerprint(title)
        item["content_digest"] = build_content_digest(item)

        keep, reason, reasons, score = is_target_story(item)
        item["relevance_score"] = score
        item["ranking_reasons"] = reasons
        if not keep:
            log_event("skip", f"{reason}: {title}")
            continue

        normalized = normalize_title(title)
        if url in exact_url_map:
            exact_url_map[url] = choose_better_item(exact_url_map[url], item, "精确URL去重")
            continue
        exact_url_map[url] = item

        existing = normalized_title_map.get(normalized)
        if existing is not None:
            normalized_title_map[normalized] = choose_better_item(existing, item, "标题标准化去重")
            continue

        fuzzy_hit_idx = None
        for idx, existing_item in enumerate(accepted_items):
            if titles_are_near_duplicate(title, str(existing_item.get("title", ""))):
                token_ratio = title_token_similarity(title, str(existing_item.get("title", "")))
                log_event("dedupe", f"标题相似去重候选({token_ratio:.2f}): {title} ~= {existing_item.get('title', '')}")
                fuzzy_hit_idx = idx
                break
        if fuzzy_hit_idx is not None:
            accepted_items[fuzzy_hit_idx] = choose_better_item(
                accepted_items[fuzzy_hit_idx], item, "标题模糊去重"
            )
            continue

        content_hit_idx = None
        if extracted_content_length(item) >= MIN_EXTRACTED_CONTENT_LENGTH:
            for idx, existing_item in enumerate(content_seen):
                existing_regions = set(detect_regions(combine_candidate_text(existing_item)))
                current_regions = set(detect_regions(combine_candidate_text(item)))
                if not (existing_regions & current_regions):
                    continue
                similarity = content_similarity(
                    str(item.get("content_text", "")),
                    str(existing_item.get("content_text", "")),
                )
                if similarity >= CONTENT_SIMILARITY_THRESHOLD:
                    content_hit_idx = idx
                    log_event(
                        "dedupe",
                        f"正文相似去重({similarity:.2f}): {title} ~= {existing_item.get('title', '')}",
                    )
                    break
        if content_hit_idx is not None:
            content_seen[content_hit_idx] = choose_better_item(
                content_seen[content_hit_idx], item, "正文相似去重"
            )
            accepted_items = content_seen[:]
            normalized_title_map = {normalize_title(str(entry.get("title", ""))): entry for entry in accepted_items}
            exact_url_map = {str(entry.get("url", "")): entry for entry in accepted_items}
            continue

        accepted_items.append(item)
        content_seen.append(item)
        normalized_title_map[normalized] = item
        log_event("rank", f"保留: score={score} | {title} | {'; '.join(reasons[:5])}")

    accepted_items.sort(
        key=lambda item: (
            str(item.get("published_at", "")),
            freshness_score(str(item.get("published_at", "")))[0],
            int(item.get("relevance_score", 0)),
            int(item.get("source_tier", 0)),
            1 if item.get("trusted") else 0,
            extracted_content_length(item),
        ),
        reverse=True,
    )
    return accepted_items[:CACHE_LIMIT]


def finalize_items(items: list[dict], provider: Optional["SummaryProvider"] = None) -> list[dict]:
    for item in items:
        if item.get("why_it_matters"):
            item["why_it_matters"] = strip_why_prefix(str(item.get("why_it_matters", "")))
        tags = item.get("tags")
        if not isinstance(tags, list) or not tags:
            item["tags"] = tag_story(item)
        else:
            normalized_tags = []
            for tag in tags:
                cleaned = normalize_whitespace(str(tag))
                if cleaned and cleaned not in normalized_tags:
                    normalized_tags.append(cleaned)
            item["tags"] = normalized_tags[:5]
        if item.get("summary") and not item.get("why_it_matters"):
            item["why_it_matters"] = fallback_why_it_matters(item)
        if not item.get("summary") and extracted_content_length(item) < MIN_EXTRACTED_CONTENT_LENGTH:
            item["summary_confidence"] = "low"
    return enrich_network_metadata(items, provider)


def write_data_json(items: list[dict]) -> None:
    companies = build_company_index(items)
    topics = build_topic_index(items)
    regions = build_region_index(items)
    serializable = []
    hidden_keys = {"content_text", "_existing", "content_digest"}
    for item in items:
        cloned = {key: value for key, value in item.items() if key not in hidden_keys}
        serializable.append(cloned)
    payload = {
        "updated_at": datetime.now(CST).isoformat(),
        "item_count": len(serializable),
        "items": serializable,
        "companies": [
            {
                "slug": entry["slug"],
                "name": entry["name"],
                "type": entry["type"],
                "mention_count": entry["mention_count"],
                "tags": entry["tags"],
                "cities": entry["cities"],
                "first_appearance": entry["first_appearance"],
                "last_appearance": entry["last_appearance"],
            }
            for entry in companies.values()
        ],
        "topics": [
            {
                "slug": entry["slug"],
                "label": entry["label"],
                "count": entry["count"],
                "companies": entry["companies"],
            }
            for entry in topics.values()
        ],
        "regions": [
            {
                "slug": entry["slug"],
                "label": entry["label"],
                "company_count": len(entry["companies"]),
                "topic_count": len(entry["topics"]),
            }
            for entry in regions.values()
        ],
    }
    with open(DATA_PATH, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def write_seo_files(updated_iso: str, items: list[dict]) -> None:
    updated_date = updated_iso[:10] if updated_iso else datetime.now(CST).strftime("%Y-%m-%d")
    company_index = build_company_index(items)
    topic_index = build_topic_index(items)
    region_index = build_region_index(items)
    robots = "\n".join(
        [
            "User-agent: *",
            "Allow: /",
            "",
            "Sitemap: https://wuxiai.com/sitemap.xml",
            "",
        ]
    )
    sitemap_lines = [
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
        "  <url>",
        "    <loc>https://wuxiai.com/weekly/</loc>",
        f"    <lastmod>{updated_date}</lastmod>",
        "    <changefreq>daily</changefreq>",
        "    <priority>0.8</priority>",
        "  </url>",
        "  <url>",
        "    <loc>https://wuxiai.com/submit/</loc>",
        f"    <lastmod>{updated_date}</lastmod>",
        "    <changefreq>weekly</changefreq>",
        "    <priority>0.5</priority>",
        "  </url>",
    ]
    for page_number in range(1, get_history_page_count(items) + 1):
        sitemap_lines.extend(
            [
                "  <url>",
                f"    <loc>{history_page_url(page_number)}</loc>",
                f"    <lastmod>{updated_date}</lastmod>",
                "    <changefreq>hourly</changefreq>",
                f"    <priority>{'0.8' if page_number == 1 else '0.7'}</priority>",
                "  </url>",
            ]
        )
    for entry in company_index.values():
        sitemap_lines.extend(["  <url>", f"    <loc>https://wuxiai.com/company/{entry['slug']}/</loc>", f"    <lastmod>{updated_date}</lastmod>", "    <changefreq>daily</changefreq>", "    <priority>0.7</priority>", "  </url>"])
    for entry in topic_index.values():
        sitemap_lines.extend(["  <url>", f"    <loc>https://wuxiai.com/topic/{entry['slug']}/</loc>", f"    <lastmod>{updated_date}</lastmod>", "    <changefreq>daily</changefreq>", "    <priority>0.7</priority>", "  </url>"])
    for entry in region_index.values():
        sitemap_lines.extend(["  <url>", f"    <loc>https://wuxiai.com/region/{entry['slug']}/</loc>", f"    <lastmod>{updated_date}</lastmod>", "    <changefreq>daily</changefreq>", "    <priority>0.7</priority>", "  </url>"])
    sitemap_lines.extend(["</urlset>", ""])
    with open(ROBOTS_PATH, "w", encoding="utf-8") as handle:
        handle.write(robots)
    with open(SITEMAP_PATH, "w", encoding="utf-8") as handle:
        handle.write("\n".join(sitemap_lines))


def render_news_item(news: dict) -> str:
    title = html.escape(str(news.get("title", "")))
    source = html.escape(str(news.get("source", "未知来源")))
    pub_date = html.escape(format_cst_time(str(news.get("published_at", ""))))
    url = html.escape(str(news.get("url", "")), quote=True)
    summary = html.escape(str(news.get("summary", "")).strip())
    why_it_matters = html.escape(str(news.get("why_it_matters", "")).strip())
    tags = news.get("tags") if isinstance(news.get("tags"), list) else []
    companies = news.get("companies") if isinstance(news.get("companies"), list) else []
    regions = news.get("regions") if isinstance(news.get("regions"), list) else []
    tag_parts = []
    for tag in tags[:3]:
        topic_slug = topic_slug_from_label(str(tag))
        if topic_slug:
            tag_parts.append(
                f'<a class="tag" href="{html.escape(path_join_url("topic", topic_slug), quote=True)}">{html.escape(str(tag))}</a>'
            )
        elif str(tag) in REGION_SLUGS:
            tag_parts.append(
                f'<a class="tag" href="{html.escape(path_join_url("region", REGION_SLUGS[str(tag)]), quote=True)}">{html.escape(str(tag))}</a>'
            )
        else:
            tag_parts.append(f'<span class="tag">{html.escape(str(tag))}</span>')
    tag_html = "".join(tag_parts)
    company_html = "，".join(
        f'<a href="{html.escape(path_join_url("company", slugify(company)), quote=True)}">{html.escape(str(company))}</a>'
        for company in companies[:3]
    )
    region_html = "".join(
        f'<a class="tag" href="{html.escape(path_join_url("region", REGION_SLUGS.get(region, slugify(region))), quote=True)}">{html.escape(region)}</a>'
        for region in regions[:2]
    )

    lines = [
        '    <article class="news-item">',
        f'      <h2 class="news-title"><a href="{url}" target="_blank" rel="noopener noreferrer">{title}</a></h2>',
        f'      <div class="src">{source} | {pub_date}</div>',
    ]
    if region_html:
        lines.append(f'      <div class="tags">{region_html}</div>')
    if summary:
        lines.append(f'      <p class="summary">{summary}</p>')
    if why_it_matters:
        lines.append(f'      <p class="why"><strong>为什么值得关注：</strong>{why_it_matters}</p>')
    if company_html:
        lines.append(f'      <p class="why"><strong>涉及公司：</strong>{company_html}</p>')
    if tag_html:
        lines.append(f'      <div class="tags">{tag_html}</div>')
    lines.append("    </article>")
    return "\n".join(lines)


def build_page_html(
    *,
    items: list[dict],
    page_title: str,
    canonical_url: str,
    description: str,
    heading: str,
    intro: str,
    show_limit: Optional[int],
    more_link_html: str = "",
    page_meta: str = "",
) -> str:
    now_iso = datetime.now(CST).isoformat()
    seo_json_ld = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "CollectionPage",
            "name": page_title,
            "url": canonical_url,
            "inLanguage": "zh-CN",
            "description": description,
            "isPartOf": {
                "@type": "WebSite",
                "name": "无锡AI",
                "url": "https://wuxiai.com/",
            },
        },
        ensure_ascii=False,
    )
    sorted_items = sorted(
        items,
        key=lambda item: (
            str(item.get("published_at", "")),
            freshness_score(str(item.get("published_at", "")))[0],
            int(item.get("relevance_score", 0)),
            int(item.get("network_density", 0)),
            int(item.get("source_tier", 0)),
            1 if item.get("trusted") else 0,
            extracted_content_length(item),
        ),
        reverse=True,
    )

    display_items = []
    source_counts: dict[str, int] = {}
    for item in sorted_items:
        source = str(item.get("source", "未知来源")).strip() or "未知来源"
        if show_limit is not None and source_counts.get(source, 0) >= MAX_PER_SOURCE_ON_PAGE:
            continue
        source_counts[source] = source_counts.get(source, 0) + 1
        display_items.append(item)
        if show_limit is not None and len(display_items) >= show_limit:
            break

    lines = [
        "<!doctype html>",
        '<html lang="zh-CN">',
        "<head>",
        '  <meta charset="utf-8">',
        '  <meta name="viewport" content="width=device-width, initial-scale=1">',
        f'  <meta name="description" content="{html.escape(description, quote=True)}">',
        '  <meta name="keywords" content="无锡人工智能, 无锡AI, 无锡机器人, 苏州人工智能, 苏州AI, 苏州机器人, 长三角人工智能">',
        '  <meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1,max-video-preview:-1">',
        '  <meta name="applicable-device" content="pc,mobile">',
        '  <meta name="renderer" content="webkit">',
        f'  <link rel="canonical" href="{html.escape(canonical_url, quote=True)}">',
        '  <meta property="og:type" content="website">',
        '  <meta property="og:locale" content="zh_CN">',
        '  <meta property="og:site_name" content="无锡AI">',
        f'  <meta property="og:title" content="{html.escape(page_title, quote=True)}">',
        f'  <meta property="og:description" content="{html.escape(description, quote=True)}">',
        f'  <meta property="og:url" content="{html.escape(canonical_url, quote=True)}">',
        '  <meta name="twitter:card" content="summary">',
        f'  <meta name="twitter:title" content="{html.escape(page_title, quote=True)}">',
        f'  <meta name="twitter:description" content="{html.escape(description, quote=True)}">',
        f'  <meta property="article:modified_time" content="{html.escape(now_iso)}">',
        f"  <title>{html.escape(page_title)}</title>",
        f'  <script type="application/ld+json">{seo_json_ld}</script>',
        "  <style>",
        "    :root { --bg: #f5f7fb; --paper: #ffffff; --text: #1f2937; --muted: #6b7280; --line: #e5e7eb; --brand: #1d4ed8; --soft: #eff6ff; }",
        "    * { box-sizing: border-box; }",
        "    body { margin: 0; background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', sans-serif; line-height: 1.7; }",
        "    main { max-width: 920px; margin: 28px auto; padding: 0 16px; }",
        "    .card { background: var(--paper); border: 1px solid var(--line); border-radius: 14px; padding: 22px 22px 16px; box-shadow: 0 8px 24px rgba(16, 24, 40, 0.04); }",
        "    h1 { margin: 0; font-size: 30px; letter-spacing: 0.2px; }",
        "    .meta { color: var(--muted); margin: 8px 0 16px; font-size: 14px; }",
        "    .intro { margin: 0 0 18px; color: #374151; font-size: 15px; }",
        "    a { color: var(--brand); text-decoration: none; }",
        "    a:hover { text-decoration: underline; }",
        "    .news-list { display: grid; gap: 14px; }",
        "    .news-item { padding: 0 0 14px; border-bottom: 1px solid var(--line); }",
        "    .news-item:last-child { border-bottom: 0; padding-bottom: 0; }",
        "    .news-title { margin: 0 0 6px; font-size: 20px; line-height: 1.45; }",
        "    .src { color: var(--muted); font-size: 13px; }",
        "    .summary { margin: 8px 0 0; color: #374151; font-size: 15px; }",
        "    .why { margin: 8px 0 0; color: #111827; font-size: 14px; }",
        "    .tags { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }",
        "    .tag { display: inline-flex; align-items: center; padding: 2px 10px; border-radius: 999px; background: var(--soft); color: #1e40af; font-size: 12px; }",
        "    .more { margin-top: 18px; padding-top: 14px; border-top: 1px solid var(--line); font-size: 14px; }",
        "    .pager { display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; align-items: center; }",
        "    .pager span { color: var(--muted); }",
        "    .contact { margin-top: 18px; padding-top: 14px; border-top: 1px solid var(--line); color: #4b5563; font-size: 14px; }",
        "    .footer-nav { display: flex; flex-wrap: wrap; gap: 12px 20px; align-items: center; }",
        "    @media (max-width: 640px) { .card { padding: 18px 16px 14px; } .news-title { font-size: 18px; } }",
        "  </style>",
        "</head>",
        "<body>",
        "  <main>",
        '  <section class="card">',
        f"  <h1>{html.escape(heading)}</h1>",
        f'  <p class="intro">{html.escape(intro)}</p>',
    ]
    if page_meta:
        lines.append(f'  <p class="meta">{html.escape(page_meta)}</p>')
    if not display_items:
        lines.append("  <p>暂无可展示的新闻，请稍后再试。</p>")
    else:
        lines.append('  <div class="news-list">')
        for news in display_items:
            lines.append(render_news_item(news))
        lines.append("  </div>")
        if more_link_html:
            lines.append(f'  <div class="more">{more_link_html}</div>')
    lines.extend(
        [
            '  <div class="contact">',
            '    <div class="footer-nav"><span><a href="/weekly/">每周观察</a></span><span><a href="/submit/">提交线索</a></span><span><a href="/contact.html">联系方式</a></span><span><a href="https://aild.org/zh/" target="_blank" rel="noopener noreferrer">版权所有：人工智能领导力与发展研究院（AILD）</a></span></div>',
            "  </div>",
            "  </section>",
            "  </main>",
            "</body>",
            "</html>",
            "",
        ]
    )
    return "\n".join(lines)


def build_home_html(items: list[dict]) -> str:
    return build_page_html(
        items=items,
        page_title="无锡AI | 无锡、苏州与长三角人工智能新闻",
        canonical_url="https://wuxiai.com/",
        description="聚合无锡人工智能、无锡机器人、苏州AI、苏州机器人与长三角人工智能新闻，提供中文摘要、为什么值得关注与标签。",
        heading="无锡AI",
        intro="聚合无锡、苏州与长三角人工智能和机器人新闻，优先保留更权威、更完整、与区域产业更相关的版本，并提供中文摘要与关注重点。",
        show_limit=MAX_ITEMS,
        more_link_html='想看更早的内容？<a href="/history.html">查看历史新闻</a>',
    )


def history_page_filename(page_number: int) -> str:
    if page_number <= 1:
        return "history.html"
    return f"{HISTORY_PAGE_PREFIX}{page_number}.html"


def history_page_url(page_number: int) -> str:
    return f"https://wuxiai.com/{history_page_filename(page_number)}"


def get_history_page_count(items: list[dict]) -> int:
    history_item_count = max(len(items) - MAX_ITEMS, 0)
    if history_item_count == 0:
        return 0
    return (history_item_count + MAX_ITEMS - 1) // MAX_ITEMS


def build_history_navigation(page_number: int, total_pages: int) -> str:
    prev_html = f'<a href="/{history_page_filename(page_number - 1)}">上一页</a>' if page_number > 1 else "已经是第一页"
    next_html = f'<a href="/{history_page_filename(page_number + 1)}">下一页</a>' if page_number < total_pages else "已经到底了"
    return (
        '<div class="pager">'
        f"<span>第 {page_number} 页，共 {total_pages} 页</span>"
        f'<span><a href="/">返回首页最新新闻</a> | {prev_html} | {next_html}</span>'
        "</div>"
    )


def build_history_html(items: list[dict], page_number: int, total_pages: int) -> str:
    history_items = items[MAX_ITEMS:]
    start = (page_number - 1) * MAX_ITEMS
    end = start + MAX_ITEMS
    page_items = history_items[start:end]
    return build_page_html(
        items=page_items,
        page_title="无锡AI历史新闻" if page_number == 1 else f"无锡AI历史新闻 - 第 {page_number} 页",
        canonical_url=history_page_url(page_number),
        description="无锡AI历史新闻归档页，按相关性与时间倒序查看无锡、苏州与长三角人工智能及机器人新闻。",
        heading="无锡AI历史新闻",
        intro="这里收录首页之外的更早新闻，保留摘要、关注点与标签，方便继续追踪区域AI与机器人动态。",
        show_limit=None,
        more_link_html=build_history_navigation(page_number, total_pages),
        page_meta=f"归档分页：第 {page_number} 页 / 共 {total_pages} 页",
    )


def write_history_pages(items: list[dict]) -> None:
    total_pages = get_history_page_count(items)
    expected_paths = set()
    if total_pages == 0:
        if os.path.exists(HISTORY_PATH):
            os.remove(HISTORY_PATH)
    else:
        for page_number in range(1, total_pages + 1):
            path = os.path.join(ROOT_DIR, history_page_filename(page_number))
            expected_paths.add(path)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(build_history_html(items, page_number, total_pages))
    for name in os.listdir(ROOT_DIR):
        if not name.startswith(HISTORY_PAGE_PREFIX) or not name.endswith(".html"):
            continue
        path = os.path.join(ROOT_DIR, name)
        if path not in expected_paths and os.path.exists(path):
            os.remove(path)


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def reset_output_dir(path: str) -> None:
    if os.path.isdir(path):
        shutil.rmtree(path)
    os.makedirs(path, exist_ok=True)


def build_network_page_html(*, page_title: str, canonical_url: str, description: str, heading: str, intro: str, stats: list[str], news_items: list[dict], extra_sections: list[str]) -> str:
    base = build_page_html(
        items=news_items,
        page_title=page_title,
        canonical_url=canonical_url,
        description=description,
        heading=heading,
        intro=intro,
        show_limit=None,
    )
    insertion = []
    if stats:
        insertion.append('<div class="meta">' + " · ".join(html.escape(stat) for stat in stats) + "</div>")
    insertion.extend(extra_sections)
    snippet = "\n".join(insertion)
    if '<div class="news-list">' in base:
        return base.replace('<div class="news-list">', snippet + '\n  <div class="news-list">', 1)
    return base.replace("</section>", snippet + "\n  </section>", 1)


def write_company_pages(items: list[dict]) -> None:
    reset_output_dir(COMPANY_DIR)
    for entry in build_company_index(items).values():
        path = os.path.join(COMPANY_DIR, entry["slug"], "index.html")
        ensure_dir(os.path.dirname(path))
        extras = []
        if entry["cities"]:
            extras.append("<p class=\"intro\">涉及城市：" + "、".join(html.escape(city) for city in entry["cities"]) + "</p>")
        if entry["tags"]:
            extras.append("<p class=\"intro\">相关标签：" + "、".join(html.escape(tag) for tag in entry["tags"][:6]) + "</p>")
        html_text = build_network_page_html(
            page_title=f"{entry['name']} | 无锡AI 公司情报",
            canonical_url=f"https://wuxiai.com/company/{entry['slug']}/",
            description=f"{entry['name']} 在无锡AI新闻中的相关动态、提及次数与关联城市。",
            heading=entry["name"],
            intro="自动聚合该机构在无锡 / 苏州 / 长三角 AI 生态中的相关报道。",
            stats=[
                f"提及次数：{entry['mention_count']}",
                f"首次出现：{format_cst_time(entry['first_appearance'])}",
                f"最近出现：{format_cst_time(entry['last_appearance'])}",
            ],
            news_items=entry["news"][:24],
            extra_sections=extras,
        )
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(html_text)


def write_topic_pages(items: list[dict]) -> None:
    reset_output_dir(TOPIC_DIR)
    for entry in build_topic_index(items).values():
        path = os.path.join(TOPIC_DIR, entry["slug"], "index.html")
        ensure_dir(os.path.dirname(path))
        extras = []
        if entry["companies"]:
            extras.append("<p class=\"intro\">相关机构：" + "、".join(html.escape(name) for name in entry["companies"][:10]) + "</p>")
        html_text = build_network_page_html(
            page_title=f"{entry['label']} | 无锡AI 主题情报",
            canonical_url=f"https://wuxiai.com/topic/{entry['slug']}/",
            description=f"{entry['label']} 在无锡、苏州与长三角 AI 生态中的相关新闻与相关机构。",
            heading=entry["label"],
            intro="从新闻中自动聚合的技术主题页，用于追踪该技术在区域生态中的出现频率与相关主体。",
            stats=[f"提及次数：{entry['count']}", f"相关机构：{len(entry['companies'])}"],
            news_items=entry["news"][:24],
            extra_sections=extras,
        )
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(html_text)


def write_region_pages(items: list[dict]) -> None:
    reset_output_dir(REGION_DIR)
    for entry in build_region_index(items).values():
        path = os.path.join(REGION_DIR, entry["slug"], "index.html")
        ensure_dir(os.path.dirname(path))
        extras = []
        if entry["companies"]:
            extras.append("<p class=\"intro\">重点机构：" + "、".join(html.escape(name) for name in entry["companies"][:10]) + "</p>")
        if entry["topics"]:
            extras.append("<p class=\"intro\">高频主题：" + "、".join(html.escape(topic) for topic in entry["topics"][:10]) + "</p>")
        html_text = build_network_page_html(
            page_title=f"{entry['label']} | 无锡AI 区域情报",
            canonical_url=f"https://wuxiai.com/region/{entry['slug']}/",
            description=f"{entry['label']} 区域的 AI / 机器人相关新闻、重点机构与技术主题。",
            heading=entry["label"],
            intro="区域情报页会自动聚合该地区的最新动态、重点机构和高频技术主题。",
            stats=[f"新闻数：{len(entry['news'])}", f"机构数：{len(entry['companies'])}", f"主题数：{len(entry['topics'])}"],
            news_items=entry["news"][:24],
            extra_sections=extras,
        )
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(html_text)


def generate_weekly_trend_summary(items: list[dict]) -> str:
    if not LLM_API_KEY:
        return ""
    weekly_items = [item for item in items if age_in_days(str(item.get("published_at", ""))) <= 7][:10]
    if not weekly_items:
        return ""
    prompt = (
        "你是区域 AI 产业分析编辑。请用中文写一小段 3 句以内的周观察，"
        "聚焦无锡、苏州、长三角的公司、技术和产业动向，不要使用空话。"
    )
    content = json.dumps(
        [
            {
                "title": item.get("title", ""),
                "regions": item.get("regions", []),
                "companies": item.get("companies", []),
                "topics": [topic.get("label", "") for topic in item.get("topics", [])],
            }
            for item in weekly_items
        ],
        ensure_ascii=False,
    )
    req = urllib.request.Request(
        f"{LLM_BASE_URL}/chat/completions",
        data=json.dumps(
            {
                "model": LLM_MODEL,
                "temperature": 0.2,
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": content},
                ],
            }
        ).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LLM_API_KEY}",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return normalize_whitespace(payload["choices"][0]["message"]["content"])
    except Exception as exc:
        log_event("weekly", f"周观察生成失败: {exc}")
        return ""


def write_weekly_page(items: list[dict]) -> None:
    ensure_dir(WEEKLY_DIR)
    weekly_items = [item for item in items if age_in_days(str(item.get("published_at", ""))) <= 7]
    company_index = build_company_index(weekly_items)
    topic_index = build_topic_index(weekly_items)
    trend_summary = generate_weekly_trend_summary(weekly_items)
    extras = []
    if company_index:
        extras.append("<p class=\"intro\">本周高频机构：" + "、".join(html.escape(entry["name"]) for entry in list(company_index.values())[:8]) + "</p>")
    if topic_index:
        extras.append("<p class=\"intro\">本周高频技术：" + "、".join(html.escape(entry["label"]) for entry in list(topic_index.values())[:8]) + "</p>")
    if trend_summary:
        extras.append("<p class=\"why\"><strong>本周观察：</strong>" + html.escape(trend_summary) + "</p>")
    html_text = build_network_page_html(
        page_title="本周AI观察 | 无锡AI",
        canonical_url="https://wuxiai.com/weekly/",
        description="自动生成的无锡 / 苏州 / 长三角 AI 周度观察，汇总本周重点新闻、机构和技术主题。",
        heading="本周无锡AI观察",
        intro="自动汇总最近 7 天区域 AI 生态中的重点新闻、机构与技术主题。",
        stats=[f"本周新闻：{len(weekly_items)}", f"本周机构：{len(company_index)}", f"本周主题：{len(topic_index)}"],
        news_items=weekly_items[:18],
        extra_sections=extras,
    )
    with open(os.path.join(WEEKLY_DIR, "index.html"), "w", encoding="utf-8") as handle:
        handle.write(html_text)


def build_submit_page() -> str:
    template = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>提交新闻线索 | 无锡AI</title><style>body{font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;background:#f5f7fb;color:#1f2937;margin:0}main{max-width:760px;margin:28px auto;padding:0 16px}.card{background:#fff;border:1px solid #e5e7eb;border-radius:14px;padding:22px}label{display:block;margin:12px 0 6px;font-weight:600}input,textarea{width:100%;padding:10px 12px;border:1px solid #d1d5db;border-radius:10px;font:inherit}button{margin-top:16px;background:#1d4ed8;color:#fff;border:0;border-radius:10px;padding:10px 16px;font:inherit;cursor:pointer}.muted{color:#6b7280;font-size:14px}</style></head>
<body><main><section class="card"><h1>提交新闻线索</h1><p class="muted">你提交的内容会进入自动抓取与评分流程；若链接和内容足够相关，系统会自动纳入发布。</p>
<form id="submit-form"><label>Title</label><input name="title" required><label>URL</label><input name="url" required><label>Company (optional)</label><input name="company"><label>City (optional)</label><input name="city"><label>Description (optional)</label><textarea name="description" rows="5"></textarea><button type="submit">提交到线索入口</button></form></section></main>
<script>
document.getElementById('submit-form').addEventListener('submit', function (event) {
  event.preventDefault();
  const data = new FormData(event.target);
  const title = `[submit] ${data.get('title')}`;
  const body = [
    `Title: ${data.get('title') || ''}`,
    `URL: ${data.get('url') || ''}`,
    `Company: ${data.get('company') || ''}`,
    `City: ${data.get('city') || ''}`,
    `Description: ${data.get('description') || ''}`
  ].join('\\n');
  const url = `https://github.com/__GITHUB_REPO__/issues/new?labels=submission&title=${encodeURIComponent(title)}&body=${encodeURIComponent(body)}`;
  window.location.href = url;
});
</script></body></html>"""
    return template.replace("__GITHUB_REPO__", html.escape(GITHUB_REPO, quote=True))


def write_submit_page() -> None:
    ensure_dir(SUBMIT_DIR)
    with open(os.path.join(SUBMIT_DIR, "index.html"), "w", encoding="utf-8") as handle:
        handle.write(build_submit_page())


def parse_submission_body(body: str) -> dict[str, str]:
    parsed = {}
    for line in (body or "").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        parsed[key.strip().lower()] = value.strip()
    return parsed


def fetch_submission_items() -> list[dict]:
    if not GITHUB_REPO:
        return []
    url = f"https://api.github.com/repos/{GITHUB_REPO}/issues?state=open&labels=submission&per_page=50"
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SECONDS) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        log_event("submission", f"拉取提交线索失败: {exc}")
        return []
    submissions = []
    for issue in payload:
        body = parse_submission_body(str(issue.get("body", "")))
        title = body.get("title") or str(issue.get("title", "")).replace("[submit]", "").strip()
        link = body.get("url", "").strip()
        if not title or not link:
            continue
        description = body.get("description", "")
        company = body.get("company", "")
        city = body.get("city", "")
        submissions.append(
            {
                "title": title,
                "url": link,
                "source": "社区提交",
                "published_at": parse_iso_datetime(str(issue.get("created_at", "")).replace("Z", "+00:00")).astimezone(CST).isoformat() if issue.get("created_at") else "",
                "feed": "submission",
                "rss_description": normalize_whitespace(" ".join(part for part in [description, company, city] if part)),
            }
        )
    return submissions


def collect_items() -> list[dict]:
    existing = load_existing_items()
    existing_url_set = {clean_url(str(item.get("url", ""))) for item in existing}
    existing_title_set = {normalize_title(str(item.get("title", ""))) for item in existing}

    raw_items = []
    raw_items.extend(fetch_submission_items())
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_url, url): (name, url) for name, url in FEED_SOURCES}
        for future in as_completed(futures):
            name, _ = futures[future]
            try:
                xml_bytes = future.result()
            except Exception as exc:
                log_event("feed", f"抓取 RSS 失败: {name} | {exc}")
                continue
            raw_items.extend(parse_feed(name, xml_bytes))

    raw_items = resolve_google_links(raw_items)
    for item in raw_items:
        item["_existing"] = False
        normalized = normalize_title(str(item.get("title", "")))
        item["_is_new_candidate"] = clean_url(str(item.get("url", ""))) not in existing_url_set and normalized not in existing_title_set

    merged = raw_items + existing
    merged = enrich_items_with_article_context(merged)
    merged = dedupe_items(merged)
    provider = build_summary_provider()
    merged = enrich_items_with_summaries(merged, provider)
    merged = finalize_items(merged, provider)
    return merged[:CACHE_LIMIT]


def main() -> None:
    items = collect_items()
    updated_iso = datetime.now(CST).isoformat()
    write_data_json(items)
    write_seo_files(updated_iso, items)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as handle:
        handle.write(build_home_html(items))
    write_history_pages(items)
    write_company_pages(items)
    write_topic_pages(items)
    write_region_pages(items)
    write_weekly_page(items)
    write_submit_page()


if __name__ == "__main__":
    main()
