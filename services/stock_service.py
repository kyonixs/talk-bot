import logging
import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=10)

# 日本株の企業名キャッシュ（プロセス存続中は再スクレイピングしない）
_jp_name_cache: dict[str, str] = {}

async def fetch_yahoo_chart(ticker: str, session: aiohttp.ClientSession = None,
                            chart_range: str = "5d") -> dict:
    """Yahoo Finance API (v8) からチャートデータを取得する
    chart_range: '5d', '1mo', '3mo', '6mo' など
    """
    hosts = [
        "https://query1.finance.yahoo.com",
        "https://query2.finance.yahoo.com"
    ]
    path = f"/v8/finance/chart/{ticker}?range={chart_range}&interval=1d"
    headers = {"User-Agent": USER_AGENT}

    owns_session = session is None
    if owns_session:
        session = aiohttp.ClientSession()

    last_error = None
    try:
        for i, host in enumerate(hosts):
            try:
                async with session.get(host + path, headers=headers, timeout=_REQUEST_TIMEOUT) as response:
                    if response.status != 200:
                        last_error = Exception(f"HTTP {response.status} from {host}")
                        continue

                    json_data = await response.json()
                    result = json_data.get("chart", {}).get("result", [])
                    if not result:
                        last_error = Exception(f"No data from {host}")
                        continue

                    data = result[0]
                    meta = data.get("meta", {})

                    indicators = data.get("indicators", {})
                    quote = indicators.get("quote", [{}])[0]
                    closes = quote.get("close", [])
                    volumes = quote.get("volume", [])

                    # 不要な None などを除去（インデックスを揃えるため同時フィルタ）
                    valid_closes = [c for c in closes if c is not None]
                    valid_volumes = [volumes[i] if i < len(volumes) and volumes[i] is not None else 0
                                     for i, c in enumerate(closes) if c is not None]

                    return {"meta": meta, "valid_closes": valid_closes, "valid_volumes": valid_volumes}

            except Exception as e:
                last_error = e
                logger.warning(f"Yahoo Finance Fallback: {host} -> {e}")
    finally:
        if owns_session:
            await session.close()

    raise last_error or Exception(f"All hosts failed for: {ticker}")


async def fetch_market_indices(market: str, session: aiohttp.ClientSession = None) -> dict:
    """主要指数データを取得する。market: 'US' or 'JP'"""
    if market == "US":
        tickers = {
            "S&P 500": "^GSPC",
            "NASDAQ": "^IXIC",
            "VIX": "^VIX",
            "米10年債利回り": "^TNX",
            "USD/JPY": "JPY=X",
        }
    else:
        tickers = {
            "日経平均": "^N225",
            "TOPIX": "^TOPX",
            "USD/JPY": "JPY=X",
        }

    # 利回り系は変化率ではなく差分（bps）で表示する
    _yield_tickers = {"^TNX"}
    # VIXはポイント差分で表示
    _point_diff_tickers = {"^VIX"}

    results = {}
    for label, ticker in tickers.items():
        try:
            chart_data = await fetch_yahoo_chart(ticker, session=session)
            closes = chart_data["valid_closes"]
            if len(closes) >= 2:
                current = closes[-1]
                prev = closes[-2]
                if ticker in _yield_tickers:
                    # 利回り: 差分をbps (basis points) で表示
                    diff = (current - prev) * 100  # 1% = 100bps
                    sign = "+" if diff >= 0 else ""
                    results[label] = {
                        "value": f"{current:.2f}%",
                        "change": f"{sign}{diff:.1f}bps",
                    }
                elif ticker in _point_diff_tickers:
                    # VIX等: ポイント差分で表示
                    diff = current - prev
                    sign = "+" if diff >= 0 else ""
                    results[label] = {
                        "value": f"{current:.2f}",
                        "change": f"{sign}{diff:.2f}pt",
                    }
                else:
                    pct = ((current - prev) / prev) * 100 if prev is not None and prev != 0 else 0
                    sign = "+" if pct >= 0 else ""
                    results[label] = {
                        "value": round(current, 2),
                        "change": f"{sign}{pct:.2f}%",
                    }
            elif closes:
                results[label] = {"value": round(closes[-1], 2), "change": "-"}
            else:
                results[label] = {"value": "-", "change": "-"}
        except Exception as e:
            logger.warning(f"Failed to fetch index {label} ({ticker}): {e}")
            results[label] = {"value": "-", "change": "-"}

    return results


async def fetch_extended_chart(ticker: str, session: aiohttp.ClientSession = None) -> dict:
    """テクニカル分析用に1年分の日足データ（終値・出来高）を取得する"""
    try:
        chart_data = await fetch_yahoo_chart(ticker, session=session, chart_range="1y")
        return {
            "closes": chart_data["valid_closes"],
            "volumes": chart_data["valid_volumes"],
        }
    except Exception as e:
        logger.warning(f"Failed to fetch extended chart for {ticker}: {e}")
        return {"closes": [], "volumes": []}


async def fetch_sector_etfs(session: aiohttp.ClientSession = None) -> dict:
    """米国セクターETFの直近パフォーマンスを取得する"""
    etfs = {
        "XLK": "テクノロジー",
        "XLF": "金融",
        "XLE": "エネルギー",
        "XLV": "ヘルスケア",
        "XLI": "資本財",
        "XLP": "生活必需品",
        "XLY": "一般消費財",
        "XLU": "公益",
    }
    results = {}
    for ticker, name in etfs.items():
        try:
            chart_data = await fetch_yahoo_chart(ticker, session=session)
            closes = chart_data["valid_closes"]
            if len(closes) >= 2:
                pct = ((closes[-1] - closes[-2]) / closes[-2]) * 100
                sign = "+" if pct >= 0 else ""
                results[name] = f"{sign}{pct:.2f}%"
            else:
                results[name] = "-"
        except Exception as e:
            logger.warning(f"Failed to fetch sector ETF {ticker}: {e}")
            results[name] = "-"
    return results


async def fetch_us_stock(ticker: str, cached_name: str = "", session: aiohttp.ClientSession = None) -> dict:
    """米国株の価格情報を取得する"""
    try:
        chart_data = await fetch_yahoo_chart(ticker, session=session)
        meta = chart_data["meta"]
        valid_closes = chart_data["valid_closes"]

        price = valid_closes[-1] if valid_closes else meta.get("regularMarketPrice")
        previous_close = valid_closes[-2] if len(valid_closes) >= 2 else meta.get("previousClose")

        change_pct_str = ""
        if price is not None and previous_close is not None and previous_close != 0:
            pct = ((price - previous_close) / previous_close) * 100
            sign = "+" if pct >= 0 else ""
            change_pct_str = f"{sign}{pct:.2f}%"

        if price is not None:
            price = round(price, 2)

        # 週間変動の計算
        weekly_change_pct_str = ""
        if len(valid_closes) >= 2:
            week_start = valid_closes[0]
            week_end = valid_closes[-1]
            if week_start is not None and week_end is not None and week_start != 0:
                pct_w = ((week_end - week_start) / week_start) * 100
                sign_w = "+" if pct_w >= 0 else ""
                weekly_change_pct_str = f"{sign_w}{pct_w:.2f}%"

        name = cached_name or meta.get("shortName") or meta.get("longName") or ""

        return {
            "price": price if price is not None else "",
            "change": change_pct_str,
            "weeklyChange": weekly_change_pct_str,
            "name": name
        }

    except Exception as e:
        logger.warning(f"Failed to fetch US stock {ticker}: {e}")
        raise e


async def fetch_jp_company_name(code: str, session: aiohttp.ClientSession = None) -> str:
    """Yahoo Finance JP から日本株の企業名をスクレイピングする（キャッシュ付き）"""
    if code in _jp_name_cache:
        logger.debug(f"[JP名前] キャッシュヒット: {code} → {_jp_name_cache[code]}")
        return _jp_name_cache[code]

    owns_session = session is None
    if owns_session:
        session = aiohttp.ClientSession()

    try:
        url = f"https://finance.yahoo.co.jp/quote/{code}.T"
        headers = {"User-Agent": USER_AGENT}

        async with session.get(url, headers=headers, timeout=_REQUEST_TIMEOUT) as response:
            if response.status != 200:
                logger.debug(f"[JP名前] HTTP {response.status}: {code}")
                return ""

            html = await response.text()
            soup = BeautifulSoup(html, "html.parser")

            title = soup.title.string if soup.title else ""
            if not title:
                return ""

            # "トヨタ自動車【7203】..." or "トヨタ自動車(7203)..." などのパース
            for sep in ["【", "(", " - "]:
                idx = title.find(sep)
                if idx > 0:
                    name = title[:idx].strip()
                    _jp_name_cache[code] = name
                    logger.debug(f"[JP名前] スクレイピング成功: {code} → {name}")
                    return name

            return ""
    except Exception as e:
        logger.warning(f"Fetch JP Name Error ({code}): {e}")
        return ""
    finally:
        if owns_session:
            await session.close()


async def fetch_jp_stock(code: str, cached_name: str = "", session: aiohttp.ClientSession = None) -> dict:
    """日本株の価格情報を取得する"""
    try:
        ticker = f"{code}.T"
        chart_data = await fetch_yahoo_chart(ticker, session=session)
        meta = chart_data["meta"]
        valid_closes = chart_data["valid_closes"]

        price = valid_closes[-1] if valid_closes else meta.get("regularMarketPrice")
        previous_close = valid_closes[-2] if len(valid_closes) >= 2 else meta.get("previousClose")

        change_pct_str = ""
        if price is not None and previous_close is not None and previous_close != 0:
            pct = ((price - previous_close) / previous_close) * 100
            sign = "+" if pct >= 0 else ""
            change_pct_str = f"{sign}{pct:.2f}%"

        if price is not None:
            # 日本株は小数第1位まで
            price = round(price, 1)

        # 週間変動の計算
        weekly_change_pct_str = ""
        if len(valid_closes) >= 2:
            week_start = valid_closes[0]
            week_end = valid_closes[-1]
            if week_start is not None and week_end is not None and week_start != 0:
                pct_w = ((week_end - week_start) / week_start) * 100
                sign_w = "+" if pct_w >= 0 else ""
                weekly_change_pct_str = f"{sign_w}{pct_w:.2f}%"

        name = cached_name
        if not name:
            name = await fetch_jp_company_name(code, session=session) or meta.get("shortName") or meta.get("longName") or ""

        return {
            "price": price if price is not None else "",
            "change": change_pct_str,
            "weeklyChange": weekly_change_pct_str,
            "name": name
        }

    except Exception as e:
        logger.warning(f"Failed to fetch JP stock {code}: {e}")
        raise e
