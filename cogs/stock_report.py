import discord
from discord.ext import commands, tasks
import asyncio
import traceback
import aiohttp
from datetime import datetime, timedelta
from config.stock_config import STOCK_CONFIG, get_us_market_close_jst, is_holiday, is_us_dst, TZ_JST
from services.sheets_service import get_stocks_from_sheet
from services.stock_service import fetch_us_stock, fetch_jp_stock
from services.gemini_service import GeminiService
import prompts.stock_prompts as prompts

class StockReportCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Botの初期化時に取得済みの株式用APIキー・Webhook URLを使用
        self.gemini_service = GeminiService(api_key=bot.gemini_api_key_stock)
        self.webhook_url = bot.discord_webhook_stock
        self.spreadsheet_id = bot.spreadsheet_id

        # 同時実行を防ぐロック
        self._report_lock = asyncio.Lock()

        # 毎分チェックのループタスクを開始
        self.check_and_run_reports.start()
        print("StockReportCog loaded and scheduler started.")

    def cog_unload(self):
        self.check_and_run_reports.cancel()
        print("StockReportCog unloaded and scheduler stopped.")

    # =========================================================================
    # Scheduler
    # =========================================================================
    
    @tasks.loop(minutes=1)
    async def check_and_run_reports(self):
        """毎分実行され、設定されたスケジュール時刻と一致した場合にレポート処理を起動する"""
        now = datetime.now(TZ_JST)
        is_weekday = now.weekday() < 5  # 0-4 (Mon-Fri)
        is_saturday = now.weekday() == 5 # 5 (Sat)
        
        # 1. 米国株 日次 (平日, 祝日除外, サマータイム対応)
        schedules = STOCK_CONFIG["schedules"]
        us_daily = schedules["us_daily"]
        if is_weekday and us_daily.get("weekdays_only"):
            # 今日の祝日チェック
            if us_daily.get("skip_holidays") and is_holiday(now.date(), us_daily["skip_holidays"]):
                pass # 祝日はスキップ（毎分ログが出ないようここではpassだけ）
            else:
                target_time = get_us_market_close_jst(now)
                offset = STOCK_CONFIG.get("market_close_offset_minutes", 30)
                # target_timeにoffset(分)を足す
                target_dt = datetime.combine(now.date(), target_time, tzinfo=TZ_JST)
                target_dt += timedelta(minutes=offset)
                
                if now.hour == target_dt.hour and now.minute == target_dt.minute:
                    print("Triggering US Daily Report...")
                    asyncio.create_task(self.run_us_daily_report())

        # 2. 日本株 日次 (平日, 祝日除外)
        jp_daily = schedules["jp_daily"]
        if is_weekday and jp_daily.get("weekdays_only"):
            if jp_daily.get("skip_holidays") and is_holiday(now.date(), jp_daily["skip_holidays"]):
                pass
            else:
                target_time = jp_daily["market_close_jst"]
                offset = STOCK_CONFIG.get("market_close_offset_minutes", 30)
                target_dt = datetime.combine(now.date(), target_time, tzinfo=TZ_JST)
                target_dt += timedelta(minutes=offset)
                
                if now.hour == target_dt.hour and now.minute == target_dt.minute:
                    print("Triggering JP Daily Report...")
                    asyncio.create_task(self.run_jp_daily_report())

        # 3. 日本株 週次 (土曜固定)
        jp_weekly = schedules["jp_weekly"]
        if is_saturday and jp_weekly.get("saturday_only"):
            if now.hour == jp_weekly["hour"] and now.minute == jp_weekly["minute"]:
                print("Triggering JP Weekly Report...")
                asyncio.create_task(self.run_jp_weekly_report())

        # 4. 米国株 週次 (土曜固定)
        us_weekly = schedules["us_weekly"]
        if is_saturday and us_weekly.get("saturday_only"):
            if now.hour == us_weekly["hour"] and now.minute == us_weekly["minute"]:
                print("Triggering US Weekly Report...")
                asyncio.create_task(self.run_us_weekly_report())

    @check_and_run_reports.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    # =========================================================================
    # Report Runners
    # =========================================================================

    async def run_us_daily_report(self):
        await self._run_report_workflow("米国株 日次", "US", False)

    async def run_jp_daily_report(self):
        await self._run_report_workflow("日本株 日次", "JP", False)

    async def run_us_weekly_report(self):
        await self._run_report_workflow("米国株 週次", "US", True)

    async def run_jp_weekly_report(self):
        await self._run_report_workflow("日本株 週次", "JP", True)

    async def _run_report_workflow(self, report_name: str, market: str, weekly: bool):
        """全体のワークフロー: データ取得 -> レポート生成 -> Discord送信"""
        if self._report_lock.locked():
            print(f"[{report_name}] 別のレポートが実行中のためスキップ")
            return

        async with self._report_lock:
            await self._run_report_workflow_inner(report_name, market, weekly)

    async def _run_report_workflow_inner(self, report_name: str, market: str, weekly: bool):
        print(f"--- 🚀 Starting {report_name} workflow ---")
        try:
            # 1. Sheetsから銘柄リスト取得
            holdings_list = await get_stocks_from_sheet("保有銘柄", self.spreadsheet_id)
            watchlist_list = await get_stocks_from_sheet("監視銘柄", self.spreadsheet_id)

            # 2. Yahoo Financeから株価・企業情報を取得
            holdings_map = await self._fetch_all_stocks(holdings_list, market)
            watchlist_map = await self._fetch_all_stocks(watchlist_list, market)

            # 3. プロンプト生成
            if market == "US":
                prompt = prompts.build_us_weekly_prompt(holdings_map, watchlist_map) if weekly \
                    else prompts.build_us_daily_prompt(holdings_map, watchlist_map)
            else:
                prompt = prompts.build_jp_weekly_prompt(holdings_map, watchlist_map) if weekly \
                    else prompts.build_jp_daily_prompt(holdings_map, watchlist_map)

            # 4. Gemini でレポート生成
            print(f"Generating {report_name} using Gemini...")
            ai_result = await self.gemini_service.generate_stock_report(prompt)
            result_text = ai_result.get("text", "")
            if ai_result.get("truncated"):
                result_text += "\n\n*(※文字数制限により途切れています)*"

            # 5. Discord Webhook へ送信
            header = f"📊 **{report_name}レポート**"
            await self.send_stock_report(result_text, header)
            
            print(f"--- ✅ {report_name} workflow finished ---")

        except Exception as e:
            await self.notify_error(f"{report_name} Workflow", e)

    async def _fetch_all_stocks(self, stock_list: list[dict], market: str) -> dict:
        """指定されたリストの全銘柄情報を並列取得し、辞書で返す（セッション共有）"""
        stock_map = {}
        fetch_tasks = []

        async with aiohttp.ClientSession() as session:
            async def fetch_single(stock: dict):
                ticker = stock["ticker"]
                try:
                    if market == "US":
                        data = await fetch_us_stock(ticker, session=session)
                    else:
                        data = await fetch_jp_stock(ticker, session=session)

                    # dictにマージして保存
                    stock_map[ticker] = {**stock, **data}
                except Exception as e:
                    print(f"Error fetching {ticker}: {e}")
                    stock_map[ticker] = {**stock, "price": "Error", "change": "-", "weeklyChange": "-", "name": ticker}

            for stock in stock_list:
                fetch_tasks.append(fetch_single(stock))

            await asyncio.gather(*fetch_tasks)
        return stock_map

    # =========================================================================
    # Discord Webhook Sender
    # =========================================================================

    async def send_stock_report(self, text: str, header: str):
        """Webhook URL を使用してDiscordに投稿する（1900文字分割）"""
        if not self.webhook_url:
            print("Error: Webhook URL is not set.")
            return

        print(f"Sending message to Webhook... Length: {len(text)}")
        chunks = self._chunk_message(text, 1900)
        
        async with aiohttp.ClientSession() as session:
            for i, chunk in enumerate(chunks):
                if i == 0:
                    content = f"{header}\n\n{chunk}"
                else:
                    content = f"(続き)\n{chunk}"

                payload = {
                    "content": content,
                    # Webhookの名前やアイコンをここで上書き可能（要件次第）
                    "username": "AI株式アシスタント",
                    "avatar_url": "https://img.icons8.com/color/96/bullish.png"
                }

                try:
                    async with session.post(self.webhook_url, json=payload) as resp:
                        if resp.status not in (200, 204):
                            print(f"Webhook error: {resp.status} - {await resp.text()}")
                except Exception as e:
                    print(f"Failed to post to webhook: {e}")

    def _chunk_message(self, text: str, max_length: int) -> list[str]:
        chunks = []
        lines = text.split('\n')
        current_chunk = ""

        for line in lines:
            if len(current_chunk) + len(line) + 1 > max_length:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = line
            else:
                current_chunk = f"{current_chunk}\n{line}" if current_chunk else line

        if current_chunk:
            chunks.append(current_chunk)

        if not chunks:
            chunks = ["（内容が空です）"]

        return chunks

    async def notify_error(self, func_name: str, error: Exception):
        """エラー発生時にWebhookに通知する（内部情報はログのみ）"""
        # スタックトレースはサーバーログにのみ出力
        print(f"[ERROR] {func_name}: {traceback.format_exc()}")

        # Discordにはエラー種別と概要のみ送信（パスやモジュール名を露出しない）
        error_type = type(error).__name__
        text = f"🚨 **Stock Report Error** 🚨\n**処理:** {func_name}\n**種別:** {error_type}\n詳細はサーバーログを確認してください。"
            
        if self.webhook_url:
            async with aiohttp.ClientSession() as session:
                payload = {"content": text, "username": "エラー監視"}
                try:
                    await session.post(self.webhook_url, json=payload)
                except Exception as push_err:
                    print(f"Failed to push error log to webhook: {push_err}")

async def setup(bot):
    await bot.add_cog(StockReportCog(bot))
