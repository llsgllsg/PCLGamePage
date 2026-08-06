import requests
import re
import html as html_mod
import os
import json
from datetime import datetime, timedelta

CACHE_DIR = "cache"
CACHE_FILE = os.path.join(CACHE_DIR, "steam_games.json")
CACHE_EXPIRE_MINUTES = 60

# 过滤与打分参数
MIN_REVIEWS = 100           # 过滤评测数过少的新游戏，避免好评率失真
MIN_REVIEW_PCT = 70         # 只保留至少"多半好评"的游戏（高分精选）
W_DISCOUNT = 0.35           # 混合打分：折扣权重
W_REVIEW = 0.35             # 混合打分：好评率权重
W_RECENT = 0.30             # 混合打分：发售新度权重（越新越靠前）

# 特惠搜索页解析正则
ROW_RE = re.compile(r'<a\b[^>]*class="[^"]*search_result_row[^"]*"[^>]*>.*?</a>', re.S)
APPID_RE = re.compile(r'data-ds-appid="(\d+)"')
TITLE_RE = re.compile(r'<span class="title">(.*?)</span>', re.S)
CAPSULE_RE = re.compile(r'<div class="search_capsule"><img src="([^"]+)"')
RELEASED_RE = re.compile(r'<div class="search_released[^"]*"[^>]*>(.*?)</div>', re.S)
REVIEW_RE = re.compile(r'class="search_review_summary[^"]*" data-tooltip-html="([^"]*)"')
TOOLTIP_RE = re.compile(r'([\d,]+) 篇用户评测中有 (\d+)% 为好评')
PRICE_FINAL_RE = re.compile(r'class="search_price_discount_combined[^"]*" data-price-final="(\d+)"')
DISCOUNT_RE = re.compile(r'data-discount="(\d+)"')
ORIG_PRICE_RE = re.compile(r'<div class="discount_original_price">([^<]*)</div>')

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def _ensure_cache_dir():
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)


def _parse_price(text):
    """把 '¥33.00' / '33.00' 解析成 float，失败返回 None。"""
    if not text:
        return None
    try:
        return float(text.replace("¥", "").replace(",", "").strip())
    except ValueError:
        return None


def parse_row(block):
    """解析搜索结果中的一行（一款游戏）。"""
    m_appid = APPID_RE.search(block)
    if not m_appid:
        return None
    appid = int(m_appid.group(1))

    m_name = TITLE_RE.search(block)
    name = m_name.group(1).strip() if m_name else None

    m_capsule = CAPSULE_RE.search(block)
    small_image = m_capsule.group(1) if m_capsule else None

    m_released = RELEASED_RE.search(block)
    release_date = m_released.group(1).strip() if m_released else ""
    year = None
    if release_date:
        m_year = re.search(r"(20\d{2})", release_date)
        if m_year:
            year = int(m_year.group(1))

    # 好评信息（好评等级 + 好评率 + 评测数）
    rating_text = None
    review_pct = None
    review_count = 0
    m_rev = REVIEW_RE.search(block)
    if m_rev:
        tooltip = html_mod.unescape(m_rev.group(1))
        first_line = tooltip.split("<br>")[0].strip()
        if first_line:
            rating_text = first_line
        m_tip = TOOLTIP_RE.search(tooltip)
        if m_tip:
            review_count = int(m_tip.group(1).replace(",", ""))
            review_pct = int(m_tip.group(2))

    # 价格与折扣
    m_disc = DISCOUNT_RE.search(block)
    discount_percent = int(m_disc.group(1)) if m_disc else 0
    m_final = PRICE_FINAL_RE.search(block)
    final_price = int(m_final.group(1)) / 100 if m_final else None
    m_orig = ORIG_PRICE_RE.search(block)
    original_price = _parse_price(m_orig.group(1)) if m_orig else None

    return {
        "id": appid,
        "name": name,
        "small_image": small_image,
        "release_date": release_date,
        "year": year,
        "rating_text": rating_text,
        "review_pct": review_pct,
        "review_count": review_count,
        "discounted": discount_percent > 0,
        "discount_percent": discount_percent,
        "final_price": final_price,
        "original_price": original_price,
    }


def fetch_search_specials(count=100, cc="cn", language="schinese"):
    """从 Steam 特惠搜索页抓取打折游戏列表（category1=998 排除 DLC/软件）。"""
    url = "https://store.steampowered.com/search/results/"
    params = {
        "query": "", "start": 0, "count": count,
        "specials": 1, "category1": 998,
        "cc": cc, "l": language,
    }
    resp = requests.get(url, params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    games = []
    for m in ROW_RE.finditer(resp.text):
        g = parse_row(m.group(0))
        if g:
            games.append(g)
    return games


def resolve_image(game):
    """优先用 616x353 高清横版封面；极少数新游戏没有无 hash 图时回退到详情页 header 图。"""
    url = f"https://cdn.akamai.steamstatic.com/steam/apps/{game['id']}/capsule_616x353.jpg"
    try:
        r = requests.head(url, headers=HEADERS, timeout=8)
        if r.status_code == 200:
            return url
    except Exception:
        pass
    try:
        r = requests.get("https://store.steampowered.com/api/appdetails",
                         params={"appids": game["id"], "cc": "cn", "l": "schinese"}, timeout=15)
        data = r.json().get(str(game["id"]), {}).get("data", {})
        if data.get("header_image"):
            return data["header_image"]
    except Exception:
        pass
    return game.get("small_image")


def _recency_score(year):
    """按发售年份给新度打分，越新分数越高（满分 100）。"""
    if not year:
        return 0
    age = max(0, datetime.now().year - year)
    return max(0, 100 - age * 18)


def _compute_score(game):
    """混合打分：折扣 × 权重 + 好评率 × 权重 + 发售新度 × 权重。"""
    return (
        W_DISCOUNT * game["discount_percent"]
        + W_REVIEW * (game["review_pct"] or 0)
        + W_RECENT * _recency_score(game.get("year"))
    )


def get_games(limit=8, cc="cn", language="schinese"):
    """读取缓存或抓取特惠游戏，过滤后按混合打分排序，返回前 limit 个（已解析高清图）。"""
    _ensure_cache_dir()
    games = None
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
                cache_time = datetime.fromisoformat(cache["timestamp"])
                if datetime.now() - cache_time < timedelta(minutes=CACHE_EXPIRE_MINUTES):
                    games = cache["games"]
        except Exception as e:
            print(f"[警告] 读取缓存失败: {e}")

    if games is None:
        print("[信息] 正在从 Steam 特惠搜索页获取数据...")
        games = fetch_search_specials(cc=cc, language=language)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"timestamp": datetime.now().isoformat(), "games": games}, f, ensure_ascii=False, indent=2)

    # 过滤：有折扣、评测数足够、好评率达标
    pool = [
        g for g in games
        if g["discount_percent"] > 0
        and g["review_count"] >= MIN_REVIEWS
        and (g["review_pct"] or 0) >= MIN_REVIEW_PCT
    ]
    for g in pool:
        g["score"] = _compute_score(g)
    pool.sort(key=lambda g: g["score"], reverse=True)

    selected = pool[:limit]
    for g in selected:
        g["img"] = resolve_image(g)
    return selected
