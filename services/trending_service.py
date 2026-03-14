import asyncio
import logging
import xml.etree.ElementTree as ET

import aiohttp

logger = logging.getLogger(__name__)

GOOGLE_TRENDS_RSS = "https://trends.google.co.jp/trending/rss?geo=JP"

HATENA_CATEGORIES = {
    "entertainment": "https://b.hatena.ne.jp/hotentry/entertainment.rss",
    "it": "https://b.hatena.ne.jp/hotentry/it.rss",
    "life": "https://b.hatena.ne.jp/hotentry/life.rss",
    "general": "https://b.hatena.ne.jp/hotentry.rss",
}

# キャラの description キーワード → はてなカテゴリ
_KEYWORD_TO_CATEGORY = {
    "エンタメ": "entertainment",
    "芸能": "entertainment",
    "スポーツ": "entertainment",
    "テック": "it",
    "IT": "it",
    "テクノロジー": "it",
    "美容": "life",
    "ファッション": "life",
    "恋愛": "life",
    "料理": "life",
    "レシピ": "life",
    "占い": "life",
}

_TIMEOUT = aiohttp.ClientTimeout(total=10)


async def _fetch_rss(url: str, retries: int = 2) -> str | None:
    for attempt in range(retries + 1):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=_TIMEOUT) as resp:
                    if resp.status == 200:
                        return await resp.text()
                    logger.warning(f"RSS fetch failed ({resp.status}): {url}")
        except Exception as e:
            logger.warning(f"RSS fetch error (attempt {attempt + 1}/{retries + 1}): {url} - {e}")
        if attempt < retries:
            await asyncio.sleep(2 ** attempt)
    return None


async def _fetch_google_trends(limit: int = 10) -> list[str]:
    text = await _fetch_rss(GOOGLE_TRENDS_RSS)
    if not text:
        return []
    try:
        root = ET.fromstring(text)
        items = root.findall(".//{http://www.w3.org/2005/Atom}entry/{http://www.w3.org/2005/Atom}title")
        if not items:
            items = root.findall(".//item/title")
        return [item.text.strip() for item in items[:limit] if item.text]
    except ET.ParseError as e:
        logger.warning(f"Google Trends RSS parse error: {e}")
        return []


async def _fetch_hatena_hotentry(category: str = "general", limit: int = 10) -> list[str]:
    url = HATENA_CATEGORIES.get(category, HATENA_CATEGORIES["general"])
    text = await _fetch_rss(url)
    if not text:
        return []
    try:
        root = ET.fromstring(text)
        ns = {"rss": "http://purl.org/rss/1.0/"}
        items = root.findall(".//rss:item/rss:title", ns)
        if not items:
            items = root.findall(".//item/title")
        return [item.text.strip() for item in items[:limit] if item.text]
    except ET.ParseError as e:
        logger.warning(f"Hatena RSS parse error: {e}")
        return []


def _detect_hatena_category(description: str) -> str:
    for keyword, category in _KEYWORD_TO_CATEGORY.items():
        if keyword in description:
            return category
    return "general"


async def fetch_trending_context(description: str) -> str:
    """
    キャラの担当ジャンル (description) に基づき、
    Google Trends + はてブ Hot Entry からトレンド情報を取得して
    プロンプトに注入するテキストを返す。
    取得失敗時は空文字を返す。
    """
    hatena_cat = _detect_hatena_category(description)

    trends, hotentry = await asyncio.gather(
        _fetch_google_trends(limit=10),
        _fetch_hatena_hotentry(category=hatena_cat, limit=10),
    )

    lines: list[str] = []
    if trends:
        lines.append("【今Googleでバズってる検索ワード】")
        for i, t in enumerate(trends[:8], 1):
            lines.append(f"  {i}. {t}")

    if hotentry:
        lines.append("【今ネットで話題の記事タイトル】")
        for i, t in enumerate(hotentry[:5], 1):
            lines.append(f"  {i}. {t}")

    return "\n".join(lines)
