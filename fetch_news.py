#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
出海泛娱乐 资讯日报 · 抓取脚本
读取 sources.yaml → 抓取近 N 小时的 RSS/网页源 → 关键词过滤 → 去重
→ 输出候选清单草稿（按板块/赛道分组），供 agent 套模板 A/B/C 浓缩成日报。

用法：
    pip install feedparser pyyaml requests
    python fetch_news.py                 # 默认回看 sources.yaml 里的 time_window_hours
    python fetch_news.py --hours 24      # 覆盖时间窗
    python fetch_news.py --out draft.md  # 指定输出文件

设计原则：
- 每个源独立 try/except，单源失败不影响整体。
- wechat 源无官方 API：脚本不抓，仅在草稿里列出"待人工贴链接"清单。
- api 源（点点数据等）：读 .env 里的 key；未配置则跳过并标注。
"""

import argparse
import datetime as dt
import glob
import html as _html
import json
import os
import re
import socket
import sys
from collections import defaultdict

socket.setdefaulttimeout(20)  # 单源最长等待，避免死源拖垮整体

try:
    import yaml
    import feedparser
except ImportError:
    sys.exit("缺依赖：pip install feedparser pyyaml requests")

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCES = os.path.join(HERE, "sources.yaml")
OUT_DIR = os.path.abspath(os.path.join(HERE, ".."))
UNDATED_SEEN_FILE = os.path.join(HERE, ".undated_seen_urls.json")
HISTORY_LOOKBACK_DAYS = 2
URL_RE = re.compile(r"https?://[^\s)\]>]+")
LISTPAGE_SOURCE_MARKERS = ("｜白鲸出海", "｜36氪出海")


def normalize_url(url):
    """Markdown/Feishu 里会转义 URL，跨日去重前先归一。"""
    url = _html.unescape(url or "").replace("\\", "").strip()
    return url.rstrip("。；，,.;")


def extract_urls(text):
    return {u for u in (normalize_url(m.group(0)) for m in URL_RE.finditer(text or "")) if u}


def read_urls_from_file(path):
    if not os.path.exists(path):
        return set()
    try:
        with open(path, encoding="utf-8") as f:
            return extract_urls(f.read())
    except Exception:
        return set()


def daily_paths_for_date(day):
    """返回某天草稿/成稿路径；跨日去重同时参考候选池和最终稿。"""
    ymd = day.strftime("%Y%m%d")
    return [
        os.path.join(HERE, f"资讯日报-草稿-{ymd}.md"),
        os.path.join(OUT_DIR, f"资讯类简报-{day.month}.{day.day}日.md"),
    ]


def load_recent_links(target_ymd, days=HISTORY_LOOKBACK_DAYS):
    """回溯最近 N 天链接，生成当天草稿时不再新增重复 URL。"""
    try:
        target = dt.datetime.strptime(target_ymd, "%Y%m%d").date()
    except Exception:
        return set(), []
    links, sources = set(), []
    for i in range(1, days + 1):
        day = target - dt.timedelta(days=i)
        for path in daily_paths_for_date(day):
            if os.path.exists(path):
                links.update(read_urls_from_file(path))
                sources.append(path)
    return links, sources


def seed_undated_seen_from_draft(path, seen):
    """从已有草稿补一遍无时间戳链接的首次出现日期，用于平滑接入新规则。"""
    m = re.search(r"资讯日报-草稿-(\d{8})\.md$", os.path.basename(path))
    if not m or not os.path.exists(path):
        return
    first_seen = m.group(1)
    in_undated_item = False
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s.startswith("- 备选："):
                    if any(marker in s for marker in LISTPAGE_SOURCE_MARKERS):
                        for url in extract_urls(s):
                            seen.setdefault(url, first_seen)
                    in_undated_item = False
                    continue
                if s.startswith("- ⭐"):
                    in_undated_item = "⏱无时间戳" in s
                    continue
                if in_undated_item and s.startswith("- http"):
                    for url in extract_urls(s):
                        seen.setdefault(url, first_seen)
                    in_undated_item = False
    except Exception:
        return


def load_undated_seen():
    """无时间戳链接只在第一次出现时保留；同一天重跑仍允许复现。"""
    seen = {}
    if os.path.exists(UNDATED_SEEN_FILE):
        try:
            with open(UNDATED_SEEN_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                seen.update({normalize_url(k): str(v) for k, v in data.items() if normalize_url(k)})
        except Exception:
            seen = {}
    for path in sorted(glob.glob(os.path.join(HERE, "资讯日报-草稿-*.md"))):
        seed_undated_seen_from_draft(path, seen)
    return seen


def save_undated_seen(seen):
    tmp = UNDATED_SEEN_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(seen.items())), f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, UNDATED_SEEN_FILE)


def load_env():
    """读取同目录 .env（KEY=VALUE），用于 api 源的密钥。"""
    env = {}
    p = os.path.join(HERE, ".env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def feed_url(src, base):
    if src.get("route"):
        return base.rstrip("/") + src["route"]
    return src.get("url")


def bj_window(hours_override=None, target_ymd=None):
    """返回 (start_utc, end_utc, start_bj, end_bj)。
    默认按北京时间 昨16:00—今16:00 的滚动窗口；--date 可指定历史日；
    --hours 时退化为"近N小时"便于测试。"""
    if target_ymd:
        target = dt.datetime.strptime(target_ymd, "%Y%m%d")
        end_bj = target.replace(hour=16, minute=0, second=0, microsecond=0)
        start_bj = end_bj - dt.timedelta(days=1)
        return (start_bj - dt.timedelta(hours=8), end_bj - dt.timedelta(hours=8),
                start_bj, end_bj)
    now_utc = dt.datetime.utcnow()
    if hours_override:
        return now_utc - dt.timedelta(hours=hours_override), now_utc, None, None
    now_bj = now_utc + dt.timedelta(hours=8)
    end_bj = now_bj.replace(hour=16, minute=0, second=0, microsecond=0)
    if now_bj < end_bj:
        end_bj -= dt.timedelta(days=1)
    start_bj = end_bj - dt.timedelta(days=1)
    return (end_bj - dt.timedelta(days=1, hours=8), end_bj - dt.timedelta(hours=8),
            start_bj, end_bj)


def in_window(entry, start_utc, end_utc):
    """True=窗内 / False=窗外 / None=无日期（保留并标注）。feedparser 时间为 UTC。"""
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            try:
                ts = dt.datetime(*t[:6])
                return start_utc <= ts <= end_utc
            except Exception:
                pass
    return None  # 无日期信息


# ---- 去重：标题归一化 + 近重复（跨源同一条新闻）----
def sig_tokens(t):
    zh = re.findall(r"[一-龥]{2,}", t)
    en = re.findall(r"[a-zA-Z][a-zA-Z0-9\.]{2,}", t.lower())
    toks = set(en)
    for w in zh:
        for i in range(len(w) - 1):
            toks.add(w[i:i + 2])
    return toks


def is_dup(sig, seen_sigs, thresh=0.7):
    """近重复：与已收录条目的 2-gram 集合 含入度 ≥ 阈值 即判为重复。"""
    if len(sig) < 4:
        return False
    for s in seen_sigs:
        if len(s) < 4:
            continue
        inter = len(sig & s)
        if inter / min(len(sig), len(s)) >= thresh:
            return True
    return False


# ---- 精选打分（越高越优先）----
HOT = ["腾讯", "字节", "抖音", "快手", "阿里", "网易", "米哈游", "谷歌", "google",
       "openai", "anthropic", "meta", "sensor tower", "kuku", "点点", "b站", "bilibili"]
DATA_SIG = ["流水", "下载", "mau", "dau", "榜", "收入", "营收", "增长", "估值",
            "融资", "亿", "万美元", "美元", "$", "%", "ipo"]


def score(it):
    t = (it["title"] + " " + it.get("summary", "")).lower()
    s = 0
    if any(k in t for k in ("出海", "海外", "全球")):
        s += 3
    if is_funding_event(t):
        s += 3
    s += 2 * min(2, sum(1 for k in HOT if k in t))
    s += min(4, sum(1 for k in DATA_SIG if k in t))
    if it.get("summary"):
        s += 1
    return s


def hit_keywords(text, include, exclude, protect=()):
    t = text.lower()
    te = t
    for p in protect:                    # 保护词：避免"聊天机器人"被"机器人"误杀
        te = te.replace(p.lower(), "")
    if any(x.lower() in te for x in exclude):
        return False
    if not include:
        return True
    return any(x.lower() in t for x in include)


PERSONAL_LIFESTYLE_PATTERNS = [
    r"(创始人|ceo|老板|高管|富豪|个人|私人).{0,30}(购入|买下|斥资|购买).{0,30}(豪宅|别墅|游艇|私人飞机|豪车|房产)",
    r"(豪宅|别墅|游艇|私人飞机|豪车|房产).{0,30}(创始人|ceo|老板|高管|富豪|个人|私人)",
    r"(私人码头|船只升降机|海滨豪宅|超级游艇)",
]

LOW_INFO_TITLE_ONLY_PATTERNS = [
    r"(等)?\d+家(企业|公司).{0,20}(加码|布局|发力|大动作|提速)",
    r"(加码|布局|发力|大动作|提速).{0,20}(出海|短剧|游戏|ai).{0,20}(企业|公司)",
]

TITLE_ONLY_HARD_FACT_PATTERNS = [
    r"(收入|营收|流水|分成|下载|用户|mau|dau|估值|融资|募资|ipo|上市)",
    r"(\$|美元|万美元|亿元|亿美元|万|亿|%)",
    r"(登顶|榜首|top\s?\d+|第\d+)",
]


def is_personal_lifestyle_noise(text):
    """剔除名人个人消费/资产新闻；除非和公司经营、产品或资本动作直接相关。"""
    t = (text or "").lower()
    return any(re.search(p, t, flags=re.I) for p in PERSONAL_LIFESTYLE_PATTERNS)


def is_low_info_title_only(title, summary):
    """剔除只有标题、且仅表达“加码/布局/大动作”的弱信号。"""
    title = title or ""
    summary = summary or ""
    if len(summary.strip()) >= 15:
        return False
    if not any(re.search(p, title, flags=re.I) for p in LOW_INFO_TITLE_ONLY_PATTERNS):
        return False
    return not any(re.search(p, title, flags=re.I) for p in TITLE_ONLY_HARD_FACT_PATTERNS)


def clean(s, n=220):
    s = re.sub(r"<[^>]+>", "", s or "")
    s = _html.unescape(s)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"(?:\s*[&|｜·•]\s*){2,}", " ", s).strip()   # 去公众号正文残留符号串（如 &&&&）
    if not re.search(r"[一-龥A-Za-z0-9]", s):       # 清理后无中文也无字母数字=无效正文
        return ""
    return s[:n]


def entry_best_text(e):
    """RSS 条目取信息量最大的正文：优先 content（全文，如 WeWe fulltext），否则 summary。"""
    best = e.get("summary", "") or ""
    for c in (e.get("content") or []):
        v = c.get("value", "") if isinstance(c, dict) else ""
        if len(v) > len(best):
            best = v
    return best


# ---- 板块/赛道分类（aibot 等无赛道标注的源用）----
FUND_PATTERNS = [
    r"(完成|宣布|获得|获|拿到).{0,24}(融资|投资|募资)",
    r"(融资|募资).{0,24}(完成|宣布|获得|获|领投|跟投|投资方|资金)",
    r"(领投|跟投|本轮融资|本轮股东|投后估值|获投)",
    r"(天使轮|种子轮|pre-[a-z]|[abcde]\+?轮)",
    r"(ipo|上市|招股|挂牌|发售|募资)",
    r"(funding round|seed round|series [a-z]|raised|raises|valuation)",
]
ENT_KW = {
    "短剧": "短剧/漫剧", "漫剧": "短剧/漫剧",
    "网文": "小说·网文", "小说": "小说·网文",
    "社交": "社交·Dating", "dating": "社交·Dating", "陪伴": "社交·Dating",
    "游戏": "休闲游戏",
}


def is_funding_event(text):
    """只把明确融资/IPO/上市事件归入全球融资，避免 VC 观点或“新一轮”误入。"""
    t = (text or "").lower()
    return any(re.search(p, t, flags=re.I) for p in FUND_PATTERNS)


def classify(text):
    t = text.lower()
    is_fund = is_funding_event(t)
    ent_track = None
    for k, v in ENT_KW.items():
        if k.lower() in t:
            ent_track = v
            break
    if is_fund:
        track = "泛娱乐融资" if ent_track else "泛AI·AI应用融资"
        return "全球融资", track
    if ent_track:
        return "泛娱乐·出海", ent_track
    return "创新·AI娱乐", "AI模型与应用（娱乐向）"


def parse_aibot(url, want):
    """抓 ai-bot.cn 每日AI资讯；want 是允许的 月*100+日 日期集合（按北京时间窗口给）。"""
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    html = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "ignore")
    out = []
    cur = None
    pat = re.compile(
        r'(\d{1,2})月(\d{1,2})[·•]周[一二三四五六日]'
        r'|<div class="news-item">(.*?)</div>\s*</div>', re.S)
    for m in pat.finditer(html):
        if m.group(1):
            cur = int(m.group(1)) * 100 + int(m.group(2))
        elif m.group(3) and cur in want:
            block = m.group(3)
            th = re.search(r'<h2><a href="([^"]+)"[^>]*>(.*?)</a></h2>', block, re.S)
            ps = re.search(r"<p[^>]*>(.*?)</p>", block, re.S)
            if not (th and ps):
                continue
            link, title = th.group(1), clean(th.group(2), 200)
            body = re.sub(r'<span class="news-time.*?</span>', "", ps.group(1), flags=re.S)
            srcm = re.search(r"来源：([^<]+)", ps.group(1))
            summary = re.sub(r"来源：.*$", "", clean(body, 400)).strip()
            out.append({"title": title, "summary": summary, "link": link,
                        "src": "ai-bot/" + (srcm.group(1).strip() if srcm else "")})
    return out


def _download_html(url):
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        return urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "ignore")
    except Exception:
        return ""


_DATETIME_RE = re.compile(
    r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?"
)


def _parse_datetime_utc(value, assume_bj=False):
    """把页面里的发布时间转成 naive UTC datetime；白鲸可见时间按北京时间处理。"""
    raw = _html.unescape(str(value or "")).strip()
    if not raw:
        return None
    raw = raw.replace("Z", "+00:00")
    if re.fullmatch(r"\d{13}", raw):
        return dt.datetime.utcfromtimestamp(int(raw) / 1000)
    if re.fullmatch(r"\d{10}", raw):
        return dt.datetime.utcfromtimestamp(int(raw))
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except Exception:
        m = _DATETIME_RE.search(raw)
        if not m:
            return None
        y, mo, d, h, mi, sec = m.groups()
        parsed = dt.datetime(int(y), int(mo), int(d), int(h), int(mi), int(sec or 0))
    if parsed.tzinfo:
        return parsed.astimezone(dt.timezone.utc).replace(tzinfo=None)
    if assume_bj:
        return parsed - dt.timedelta(hours=8)
    return parsed


def _html_attrs(tag):
    attrs = {}
    for k, _, v in re.findall(r'([a-zA-Z_:.-]+)\s*=\s*(["\'])(.*?)\2', tag, re.S):
        attrs[k.lower()] = _html.unescape(v)
    return attrs


def extract_published_utc_from_html(html):
    """从文章页提取发布时间；先读结构化 meta，再读白鲸等页面的 <time>。"""
    if not html:
        return None
    meta_keys = {
        "article:published_time", "og:published_time", "datepublished", "pubdate",
        "publishdate", "publish_date", "baidu_ts", "date", "dc.date",
        "dc.date.issued", "weibo:article:create_at",
    }
    for tag in re.findall(r"<meta\b[^>]*>", html, re.I | re.S):
        attrs = _html_attrs(tag)
        key = (attrs.get("property") or attrs.get("name") or attrs.get("itemprop") or "").lower()
        if key in meta_keys and attrs.get("content"):
            published = _parse_datetime_utc(attrs["content"], assume_bj=False)
            if published:
                return published
    # 白鲸文章页会把发布时间放在 <time class="timeago">2026-06-12 17:49</time>。
    for raw in re.findall(r"<time\b[^>]*>(.*?)</time>", html, re.I | re.S):
        text = clean(raw, 80)
        published = _parse_datetime_utc(text, assume_bj=True)
        if published:
            return published
    # Next.js/WordPress 文章页常有 date_gmt；只用明确发布时间字段，避免误取推荐文章日期。
    for raw in re.findall(r'"date_gmt"\s*:\s*"([^"]+)"', html, re.I):
        published = _parse_datetime_utc(raw, assume_bj=False)
        if published:
            return published
    return None


def bj_time_label(utc_dt):
    return (utc_dt + dt.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")


# 过滤掉 logo/头像/图标/二维码/广告/占位图等非内容图
_IMG_BAD = re.compile(
    r"logo|avatar|icon|qrcode|qr[_\-]?code|/static/|placeholder|spacer|blank|no-js|/ads?[/_]"
    r"|mmbiz|qpic",   # 微信图床防盗链，飞书拉不到，直接排除
    re.I)


def extract_images_from_html(html, base_url="", limit=4):
    """从文章 HTML 抽"内容图"候选 URL（榜单图/产品截图等），过滤 logo/广告。
    同时处理：绝对链接（IT之家 img.ithome.com 等）+ 相对路径正文图
    （白鲸榜单图是 /ueditor/... 相对路径，需用 base_url 补全域名）。"""
    html = html or ""
    origin = ""
    m = re.match(r"(https?://[^/]+)", base_url or "")
    if m:
        origin = m.group(1)
    out = []
    # ① 正文相对图（白鲸榜单 /ueditor、/uploads）——内容图，优先
    if origin:
        for path in re.findall(
                r'<img[^>]+(?:data-original|data-src|src)="(/(?:ueditor|uploads)/[^"]+?\.(?:jpg|jpeg|png|webp))',
                html, re.I):
            u = origin + path
            if not _IMG_BAD.search(u) and u not in out:
                out.append(u)
    # ② 绝对链接图（IT之家产品图等）
    for u in re.findall(
            r'(?:data-original|data-src|src)="(https?://[^"\s]+?\.(?:jpg|jpeg|png|webp))',
            html, re.I):
        if not _IMG_BAD.search(u) and u not in out:
            out.append(u)
    return out[:limit]


def _text_from_html(html):
    import json as _json

    def _clean(raw):
        t = _html.unescape(re.sub(r"<[^>]+>", " ", raw))
        return re.sub(r"\s+", " ", t).strip()

    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if m:                                  # Next.js：递归找 content.rendered
        try:
            data = _json.loads(m.group(1))
            found = {}

            def walk(o):
                if isinstance(o, dict):
                    r = o.get("rendered")
                    if isinstance(r, str) and "<p>" in r:
                        found["x"] = r
                    for v in o.values():
                        walk(v)
                elif isinstance(o, list):
                    for v in o:
                        walk(v)
            walk(data)
            if found:
                return _clean(found["x"])
        except Exception:
            pass
    out = []                               # 静态 <p> 段落（白鲸）
    for p in re.findall(r"<p[^>]*>(.*?)</p>", html, re.S):
        t = _clean(p)
        if len(t) >= 15 and "{{" not in t and "JavaScript" not in t and "会员" not in t:
            out.append(t)
    return " ".join(out)


def fetch_article_full(url):
    """取文章页 → 返回 (正文文本, 候选图URL列表, 发布时间UTC)。"""
    h = _download_html(url)
    if not h:
        return "", [], None
    return (_text_from_html(h), extract_images_from_html(h, base_url=url),
            extract_published_utc_from_html(h))


def fetch_article(url):
    """取文章页 → 返回 (正文文本, 候选图URL列表)。
    白鲸正文在静态 <p>；36氪出海正文在 __NEXT_DATA__；图片同页一并抽取。"""
    body, imgs, _ = fetch_article_full(url)
    return body, imgs


def extract_article(url):
    """仅正文文本（向后兼容）。"""
    return fetch_article(url)[0]


def parse_listpage(base, pages, link_pattern, srcname):
    """通用：抓服务端渲染的列表页，返回 标题+链接（无摘要，agent 取文浓缩）。
    link_pattern：文章链接的相对路径正则（如 /article/\\d+ 或 /[0-9a-f]{6,}）。"""
    import urllib.request
    out, seen_slug = [], set()
    anchor = re.compile(r'<a[^>]+href="(' + link_pattern + r')"[^>]*>(.*?)</a>', re.S)
    for path in pages:
        url = base.rstrip("/") + path
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            g = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "ignore")
        except Exception:
            continue
        for href, txt in anchor.findall(g):
            title = clean(txt, 200)
            if len(title) >= 8 and href not in seen_slug:
                seen_slug.add(href)
                out.append({"title": title, "summary": "", "link": base.rstrip("/") + href,
                            "src": srcname})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=None, help="覆盖时间窗为近N小时（测试用）")
    ap.add_argument("--date", default=None, help="指定目标日期 YYYYMMDD，按北京时间前一日16:00—当日16:00抓取（历史测试用）")
    ap.add_argument("--include-undated", action="store_true",
                    help="配合 --date 使用时也纳入正文页仍取不到时间的列表页条目；默认跳过，避免历史测试混入当前列表页")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    if args.hours and args.date:
        ap.error("--hours 和 --date 不能同时使用")
    if args.date and not re.match(r"^\d{8}$", args.date):
        ap.error("--date 必须是 YYYYMMDD，例如 20260410")

    cfg = yaml.safe_load(open(SOURCES, encoding="utf-8"))
    base = cfg["config"]["rsshub_base"]
    kw = cfg.get("keywords", {})
    include = kw.get("include", [])
    exclude = kw.get("exclude", [])
    protect = kw.get("exclude_protect", [])
    sel = cfg["config"].get("select", {})
    per_track_top = sel.get("per_track_top", 5)
    total_cap = sel.get("total_cap", 22)
    env = load_env()

    start_utc, end_utc, start_bj, end_bj = bj_window(args.hours, args.date)
    if start_bj:                       # 默认北京16:00窗口
        want_dates = {start_bj.month * 100 + start_bj.day, end_bj.month * 100 + end_bj.day}
        window_label = (f"{start_bj:%-m月%-d日 16:00} — {end_bj:%-m月%-d日 16:00}（北京时间）")
        target_ymd = end_bj.strftime("%Y%m%d")
    else:                              # --hours 测试模式
        nb = dt.datetime.utcnow() + dt.timedelta(hours=8)
        want_dates = {(nb - dt.timedelta(days=i)).month * 100 + (nb - dt.timedelta(days=i)).day
                      for i in range(3)}
        window_label = f"近 {args.hours}h（测试模式）"
        target_ymd = nb.strftime("%Y%m%d")

    recent_links, recent_sources = load_recent_links(target_ymd)
    undated_seen = load_undated_seen()
    new_undated_seen = {}

    grouped = defaultdict(lambda: defaultdict(list))   # board -> track -> [items]
    wechat_pending, api_pending, errors = [], [], []
    seen_links, seen_sigs = set(), []
    undated = skipped_recent = skipped_undated_seen = skipped_unverified_listpage = 0

    def add(it, board=None, track=None):
        """统一入口：跨日去重 + 当前运行去重（链接 + 标题近重复）后入库。"""
        nonlocal undated, skipped_recent, skipped_undated_seen
        link = normalize_url(it.get("link", ""))
        if not link:
            return
        if link in recent_links:
            skipped_recent += 1
            return
        if it.get("undated"):
            first_seen = undated_seen.get(link)
            if first_seen and first_seen != target_ymd:
                skipped_undated_seen += 1
                return
        if link in seen_links:
            return
        sig = sig_tokens(it["title"])
        if is_dup(sig, seen_sigs):
            return
        seen_links.add(link)
        seen_sigs.append(sig)
        b, t = (board, track) if board else classify(it["title"] + " " + it.get("summary", ""))
        it["score"] = score(it)
        grouped[b][t].append(it)
        if it.get("undated"):
            undated += 1
            if link not in undated_seen:
                new_undated_seen[link] = target_ymd

    for src in cfg.get("sources", []):
        if not src.get("enabled"):
            continue
        board, track, name = src["board"], src["track"], src["name"]
        typ = src.get("type")

        if typ == "aibot":
            try:
                for it in parse_aibot(src["url"], want_dates):
                    if hit_keywords(it["title"] + " " + it["summary"], include, exclude, protect):
                        add(it)
            except Exception as ex:
                errors.append(f"{name}: {ex}")
            continue

        if typ == "listpage":
            try:
                items = parse_listpage(src["url"], src.get("pages", ["/"]),
                                       src.get("link_pattern", r"/[0-9a-f]{6,}"), name)
                fetched = 0
                body_limit = src.get("body_limit", 12)
                for it in items:
                    if not hit_keywords(it["title"], include, exclude, protect):
                        continue
                    body, imgs, published = "", [], None
                    # 列表页本身常无时间；进正文页取全文、候选图和发布时间，再做窗口过滤。
                    if src.get("fetch_body"):
                        body, imgs, published = fetch_article_full(it["link"])
                    if published:
                        if not (start_utc <= published <= end_utc):
                            continue
                        it["published_utc"] = published.isoformat(timespec="seconds")
                        it["published_bj"] = bj_time_label(published)
                        it["undated"] = False
                    else:
                        if not args.include_undated:
                            skipped_unverified_listpage += 1
                            continue
                        it["undated"] = True
                    if body and fetched < body_limit:
                        it["summary"] = body[:600]
                        fetched += 1
                        if imgs:
                            it["images"] = imgs
                    add(it)
            except Exception as ex:
                errors.append(f"{name}: {ex}")
            continue

        if typ == "wechat":
            wechat_pending.append((board, track, name, src.get("note", "")))
            continue
        if typ == "api":
            slot = src.get("api_slot", "")
            api_pending.append((name, "已配置 key，待接专抓逻辑" if env.get(slot)
                                else f"未配置 {slot}，跳过"))
            continue

        url = feed_url(src, base)
        if not url:
            continue
        try:
            d = feedparser.parse(url)
            img_fetched, image_limit = 0, src.get("image_limit", 12)
            for e in d.entries:
                title = clean(e.get("title", ""), 200)
                summ = clean(entry_best_text(e), 500)   # 取全文字段+判空，修公众号乱码/&&&&
                link = e.get("link", "")
                if not title:
                    continue
                w = in_window(e, start_utc, end_utc)
                if w is False:             # 明确在窗口外
                    continue
                if args.date and w is None and not args.include_undated:
                    continue
                text_for_filter = title + " " + summ
                if not hit_keywords(text_for_filter, include, exclude, protect):
                    continue
                if is_personal_lifestyle_noise(text_for_filter):
                    continue
                if is_low_info_title_only(title, summ):
                    continue
                if board == "全球融资" and not src.get("autoclassify") and not is_funding_event(text_for_filter):
                    continue
                it = {"title": title, "summary": summ, "link": link, "src": name,
                      "undated": w is None}
                # 产品截图类源（如 IT之家）：抓原文里的候选图
                if src.get("fetch_images") and img_fetched < image_limit:
                    imgs = extract_images_from_html(_download_html(link), base_url=link)
                    if imgs:
                        it["images"] = imgs
                        img_fetched += 1
                if src.get("autoclassify"):     # 跨板块综合源（IT之家/36氪）按标题分流
                    add(it)
                else:
                    add(it, board, track)
            if not d.entries:
                errors.append(f"{name}: 无条目/抓取失败（{url}）")
        except Exception as ex:
            errors.append(f"{name}: {ex}")

    # ---- 排序 + 精选 + 篇幅控制 ----
    BOARD_ORDER = ["泛娱乐·出海", "创新·AI娱乐", "全球融资"]
    picked, backups, total_pick = [], [], 0
    out_lines = []
    for board in BOARD_ORDER + [b for b in grouped if b not in BOARD_ORDER]:
        if board not in grouped:
            continue
        out_lines.append(f"## {board}")
        for track, items in grouped[board].items():
            items.sort(key=lambda x: x["score"], reverse=True)
            top, rest = items[:per_track_top], items[per_track_top:]
            out_lines.append(f"### {track}（精选 {len(top)} / 候选 {len(items)}）")
            for it in top:
                total_pick += 1
                flag = " ⏱无时间戳" if it.get("undated") else ""
                if it.get("published_bj"):
                    flag += f"（发布 {it['published_bj']}）"
                out_lines.append(f"- ⭐**{it['title']}**（score {it['score']}）｜{it['src']}{flag}")
                if it.get("summary"):
                    out_lines.append(f"  - {it['summary']}")
                if it.get("images"):
                    out_lines.append(f"  - 候选图: " + " | ".join(it["images"]))
                out_lines.append(f"  - {it['link']}")
            for it in rest:
                flag = " ⏱无时间戳" if it.get("undated") else ""
                if it.get("published_bj"):
                    flag += f"（发布 {it['published_bj']}）"
                out_lines.append(f"- 备选：{it['title']}｜{it['src']}{flag} — {it['link']}")
            out_lines.append("")

    # ---- 抬头 + 组装 ----
    today = target_ymd
    out = args.out or os.path.join(HERE, f"资讯日报-草稿-{today}.md")
    head = [
        f"# 资讯候选清单 · {today}",
        "",
        f"**时间范围：{window_label}**",
        f"**精选 {total_pick} 条（每赛道Top{per_track_top}，建议成稿≤{total_cap}条）；"
        f"已去重（链接+跨源近重复）；列表页已进正文页解析发布时间并按窗口过滤，"
        f"默认跳过仍无时间戳条目。**",
        f"**跨日回溯：已读取前 {HISTORY_LOOKBACK_DAYS} 天链接，跳过历史重复 {skipped_recent} 条；"
        f"无时间戳链接仅首次出现保留，跳过历史无时间戳 {skipped_undated_seen} 条。**",
        "",
        "> 下一步：agent 取 ⭐精选 按《格式规范》模板 A/B/C 浓缩成日报；篇幅过长时按 score 优先保留；"
        "融资走模板 C。备选仅作补充池。",
        "",
    ]
    lines = head + out_lines
    if wechat_pending:
        lines.append("## ⚠️ 公众号待人工贴链接（无官方API）")
        lines += [f"- [{b}/{t}] {n}（{note}）" if note else f"- [{b}/{t}] {n}"
                  for b, t, n, note in wechat_pending]
        lines.append("")
    if api_pending:
        lines.append("## API 源状态")
        lines += [f"- {n}：{st}" for n, st in api_pending]
        lines.append("")
    if skipped_recent or skipped_undated_seen:
        lines.append("## 过滤统计")
        lines.append(f"- 前 {HISTORY_LOOKBACK_DAYS} 天链接回溯去重：跳过 {skipped_recent} 条")
        lines.append(f"- 无时间戳链接首次出现去重：跳过 {skipped_undated_seen} 条")
        if recent_sources:
            lines.append("- 回溯文件：" + "、".join(os.path.basename(p) for p in recent_sources))
        lines.append("")
    if skipped_unverified_listpage:
        lines.append("## 列表页时间过滤")
        lines.append(f"- 正文页仍未解析到发布时间、默认跳过：{skipped_unverified_listpage} 条")
        lines.append("- 如需人工排查，可临时加 `--include-undated` 生成调试草稿。")
        lines.append("")
    if errors:
        lines.append("## 抓取告警")
        lines += [f"- {e}" for e in errors]
        lines.append("")

    if new_undated_seen:
        undated_seen.update(new_undated_seen)
        save_undated_seen(undated_seen)

    open(out, "w", encoding="utf-8").write("\n".join(lines))
    print(f"✅ 草稿已生成：{out}")
    print(f"   时间窗：{window_label}")
    print(f"   精选 {total_pick} 条 / 公众号待补 {len(wechat_pending)} 源 / "
          f"告警 {len(errors)} 条 / 无时间戳 {undated} 条 / "
          f"列表页无发布时间跳过 {skipped_unverified_listpage} 条")
    print(f"   跨日去重跳过 {skipped_recent} 条 / 历史无时间戳跳过 {skipped_undated_seen} 条")


if __name__ == "__main__":
    main()
