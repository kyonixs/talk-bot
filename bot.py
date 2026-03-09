import os
import discord
from discord.ext import commands
from services.secret_service import get_secret

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
        
        # Secret ManagerからAPIキー類を取得
        print("Fetching secrets from GCP Secret Manager...")
        self.gemini_api_key = get_secret("GEMINI_API_KEY_SECRET")
        self.gemini_api_key_stock = get_secret("GEMINI_API_KEY_STOCK")
        self.discord_webhook_stock = get_secret("DISCORD_WEBHOOK_STOCK")

    async def setup_hook(self):
        # 起動時にCogを読み込む
        cogs = ["cogs.news", "cogs.chat", "cogs.stock_report"]
        for cog in cogs:
            try:
                await self.load_extension(cog)
                print(f"Loaded extension: {cog}")
            except Exception as e:
                print(f"Failed to load extension {cog}: {e}")

    async def on_ready(self):
        print(f"Logged in as {self.user} (ID: {self.user.id})")
        print("------")
        # 起動ステータスの設定
        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="!help"))

if __name__ == "__main__":
    
    print("Initializing bot...")
    discord_token = get_secret("DISCORD_TOKEN_SECRET")
    
    bot = NewsBot()
    bot.run(discord_token)
