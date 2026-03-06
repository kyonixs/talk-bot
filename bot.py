import os
import discord
from discord.ext import commands
from dotenv import load_dotenv

# .envファイルの読み込み
load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise ValueError("DISCORD_TOKEN is not set. Please check your .env file.")

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
            help_command=commands.DefaultHelpCommand()
        )
        # 汎用的にアクセスできるようにServiceをここに持たせることも可能だが、
        # 今回はCog内でインスタンス化/共有する構成にする

    async def setup_hook(self):
        # 起動時にCogを読み込む
        cogs = ["cogs.news", "cogs.chat"]
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
    bot = NewsBot()
    bot.run(DISCORD_TOKEN)
