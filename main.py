#使用CC BY-NC-SA 4.0 协议

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

def replaces(template, data, no_escape_keys=None):
    if no_escape_keys is None:
        no_escape_keys = ['price']
    for key, value in data.items():
        if key in no_escape_keys:
            template = template.replace("{" + key + "}", str(value))
        else:
            template = template.replace("{" + key + "}", escape_xaml(value))
    return template

CATEGORY = "specials"
LIMIT = 8
LANGUAGE = "schinese"
COLUMNS = 1

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

    label_data = {"label": CATEGORY_LABEL.get(CATEGORY, "推荐游戏")}
    label_xaml = replaces(label_template, label_data)

    rows = (len(games) + COLUMNS - 1) // COLUMNS

    grid_columns = ""
    for i in range(COLUMNS):
        grid_columns += '<ColumnDefinition Width="1*" />\n        '

    grid_rows = ""
    for i in range(rows):
        grid_rows += '<RowDefinition Height="Auto" />\n        '

    game_items = []
    for index, game in enumerate(games):
        if game["discounted"] and game["final_price"] is not None:
            price_xaml = f'''<TextBlock Text="¥{game['final_price']:.2f}" FontSize="22" FontWeight="Bold" Foreground="{{DynamicResource ColorBrush2}}" />
<TextBlock Text="  原价 ¥{game['original_price']:.2f}" FontSize="14" Foreground="{{DynamicResource ColorBrush6}}" />
<TextBlock Text="  -{game['discount_percent']}%" FontSize="14" Foreground="{{DynamicResource ColorBrush3}}" />'''
        elif game["final_price"] == 0 or game["final_price"] is None:
            price_xaml = '<TextBlock Text="免费游玩" FontSize="22" FontWeight="Bold" Foreground="{DynamicResource ColorBrush4}" />'
        else:
            price_xaml = f'<TextBlock Text="¥{game["final_price"]:.2f}" FontSize="18" Foreground="{{DynamicResource ColorBrush5}}" />'

        store_url = f"https://store.steampowered.com/app/{game['id']}"

        row = index // COLUMNS
        col = index % COLUMNS

        data = {
            "id": game["id"],
            "img": game["header_image"],
            "name": game["name"],
            "price": price_xaml, 
            "url": store_url,
            "row": row,
            "column": col
        }
        item_xaml = replaces(game_template, data, no_escape_keys=['price'])
        game_items.append(item_xaml)

    games_block = "\n    ".join(game_items)

    games_grid = f"""    <Grid>
        <Grid.RowDefinitions>
        {grid_rows}</Grid.RowDefinitions>
        <Grid.ColumnDefinitions>
        {grid_columns}</Grid.ColumnDefinitions>
        {games_block}
    </Grid>"""

    final_xaml = header + "\n" + label_xaml + "\n" + games_grid + "\n" + footer

    output_path = "SteamPage.xaml"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(final_xaml)

    print(f"[成功] 已生成 {output_path}，共 {len(games)} 个游戏，{rows} 行 {COLUMNS} 列。")

if __name__ == "__main__":
    main()
