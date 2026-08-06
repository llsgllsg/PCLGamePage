import requests
import re
import html as html_mod
import os
import json
import time
import concurrent.futures
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

# R18 过滤第一层：命中以下 Steam 社区标签的游戏将被排除
# 9130=动漫色情(Hentai) 6650=裸露(Nudity) 12095=色情内容(Sexual Content)
R18_TAG_IDS = {9130, 6650, 12095}

# R18 过滤第二层：内容分级描述符（appdetails 的 content_descriptors）
# 1=部分裸露/性内容 3=成人专属 4=大量性内容。保留 2(频繁血腥暴力)等主流游戏。
R18_DESCRIPTOR_IDS = {1, 3, 4}

# 特惠搜索页解析正则
ROW_RE = re.compile(r'<a\b[^>]*class="[^"]*search_result_row[^"]*"[^>]*>.*?</a>', re.S)
APPID_RE = re.compile(r'data-ds-appid="(\d+)"')
TITLE_RE = re.compile(r'<span class="title">(.*?)</span>', re.S)
CAPSULE_RE = re.compile(r'<div class="search_capsule"><img src="([^"]+)"')
RELEASED_RE = re.compile(r'<div class="search_released[^"]*"[^>]*>(.*?)</div>', re.S)
REVIEW_RE = re.compile(r'class="search_review_summary[^"]*" data-tooltip-html="([^"]*)"')
TOOLTIP_RE = re.compile(r'([\d,]+) 篇用户评测中有 (\d+)% 为好评')
TAGS_RE = re.compile(r'data-ds-tagids="\[([^\]]*)\]"')
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

    # 社区标签（用于 R18/R18G 过滤）
    m_tags = TAGS_RE.search(block)
    tag_ids = []
    if m_tags:
        tag_ids = [int(x) for x in m_tags.group(1).split(",") if x.strip().isdigit()]

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
        "tag_ids": tag_ids,
        "rating_text": rating_text,
        "review_pct": review_pct,
        "review_count": review_count,
        "discounted": discount_percent > 0,
        "discount_percent": discount_percent,
        "final_price": final_price,
        "original_price": original_price,
    }


def fetch_search_specials(count=100, cc="cn", language="schinese"):
    """从 Steam 特惠搜索页抓取打折游戏列表（category1=998 排除 DLC/软件），支持翻页。"""
    url = "https://store.steampowered.com/search/results/"
    games = []
    start = 0
    while start < count:
        page_count = min(100, count - start)
        params = {
            "query": "", "start": start, "count": page_count,
            "specials": 1, "category1": 998,
            "cc": cc, "l": language,
        }
        resp = requests.get(url, params=params, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        page_games = []
        for m in ROW_RE.finditer(resp.text):
            g = parse_row(m.group(0))
            if g:
                page_games.append(g)
        games.extend(page_games)
        start += page_count
        if not page_games:
            break  # 没有更多结果
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


DESC_CACHE_FILE = os.path.join(CACHE_DIR, "descriptors.json")
DESC_CACHE_TTL = 7 * 24 * 3600   # 描述符缓存 7 天（内容分级很少变化）
_desc_cache = None


def _load_desc_cache():
    global _desc_cache
    if _desc_cache is not None:
        return _desc_cache
    _desc_cache = {}
    if os.path.exists(DESC_CACHE_FILE):
        try:
            with open(DESC_CACHE_FILE, "r", encoding="utf-8") as f:
                _desc_cache = json.load(f)
        except Exception:
            _desc_cache = {}
    return _desc_cache


def _save_desc_cache():
    global _desc_cache
    if _desc_cache is None:
        return
    _ensure_cache_dir()
    try:
        with open(DESC_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_desc_cache, f, ensure_ascii=False)
    except Exception:
        pass


def _query_descriptors(appid):
    """请求 appdetails 拿内容分级描述符；失败返回空集合（不误杀）。"""
    try:
        r = requests.get("https://store.steampowered.com/api/appdetails",
                         params={"appids": appid, "cc": "cn", "l": "schinese"}, timeout=12)
        data = r.json().get(str(appid), {}).get("data", {})
        return set(data.get("content_descriptors", {}).get("ids", []))
    except Exception:
        return set()


def _fetch_descriptors(appid):
    """带 7 天缓存的描述符查询。"""
    cache = _load_desc_cache()
    key = str(appid)
    entry = cache.get(key)
    now = time.time()
    if entry and now - entry.get("ts", 0) < DESC_CACHE_TTL:
        return set(entry.get("ids", []))
    desc = _query_descriptors(appid)
    cache[key] = {"ids": sorted(desc), "ts": now}
    return desc


def _filter_r18_descriptors(games, limit=16):
    """并发查询内容分级，只检查打分最高的候选（约 limit*3 个），过滤掉 R18 描述符游戏。"""
    if not games:
        return games
    candidates = games[:max(limit * 3, limit + 12)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        descs = list(ex.map(_fetch_descriptors, [g["id"] for g in candidates]))
    _save_desc_cache()
    return [g for g, d in zip(candidates, descs) if not (d & R18_DESCRIPTOR_IDS)]


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
        games = fetch_search_specials(count=200, cc=cc, language=language)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"timestamp": datetime.now().isoformat(), "games": games}, f, ensure_ascii=False, indent=2)

    # 过滤第一层：有折扣、评测数足够、好评率达标、排除 R18 社区标签游戏
    pool = [
        g for g in games
        if g["discount_percent"] > 0
        and g["review_count"] >= MIN_REVIEWS
        and (g["review_pct"] or 0) >= MIN_REVIEW_PCT
        and not (set(g.get("tag_ids") or []) & R18_TAG_IDS)
    ]
    for g in pool:
        g["score"] = _compute_score(g)
    pool.sort(key=lambda g: g["score"], reverse=True)

    # 过滤第二层：内容分级描述符（并发查 appdetails，排除性/裸露/成人内容）
    pool = _filter_r18_descriptors(pool, limit)

    selected = pool[:limit]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        imgs = list(ex.map(resolve_image, selected))
    for g, img in zip(selected, imgs):
        g["img"] = img
    return selected
