import google.auth
from googleapiclient.discovery import build

async def get_stocks_from_sheet(sheet_name: str, spreadsheet_id: str) -> list[dict]:
    """
    指定されたGoogleスプレッドシートのシートから銘柄情報を取得する
    VM上のService Account (ADC) を使用して認証する
    """
    try:
        # Application Default Credentials (ADC) を使って認証
        credentials, project = google.auth.default(
            scopes=['https://www.googleapis.com/auth/spreadsheets.readonly']
        )
        service = build('sheets', 'v4', credentials=credentials)

        # A列(ティッカー)とB列(カテゴリ)を取得
        range_name = f"{sheet_name}!A:B"
        sheet = service.spreadsheets()
        result = sheet.values().get(spreadsheetId=spreadsheet_id, range=range_name).execute()
        
        rows = result.get('values', [])
        if not rows or len(rows) <= 1:
            print(f"No data found in sheet: {sheet_name}")
            return []

        # 1行目はヘッダーなのでスキップし、空のティッカーを除外
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

    except Exception as e:
        print(f"Error reading from sheet {sheet_name}: {e}")
        raise e
