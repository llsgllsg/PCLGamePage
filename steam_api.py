import requests
import json
import os
import random
from datetime import datetime, timedelta

CACHE_DIR = "cache"
CACHE_FILE = os.path.join(CACHE_DIR, "steam_games.json")
CACHE_EXPIRE_MINUTES = 60

def _ensure_cache_dir():
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)

def fetch_steam_category(category, limit=10, language="schinese"):
    url = "https://store.steampowered.com/api/featuredcategories"
    params = {"l": language}
    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        cat_data = data.get(category, {})
        items = cat_data.get("items", [])
        games = []
        for item in items[:limit]:
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
    all_data = {}
    categories = ["specials", "top_sellers", "new_releases", "coming_soon"]
    for cat in categories:
        all_data[cat] = fetch_steam_category(cat, limit=limit_per_category, language=language)
    return all_data

def get_steam_games_cached(category, limit=10, language="schinese", mix_categories=True):
    _ensure_cache_dir()
    # 尝试读缓存
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
                cache_time = datetime.fromisoformat(cache["timestamp"])
                if datetime.now() - cache_time < timedelta(minutes=CACHE_EXPIRE_MINUTES):
                    if mix_categories:
                        # 混合多个分类的游戏池，丰富度更高
                        games = []
                        seen_ids = set()
                        for cat in ["specials", "top_sellers", "new_releases"]:
                            for g in cache["data"].get(cat, []):
                                if g["id"] not in seen_ids:
                                    games.append(g)
                                    seen_ids.add(g["id"])
                    else:
                        games = cache["data"].get(category, [])
                    
                    seed = int(datetime.now().strftime("%Y%m%d%H"))
                    rng = random.Random(seed)
                    rng.shuffle(games)
                    return games[:limit]
        except Exception as e:
            print(f"[警告] 读取缓存失败: {e}")
    print("[信息] 正在从 Steam 获取最新数据...")
    all_data = fetch_all_categories(limit_per_category=50, language=language)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "data": all_data
        }, f, ensure_ascii=False, indent=2)
    
    if mix_categories:
        # 混合多个分类
        games = []
        seen_ids = set()
        for cat in ["specials", "top_sellers", "new_releases"]:
            for g in all_data.get(cat, []):
                if g["id"] not in seen_ids:
                    games.append(g)
                    seen_ids.add(g["id"])
    else:
        games = all_data.get(category, [])
    
    seed = int(datetime.now().strftime("%Y%m%d%H"))
    rng = random.Random(seed)
    rng.shuffle(games)
    return games[:limit]
