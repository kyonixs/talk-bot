import logging
import os
import discord
from discord.ext import commands
from services.secret_service import get_secret

# ログ設定（全モジュール共通）— 環境変数 LOG_LEVEL で切替可能（デフォルト: INFO）
_log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, _log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Intentsの設定（Message Contentが必須）
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

# Botのセットアップ
class NewsBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None
        )
        self._heartbeat_task_running = False

        # Secret Managerからシークレット・設定値を取得
        logger.info("Fetching secrets from GCP Secret Manager...")
        try:
            self.gemini_api_key = get_secret("GEMINI_API_KEY_CHAT")
            self.gemini_api_key_stock = get_secret("GEMINI_API_KEY_STOCK")
            self.discord_webhook_stock = get_secret("DISCORD_WEBHOOK_URL_STOCK")
            self.spreadsheet_id = get_secret("GOOGLE_SPREADSHEET_ID_STOCK")

            channel_id_raw = get_secret("DISCORD_CHANNEL_ID_CHAT")
            try:
                self.channel_id = int(channel_id_raw)
            except ValueError:
                raise ValueError(f"DISCORD_CHANNEL_ID_CHAT is not a valid integer: {channel_id_raw!r}")
        except Exception as e:
            logger.error(f"Failed to retrieve secrets: {e}")
            raise

        # Anthropic APIキー（任意）— 未設定時はGeminiのみで動作
        try:
            self.anthropic_api_key = get_secret("ANTHROPIC_API_KEY_STOCK")
            logger.info("ANTHROPIC_API_KEY_STOCK loaded (2-stage pipeline available)")
        except Exception:
            logger.warning("ANTHROPIC_API_KEY_STOCK not found in Secret Manager, Claude features disabled")
            self.anthropic_api_key = None

    async def setup_hook(self):
        # 起動時にCogを読み込む
        cogs = ["cogs.random_chat", "cogs.chat", "cogs.stock_report"]
        for cog in cogs:
            try:
                await self.load_extension(cog)
                logger.info(f"Loaded extension: {cog}")
            except Exception as e:
                logger.error(f"Failed to load extension {cog}: {e}")

    async def on_ready(self):
        logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        # 起動ステータスの設定
        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="!help"))
        # ヘルスチェック用ハートビートファイルを更新
        self._update_heartbeat()
        # 定期的にハートビートを更新するタスクを開始
        if not self._heartbeat_task_running:
            self._heartbeat_task_running = True
            self.loop.create_task(self._heartbeat_loop())

    def _update_heartbeat(self):
        """ヘルスチェック用ハートビートファイルを更新する"""
        try:
            import pathlib
            pathlib.Path("/tmp/bot_heartbeat").write_text(str(os.getpid()))
        except Exception:
            pass

    async def _heartbeat_loop(self):
        """定期的にハートビートファイルを更新（Botが接続中のみ）"""
        import asyncio
        while True:
            await asyncio.sleep(30)
            if self.is_ready() and not self.is_closed():
                self._update_heartbeat()

if __name__ == "__main__":
    logger.info("Initializing bot...")
    discord_token = get_secret("DISCORD_BOT_TOKEN")

    bot = NewsBot()
    bot.run(discord_token, log_handler=None)  # discord.pyの重複ログハンドラを無効化
