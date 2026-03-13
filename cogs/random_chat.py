import random
import asyncio
import logging
from discord.ext import commands, tasks
from datetime import datetime as dt

from config.characters import CHARACTERS
from config.stock_config import TZ_JST
from services.gemini_service import GeminiService
from services.webhook_service import send_as_character

logger = logging.getLogger(__name__)


class RandomChatCog(commands.Cog):
    """ランダム雑談機能を担当するCog"""

    def __init__(self, bot):
        self.bot = bot
        self.gemini = GeminiService(bot.gemini_api_key)

        # Bot初期化時にSecret Managerから取得済みのチャンネルIDを使用
        self.channel_id = bot.channel_id

        # ランダム雑談で今日すでに話しかけたキャラを記録
        self._today_chatted = set()  # キャラ名のセット
        self._today_date = None      # 日付追跡用

        # ランダム雑談タスクの開始
        self.random_chat.start()

    def cog_unload(self):
        self.random_chat.cancel()

    # --- ランダム雑談（キャラクターが自発的に話しかける） ---

    @tasks.loop(minutes=90)
    async def random_chat(self):
        """ランダムなタイミングでキャラクターが自発的に話しかける（8〜21時JST限定）"""
        # ループ間隔にジッター（0〜30分）を追加して機械的にならないようにする
        jitter = random.randint(0, 30 * 60)
        await asyncio.sleep(jitter)

        if not self.channel_id:
            return

        # 現在のJST時刻を取得
        now_jst = dt.now(TZ_JST)

        # 8:00〜21:00 の範囲外なら何もしない
        if not (8 <= now_jst.hour < 21):
            logger.info(f"[ランダム雑談] 時間外のためスキップ ({now_jst.strftime('%H:%M')})")
            return

        # 日付が変わったら記録をリセット
        today = now_jst.date()
        if self._today_date != today:
            self._today_chatted = set()
            self._today_date = today

        # 30%の確率で発火
        if random.random() > 0.30:
            return

        # まだ今日話していないキャラだけを候補にする
        available_chars = [
            c for c in CHARACTERS.values()
            if c["name"] not in self._today_chatted
        ]
        if not available_chars:
            logger.info("[ランダム雑談] 全キャラが今日すでに発言済み。スキップ。")
            return

        # ランダムにキャラクターを1人選ぶ
        char_data = random.choice(available_chars)
        logger.info(f"[ランダム雑談] {char_data['name']} が話しかけます...")

        channel = self.bot.get_channel(self.channel_id)
        if not channel:
            return

        try:
            # キャラの担当ジャンルで最新の話題を検索して雑談メッセージを生成
            response = await self.gemini.generate_random_chat(
                personality=char_data["personality"],
                topics=char_data["description"]
            )

            if not response:
                logger.info(f"[ランダム雑談] {char_data['name']} の雑談生成に失敗。スキップ。")
                return

            await send_as_character(channel, char_data, response, wait=True)

            # 今日発言済みとして記録
            self._today_chatted.add(char_data["name"])

        except Exception as e:
            logger.error(f"[ランダム雑談] エラー: {e}")

    @random_chat.before_loop
    async def before_random_chat(self):
        await self.bot.wait_until_ready()
        # 起動直後に発火しないよう、少し待つ
        await asyncio.sleep(300)  # 5分待機


async def setup(bot):
    await bot.add_cog(RandomChatCog(bot))
