import holidays
from zoneinfo import ZoneInfo
from datetime import datetime, time

# 日本時間(JST)と米国東部標準時(EST/EDT)のタイムゾーン
TZ_JST = ZoneInfo("Asia/Tokyo")
TZ_NY = ZoneInfo("America/New_York")

STOCK_CONFIG = {
    # spreadsheet_id は Secret Manager で管理（bot.spreadsheet_id 経由）

    # 閉場後何分で実行するか
    "market_close_offset_minutes": 30,

    "schedules": {
        # --- 米国株 ---
        "us_daily": {
            "market_close_et": time(16, 0),  # NYSE/NASDAQ 閉場 16:00 ET
            "weekdays_only": True,
            "skip_holidays": "US",           # holidays.US() で判定
        },
        "us_weekly": {
            "hour": 15,                      # 土曜 15:00 JST 固定
            "minute": 0,
            "saturday_only": True,
        },
        
        # --- 日本株 ---
        "jp_daily": {
            "market_close_jst": time(15, 0), # TSE 閉場 15:00 JST
            "weekdays_only": True,
            "skip_holidays": "JP",           # holidays.JP() で判定
        },
        "jp_weekly": {
            "hour": 14,                      # 土曜 14:00 JST 固定
            "minute": 0,
            "saturday_only": True,
        },
    }
}

def is_us_dst(dt: datetime = None) -> bool:
    """指定日時（デフォルトは現在）のNYがサマータイムかどうか判定する"""
    if dt is None:
        dt = datetime.now()
    
    # dtにタイムゾーンが設定されていない場合はNY時間を想定
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_NY)
    
    # dst() が 0 でなければサマータイム
    return bool(dt.dst())

def get_us_market_close_jst(dt: datetime = None) -> time:
    """指定日時の米国市場閉場時刻をJSTで取得する（夏: 05:00, 冬: 06:00）"""
    close_et = STOCK_CONFIG["schedules"]["us_daily"]["market_close_et"]
    
    if dt is None:
        dt = datetime.now(TZ_NY)
    else:
        dt = dt.astimezone(TZ_NY)
        
    close_dt_ny = datetime.combine(dt.date(), close_et, tzinfo=TZ_NY)
    close_dt_jst = close_dt_ny.astimezone(TZ_JST)
    
    return close_dt_jst.time()

def is_holiday(date_obj, market: str) -> bool:
    """指定日付が指定市場（US/JP）の祝日（休場日）かどうか判定する"""
    year = date_obj.year
    if market == "US":
        nyse_holidays = holidays.NYSE(years=year)
        return date_obj in nyse_holidays
    elif market == "JP":
        jpn_holidays = holidays.JP(years=year)
        return date_obj in jpn_holidays

    return False
