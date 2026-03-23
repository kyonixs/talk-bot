import logging
import discord
from discord.ext import commands, tasks
import asyncio
import traceback
import aiohttp
from datetime import datetime, timedelta
from config.stock_config import STOCK_CONFIG, get_us_market_close_jst, is_holiday, TZ_JST, TZ_NY
from services.sheets_service import get_stocks_from_sheet
from services.stock_service import fetch_us_stock, fetch_jp_stock, fetch_market_indices
from services.gemini_service import GeminiService
import prompts.stock_prompts as prompts

logger = logging.getLogger(__name__)


class StockReportCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Botの初期化時に取得済みの株式用APIキー・Webhook URLを使用
        self.gemini = GeminiService(api_key=bot.gemini_api_key_stock)
        self.webhook_url = bot.discord_webhook_stock
        self.spreadsheet_id = bot.spreadsheet_id

        # 同時実行を防ぐロック
        self._report_lock = asyncio.Lock()

        # Webhook送信用の共有セッション（cog_unloadで閉じる）
        self._webhook_session: aiohttp.ClientSession | None = None

        # 毎分チェックのループタスクを開始
        self.check_and_run_reports.start()
        logger.info("StockReportCog loaded and scheduler started.")

    async def cog_unload(self):
        self.check_and_run_reports.cancel()
        if self._webhook_session and not self._webhook_session.closed:
            await self._webhook_session.close()
        logger.info("StockReportCog unloaded and scheduler stopped.")

    async def _get_webhook_session(self) -> aiohttp.ClientSession:
        """Webhook送信用セッションを取得（遅延初期化・再利用）"""
        if self._webhook_session is None or self._webhook_session.closed:
            self._webhook_session = aiohttp.ClientSession()
        return self._webhook_session

    def _create_report_task(self, coro, name: str):
        """レポートタスクを作成し、例外をロギングするコールバックを付与する"""
        task = asyncio.create_task(coro, name=name)
        task.add_done_callback(self._handle_task_exception)
        return task

    @staticmethod
    def _handle_task_exception(task: asyncio.Task):
        """タスク完了時に例外があればログに記録する"""
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error(f"Report task '{task.get_name()}' failed: {exc}", exc_info=exc)

    # =========================================================================
    # Scheduler
    # =========================================================================

    @tasks.loop(minutes=1)
    async def check_and_run_reports(self):
        """毎分実行され、設定されたスケジュール時刻と一致した場合にレポート処理を起動する"""
        now = datetime.now(TZ_JST)
        is_weekday = now.weekday() < 5  # 0-4 (Mon-Fri)
        is_saturday = now.weekday() == 5 # 5 (Sat)

        # 1. 米国株 日次 (NY時間の平日・祝日で判定, サマータイム対応)
        schedules = STOCK_CONFIG["schedules"]
        us_daily = schedules["us_daily"]
        if us_daily.get("weekdays_only"):
            # NY時間での曜日・祝日を基準に判定（JSTの早朝はNY前日の閉場後）
            ny_now = now.astimezone(TZ_NY)
            is_ny_weekday = ny_now.weekday() < 5
            is_ny_holiday = us_daily.get("skip_holidays") and is_holiday(ny_now.date(), us_daily["skip_holidays"])

            if is_ny_weekday and not is_ny_holiday:
                target_time = get_us_market_close_jst(now)
                offset = STOCK_CONFIG.get("market_close_offset_minutes", 30)
                target_dt = datetime.combine(now.date(), target_time, tzinfo=TZ_JST)
                target_dt += timedelta(minutes=offset)

                if now.hour == target_dt.hour and now.minute == target_dt.minute:
                    logger.info("Triggering US Daily Report...")
                    self._create_report_task(self.run_us_daily_report(), "us_daily_report")

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
                    logger.info("Triggering JP Daily Report...")
                    self._create_report_task(self.run_jp_daily_report(), "jp_daily_report")

        # 3. 日本株 週次 (土曜固定)
        jp_weekly = schedules["jp_weekly"]
        if is_saturday and jp_weekly.get("saturday_only"):
            if now.hour == jp_weekly["hour"] and now.minute == jp_weekly["minute"]:
                logger.info("Triggering JP Weekly Report...")
                self._create_report_task(self.run_jp_weekly_report(), "jp_weekly_report")

        # 4. 米国株 週次 (土曜固定)
        us_weekly = schedules["us_weekly"]
        if is_saturday and us_weekly.get("saturday_only"):
            if now.hour == us_weekly["hour"] and now.minute == us_weekly["minute"]:
                logger.info("Triggering US Weekly Report...")
                self._create_report_task(self.run_us_weekly_report(), "us_weekly_report")

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

    # =========================================================================
    # Manual Trigger Commands (Owner Only)
    # =========================================================================

    @commands.command(name="report")
    @commands.is_owner()
    async def manual_report(self, ctx, market: str = None, report_type: str = "daily"):
        """手動でレポートを実行する（Botオーナー限定）
        使い方: !report us / !report jp / !report us weekly / !report jp weekly
        """
        if not market or market.lower() not in ("us", "jp"):
            await ctx.reply("使い方: `!report us` / `!report jp` / `!report us weekly` / `!report jp weekly`")
            return

        market_upper = market.upper()
        weekly = report_type.lower() == "weekly"
        report_name = f"{('米国株' if market_upper == 'US' else '日本株')} {'週次' if weekly else '日次'}（手動）"

        await ctx.reply(f"📊 {report_name}レポートを開始します...")
        self._create_report_task(
            self._run_report_workflow(report_name, market_upper, weekly),
            f"manual_{market.lower()}_{'weekly' if weekly else 'daily'}_report",
        )

    @manual_report.error
    async def manual_report_error(self, ctx, error):
        if isinstance(error, commands.NotOwner):
            await ctx.reply("⚠️ このコマンドはBotオーナーのみ使用できます。")
        else:
            await ctx.reply(f"⚠️ エラー: {error}")

    async def _run_report_workflow(self, report_name: str, market: str, weekly: bool):
        """全体のワークフロー: データ取得 -> レポート生成 -> Discord送信"""
        if self._report_lock.locked():
            logger.warning(f"[{report_name}] 別のレポートが実行中のためスキップ（ロック保持中）")
            return

        async with self._report_lock:
            await self._run_report_workflow_inner(report_name, market, weekly)

    async def _run_report_workflow_inner(self, report_name: str, market: str, weekly: bool):
        logger.info(f"--- Starting {report_name} workflow ---")
        start_time = asyncio.get_running_loop().time()
        try:
            # 1. Sheetsから銘柄リスト取得
            holdings_list = await get_stocks_from_sheet(f"{market}_Holdings", self.spreadsheet_id)
            watchlist_list = await get_stocks_from_sheet(f"{market}_Watchlist", self.spreadsheet_id)

            logger.info(f"[{report_name}] シート読込完了: Holdings={len(holdings_list)}件, Watchlist={len(watchlist_list)}件")
            if not holdings_list and not watchlist_list:
                logger.warning(f"{report_name}: スプレッドシートに銘柄データがありません。レポートを中止します。")
                return

            # 2. Yahoo Financeから株価・企業情報 + 主要指数を並列取得（セッション共有）
            async with aiohttp.ClientSession() as session:
                results = await asyncio.gather(
                    self._fetch_all_stocks(holdings_list, market, session),
                    self._fetch_all_stocks(watchlist_list, market, session),
                    fetch_market_indices(market, session=session),
                    return_exceptions=True,
                )

                # 個別タスクの例外をチェック
                task_names = ["保有銘柄取得", "監視銘柄取得", "指数取得"]
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        logger.error(f"{report_name}: {task_names[i]}に失敗: {result}")
                        raise result

                holdings_map, watchlist_map, indices = results
                logger.info(f"[{report_name}] 株価取得完了: Holdings={len(holdings_map)}件, Watchlist={len(watchlist_map)}件, 指数={len(indices)}件")

            # 3. プロンプト生成（指数データ付き、戻り値は {"system_instruction": s, "user_prompt": u} の dict）
            if market == "US":
                prompt_data = prompts.build_us_weekly_prompt(holdings_map, watchlist_map, indices) if weekly \
                    else prompts.build_us_daily_prompt(holdings_map, watchlist_map, indices)
            else:
                prompt_data = prompts.build_jp_weekly_prompt(holdings_map, watchlist_map, indices) if weekly \
                    else prompts.build_jp_daily_prompt(holdings_map, watchlist_map, indices)

            # 4. Gemini でレポート生成
            logger.info(f"Generating {report_name} using Gemini...")
            ai_result = await self.gemini.generate_stock_report(prompt_data)
            result_text = ai_result.get("text", "")
            if ai_result.get("truncated"):
                result_text += "\n\n*(※文字数制限により途切れています)*"

            # 5. Discord Webhook へ送信（Embedヘッダー + 本文テキスト）
            await self.send_stock_report(result_text, report_name, indices)

            elapsed = asyncio.get_running_loop().time() - start_time
            logger.info(f"--- {report_name} workflow finished in {elapsed:.1f}s ---")

        except Exception as e:
            elapsed = asyncio.get_running_loop().time() - start_time
            logger.error(f"--- {report_name} workflow failed after {elapsed:.1f}s ---")
            await self.notify_error(f"{report_name} Workflow", e)

    async def _fetch_all_stocks(self, stock_list: list[dict], market: str,
                                session: aiohttp.ClientSession = None) -> dict:
        """指定されたリストの全銘柄情報を並列取得し、辞書で返す"""
        stock_map = {}
        fetch_tasks = []
        owns_session = session is None
        if owns_session:
            session = aiohttp.ClientSession()

        try:
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
                    logger.warning(f"Error fetching {ticker}: {e}")
                    stock_map[ticker] = {**stock, "price": "Error", "change": "-", "weeklyChange": "-", "name": ticker}

            for stock in stock_list:
                fetch_tasks.append(fetch_single(stock))

            await asyncio.gather(*fetch_tasks)
        finally:
            if owns_session:
                await session.close()
        return stock_map

    # =========================================================================
    # Discord Webhook Sender
    # =========================================================================

    def _build_header_embed(self, report_name: str, indices: dict) -> dict:
        """Embedオブジェクト（JSON）を構築する"""
        now = datetime.now(TZ_JST)
        date_str = now.strftime("%Y/%m/%d (%a)")

        # 指数サマリーをフィールドに変換
        fields = []
        for label, data in indices.items():
            fields.append({
                "name": label,
                "value": f"{data['value']}（{data['change']}）",
                "inline": True,
            })

        # 全体的に上昇か下落かで色を決定（USD/JPY以外の変化率で判定）
        color = 0x808080  # グレー（デフォルト）
        changes = []
        for label, data in indices.items():
            if label == "USD/JPY":
                continue
            try:
                pct = float(data["change"].replace("+", "").replace("%", ""))
                changes.append(pct)
            except (ValueError, KeyError):
                pass
        if changes:
            avg = sum(changes) / len(changes)
            color = 0x2ECC71 if avg > 0 else 0xE74C3C if avg < 0 else 0x808080

        return {
            "title": f"📊 {report_name}レポート",
            "description": date_str,
            "color": color,
            "fields": fields,
            "footer": {"text": "AI株式アシスタント"},
        }

    async def send_stock_report(self, text: str, report_name: str, indices: dict):
        """Embedヘッダーをチャンネルに投稿し、詳細本文はスレッド内に投稿する"""
        if not self.webhook_url:
            logger.error("Webhook URL is not set.")
            return

        logger.info(f"Sending message to Webhook... Length: {len(text)}")
        session = await self._get_webhook_session()
        webhook = discord.Webhook.from_url(self.webhook_url, session=session)
        webhook_user = "AI株式アシスタント"
        avatar_url = "https://img.icons8.com/color/96/bullish.png"

        # 1. Embedヘッダーをチャンネルに送信（wait=True でメッセージを取得）
        embed_dict = self._build_header_embed(report_name, indices)
        embed_obj = discord.Embed.from_dict(embed_dict)
        try:
            header_msg = await webhook.send(
                embed=embed_obj,
                username=webhook_user,
                avatar_url=avatar_url,
                wait=True,
            )
        except Exception as e:
            logger.error(f"Failed to post embed to webhook: {e}")
            # Embed送信失敗時はスレッドなしでフォールバック
            await self._send_chunks_flat(webhook, text, webhook_user, avatar_url)
            return

        # 2. Embedメッセージからスレッドを作成
        now = datetime.now(TZ_JST)
        thread_name = f"📊 {report_name} {now.strftime('%m/%d')}"
        try:
            channel = self.bot.get_channel(header_msg.channel.id)
            if channel is None:
                channel = await self.bot.fetch_channel(header_msg.channel.id)
            thread = await channel.create_thread(
                name=thread_name,
                message=header_msg,
                auto_archive_duration=1440,  # 24時間で自動アーカイブ
            )
        except Exception as e:
            logger.warning(f"Failed to create thread, falling back to flat: {e}")
            await self._send_chunks_flat(webhook, text, webhook_user, avatar_url)
            return

        # 3. 本文テキストをスレッド内にチャンク送信
        await asyncio.sleep(1)
        chunks = self._chunk_message(text, 1900)
        for i, chunk in enumerate(chunks):
            content = f"(続き {i + 1})\n{chunk}" if i > 0 else chunk
            for retry in range(3):  # 最大3回リトライ
                try:
                    await webhook.send(
                        content=content,
                        username=webhook_user,
                        avatar_url=avatar_url,
                        thread=thread,
                        wait=True,
                    )
                    break  # 送信成功
                except discord.HTTPException as e:
                    if e.status == 429 and retry < 2:
                        retry_after = getattr(e, "retry_after", 2)
                        logger.warning(f"Rate limited. Waiting {retry_after}s... (retry {retry + 1})")
                        await asyncio.sleep(retry_after)
                    else:
                        logger.error(f"Webhook error in thread: {e}")
                        break
                except Exception as e:
                    logger.error(f"Failed to post to thread: {e}")
                    break

            if i < len(chunks) - 1:
                await asyncio.sleep(1)

    async def _send_chunks_flat(self, webhook: discord.Webhook, text: str,
                                username: str, avatar_url: str):
        """スレッド作成失敗時のフォールバック: チャンネルに直接チャンク送信"""
        chunks = self._chunk_message(text, 1900)
        for i, chunk in enumerate(chunks):
            content = f"(続き {i + 1})\n{chunk}" if i > 0 else chunk
            for retry in range(3):
                try:
                    await webhook.send(
                        content=content,
                        username=username,
                        avatar_url=avatar_url,
                        wait=True,
                    )
                    break
                except discord.HTTPException as e:
                    if e.status == 429 and retry < 2:
                        retry_after = getattr(e, "retry_after", 2)
                        logger.warning(f"Rate limited (flat). Waiting {retry_after}s... (retry {retry + 1})")
                        await asyncio.sleep(retry_after)
                    else:
                        logger.error(f"Flat send error: {e}")
                        break
                except Exception as e:
                    logger.error(f"Flat send error: {e}")
                    break
            if i < len(chunks) - 1:
                await asyncio.sleep(1)

    def _chunk_message(self, text: str, max_length: int) -> list[str]:
        chunks = []
        lines = text.split('\n')
        current_chunk = ""

        for line in lines:
            # 単一行がmax_lengthを超える場合は文字数で強制分割
            if len(line) > max_length:
                if current_chunk:
                    chunks.append(current_chunk)
                    current_chunk = ""
                for j in range(0, len(line), max_length):
                    chunks.append(line[j:j + max_length])
                continue

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
        logger.error(f"{func_name}: {traceback.format_exc()}")

        # Discordにはエラー種別と概要を送信（パスやモジュール名を露出しない）
        error_type = type(error).__name__
        error_details = ""

        # HttpError の場合は詳細情報を抽出
        if error_type == "HttpError" and hasattr(error, 'resp') and hasattr(error, 'content'):
            try:
                import json
                status = error.resp.status
                reason = error.resp.reason
                content = json.loads(error.content.decode('utf-8'))
                message = content.get('error', {}).get('message', str(error))
                error_details = f"\n**詳細:** {status} {reason}\n**メッセージ:** {message}"
            except Exception:
                error_details = f"\n**詳細:** {str(error)}"
        else:
            # TypeError, ValueError 等すべてのエラーでメッセージを表示
            error_msg = str(error)
            if error_msg:
                error_details = f"\n**メッセージ:** {error_msg}"

        text = f"🚨 **Stock Report Error** 🚨\n**処理:** {func_name}\n**種別:** {error_type}{error_details}\n詳細はサーバーログを確認してください。"

        if self.webhook_url:
            try:
                session = await self._get_webhook_session()
                webhook = discord.Webhook.from_url(self.webhook_url, session=session)
                await webhook.send(content=text, username="エラー監視")
            except Exception as push_err:
                logger.error(f"Failed to push error log to webhook: {push_err}")

async def setup(bot):
    await bot.add_cog(StockReportCog(bot))
