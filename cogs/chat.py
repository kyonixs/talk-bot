import discord
from discord.ext import commands
from collections import defaultdict

from config.characters import CHARACTERS
from services.gemini_service import GeminiService

class ChatCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.gemini = GeminiService()
        
        # 会話履歴を保持するインメモリ辞書
        # キー: thread_id または channel_id
        # 値: [{"role": "user" or "model", "content": "..."}] のリスト
        # 最大保持ターン数は設定で決める(例: 5件〜10件)
        self.history = defaultdict(list)
        self.MAX_HISTORY = 5

    def _get_target_character(self, message_content: str, thread_name: str = ""):
        """メッセージ内容またはスレッド名からキャラクターを特定する"""
        
        # 1. スレッド名からの推測 (定時配信で作られたスレッドを想定)
        for char_key, char_data in CHARACTERS.items():
            if char_data["name"] in thread_name:
                return char_data
                
        # 2. メッセージ内でのメンション/名前指定からの推測
        for char_key, char_data in CHARACTERS.items():
            if char_data["name"] in message_content:
                return char_data
                
        # デフォルトはランダム、または特定のキャラ？
        # 指定がない場合はとりあえずタケシを返す（一番上で雑な対応が似合うキャラ）
        return CHARACTERS["タケシ"]

    @commands.Cog.listener()
    async def on_message(self, message):
        # Bot自身のメッセージは無視
        if message.author == self.bot.user:
            return

        # コマンドの場合はここで処理しない
        if message.content.startswith(self.bot.command_prefix):
            return

        is_in_thread = isinstance(message.channel, discord.Thread)
        is_mentioned = self.bot.user in message.mentions
        
        # Botへのメンション、もしくはBotが作成したスレッド内のメッセージに反応する
        should_reply = is_mentioned or (
            is_in_thread and 
            message.channel.owner_id == self.bot.user.id
        )

        if not should_reply:
            return

        thread_name = message.channel.name if is_in_thread else ""
        content_clean = message.clean_content.replace(f"@{self.bot.user.display_name}", "").strip()
        
        if not content_clean:
            return

        # キャラクターの特定
        target_char = self._get_target_character(content_clean, thread_name)
        
        # 会話コンテキストの管理キー
        context_key = message.channel.id
        
        async with message.channel.typing():
            try:
                # ユーザーメッセージを履歴に追加
                self.history[context_key].append({"role": "user", "content": content_clean})
                
                # Geminiから返答を取得
                response_text = await self.gemini.generate_chat_response(
                    personality=target_char["personality"],
                    chat_history=self.history[context_key][:-1], # 最新のユーザーメッセージは除いて渡す（内部で追加するため）
                    user_message=content_clean
                )
                
                # モデルの応答を履歴に追加
                self.history[context_key].append({"role": "model", "content": response_text})
                
                # 履歴が長すぎる場合は古いものを削除
                if len(self.history[context_key]) > self.MAX_HISTORY * 2: # user+modelで2件ずつ増えるため
                    self.history[context_key] = self.history[context_key][-self.MAX_HISTORY * 2:]
                    
                await message.reply(response_text)
                
            except Exception as e:
                print(f"Chat Cog Error: {e}")
                await message.reply(f"ごめん、今ちょっと返事ができないみたい… (Error: {str(e)[:50]})")

    @commands.command(name="ask")
    async def ask_command(self, ctx, char_name: str, *, question: str):
        """特定のキャラに質問する (!ask キャラ名 質問)"""
        if char_name not in CHARACTERS:
            names = ", ".join(CHARACTERS.keys())
            await ctx.send(f"⚠️ そのキャラはいないよ。選べるのはこれ: {names}")
            return
            
        target_char = CHARACTERS[char_name]
        
        async with ctx.typing():
            try:
                # Askコマンドの場合は文脈を引き継がない単発の処理とする設定
                response_text = await self.gemini.generate_chat_response(
                    personality=target_char["personality"],
                    chat_history=[],
                    user_message=question
                )
                await ctx.send(response_text)
            except Exception as e:
                print(f"Ask Command Error: {e}")
                await ctx.send("ごめん、今システムエラーみたい。")

async def setup(bot):
    await bot.add_cog(ChatCog(bot))
