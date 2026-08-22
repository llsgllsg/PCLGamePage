import requests
import re
import html as html_mod
import os
import json
import random
import time
import concurrent.futures
from datetime import date, datetime, timedelta

CACHE_DIR = "cache"
CACHE_FILE = os.path.join(CACHE_DIR, "steam_games.json")
CACHE_EXPIRE_MINUTES = 60

# 去重记录：把每天推过的游戏写回仓库 history.json，保证与最近 14 天推送不撞车
HISTORY_FILE = "history.json"
HISTORY_KEEP_DAYS = 14

# 图片缓存：把选中的游戏封面下载到本地 images/ 目录，随 XAML 一起上传到云端
# （仓库缓存一份 + scp 到服务器，XAML 改为引用自己服务器的图，不依赖 Steam CDN）
IMAGE_DIR = "images"
IMAGE_BASE_URL = "https://g-fish.dpdns.org/download/images/"

# 过滤与打分参数
MIN_REVIEWS = 100           # 过滤评测数过少的新游戏，避免好评率失真
MIN_REVIEW_PCT = 70         # 只保留至少"多半好评"的游戏（高分精选）
W_DISCOUNT = 0.15           # 混合打分：折扣权重
W_REVIEW = 0.25             # 混合打分：好评率权重
W_RECENT = 0.60             # 混合打分：发售新度权重（越新越靠前，主页以新游戏为主）

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


def _download_images(games):
    """把选中的游戏封面下载到本地 images/ 目录（仓库缓存 + 随 XAML 上传云端）。
    只保留当前这批，删除不再引用的旧图，避免仓库无限膨胀。
    返回成功下载的 appid 集合；已存在的直接复用，不重复下载。"""
    if not games:
        return set()
    if not os.path.exists(IMAGE_DIR):
        os.makedirs(IMAGE_DIR)

    keep_ids = {g["id"] for g in games}
    ok = set()
    for g in games:
        url = g.get("img")
        if not url:
            continue
        path = os.path.join(IMAGE_DIR, f"{g['id']}.jpg")
        if os.path.exists(path) and os.path.getsize(path) > 0:
            ok.add(g["id"])  # 已缓存过，复用
            continue
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 200 and r.content:
                with open(path, "wb") as f:
                    f.write(r.content)
                ok.add(g["id"])
                print(f"[信息] 已缓存图片 {g['id']}.jpg")
        except Exception as e:
            print(f"[警告] 下载图片失败 {g['id']}: {e}")

    # 清理不再引用的旧图，仓库里只保留当前这批封面
    for name in os.listdir(IMAGE_DIR):
        if not name.endswith(".jpg"):
            continue
        appid = name[:-4]
        if not appid.isdigit() or int(appid) not in keep_ids:
            try:
                os.remove(os.path.join(IMAGE_DIR, name))
            except OSError:
                pass
    return ok


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


def _filter_r18_descriptors(games):
    """并发查询内容分级，过滤掉 R18 描述符游戏（带 7 天缓存）。"""
    if not games:
        return games
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        descs = list(ex.map(_fetch_descriptors, [g["id"] for g in games]))
    _save_desc_cache()
    return [g for g, d in zip(games, descs) if not (d & R18_DESCRIPTOR_IDS)]


def _localize_name(appid):
    """按中文查询 appdetails 拿 Steam 官方游戏名：有中文名用中文，没有则返回英文原名。"""
    try:
        r = requests.get("https://store.steampowered.com/api/appdetails",
                         params={"appids": appid, "cc": "cn", "l": "schinese"}, timeout=12)
        data = r.json().get(str(appid), {}).get("data", {})
        name = data.get("name")
        if name:
            return name.strip()
    except Exception:
        pass
    return None


def _recency_score(year):
    """按发售年份给新度打分，越新分数越高（满分 100）。
    曲线较陡：近 3 年才有明显新度分，老游戏趋近 0，保证主页以新游戏为主。"""
    if not year:
        return 0
    age = max(0, datetime.now().year - year)
    return max(0, 100 - age * 25)


def _compute_score(game):
    """混合打分：折扣 × 权重 + 好评率 × 权重 + 发售新度 × 权重。"""
    return (
        W_DISCOUNT * game["discount_percent"]
        + W_REVIEW * (game["review_pct"] or 0)
        + W_RECENT * _recency_score(game.get("year"))
    )


def _weighted_sample(rng, games, k):
    """按 score 加权随机抽 k 个（不重复），分数越高越容易被选中。
    保底权重 1，保证低分游戏偶尔也能出现；同一天重复跑结果一致。"""
    if len(games) <= k:
        return games[:]
    pool = list(games)
    weights = [max(g["score"], 1) for g in pool]
    chosen = []
    for _ in range(k):
        total = sum(weights)
        r = rng.random() * total
        acc = 0
        for i, w in enumerate(weights):
            acc += w
            if r <= acc:
                chosen.append(pool.pop(i))
                weights.pop(i)
                break
    return chosen


def _day_number():
    """1970-01-01 至今的天数，用作每日随机种子（同一天重复跑结果一致）。"""
    return (date.today() - date(1970, 1, 1)).days


def _load_history():
    """读取仓库里的已推游戏记录，返回 {日期: [appid, ...]}。"""
    if not os.path.exists(HISTORY_FILE):
        return {}
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("history") or {}
    except Exception:
        return {}


def _prune_history(history):
    """只保留最近 HISTORY_KEEP_DAYS 天的记录，按日期升序返回。"""
    cutoff = (date.today() - timedelta(days=HISTORY_KEEP_DAYS)).isoformat()
    return dict(sorted((d, ids) for d, ids in history.items() if d >= cutoff))


def _save_history(history):
    """把去重记录写回 history.json（由 Action 提交到仓库）。"""
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump({"history": history}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[警告] 写入去重记录失败: {e}")


def get_games(limit=8, cc="cn", language="schinese"):
    """读取缓存或抓取特惠游戏，过滤后排除最近 14 天推过的，按日期随机选 limit 个（已解析高清图）。"""
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
        games = fetch_search_specials(count=500, cc=cc, language=language)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"timestamp": datetime.now().isoformat(), "games": games}, f, ensure_ascii=False, indent=2)

    # 过滤第一层：有折扣、评测数足够、好评率达标、排除 R18 社区标签、排除 100% 好评率(小样本失真)
    pool = [
        g for g in games
        if g["discount_percent"] > 0
        and g["review_count"] >= MIN_REVIEWS
        and (g["review_pct"] or 0) >= MIN_REVIEW_PCT
        and g.get("review_pct") != 100
        and not (set(g.get("tag_ids") or []) & R18_TAG_IDS)
    ]
    for g in pool:
        g["score"] = _compute_score(g)
    pool.sort(key=lambda g: g["score"], reverse=True)

    # 过滤第二层：内容分级描述符（并发查 appdetails，排除性/裸露/成人内容）
    pool = _filter_r18_descriptors(pool)
    if not pool:
        return []

    # 去重：排除最近 HISTORY_KEEP_DAYS 天推过的游戏，保证不撞车。
    # 候选池不足以选满 limit 个时，从最早一天开始逐步放宽排除窗口。
    history = _prune_history(_load_history())
    recent_days = sorted(history)
    eligible = []
    for window in range(HISTORY_KEEP_DAYS, -1, -1):
        recent_ids = set()
        for d in recent_days[-window:] if window else []:
            recent_ids.update(history[d])
        eligible = [g for g in pool if g["id"] not in recent_ids]
        if len(eligible) >= limit or window == 0:
            break

    # 用当天日期做种子，按分数加权随机抽 limit 个（同一天重复跑结果一致）。
    # 之前用 shuffle 均匀随机，打分完全不影响选中概率，导致整页偏老游戏；
    # 改为分数加权抽样后，新游戏/高折扣/好评高分的更常被选中。
    rng = random.Random(_day_number())
    selected = _weighted_sample(rng, eligible, limit)

    # 记录当天已推游戏，写回 history.json（由 Action 提交到仓库）
    history = _prune_history(_load_history())
    history[date.today().isoformat()] = [g["id"] for g in selected]
    _save_history(_prune_history(history))
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        imgs = list(ex.map(resolve_image, selected))
        names = list(ex.map(_localize_name, [g["id"] for g in selected]))
    for g, img, loc_name in zip(selected, imgs, names):
        g["img"] = img
        if loc_name:
            g["name"] = loc_name  # 游戏名优先用 Steam 官方中文名，无中文则保持英文

    # 下载封面到本地 images/ 目录，并把 XAML 引用的图片地址换成自己服务器的
    downloaded = _download_images(selected)
    for g in selected:
        if g["id"] in downloaded:
            g["img"] = f"{IMAGE_BASE_URL}{g['id']}.jpg"
    return selected


def get_epic_free_games():
    """从 uapis.cn 获取 Epic 当前免费游戏列表，返回适配 XAML 渲染的字典列表。"""
    try:
        r = requests.get("https://uapis.cn/api/v1/game/epic-free", timeout=15)
        data = r.json().get("data") or []
    except Exception as e:
        print(f"[警告] 获取 Epic 免费游戏失败: {e}")
        return []
    games = []
    for item in data:
        if not item.get("is_free_now"):
            continue
        # 去掉标题里的书名号《》
        title = item.get("title", "").strip()
        title = title.removeprefix("《").removesuffix("》")
        games.append({
            "id": item.get("id", ""),
            "name": title,
            "img": item.get("cover", ""),
            "original_price_desc": item.get("original_price_desc", ""),
            "free_end": item.get("free_end", ""),
            "link": item.get("link", ""),
        })
    return games
