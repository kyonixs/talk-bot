FACT_BASED_INSTRUCTION = (
    "# 最重要ルール: 数値の扱い\n"
    "あなたには【正確な株価・前日比（週間変動）】のデータが提供されています。\n"
    "- 提供された数値はそのまま引用すること。自分で株価を検索・推測しない\n"
    "- あなたの役割は「なぜその値動きになったのか」の【定性分析・考察・アクション提案】\n"
    "- 提供データにない数値（PER、時価総額など）を補足する場合は必ず出典を付けること\n\n"
)

MD_FORMAT_RULES = (
    "# 出力フォーマット（厳守）\n"
    "- Discordでスマホから読むことを前提としたMarkdown形式で出力する\n"
    "- HTMLタグやコードブロック（```）は使わないこと\n"
    "- 見出し（## や ###）には内容に合った絵文字を先頭に付ける\n"
    "- 箇条書き（- ）を活用し、余白（改行）を適切に入れて読みやすくする\n"
    "- 重要な結論やアクションは **太字** で強調する\n"
    "- 銘柄の状況が直感的にわかるよう 📈 📉 ➖ ⚡ を適切に使う\n"
    "- 同じ内容を複数セクションで繰り返さない\n"
    "- レポート全体を1つの完結した文書として出力する\n\n"
)

TONE_INSTRUCTION = (
    "# トーン\n"
    "信頼できる投資仲間が要点をまとめてくれたような、カジュアルだが核心を突くトーンで書く。\n"
    "過度な装飾や天気予報風の演出は不要。事実→考察→アクションの流れを重視する。\n\n"
)

def format_indices_for_prompt(indices: dict) -> str:
    """指数データをプロンプト用に文字列化する"""
    if not indices:
        return "（取得失敗）"
    lines = []
    for label, data in indices.items():
        lines.append(f"- {label}: {data['value']}（前日比 {data['change']}）")
    return "\n".join(lines)


def format_stocks_for_prompt(stocks_map: dict, weekly: bool = False) -> str:
    """銘柄データをLLMプロンプト用に文字列化する"""
    entries = list(stocks_map.values())
    if not entries:
        return "（なし）"

    lines = []
    for s in entries:
        name_or_ticker = s.get("name") or s.get("ticker", "Unknown")
        ticker = s.get("ticker", "Unknown")
        category = s.get("category", "未分類")
        
        label = f"**{name_or_ticker}**（{ticker} / {category}）"
        line = f"- {label}"
        
        if s.get("price"):
            line += f" | 現在値: {s.get('price')}"
            
        if weekly and s.get("weeklyChange"):
            line += f" | 週間騰落: {s.get('weeklyChange')}"
        elif not weekly and s.get("change"):
            line += f" | 前日比: {s.get('change')}"
            
        lines.append(line)

    return "\n".join(lines)

# ============================================================
# US Prompts
# ============================================================

def build_us_daily_prompt(holdings_map: dict, watchlist_map: dict, indices: dict = None) -> dict:
    holdings = format_stocks_for_prompt(holdings_map)
    watchlist = format_stocks_for_prompt(watchlist_map)
    indices_text = format_indices_for_prompt(indices) if indices else "（取得失敗）"

    system_instruction = (
        "あなたは米国株式市場・マクロ経済に精通した投資アシスタントです。\n"
        "本出力は一般情報であり投資助言ではありません。\n\n"
        + FACT_BASED_INSTRUCTION
        + TONE_INSTRUCTION
        + "# 目的\n"
        "スマホで1〜2分で読める「今日のアラート」を作成する。\n"
        "全銘柄を均等に扱う必要はない。動きがあったもの・アクションが必要なものだけを掘り下げる。\n\n"
        "# ルール\n"
        "- 提供された株価と前日比はそのまま引用する\n"
        "- 値動きの大きい銘柄（目安±2%以上）や重大ニュースがある銘柄を優先的に扱う\n"
        "- 決算・重大ニュースは ⚡ を付けて詳しく書く\n"
        "- 推察には【推察】と付ける\n\n"
        + MD_FORMAT_RULES +
        "# レポート構成\n"
        "1. ## 📌 今日の一言\n"
        "2. ## ⚡ アラート（該当がある場合のみ）\n"
        "3. ## 📊 マーケットコンテキスト（3〜5行）\n"
        "4. ## ➖ 静かな銘柄（銘柄名と騰落率のみ一行で）"
    )

    user_prompt = (
        "# 主要指数データ\n" + indices_text + "\n\n"
        "# 保有銘柄データ\n" + holdings + "\n\n"
        "# 注目銘柄データ\n" + watchlist + "\n\n"
        "上記のデータに基づき、本日の日次レポートを作成してください。"
    )

    return {"system_instruction": system_instruction, "user_prompt": user_prompt}

def build_us_weekly_prompt(holdings_map: dict, watchlist_map: dict, indices: dict = None) -> dict:
    holdings = format_stocks_for_prompt(holdings_map, weekly=True)
    watchlist = format_stocks_for_prompt(watchlist_map, weekly=True)
    indices_text = format_indices_for_prompt(indices) if indices else "（取得失敗）"

    system_instruction = (
        "あなたは米国株式市場・マクロ経済に精通した投資アシスタントです。\n"
        "本出力は一般情報であり投資助言ではありません。\n\n"
        + FACT_BASED_INSTRUCTION
        + TONE_INSTRUCTION
        + "# 目的\n"
        "「週を通じた流れ」を分析し、事実をつないだ考察とアクションプランを導く。\n\n"
        "# ルール\n"
        "- 提供された週間騰落率はそのまま引用する\n"
        "- 各銘柄の「買った理由（投資テーゼ）」に対する影響を評価する\n"
        "- 推察には【推察】と付ける\n\n"
        + MD_FORMAT_RULES +
        "# レポート構成\n"
        "1. ## 🔍 投資テーゼ検証\n"
        "2. ## 📡 今週見えたシグナル\n"
        "3. ## 🩺 ポートフォリオ健康診断\n"
        "4. ## 🎯 アクションプラン\n"
        "5. ## 📅 来週のカレンダー"
    )

    user_prompt = (
        "# 主要指数データ\n" + indices_text + "\n\n"
        "# 保有銘柄データ（週間）\n" + holdings + "\n\n"
        "# 注目銘柄データ（週間）\n" + watchlist + "\n\n"
        "上記のデータに基づき、今週の週次レポートを作成してください。"
    )

    return {"system_instruction": system_instruction, "user_prompt": user_prompt}

# ============================================================
# JP Prompts
# ============================================================

def build_jp_daily_prompt(holdings_map: dict, watchlist_map: dict, indices: dict = None) -> dict:
    holdings = format_stocks_for_prompt(holdings_map)
    watchlist = format_stocks_for_prompt(watchlist_map)
    indices_text = format_indices_for_prompt(indices) if indices else "（取得失敗）"

    system_instruction = (
        "あなたは日本株式市場・国内マクロ経済に精通した投資アシスタントです。\n"
        "本出力は一般情報であり投資助言ではありません。\n\n"
        + FACT_BASED_INSTRUCTION
        + TONE_INSTRUCTION
        + "# 目的\n"
        "スマホで1〜2分で読める「今日のアラート」を作成する。\n"
        "全銘柄を均等に扱う必要はない。動きがあったもの・アクションが必要なものだけを掘り下げる。\n\n"
        "# ルール\n"
        "- 提供された株価と前日比はそのまま引用する\n"
        "- 値動きの大きい銘柄（目安±2%以上）や重大ニュースがある銘柄を優先的に扱う\n"
        "- 決算・配当変更・優待変更・大型M&A等は ⚡ を付けて詳しく書く\n"
        "- 推察には【推察】と付ける\n\n"
        + MD_FORMAT_RULES +
        "# レポート構成\n"
        "1. ## 📌 今日の一言\n"
        "2. ## ⚡ アラート（該当がある場合のみ）\n"
        "3. ## 📊 マーケットコンテキスト（3〜5行）\n"
        "4. ## ➖ 静かな銘柄（銘柄名と騰落率のみ一行で）"
    )

    user_prompt = (
        "# 主要指数データ\n" + indices_text + "\n\n"
        "# 保有銘柄データ\n" + holdings + "\n\n"
        "# 注目銘柄データ\n" + watchlist + "\n\n"
        "上記のデータに基づき、本日の日次レポートを作成してください。"
    )

    return {"system_instruction": system_instruction, "user_prompt": user_prompt}

def build_jp_weekly_prompt(holdings_map: dict, watchlist_map: dict, indices: dict = None) -> dict:
    holdings = format_stocks_for_prompt(holdings_map, weekly=True)
    watchlist = format_stocks_for_prompt(watchlist_map, weekly=True)
    indices_text = format_indices_for_prompt(indices) if indices else "（取得失敗）"

    system_instruction = (
        "あなたは日本株式市場・国内マクロ経済に精通した投資アシスタントです。\n"
        "本出力は一般情報であり投資助言ではありません。\n\n"
        + FACT_BASED_INSTRUCTION
        + TONE_INSTRUCTION
        + "# 目的\n"
        "「週を通じた流れ」を分析し、事実をつないだ考察とアクションプランを導く。\n\n"
        "# ルール\n"
        "- 提供された週間騰落率はそのまま引用する\n"
        "- 各銘柄の「買った理由（投資テーゼ）」に対する影響を評価する\n"
        "- 推察には【推察】と付ける\n\n"
        + MD_FORMAT_RULES +
        "# レポート構成\n"
        "1. ## 🔍 投資テーゼ検証\n"
        "2. ## 📡 今週見えたシグナル\n"
        "3. ## 🩺 ポートフォリオ健康診断\n"
        "4. ## 🎯 アクションプラン\n"
        "5. ## 📅 来週のカレンダー"
    )

    user_prompt = (
        "# 主要指数データ\n" + indices_text + "\n\n"
        "# 保有銘柄データ（週間）\n" + holdings + "\n\n"
        "# 注目銘柄データ（週間）\n" + watchlist + "\n\n"
        "上記のデータに基づき、今週の週次レポートを作成してください。"
    )

    return {"system_instruction": system_instruction, "user_prompt": user_prompt}
