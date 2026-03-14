import logging
import discord
from discord.ext import commands
from services.secret_service import get_secret

# ログ設定（全モジュール共通）
logging.basicConfig(
    level=logging.INFO,
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

if __name__ == "__main__":
    logger.info("Initializing bot...")
    discord_token = get_secret("DISCORD_BOT_TOKEN")

    bot = NewsBot()
    bot.run(discord_token, log_handler=None)  # discord.pyの重複ログハンドラを無効化
