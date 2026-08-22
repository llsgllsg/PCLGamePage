#使用CC BY-NC-SA 4.0 协议

import os
from api import get_games, get_epic_free_games
#修改了API名字
LABEL = "每日游戏推荐"
EPIC_LABEL = "Epic本周免费"
LIMIT = 20
EPIC_LIMIT = 10
COLUMNS = 2


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
        no_escape_keys = []
    for key, value in data.items():
        if key in no_escape_keys:
            template = template.replace("{" + key + "}", str(value))
        else:
            template = template.replace("{" + key + "}", escape_xaml(value))
    return template


def build_price_xaml(game):
    fp = game.get("final_price")
    dp = game.get("discount_percent") or 0
    if fp is not None and dp > 0:
        # 每项单独一行并水平居中，避免窄卡片上横向重叠，同时价格更醒目
        parts = [
            f'<TextBlock Text="¥{fp:.2f}" FontSize="24" FontWeight="Bold" HorizontalAlignment="Center" '
            f'Foreground="{{DynamicResource ColorBrush1}}" />'
        ]
        if game.get("original_price") is not None:
            parts.append(
                f'<TextBlock Text="原价 ¥{game["original_price"]:.2f}" FontSize="16" FontWeight="Bold" '
                f'HorizontalAlignment="Center" TextDecorations="Strikethrough" '
                f'Foreground="{{DynamicResource ColorBrush1}}" />'
            )
        parts.append(
            f'<TextBlock Text="-{dp}%" FontSize="15" FontWeight="Bold" HorizontalAlignment="Center" '
            f'Foreground="{{DynamicResource ColorBrush3}}" />'
        )
        return "\n".join(parts)
    if fp == 0:
        return '<TextBlock Text="免费游玩" FontSize="22" FontWeight="Bold" HorizontalAlignment="Center" Foreground="{DynamicResource ColorBrush3}" />'
    if fp is not None:
        return f'<TextBlock Text="¥{fp:.2f}" FontSize="20" FontWeight="Bold" HorizontalAlignment="Center" Foreground="{{DynamicResource ColorBrush1}}" />'
    return '<TextBlock Text="暂无价格" FontSize="16" HorizontalAlignment="Center" Foreground="{DynamicResource ColorBrush6}" />'


def build_rating_xaml(game):
    rating_text = game.get("rating_text")
    review_pct = game.get("review_pct")
    if rating_text and review_pct is not None:
        return (
            f'<TextBlock Margin="0,4,0,0" HorizontalAlignment="Center" TextAlignment="Center" '
            f'VerticalAlignment="Center" FontSize="13" FontWeight="Bold" '
            f'Foreground="{{DynamicResource ColorBrush3}}" Text="{escape_xaml(rating_text)} {review_pct}%" />'
        )
    return ""


def main():
    games = get_games(limit=LIMIT)
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
    with open(os.path.join(template_dir, "epic_game.xaml"), "r", encoding="utf-8") as f:
        epic_game_template = f.read()

    label_data = {"label": LABEL}
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
        price_xaml = build_price_xaml(game)
        rating_xaml = build_rating_xaml(game)
        store_url = f"https://store.steampowered.com/app/{game['id']}"

        row = index // COLUMNS
        col = index % COLUMNS

        data = {
            "id": game["id"],
            "img": game.get("img"),
            "name": game["name"],
            "price": price_xaml,
            "rating": rating_xaml,
            "url": store_url,
            "row": row,
            "column": col
        }
        item_xaml = replaces(game_template, data, no_escape_keys=['price', 'rating'])
        game_items.append(item_xaml)

    games_block = "\n    ".join(game_items)

    games_grid = f"""    <Grid>
        <Grid.RowDefinitions>
        {grid_rows}</Grid.RowDefinitions>
        <Grid.ColumnDefinitions>
        {grid_columns}</Grid.ColumnDefinitions>
        {games_block}
    </Grid>"""

    # ===== Epic 免费游戏板块 =====
    epic_games = get_epic_free_games()[:EPIC_LIMIT]
    epic_section = ""
    if epic_games:
        epic_label_xaml = f'<TextBlock Text="{EPIC_LABEL}" FontSize="20" FontWeight="Bold" Foreground="{{DynamicResource ColorBrush2}}" Margin="0,18,0,12" VerticalAlignment="Center" />'
        epic_rows = (len(epic_games) + COLUMNS - 1) // COLUMNS
        epic_grid_rows = ""
        for i in range(epic_rows):
            epic_grid_rows += '<RowDefinition Height="Auto" />\n        '
        epic_items = []
        for index, game in enumerate(epic_games):
            row = index // COLUMNS
            col = index % COLUMNS
            data = {
                "id": game["id"],
                "img": game.get("img", ""),
                "name": game["name"],
                "price": escape_xaml(game.get("original_price_desc", "")),
                "free_end": escape_xaml(game.get("free_end", "")),
                "url": game.get("link", ""),
                "row": row,
                "column": col,
            }
            item_xaml = replaces(epic_game_template, data, no_escape_keys=["price", "free_end"])
            epic_items.append(item_xaml)
        epic_block = "\n    ".join(epic_items)
        epic_grid = f"""    <Grid>
        <Grid.RowDefinitions>
        {epic_grid_rows}</Grid.RowDefinitions>
        <Grid.ColumnDefinitions>
        {grid_columns}</Grid.ColumnDefinitions>
        {epic_block}
    </Grid>"""
        epic_section = "\n" + epic_label_xaml + "\n" + epic_grid

    final_xaml = header + "\n" + label_xaml + "\n" + games_grid + epic_section + "\n" + footer

    output_path = "SteamPage.xaml"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(final_xaml)

    epic_count = len(epic_games)
    print(f"[成功] 已生成 {output_path}，Steam {len(games)} 个（{rows} 行 {COLUMNS} 列），Epic 免费 {epic_count} 个。")


if __name__ == "__main__":
    main()
