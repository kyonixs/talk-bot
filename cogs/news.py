import os
import discord
from discord.ext import commands, tasks
import datetime

from config.characters import CHARACTERS
from services.gemini_service import GeminiService

class NewsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.gemini = GeminiService(bot.gemini_api_key)
        
        # 環境変数からチャンネルIDを取得
        self.channel_id = int(os.getenv("CHANNEL_ID", 0))
        
        # TZを考慮したスケジュール設定用の時刻オブジェクトを作成
        self.tz = datetime.timezone(datetime.timedelta(hours=9)) # JST固定で扱う
        
        # 定時実行タスクの開始
        self.scheduled_news.start()

    def cog_unload(self):
        self.scheduled_news.cancel()

    @tasks.loop(time=[
        datetime.time(hour=8, minute=0, tzinfo=datetime.timezone(datetime.timedelta(hours=9))),
        datetime.time(hour=18, minute=0, tzinfo=datetime.timezone(datetime.timedelta(hours=9)))
    ])
    async def scheduled_news(self):
        """毎日朝8時と夕方18時に定時実行されるタスク"""
        await self.bot.wait_until_ready()
        print(f"[{datetime.datetime.now()}] 定時ニュース配信を開始します...")
        
        if not self.channel_id:
            print("CHANNEL_IDが設定されていません。")
            return
            
        channel = self.bot.get_channel(self.channel_id)
        if not channel:
            print(f"チャンネルID {self.channel_id} が見つかりませんでした。")
            return
            
        await self._send_all_characters_news(channel)
        
    @scheduled_news.before_loop
    async def before_scheduled_news(self):
        await self.bot.wait_until_ready()

    @commands.command(name="news")
    async def force_news(self, ctx):
        """手動で全キャラのニュースを配信するコマンド (!news)"""
        await ctx.send("📡 ニュースを取得してくるからちょっと待ってね！")
        
        await self._send_all_characters_news(ctx.channel)
        
        await ctx.send("✅ 配信完了！スレッドで話しかけてみてね！")

    async def _send_all_characters_news(self, channel):
        """全キャラクター分のニュースを取得し、チャンネルに投稿してスレッドを作成する"""
        for char_key, char_data in CHARACTERS.items():
            try:
                # ニュース生成（API呼び出しは同期的に行われるため、順次実行）
                print(f"[{char_data['name']}] 担当ジャンルのニュースを生成中...")
                content = await self.gemini.generate_news(
                    personality=char_data["personality"],
                    topics=char_data["description"]
                )
                
                # Embedの作成
                # Embed の description は4096文字制限
                if len(content) > 4096:
                    content = content[:4093] + "..."

                embed = discord.Embed(
                    description=content,
                    color=char_data["color"],
                    timestamp=discord.utils.utcnow()
                )
                
                embed.set_author(name=f"{char_data['name']}（{char_data['role']}）")
                embed.set_footer(text=f"担当: {char_data['description']}")
                
                # チャンネルへの送信とスレッドの自動作成
                message = await channel.send(embed=embed)
                
                # スレッド名の生成 (例: "タケシのニュース討論会")
                thread_name = f"{char_data['name']}と話す💭"
                
                await message.create_thread(
                    name=thread_name,
                    auto_archive_duration=1440 # 24時間
                )
                
            except Exception as e:
                print(f"[{char_key}] ニュース配信中にエラーが発生しました: {e}")
                
async def setup(bot):
    await bot.add_cog(NewsCog(bot))
