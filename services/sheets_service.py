import asyncio
import logging
import google.auth
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

# モジュールレベルでキャッシュ（同一プロセス内で再利用）
_cached_service = None


def _get_sheets_service(force_refresh: bool = False):
    """Google Sheets APIサービスを取得（キャッシュ済みなら再利用）"""
    global _cached_service
    if _cached_service is None or force_refresh:
        credentials, project = google.auth.default(
            scopes=['https://www.googleapis.com/auth/spreadsheets.readonly']
        )
        _cached_service = build('sheets', 'v4', credentials=credentials)
        if force_refresh:
            logger.info("Sheets API service refreshed (credentials renewed)")
    return _cached_service


def _fetch_from_sheet_sync(sheet_name: str, spreadsheet_id: str) -> list[dict]:
    """
    Google Sheets API（同期）で銘柄情報を取得する。
    VM上のService Account (ADC) を使用して認証する。
    """
    service = _get_sheets_service()

    range_name = f"{sheet_name}!A:D"
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

        # C列: 取得単価（任意）
        cost_basis = None
        if len(row) > 2 and row[2]:
            try:
                cost_basis = float(row[2].strip().replace(",", ""))
            except (ValueError, AttributeError):
                pass

        # D列: 保有株数（任意）
        shares = None
        if len(row) > 3 and row[3]:
            try:
                shares = float(row[3].strip().replace(",", ""))
            except (ValueError, AttributeError):
                pass

        stock = {"ticker": ticker, "category": category}
        if cost_basis is not None:
            stock["cost_basis"] = cost_basis
        if shares is not None:
            stock["shares"] = shares
        stocks.append(stock)

    logger.info(f"Loaded {len(stocks)} stocks from {sheet_name}")
    return stocks


async def get_stocks_from_sheet(sheet_name: str, spreadsheet_id: str) -> list[dict]:
    """
    イベントループをブロックしないよう、同期API呼び出しを別スレッドで実行する。
    一時的なエラーに対して最大3回リトライする。
    """
    max_retries = 3
    for attempt in range(max_retries):
        try:
            return await asyncio.to_thread(_fetch_from_sheet_sync, sheet_name, spreadsheet_id)
        except Exception as e:
            # HttpError (429, 500, 503 等) や一時的なネットワークエラーを想定
            is_retriable = False
            error_msg = str(e)

            # HttpError のステータスコードを確認 (googleapiclient.errors.HttpError)
            if hasattr(e, 'resp') and hasattr(e.resp, 'status'):
                status = e.resp.status
                if status in [429, 500, 502, 503, 504]:
                    is_retriable = True
                elif status in [401, 403]:
                    # 認証トークン期限切れの可能性 → サービスを再構築してリトライ
                    _get_sheets_service(force_refresh=True)
                    is_retriable = True

            # ネットワーク系エラーもリトライ対象
            if isinstance(e, (OSError, TimeoutError, ConnectionError)):
                is_retriable = True

            if is_retriable and attempt < max_retries - 1:
                wait_time = (attempt + 1) * 2
                logger.warning(f"Retry reading sheet {sheet_name} (attempt {attempt + 1}/{max_retries}) after {wait_time}s due to: {error_msg}")
                await asyncio.sleep(wait_time)
            else:
                logger.error(f"Error reading from sheet {sheet_name}: {e}")
                raise e
