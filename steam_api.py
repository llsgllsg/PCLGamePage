import requests
import json
import os
from datetime import datetime, timedelta

CACHE_DIR = "cache"
CACHE_FILE = os.path.join(CACHE_DIR, "steam_games.json")
CACHE_EXPIRE_MINUTES = 60  # 缓存有效时间（分钟）

def _ensure_cache_dir():
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)

def fetch_steam_category(category, limit=10, language="schinese"):
    """
    直接请求 Steam featuredcategories 接口（无缓存）
    """
    url = "https://store.steampowered.com/api/featuredcategories"
    params = {"l": language}
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        cat_data = data.get(category, {})
        items = cat_data.get("items", [])
        games = []
        for item in items[:limit]:
            # 提取必要字段
            game = {
                "id": item.get("id"),
                "name": item.get("name"),
                "header_image": item.get("header_image"),
                "discounted": item.get("discounted", False),
                "discount_percent": item.get("discount_percent", 0),
                "original_price": item.get("original_price", 0) / 100 if item.get("original_price") else None,
                "final_price": item.get("final_price", 0) / 100 if item.get("final_price") else None,
            }
            games.append(game)
        return games
    except Exception as e:
        print(f"[错误] 请求 Steam API 失败: {e}")
        return []

def fetch_all_categories(limit_per_category=50, language="schinese"):
    """
    获取所有分类的数据，用于缓存
    """
    all_data = {}
    categories = ["specials", "top_sellers", "new_releases", "coming_soon"]
    for cat in categories:
        all_data[cat] = fetch_steam_category(cat, limit=limit_per_category, language=language)
    return all_data

def get_steam_games_cached(category, limit=10, language="schinese"):
    """
    带缓存的获取方式，优先读取缓存，过期则刷新
    """
    _ensure_cache_dir()
    # 尝试读缓存
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
                cache_time = datetime.fromisoformat(cache["timestamp"])
                if datetime.now() - cache_time < timedelta(minutes=CACHE_EXPIRE_MINUTES):
                    # 缓存有效，返回对应分类的数据
                    cached_data = cache["data"].get(category, [])
                    return cached_data[:limit]
        except Exception as e:
            print(f"[警告] 读取缓存失败: {e}，将重新请求")
    # 缓存失效或不存在，重新拉取所有分类并缓存
    print("[信息] 正在从 Steam 获取最新数据...")
    all_data = fetch_all_categories(limit_per_category=50, language=language)
    # 保存缓存
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "data": all_data
        }, f, ensure_ascii=False, indent=2)
    # 返回请求的分类数据
    return all_data.get(category, [])[:limit]
