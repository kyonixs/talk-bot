"""テクニカル指標の計算、シグナル検出、ポートフォリオ分析を行うサービス"""
import logging
import math
from collections import defaultdict

logger = logging.getLogger(__name__)

# ============================================================
# Sparkline (テキストベースのミニチャート)
# ============================================================

_SPARK_CHARS = "▁▂▃▄▅▆▇█"


def generate_sparkline(values: list[float], length: int = 10) -> str:
    """直近N個の値からテキストスパークラインを生成する"""
    if not values:
        return ""
    data = values[-length:]
    if len(data) < 2:
        return _SPARK_CHARS[4]

    lo, hi = min(data), max(data)
    rng = hi - lo
    if rng == 0:
        return _SPARK_CHARS[4] * len(data)

    return "".join(
        _SPARK_CHARS[min(int((v - lo) / rng * (len(_SPARK_CHARS) - 1)), len(_SPARK_CHARS) - 1)]
        for v in data
    )


# ============================================================
# テクニカル指標
# ============================================================

def calculate_sma(closes: list[float], period: int) -> float | None:
    """単純移動平均線"""
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def calculate_ema(closes: list[float], period: int) -> float | None:
    """指数移動平均線"""
    if len(closes) < period:
        return None
    multiplier = 2 / (period + 1)
    ema = sum(closes[:period]) / period  # 初期値はSMA
    for price in closes[period:]:
        ema = (price - ema) * multiplier + ema
    return ema


def _ema_series(data: list[float], period: int) -> list[float]:
    """EMAの全時系列を返す（MACD計算用）"""
    if len(data) < period:
        return []
    multiplier = 2 / (period + 1)
    ema_val = sum(data[:period]) / period
    result = [ema_val]
    for v in data[period:]:
        ema_val = (v - ema_val) * multiplier + ema_val
        result.append(ema_val)
    return result


def calculate_rsi(closes: list[float], period: int = 14) -> float | None:
    """RSI (Relative Strength Index)"""
    if len(closes) < period + 1:
        return None

    gains = []
    losses = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))

    # Wilder's smoothing
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_bollinger_bands(closes: list[float], period: int = 20, num_std: float = 2.0) -> dict | None:
    """ボリンジャーバンド"""
    if len(closes) < period:
        return None

    window = closes[-period:]
    sma = sum(window) / period
    variance = sum((x - sma) ** 2 for x in window) / period
    std = math.sqrt(variance)

    current = closes[-1]
    upper = sma + num_std * std
    lower = sma - num_std * std

    # %B = (価格 - 下限) / (上限 - 下限)
    band_width = upper - lower
    pct_b = (current - lower) / band_width if band_width > 0 else 0.5

    return {
        "upper": round(upper, 2),
        "middle": round(sma, 2),
        "lower": round(lower, 2),
        "pct_b": round(pct_b, 2),
        "bandwidth": round(band_width / sma * 100, 2) if sma > 0 else 0,
    }


def calculate_macd(closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> dict | None:
    """MACD (Moving Average Convergence Divergence)"""
    if len(closes) < slow + signal:
        return None

    ema_fast = _ema_series(closes, fast)
    ema_slow = _ema_series(closes, slow)

    # MACDラインはfast EMA - slow EMA（共通の開始点から）
    offset = slow - fast
    macd_line = [f - s for f, s in zip(ema_fast[offset:], ema_slow)]

    if len(macd_line) < signal:
        return None

    signal_line = _ema_series(macd_line, signal)
    if not signal_line:
        return None

    macd_val = macd_line[-1]
    signal_val = signal_line[-1]
    histogram = macd_val - signal_val

    # クロス検出（直近2日）
    cross = "none"
    if len(macd_line) >= 2 and len(signal_line) >= 2:
        prev_macd = macd_line[-2]
        signal_offset = len(macd_line) - len(signal_line)
        if signal_offset >= 0 and len(signal_line) >= 2:
            prev_signal = signal_line[-2]
            if prev_macd <= prev_signal and macd_val > signal_val:
                cross = "golden"
            elif prev_macd >= prev_signal and macd_val < signal_val:
                cross = "dead"

    return {
        "macd": round(macd_val, 4),
        "signal": round(signal_val, 4),
        "histogram": round(histogram, 4),
        "cross": cross,
    }


def calculate_volume_ratio(volumes: list[float], period: int = 20) -> float | None:
    """出来高変化率: 直近出来高 / 期間平均出来高"""
    valid = [v for v in volumes if v is not None and v > 0]
    if len(valid) < period + 1:
        return None
    avg = sum(valid[-period - 1:-1]) / period
    if avg == 0:
        return None
    return valid[-1] / avg


# ============================================================
# 総合テクニカル分析（1銘柄分）
# ============================================================

def analyze_technicals(closes: list[float], volumes: list[float] = None) -> dict:
    """1銘柄の全テクニカル指標を計算して返す"""
    result = {}

    # 移動平均線（短期〜長期）
    for period in [5, 25, 75, 200]:
        sma = calculate_sma(closes, period)
        if sma is not None:
            result[f"sma{period}"] = round(sma, 2)

    # RSI
    rsi = calculate_rsi(closes)
    if rsi is not None:
        result["rsi"] = round(rsi, 1)

    # ボリンジャーバンド
    bb = calculate_bollinger_bands(closes)
    if bb:
        result["bb"] = bb

    # MACD
    macd = calculate_macd(closes)
    if macd:
        result["macd"] = macd

    # 出来高変化率
    if volumes:
        vol_ratio = calculate_volume_ratio(volumes)
        if vol_ratio is not None:
            result["volume_ratio"] = round(vol_ratio, 2)

    # スパークライン
    result["sparkline"] = generate_sparkline(closes)

    # トレンドコンテキスト（中期・長期）
    trend = analyze_trend_context(closes)
    if trend:
        result["trend"] = trend

    return result


# ============================================================
# 中期・長期トレンド分析
# ============================================================

def _period_return(closes: list[float], days: int) -> float | None:
    """直近N営業日のリターン（%）を計算する"""
    if len(closes) < days + 1:
        return None
    return ((closes[-1] - closes[-days - 1]) / closes[-days - 1]) * 100


def _classify_direction(current: float, sma: float | None) -> str:
    """価格とSMAの位置関係からトレンド方向を判定する"""
    if sma is None:
        return "?"
    pct = ((current - sma) / sma) * 100
    if pct > 3:
        return "↑"
    elif pct < -3:
        return "↓"
    return "→"


def analyze_trend_context(closes: list[float]) -> dict | None:
    """短期・中期・長期のトレンドコンテキストを凝縮して返す"""
    if len(closes) < 26:
        return None

    current = closes[-1]

    # 各タイムフレームのトレンド方向
    sma5 = calculate_sma(closes, 5)
    sma25 = calculate_sma(closes, 25)
    sma75 = calculate_sma(closes, 75)
    sma200 = calculate_sma(closes, 200)

    short_dir = _classify_direction(current, sma5)
    mid_dir = _classify_direction(current, sma25)
    long_dir = _classify_direction(current, sma75)
    secular_dir = _classify_direction(current, sma200)

    # 期間リターン
    ret_1m = _period_return(closes, 21)   # 約1ヶ月
    ret_3m = _period_return(closes, 63)   # 約3ヶ月
    ret_6m = _period_return(closes, 126)  # 約6ヶ月

    # 52週高値・安値からの乖離
    high_52w = max(closes[-min(252, len(closes)):])
    low_52w = min(closes[-min(252, len(closes)):])
    from_high = ((current - high_52w) / high_52w) * 100 if high_52w > 0 else 0
    from_low = ((current - low_52w) / low_52w) * 100 if low_52w > 0 else 0

    # トレンド一致度（全タイムフレームが同方向なら強いトレンド）
    dirs = [short_dir, mid_dir, long_dir]
    if secular_dir != "?":
        dirs.append(secular_dir)

    up_count = sum(1 for d in dirs if d == "↑")
    down_count = sum(1 for d in dirs if d == "↓")

    if up_count == len(dirs):
        alignment = "全面上昇トレンド"
    elif down_count == len(dirs):
        alignment = "全面下落トレンド"
    elif up_count > down_count:
        alignment = "上昇基調"
    elif down_count > up_count:
        alignment = "下落基調"
    else:
        alignment = "もみ合い"

    result = {
        "direction": f"短期{short_dir} 中期{mid_dir} 長期{long_dir}",
        "alignment": alignment,
        "from_52w_high": round(from_high, 1),
        "from_52w_low": round(from_low, 1),
    }

    if secular_dir != "?":
        result["direction"] += f" 超長期{secular_dir}"

    if ret_1m is not None:
        result["return_1m"] = round(ret_1m, 1)
    if ret_3m is not None:
        result["return_3m"] = round(ret_3m, 1)
    if ret_6m is not None:
        result["return_6m"] = round(ret_6m, 1)

    return result


# ============================================================
# シグナル検出（アラート精度向上）
# ============================================================

def detect_signals(ticker: str, closes: list[float], volumes: list[float] = None,
                   technicals: dict = None, category: str = "") -> list[dict]:
    """テクニカル指標からシグナルを検出する"""
    if technicals is None:
        technicals = analyze_technicals(closes, volumes)

    signals = []
    current_price = closes[-1] if closes else None
    if current_price is None:
        return signals

    # 1. RSI極端値
    rsi = technicals.get("rsi")
    if rsi is not None:
        if rsi >= 70:
            signals.append({"type": "rsi_overbought", "severity": "warning",
                            "message": f"RSI={rsi:.0f} 買われすぎゾーン"})
        elif rsi <= 30:
            signals.append({"type": "rsi_oversold", "severity": "opportunity",
                            "message": f"RSI={rsi:.0f} 売られすぎゾーン"})

    # 2. ボリンジャーバンド突破
    bb = technicals.get("bb")
    if bb:
        if bb["pct_b"] > 1.0:
            signals.append({"type": "bb_upper_break", "severity": "warning",
                            "message": f"BB上限突破（%B={bb['pct_b']:.2f}）"})
        elif bb["pct_b"] < 0.0:
            signals.append({"type": "bb_lower_break", "severity": "opportunity",
                            "message": f"BB下限突破（%B={bb['pct_b']:.2f}）"})

    # 3. MACDクロス
    macd = technicals.get("macd")
    if macd:
        if macd["cross"] == "golden":
            signals.append({"type": "macd_golden_cross", "severity": "bullish",
                            "message": "MACDゴールデンクロス発生"})
        elif macd["cross"] == "dead":
            signals.append({"type": "macd_dead_cross", "severity": "bearish",
                            "message": "MACDデッドクロス発生"})

    # 4. 移動平均線クロス（5日線 vs 25日線）
    sma5 = technicals.get("sma5")
    sma25 = technicals.get("sma25")
    if sma5 is not None and sma25 is not None and len(closes) >= 26:
        prev_sma5 = calculate_sma(closes[:-1], 5)
        prev_sma25 = calculate_sma(closes[:-1], 25)
        if prev_sma5 is not None and prev_sma25 is not None:
            if prev_sma5 <= prev_sma25 and sma5 > sma25:
                signals.append({"type": "ma_golden_cross", "severity": "bullish",
                                "message": "5日/25日線ゴールデンクロス"})
            elif prev_sma5 >= prev_sma25 and sma5 < sma25:
                signals.append({"type": "ma_dead_cross", "severity": "bearish",
                                "message": "5日/25日線デッドクロス"})

    # 5. 出来高異常
    vol_ratio = technicals.get("volume_ratio")
    if vol_ratio is not None and vol_ratio >= 2.0:
        signals.append({"type": "volume_spike", "severity": "alert",
                        "message": f"出来高急増（平均の{vol_ratio:.1f}倍）"})

    # 6. 連続上昇/下落（3日以上）
    if len(closes) >= 4:
        streak = 0
        direction = None
        for i in range(len(closes) - 1, max(len(closes) - 8, 0), -1):
            diff = closes[i] - closes[i - 1]
            if direction is None:
                direction = "up" if diff > 0 else "down" if diff < 0 else None
                streak = 1
            elif (direction == "up" and diff > 0) or (direction == "down" and diff < 0):
                streak += 1
            else:
                break

        if streak >= 3:
            label = "連続上昇" if direction == "up" else "連続下落"
            sev = "bullish" if direction == "up" else "bearish"
            signals.append({"type": "streak", "severity": sev,
                            "message": f"{streak}日{label}中"})

    # 7. ボラティリティ適応型の日次変動アラート
    if len(closes) >= 2:
        daily_pct = ((closes[-1] - closes[-2]) / closes[-2]) * 100
        threshold = _get_volatility_threshold(closes, category)
        if abs(daily_pct) >= threshold:
            direction = "急騰" if daily_pct > 0 else "急落"
            signals.append({"type": "price_alert", "severity": "alert",
                            "message": f"{direction} {daily_pct:+.2f}%（閾値±{threshold:.1f}%）"})

    return signals


def _get_volatility_threshold(closes: list[float], category: str = "") -> float:
    """銘柄のヒストリカルボラティリティに基づく動的閾値を計算する"""
    # カテゴリーベースのデフォルト
    category_defaults = {
        "ハイテク": 3.0, "テック": 3.0, "Tech": 3.0, "Growth": 3.0,
        "ディフェンシブ": 1.5, "Defensive": 1.5, "公益": 1.5, "Utilities": 1.5,
        "高配当": 1.5, "Dividend": 1.5,
    }
    default = 2.0
    for key, val in category_defaults.items():
        if key.lower() in category.lower():
            default = val
            break

    # ヒストリカルボラティリティから計算（20日間の標準偏差×2）
    if len(closes) < 20:
        return default

    returns = [(closes[i] - closes[i - 1]) / closes[i - 1] * 100
               for i in range(max(1, len(closes) - 20), len(closes))]
    if not returns:
        return default

    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / len(returns)
    std = math.sqrt(variance)

    # 閾値 = 2σ（最低1.0%、最大5.0%）
    return max(1.0, min(5.0, std * 2))


# ============================================================
# スコアリング（Bull/Bear/Neutral）
# ============================================================

def calculate_score(technicals: dict, signals: list[dict]) -> dict:
    """銘柄のBull/Bear/Neutralスコアを計算する"""
    score = 0  # -100 ~ +100

    # RSIスコア
    rsi = technicals.get("rsi")
    if rsi is not None:
        if rsi > 70:
            score -= 20
        elif rsi > 60:
            score -= 5
        elif rsi < 30:
            score += 20
        elif rsi < 40:
            score += 5

    # MACD
    macd = technicals.get("macd")
    if macd:
        if macd["histogram"] > 0:
            score += 10
        else:
            score -= 10
        if macd["cross"] == "golden":
            score += 15
        elif macd["cross"] == "dead":
            score -= 15

    # BBポジション
    bb = technicals.get("bb")
    if bb:
        if bb["pct_b"] > 1.0:
            score -= 10
        elif bb["pct_b"] < 0.0:
            score += 10

    # トレンド一致度
    trend = technicals.get("trend")
    if trend:
        alignment = trend.get("alignment", "")
        if alignment == "全面上昇トレンド":
            score += 15
        elif alignment == "全面下落トレンド":
            score -= 15
        elif alignment == "上昇基調":
            score += 5
        elif alignment == "下落基調":
            score -= 5

    # シグナルからのスコア加算
    for sig in signals:
        if sig["severity"] == "bullish":
            score += 10
        elif sig["severity"] == "bearish":
            score -= 10
        elif sig["severity"] == "opportunity":
            score += 5

    # クランプ
    score = max(-100, min(100, score))

    if score >= 20:
        label = "Bull"
    elif score <= -20:
        label = "Bear"
    else:
        label = "Neutral"

    return {"score": score, "label": label}


def classify_action_priority(score: dict, signals: list[dict]) -> str:
    """アクション優先度: 要注意 / 経過観察 / 安定"""
    if any(s["severity"] in ("alert", "warning") for s in signals):
        return "要注意"
    if abs(score["score"]) >= 30 or len(signals) >= 2:
        return "経過観察"
    return "安定"


# ============================================================
# ポートフォリオ分析
# ============================================================

def analyze_portfolio(holdings_map: dict) -> dict:
    """保有銘柄全体のポートフォリオ分析を行う"""
    result = {
        "sector_allocation": {},
        "total_pnl": None,
        "holdings_pnl": [],
        "risk_summary": "",
    }

    # セクター配分
    sector_counts = defaultdict(int)
    sector_values = defaultdict(float)
    total_value = 0
    pnl_items = []

    for ticker, data in holdings_map.items():
        category = data.get("category", "未分類")
        sector_counts[category] += 1

        price = data.get("price")
        cost = data.get("cost_basis")
        shares = data.get("shares")

        if price and isinstance(price, (int, float)):
            position_value = price * (shares if shares else 1)
            sector_values[category] += position_value
            total_value += position_value

        # 損益計算（コストベースと株数がある場合）
        if price and cost and shares and isinstance(price, (int, float)) and isinstance(cost, (int, float)):
            pnl = (price - cost) * shares
            pnl_pct = ((price - cost) / cost) * 100
            pnl_items.append({
                "ticker": ticker,
                "name": data.get("name", ticker),
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
                "cost": cost,
                "price": price,
                "shares": shares,
            })

    # セクター比率
    if total_value > 0:
        for cat in sector_values:
            result["sector_allocation"][cat] = round(sector_values[cat] / total_value * 100, 1)
    else:
        # 銘柄数ベースのフォールバック
        total = sum(sector_counts.values())
        if total > 0:
            for cat in sector_counts:
                result["sector_allocation"][cat] = round(sector_counts[cat] / total * 100, 1)

    # 損益
    if pnl_items:
        total_pnl = sum(item["pnl"] for item in pnl_items)
        total_cost = sum(item["cost"] * item["shares"] for item in pnl_items)
        result["total_pnl"] = {
            "amount": round(total_pnl, 2),
            "pct": round(total_pnl / total_cost * 100, 2) if total_cost > 0 else 0,
        }
        result["holdings_pnl"] = sorted(pnl_items, key=lambda x: x["pnl_pct"])

    # リスク分散サマリー
    n_sectors = len(sector_counts)
    if n_sectors <= 1:
        result["risk_summary"] = "集中投資（1セクター）: 分散を検討"
    elif n_sectors <= 3:
        result["risk_summary"] = f"やや集中（{n_sectors}セクター）: 追加分散を推奨"
    else:
        result["risk_summary"] = f"分散良好（{n_sectors}セクター）"

    return result


def calculate_correlation(closes_a: list[float], closes_b: list[float], period: int = 20) -> float | None:
    """2銘柄の日次リターンの相関係数を計算する"""
    min_len = min(len(closes_a), len(closes_b))
    if min_len < period + 1:
        return None

    a = closes_a[-period - 1:]
    b = closes_b[-period - 1:]
    ret_a = [(a[i] - a[i - 1]) / a[i - 1] for i in range(1, len(a))]
    ret_b = [(b[i] - b[i - 1]) / b[i - 1] for i in range(1, len(b))]

    n = min(len(ret_a), len(ret_b))
    if n < 2:
        return None

    mean_a = sum(ret_a[:n]) / n
    mean_b = sum(ret_b[:n]) / n

    cov = sum((ret_a[i] - mean_a) * (ret_b[i] - mean_b) for i in range(n)) / n
    std_a = math.sqrt(sum((ret_a[i] - mean_a) ** 2 for i in range(n)) / n)
    std_b = math.sqrt(sum((ret_b[i] - mean_b) ** 2 for i in range(n)) / n)

    if std_a == 0 or std_b == 0:
        return None
    return round(cov / (std_a * std_b), 2)
