import os
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

CATEGORY = "specials"
LIMIT = 8
LANGUAGE = "schinese"
COLUMNS = 2

CATEGORY_LABEL = {
    "specials": "特惠游戏",
    "top_sellers": "热销商品",
    "new_releases": "新品上架",
    "coming_soon": "即将推出"
}

def main():
    games = get_steam_games_cached(CATEGORY, limit=LIMIT, language=LANGUAGE)
    if not games:
        print("[错误] 未能获取到游戏数据，请检查网络或重试。")
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

    # 处理 label，在标题后添加刷新按钮
    label_data = {
        "label": CATEGORY_LABEL.get(CATEGORY, "推荐游戏")
    }
    label_xaml = replaces(label_template, label_data)

    # 构建 Grid 列定义
    grid_columns = ""
    for i in range(COLUMNS):
        grid_columns += '<ColumnDefinition Width="1*" />\n        '
    
    # 构建游戏卡片
    game_items = []
    for index, game in enumerate(games):
        if game["discounted"] and game["final_price"] is not None:
            price_info = f"¥{game['final_price']:.2f} (原价 ¥{game['original_price']:.2f}，-{game['discount_percent']}%)"
        elif game["final_price"] is not None:
            price_info = f"¥{game['final_price']:.2f}"
        else:
            price_info = "免费"

        store_url = f"https://store.steampowered.com/app/{game['id']}"

        data = {
            "id": game["id"],
            "img": game["header_image"],
            "name": game["name"],
            "price": price_info,
            "url": store_url,
            "column": index % COLUMNS
        }
        item_xaml = replaces(game_template, data)
        game_items.append(item_xaml)

    games_block = "\n    ".join(game_items)
    
    games_grid = f"""    <Grid>
        <Grid.ColumnDefinitions>
        {grid_columns}</Grid.ColumnDefinitions>
        {games_block}
    </Grid>"""

    final_xaml = header + "\n" + label_xaml + "\n" + games_grid + "\n" + footer

    output_path = "SteamPage.xaml"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(final_xaml)

    print(f"[成功] 已生成 {output_path}，共 {len(games)} 个游戏。")

if __name__ == "__main__":
    main()
