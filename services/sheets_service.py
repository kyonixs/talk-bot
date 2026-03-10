import asyncio
import google.auth
from googleapiclient.discovery import build


def _fetch_from_sheet_sync(sheet_name: str, spreadsheet_id: str) -> list[dict]:
    """
    Google Sheets API（同期）で銘柄情報を取得する。
    VM上のService Account (ADC) を使用して認証する。
    """
    credentials, project = google.auth.default(
        scopes=['https://www.googleapis.com/auth/spreadsheets.readonly']
    )
    service = build('sheets', 'v4', credentials=credentials)

    range_name = f"{sheet_name}!A:B"
    sheet = service.spreadsheets()
    result = sheet.values().get(spreadsheetId=spreadsheet_id, range=range_name).execute()

    rows = result.get('values', [])
    if not rows or len(rows) <= 1:
        print(f"No data found in sheet: {sheet_name}")
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

    print(f"Loaded {len(stocks)} stocks from {sheet_name}")
    return stocks


async def get_stocks_from_sheet(sheet_name: str, spreadsheet_id: str) -> list[dict]:
    """
    イベントループをブロックしないよう、同期API呼び出しを別スレッドで実行する。
    """
    try:
        return await asyncio.to_thread(_fetch_from_sheet_sync, sheet_name, spreadsheet_id)
    except Exception as e:
        print(f"Error reading from sheet {sheet_name}: {e}")
        raise e
