import asyncio
import logging
import google.auth
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

# モジュールレベルでキャッシュ（同一プロセス内で再利用）
_cached_service = None


def _get_sheets_service():
    """Google Sheets APIサービスを取得（キャッシュ済みなら再利用）"""
    global _cached_service
    if _cached_service is None:
        credentials, project = google.auth.default(
            scopes=['https://www.googleapis.com/auth/spreadsheets.readonly']
        )
        _cached_service = build('sheets', 'v4', credentials=credentials)
    return _cached_service


def _fetch_from_sheet_sync(sheet_name: str, spreadsheet_id: str) -> list[dict]:
    """
    Google Sheets API（同期）で銘柄情報を取得する。
    VM上のService Account (ADC) を使用して認証する。
    """
    service = _get_sheets_service()

    range_name = f"{sheet_name}!A:B"
    sheet = service.spreadsheets()
    result = sheet.values().get(spreadsheetId=spreadsheet_id, range=range_name).execute()

    rows = result.get('values', [])
    if not rows or len(rows) <= 1:
        logger.warning(f"No data found in sheet: {sheet_name}")
        return []

    stocks = []
    for row in rows[1:]:
        ticker = row[0].strip() if len(row) > 0 and row[0] else ""
        if not ticker:
            continue

        category = row[1].strip() if len(row) > 1 and row[1] else "未分類"
        stocks.append({
            "ticker": ticker,
            "category": category
        })

    logger.info(f"Loaded {len(stocks)} stocks from {sheet_name}")
    return stocks


async def get_stocks_from_sheet(sheet_name: str, spreadsheet_id: str) -> list[dict]:
    """
    イベントループをブロックしないよう、同期API呼び出しを別スレッドで実行する。
    """
    try:
        return await asyncio.to_thread(_fetch_from_sheet_sync, sheet_name, spreadsheet_id)
    except Exception as e:
        logger.error(f"Error reading from sheet {sheet_name}: {e}")
        raise e
