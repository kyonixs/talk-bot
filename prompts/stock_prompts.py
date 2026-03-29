FACT_BASED_INSTRUCTION = (
    "# 最重要ルール: 数値の扱い\n"
    "あなたには【正確な株価・前日比（週間変動）・テクニカル指標・シグナル】のデータが提供されています。\n"
    "- 提供された数値はそのまま引用すること。自分で株価を検索・推測しない\n"
    "- あなたの役割は「なぜその値動きになったのか」の【定性分析・考察・アクション提案】\n"
    "- テクニカル指標データは分析の裏付けとして活用する（数値の羅列はしない）\n"
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

TECHNICAL_INSTRUCTION = (
    "# テクニカル指標の扱い\n"
    "提供されたテクニカルデータ（RSI, MACD, BB, 移動平均線, 出来高変化率, トレンドコンテキスト）は以下のように活用する:\n"
    "- RSI: 70以上=買われすぎ、30以下=売られすぎの判断材料\n"
    "- MACD: ゴールデンクロス/デッドクロスはトレンド転換のシグナル\n"
    "- ボリンジャーバンド: %Bが1超=上限突破（過熱）、0未満=下限突破（売られすぎ）\n"
    "- 移動平均線: 5日/25日/75日/200日のクロスや乖離率でトレンド判定\n"
    "- 出来高変化率: 2倍以上は異常出来高として注目\n"
    "- スコア: Bull/Bear/Neutralは総合判定の参考値として自然に組み込む\n"
    "- **テクニカル指標を一覧表として羅列しない。分析の文脈で自然に言及すること**\n\n"
    "# 中期・長期トレンドの扱い\n"
    "各銘柄にはトレンドコンテキスト（短期〜超長期の方向性、1M/3M/6Mリターン、52週高値安値からの乖離）が付与されている。\n"
    "- 日次レポート: 短期の値動きを主軸にしつつ、中長期トレンドとの矛盾や合流を**一言で**触れる（例:「短期は反発だが中長期の下落基調は変わらず」）\n"
    "- 週次レポート: 中長期トレンドをより積極的に分析に組み込む。特に52週高値/安値付近の銘柄、トレンド転換が見える銘柄に注目\n"
    "- **中長期分析で別セクションを作らない。既存セクション内で簡潔に織り込むこと**\n"
    "- 全銘柄のトレンドを逐一述べる必要はない。注目すべき銘柄のみ言及する\n\n"
)


# ============================================================
# フォーマッター
# ============================================================

def format_indices_for_prompt(indices: dict) -> str:
    """指数データをプロンプト用に文字列化する"""
    if not indices:
        return "（取得失敗）"
    lines = []
    for label, data in indices.items():
        lines.append(f"- {label}: {data['value']}（前日比 {data['change']}）")
    return "\n".join(lines)


def format_sector_etfs_for_prompt(sector_etfs: dict) -> str:
    """セクターETFデータをプロンプト用に文字列化する"""
    if not sector_etfs:
        return ""
    lines = ["# セクター別パフォーマンス（米国ETF）"]
    for name, change in sector_etfs.items():
        lines.append(f"- {name}: {change}")
    return "\n".join(lines)


def format_stocks_for_prompt(stocks_map: dict, weekly: bool = False) -> str:
    """銘柄データをLLMプロンプト用に文字列化する（テクニカル指標付き）"""
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

        # テクニカル指標（あれば追加）
        tech = s.get("technicals")
        if tech:
            tech_parts = []
            if tech.get("sparkline"):
                tech_parts.append(f"チャート: {tech['sparkline']}")
            if tech.get("rsi") is not None:
                tech_parts.append(f"RSI: {tech['rsi']}")
            for period in [5, 25, 75]:
                key = f"sma{period}"
                if tech.get(key) is not None:
                    tech_parts.append(f"SMA{period}: {tech[key]}")
            bb = tech.get("bb")
            if bb:
                tech_parts.append(f"BB%B: {bb['pct_b']}")
            macd = tech.get("macd")
            if macd:
                hist_sign = "+" if macd["histogram"] >= 0 else ""
                tech_parts.append(f"MACDヒストグラム: {hist_sign}{macd['histogram']}")
                if macd["cross"] != "none":
                    tech_parts.append(f"MACDクロス: {macd['cross']}")
            if tech.get("volume_ratio") is not None:
                tech_parts.append(f"出来高倍率: {tech['volume_ratio']}x")
            if tech_parts:
                line += f"\n  テクニカル: {' | '.join(tech_parts)}"

        # トレンドコンテキスト（中期・長期、1行に凝縮）
        trend = tech.get("trend") if tech else None
        if trend:
            trend_parts = [trend["direction"], trend["alignment"]]
            if trend.get("return_1m") is not None:
                trend_parts.append(f"1M:{trend['return_1m']:+.1f}%")
            if trend.get("return_3m") is not None:
                trend_parts.append(f"3M:{trend['return_3m']:+.1f}%")
            if trend.get("return_6m") is not None:
                trend_parts.append(f"6M:{trend['return_6m']:+.1f}%")
            trend_parts.append(f"52週高値比:{trend['from_52w_high']:+.1f}%")
            line += f"\n  トレンド: {' | '.join(trend_parts)}"

        # スコア（あれば追加）
        score = s.get("score")
        if score:
            line += f"\n  判定: {score['label']}（スコア: {score['score']:+d}）"

        # シグナル（あれば追加）
        sigs = s.get("signals")
        if sigs:
            sig_texts = [sig["message"] for sig in sigs]
            line += f"\n  シグナル: {' / '.join(sig_texts)}"

        # アクション優先度（あれば追加）
        priority = s.get("action_priority")
        if priority:
            line += f" → 【{priority}】"

        lines.append(line)

    return "\n".join(lines)


def format_portfolio_for_prompt(portfolio: dict) -> str:
    """ポートフォリオ分析結果をプロンプト用に文字列化する"""
    if not portfolio:
        return ""

    lines = ["# ポートフォリオ分析"]

    # セクター配分
    allocation = portfolio.get("sector_allocation", {})
    if allocation:
        lines.append("## セクター配分")
        for cat, pct in sorted(allocation.items(), key=lambda x: -x[1]):
            lines.append(f"- {cat}: {pct}%")

    # リスク分散評価
    risk = portfolio.get("risk_summary")
    if risk:
        lines.append(f"分散評価: {risk}")

    # 損益
    total_pnl = portfolio.get("total_pnl")
    if total_pnl:
        sign = "+" if total_pnl["amount"] >= 0 else ""
        lines.append(f"\n## 含み損益サマリー")
        lines.append(f"- 合計: {sign}{total_pnl['amount']:,.0f}（{sign}{total_pnl['pct']:.2f}%）")

    pnl_items = portfolio.get("holdings_pnl", [])
    if pnl_items:
        # ワースト3とベスト3
        worst = pnl_items[:3]
        best = pnl_items[-3:][::-1]
        if worst:
            lines.append("- ワースト: " + ", ".join(
                f"{item['name']}({item['pnl_pct']:+.1f}%)" for item in worst
            ))
        if best and best != worst:
            lines.append("- ベスト: " + ", ".join(
                f"{item['name']}({item['pnl_pct']:+.1f}%)" for item in best
            ))

    return "\n".join(lines)


# ============================================================
# US Prompts
# ============================================================

def build_us_daily_prompt(holdings_map: dict, watchlist_map: dict,
                          indices: dict = None, sector_etfs: dict = None,
                          portfolio: dict = None) -> dict:
    holdings = format_stocks_for_prompt(holdings_map)
    watchlist = format_stocks_for_prompt(watchlist_map)
    indices_text = format_indices_for_prompt(indices) if indices else "（取得失敗）"

    system_instruction = (
        "あなたは米国株式市場・マクロ経済に精通した投資アシスタントです。\n"
        "本出力は一般情報であり投資助言ではありません。\n\n"
        + FACT_BASED_INSTRUCTION
        + TECHNICAL_INSTRUCTION
        + TONE_INSTRUCTION
        + "# 目的\n"
        "スマホで1〜2分で読める「今日のアラート」を作成する。\n"
        "全銘柄を均等に扱う必要はない。動きがあったもの・アクションが必要なものだけを掘り下げる。\n\n"
        "# ルール\n"
        "- 提供された株価と前日比はそのまま引用する\n"
        "- 【要注意】マーク付き銘柄やシグナルが出ている銘柄を最優先で扱う\n"
        "- 決算・重大ニュースは ⚡ を付けて詳しく書く\n"
        "- 推察には【推察】と付ける\n\n"
        + MD_FORMAT_RULES +
        "# レポート構成\n"
        "1. ## 📌 今日の一言\n"
        "2. ## ⚡ アラート＆シグナル（テクニカルシグナルや値動き警告がある銘柄。該当なしなら省略）\n"
        "3. ## 📊 マーケットコンテキスト（指数・VIX・セクター動向を含め3〜5行）\n"
        "4. ## 💼 ポートフォリオスナップショット（含み損益・セクター偏りの簡潔な所見。データがあれば）\n"
        "5. ## ➖ 静かな銘柄（銘柄名と騰落率のみ一行で）"
    )

    # ユーザープロンプト組み立て
    parts = [
        "# 主要指数データ\n" + indices_text,
    ]
    if sector_etfs:
        parts.append(format_sector_etfs_for_prompt(sector_etfs))
    parts.append("# 保有銘柄データ\n" + holdings)
    parts.append("# 注目銘柄データ\n" + watchlist)
    if portfolio:
        parts.append(format_portfolio_for_prompt(portfolio))
    parts.append("上記のデータに基づき、本日の日次レポートを作成してください。")

    user_prompt = "\n\n".join(parts)
    return {"system_instruction": system_instruction, "user_prompt": user_prompt}


def build_us_weekly_prompt(holdings_map: dict, watchlist_map: dict,
                           indices: dict = None, sector_etfs: dict = None,
                           portfolio: dict = None) -> dict:
    holdings = format_stocks_for_prompt(holdings_map, weekly=True)
    watchlist = format_stocks_for_prompt(watchlist_map, weekly=True)
    indices_text = format_indices_for_prompt(indices) if indices else "（取得失敗）"

    system_instruction = (
        "あなたは米国株式市場・マクロ経済に精通した投資アシスタントです。\n"
        "本出力は一般情報であり投資助言ではありません。\n\n"
        + FACT_BASED_INSTRUCTION
        + TECHNICAL_INSTRUCTION
        + TONE_INSTRUCTION
        + "# 目的\n"
        "「週を通じた流れ」を分析し、テクニカル指標も踏まえた考察とアクションプランを導く。\n\n"
        "# ルール\n"
        "- 提供された週間騰落率はそのまま引用する\n"
        "- 各銘柄の「買った理由（投資テーゼ）」に対する影響を評価する\n"
        "- テクニカルシグナル（RSI極端値、MACDクロス、BB突破等）は「今週見えたシグナル」に統合する\n"
        "- 推察には【推察】と付ける\n\n"
        + MD_FORMAT_RULES +
        "# レポート構成\n"
        "1. ## 🔍 投資テーゼ検証\n"
        "2. ## 📡 今週見えたシグナル（テクニカル＋ファンダメンタルズ統合）\n"
        "3. ## 🩺 ポートフォリオ健康診断（セクター配分・損益・分散評価を含む）\n"
        "4. ## 🎯 アクションプラン（優先度付き）\n"
        "5. ## 📅 来週のカレンダー"
    )

    parts = [
        "# 主要指数データ\n" + indices_text,
    ]
    if sector_etfs:
        parts.append(format_sector_etfs_for_prompt(sector_etfs))
    parts.append("# 保有銘柄データ（週間）\n" + holdings)
    parts.append("# 注目銘柄データ（週間）\n" + watchlist)
    if portfolio:
        parts.append(format_portfolio_for_prompt(portfolio))
    parts.append("上記のデータに基づき、今週の週次レポートを作成してください。")

    user_prompt = "\n\n".join(parts)
    return {"system_instruction": system_instruction, "user_prompt": user_prompt}


# ============================================================
# JP Prompts
# ============================================================

def build_jp_daily_prompt(holdings_map: dict, watchlist_map: dict,
                          indices: dict = None, portfolio: dict = None) -> dict:
    holdings = format_stocks_for_prompt(holdings_map)
    watchlist = format_stocks_for_prompt(watchlist_map)
    indices_text = format_indices_for_prompt(indices) if indices else "（取得失敗）"

    system_instruction = (
        "あなたは日本株式市場・国内マクロ経済に精通した投資アシスタントです。\n"
        "本出力は一般情報であり投資助言ではありません。\n\n"
        + FACT_BASED_INSTRUCTION
        + TECHNICAL_INSTRUCTION
        + TONE_INSTRUCTION
        + "# 目的\n"
        "スマホで1〜2分で読める「今日のアラート」を作成する。\n"
        "全銘柄を均等に扱う必要はない。動きがあったもの・アクションが必要なものだけを掘り下げる。\n\n"
        "# ルール\n"
        "- 提供された株価と前日比はそのまま引用する\n"
        "- 【要注意】マーク付き銘柄やシグナルが出ている銘柄を最優先で扱う\n"
        "- 決算・配当変更・優待変更・大型M&A等は ⚡ を付けて詳しく書く\n"
        "- 推察には【推察】と付ける\n\n"
        + MD_FORMAT_RULES +
        "# レポート構成\n"
        "1. ## 📌 今日の一言\n"
        "2. ## ⚡ アラート＆シグナル（テクニカルシグナルや値動き警告がある銘柄。該当なしなら省略）\n"
        "3. ## 📊 マーケットコンテキスト（指数・為替動向を含め3〜5行）\n"
        "4. ## 💼 ポートフォリオスナップショット（含み損益・セクター偏りの簡潔な所見。データがあれば）\n"
        "5. ## ➖ 静かな銘柄（銘柄名と騰落率のみ一行で）"
    )

    parts = [
        "# 主要指数データ\n" + indices_text,
        "# 保有銘柄データ\n" + holdings,
        "# 注目銘柄データ\n" + watchlist,
    ]
    if portfolio:
        parts.append(format_portfolio_for_prompt(portfolio))
    parts.append("上記のデータに基づき、本日の日次レポートを作成してください。")

    user_prompt = "\n\n".join(parts)
    return {"system_instruction": system_instruction, "user_prompt": user_prompt}


def build_jp_weekly_prompt(holdings_map: dict, watchlist_map: dict,
                           indices: dict = None, portfolio: dict = None) -> dict:
    holdings = format_stocks_for_prompt(holdings_map, weekly=True)
    watchlist = format_stocks_for_prompt(watchlist_map, weekly=True)
    indices_text = format_indices_for_prompt(indices) if indices else "（取得失敗）"

    system_instruction = (
        "あなたは日本株式市場・国内マクロ経済に精通した投資アシスタントです。\n"
        "本出力は一般情報であり投資助言ではありません。\n\n"
        + FACT_BASED_INSTRUCTION
        + TECHNICAL_INSTRUCTION
        + TONE_INSTRUCTION
        + "# 目的\n"
        "「週を通じた流れ」を分析し、テクニカル指標も踏まえた考察とアクションプランを導く。\n\n"
        "# ルール\n"
        "- 提供された週間騰落率はそのまま引用する\n"
        "- 各銘柄の「買った理由（投資テーゼ）」に対する影響を評価する\n"
        "- テクニカルシグナル（RSI極端値、MACDクロス、BB突破等）は「今週見えたシグナル」に統合する\n"
        "- 推察には【推察】と付ける\n\n"
        + MD_FORMAT_RULES +
        "# レポート構成\n"
        "1. ## 🔍 投資テーゼ検証\n"
        "2. ## 📡 今週見えたシグナル（テクニカル＋ファンダメンタルズ統合）\n"
        "3. ## 🩺 ポートフォリオ健康診断（セクター配分・損益・分散評価を含む）\n"
        "4. ## 🎯 アクションプラン（優先度付き）\n"
        "5. ## 📅 来週のカレンダー"
    )

    parts = [
        "# 主要指数データ\n" + indices_text,
        "# 保有銘柄データ（週間）\n" + holdings,
        "# 注目銘柄データ（週間）\n" + watchlist,
    ]
    if portfolio:
        parts.append(format_portfolio_for_prompt(portfolio))
    parts.append("上記のデータに基づき、今週の週次レポートを作成してください。")

    user_prompt = "\n\n".join(parts)
    return {"system_instruction": system_instruction, "user_prompt": user_prompt}
