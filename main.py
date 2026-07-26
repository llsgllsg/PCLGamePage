import os
import re
from steam_api import get_steam_games_cached

def escape_xaml(text):
    if text is None:
        return ""
    text = str(text)
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    text = text.replace("\"", "&quot;")
    text = text.replace("'", "&apos;")
    return text

def replaces(template, data):
    for key, value in data.items():
        template = template.replace("{" + key + "}", escape_xaml(value))
    return template

#Debug
CATEGORY = "specials"        # 类型: specials, top_sellers, new_releases, coming_soon
LIMIT = 10
LANGUAGE = "schinese"

#名称汉化
CATEGORY_LABEL = {
    "specials": "特惠游戏",
    "top_sellers": "热销商品",
    "new_releases": "新品上架",
    "coming_soon": "即将推出"
}

def main():
    games = get_steam_games_cached(CATEGORY, limit=LIMIT, language=LANGUAGE)
    if not games:
        print("[Fuck] 未能获取到游戏数据")
        return

    template_dir = "templates"
    with open(os.path.join(template_dir, "header.xaml"), "r", encoding="utf-8") as f:
        header = f.read()
    with open(os.path.join(template_dir, "label.xaml"), "r", encoding="utf-8") as f:
        label_template = f.read()
    with open(os.path.join(template_dir, "game.xaml"), "r", encoding="utf-8") as f:
        game_template = f.read()
    with open(os.path.join(template_dir, "footer.xaml"), "r", encoding="utf-8") as f:
        footer = f.read()

    label_data = {
        "label": CATEGORY_LABEL.get(CATEGORY, "推荐游戏"),
        "tag": CATEGORY
    }
    label_xaml = replaces(label_template, label_data)

    game_items = []
    for idx, game in enumerate(games):
        #显示价格
        if game["discounted"]:
            price_display = f"¥{game['final_price']:.2f} (-{game['discount_percent']}%)"
        else:
            price_display = f"¥{game['final_price']:.2f}" if game['final_price'] is not None else "免费"

        data = {
            "id": game["id"],
            "img": game["header_image"],
            "name": game["name"],
            "artists": price_display,               # 显示价格
            "album": CATEGORY_LABEL.get(CATEGORY, ""),
            "url": f"https://store.steampowered.com/app/{game['id']}",
            "tag": CATEGORY,
            "label": CATEGORY_LABEL.get(CATEGORY, ""),
            "khd": "",   
            "khdtype": ""
        }
        item_xaml = replaces(game_template, data)
        game_items.append(item_xaml)


    final_xaml = header + "\n" + label_xaml + "\n" + "\n".join(game_items) + "\n" + footer


    output_dir = "output"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    output_path = os.path.join(output_dir, "Custom.xaml")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(final_xaml)

    print(f"[Debug] 已生成 {output_path}，共 {len(games)} 个游戏。")

if __name__ == "__main__":
    main()
