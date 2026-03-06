import os
import discord
from discord.ext import commands
from collections import OrderedDict

from config.characters import CHARACTERS
from services.gemini_service import GeminiService

# キャラクター名の別名マッピング（柔軟なマッチング用）
CHARACTER_ALIASES = {}
for _key, _data in CHARACTERS.items():
    name = _data["name"]
    # 正式名をそのまま登録
    CHARACTER_ALIASES[name] = _data
    # 辞書キーも登録（キーと name が異なる場合に備える）
    CHARACTER_ALIASES[_key] = _data
    # ひらがな版を登録
    _hiragana_map = {
        "タケシ": "たけし",
        "アカリ先輩": "あかり先輩",
        "ゆうた": "ゆうた",
        "れな": "れな",
    }
    if name in _hiragana_map:
        CHARACTER_ALIASES[_hiragana_map[name]] = _data


class ChatCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.gemini = GeminiService(bot.gemini_api_key)

        # 会話履歴を保持するインメモリ辞書（LRU方式で古いエントリを自動削除）
        # キー: thread_id または channel_id
        # 値: {"messages": [...], "last_used": timestamp}
        self.history = OrderedDict()
        self.MAX_HISTORY = 5
        self.MAX_CONTEXTS = 100  # 最大保持コンテキスト数

    def _get_history(self, context_key: int) -> list:
        """会話履歴を取得（LRU方式で管理）"""
        if context_key in self.history:
            self.history.move_to_end(context_key)
            return self.history[context_key]
        # 上限を超えたら最も古いエントリを削除
        if len(self.history) >= self.MAX_CONTEXTS:
            self.history.popitem(last=False)
        self.history[context_key] = []
        return self.history[context_key]

    def _find_character(self, name: str):
        """別名マッピングからキャラクターを検索"""
        # 完全一致
        if name in CHARACTER_ALIASES:
            return CHARACTER_ALIASES[name]
        # 部分一致（メッセージ内にキャラ名が含まれるケース）
        for alias, char_data in CHARACTER_ALIASES.items():
            if alias in name:
                return char_data
        return None

    async def _get_target_character(self, message_content: str, thread_name: str = ""):
        """メッセージ内容またはスレッド名からキャラクターを特定する"""

        # 1. メッセージ内での明示的なメンション/名前指定からの推測
        if message_content:
            char = self._find_character(message_content)
            if char:
                return char

        # 2. スレッド名からの推測 (定時配信で作られたスレッドを想定)
        if thread_name:
            char = self._find_character(thread_name)
            if char:
                return char

        # 3. 指定がない場合はAIルーターによる自動振り分け
        routed_name = await self.gemini.determine_character(message_content)
        char = self._find_character(routed_name)
        if char:
            return char

        # フォールバック
        return CHARACTERS["タケシ"]

    async def _send_via_webhook(self, channel, character: dict, content: str):
        """Webhookを使用してキャラクターになりすましてメッセージを送信する"""
        
        target_channel = channel.parent if isinstance(channel, discord.Thread) else channel
        thread = channel if isinstance(channel, discord.Thread) else discord.utils.MISSING
        
        try:
            webhooks = await target_channel.webhooks()
            webhook = discord.utils.get(webhooks, name="NewsBotWebhook")
            if not webhook:
                webhook = await target_channel.create_webhook(name="NewsBotWebhook")
                
            icon_url = character.get("icon_url", None)
            
            if len(content) <= 2000:
                await webhook.send(
                    content=content,
                    username=character["name"],
                    avatar_url=icon_url,
                    thread=thread
                )
            else:
                for i in range(0, len(content), 2000):
                    await webhook.send(
                        content=content[i:i + 2000],
                        username=character["name"],
                        avatar_url=icon_url,
                        thread=thread
                    )
            return True
        except discord.Forbidden:
            print("Webhook creation forbidden. Falling back to normal reply.")
            return False
        except Exception as e:
            print(f"Webhook send error: {e}")
            return False

    @commands.Cog.listener()
    async def on_message(self, message):
        # Bot自身、またはWebhookからのメッセージは無視（無限ループ防止）
        if message.author.bot or message.webhook_id:
            return

        # コマンドの場合はここで処理しない
        if message.content.startswith(self.bot.command_prefix):
            return

        is_in_thread = isinstance(message.channel, discord.Thread)
        is_mentioned = self.bot.user in message.mentions
        
        target_channel_id = int(os.getenv("CHANNEL_ID", 0))
        is_in_target_channel = message.channel.id == target_channel_id if not is_in_thread else message.channel.parent_id == target_channel_id

        # 当該チャンネルか、Bot作成スレッド内、またはメンションされたら反応
        should_reply = is_mentioned or (
            is_in_thread and
            message.channel.owner_id == self.bot.user.id
        ) or is_in_target_channel

        if not should_reply:
            return

        thread_name = message.channel.name if is_in_thread else ""
        content_clean = message.clean_content.replace(f"@{self.bot.user.display_name}", "").strip()

        if not content_clean:
            return

        # キャラクターの特定 (AI Router 経由)
        target_char = await self._get_target_character(content_clean, thread_name)

        # 会話コンテキストの管理キー
        context_key = message.channel.id
        history = self._get_history(context_key)

        async with message.channel.typing():
            try:
                # ユーザーメッセージを履歴に追加
                history.append({"role": "user", "content": content_clean})

                # Geminiから返答を取得
                response_text = await self.gemini.generate_chat_response(
                    personality=target_char["personality"],
                    chat_history=history[:-1],  # 最新のユーザーメッセージは除いて渡す
                    user_message=content_clean
                )

                # モデルの応答を履歴に追加
                history.append({"role": "model", "content": response_text})

                # 履歴が長すぎる場合は古いものを削除
                if len(history) > self.MAX_HISTORY * 2:
                    del history[:len(history) - self.MAX_HISTORY * 2]

                # Webhookでなりすまし送信
                success = await self._send_via_webhook(message.channel, target_char, response_text)
                
                # Webhookが使えない場合は通常のreplyにフォールバック
                if not success:
                    if len(response_text) <= 2000:
                        await message.reply(response_text)
                    else:
                        for i in range(0, len(response_text), 2000):
                            chunk = response_text[i:i + 2000]
                            await message.reply(chunk)

            except Exception as e:
                print(f"Chat Cog Error: {e}")
                await message.reply(f"ごめん、今ちょっと返事ができないみたい… (Error: {str(e)[:50]})")

    @commands.command(name="ask")
    async def ask_command(self, ctx, char_name: str, *, question: str):
        """特定のキャラに質問する (!ask キャラ名 質問)"""
        # 別名マッピングでキャラクターを検索
        target_char = CHARACTER_ALIASES.get(char_name)
        if not target_char:
            names = ", ".join(CHARACTERS.keys())
            await ctx.send(f"⚠️ そのキャラはいないよ。選べるのはこれ: {names}")
            return

        async with ctx.typing():
            try:
                response_text = await self.gemini.generate_chat_response(
                    personality=target_char["personality"],
                    chat_history=[],
                    user_message=question
                )
                # Webhookでなりすまし送信
                success = await self._send_via_webhook(ctx.channel, target_char, response_text)
                if not success:
                    if len(response_text) <= 2000:
                        await ctx.send(response_text)
                    else:
                        for i in range(0, len(response_text), 2000):
                            await ctx.send(response_text[i:i + 2000])
            except Exception as e:
                print(f"Ask Command Error: {e}")
                await ctx.send("ごめん、今システムエラーみたい。")

    @commands.command(name="help")
    async def help_command(self, ctx):
        """ヘルプ表示（キャラ紹介 + コマンド一覧）"""
        embed = discord.Embed(
            title="雑談ニュースBot ヘルプ",
            description="4人のキャラクターが毎日のニュースや雑談を届けてくれるよ！",
            color=0x2F3136
        )

        # キャラクター紹介
        for char_data in CHARACTERS.values():
            embed.add_field(
                name=f"{char_data['name']}（{char_data['role']}）",
                value=f"担当: {char_data['description']}",
                inline=False
            )

        # コマンド一覧
        embed.add_field(
            name="コマンド一覧",
            value=(
                "`!news` — 今すぐ全キャラのニュースを配信\n"
                "`!ask {キャラ名} {質問}` — 特定のキャラに質問\n"
                "`!help` — このヘルプを表示"
            ),
            inline=False
        )

        embed.add_field(
            name="話しかけ方",
            value=(
                "- ニュース配信チャンネル内で自由に発言 → AIが最適なキャラを自動選択\n"
                "- ニュース配信のスレッド内で返信 → そのスレッドのキャラが応答\n"
                "- Botをメンションして話しかける"
            ),
            inline=False
        )

        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(ChatCog(bot))
