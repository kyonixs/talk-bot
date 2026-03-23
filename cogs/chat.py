import asyncio
import time
import logging
import discord
from discord.ext import commands
from collections import OrderedDict

from config.characters import CHARACTERS, CHARACTER_ALIASES
from services.gemini_service import GeminiService
from services.webhook_service import send_as_character

logger = logging.getLogger(__name__)

# 同一ユーザーからの連続リクエストを抑制する間隔（秒）
_COOLDOWN_SECONDS = 3


class ChatCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.gemini = GeminiService(bot.gemini_api_key)

        # 会話履歴を保持するインメモリ辞書（LRU方式で古いエントリを自動削除）
        # キー: thread_id または (channel_id, user_id)
        # 値: {"char_name": str, "messages": [{"role": "user"|"model", "content": str}, ...]}
        self.history = OrderedDict()
        self.MAX_HISTORY = 5
        self.MAX_CONTEXTS = 100  # 最大保持コンテキスト数

        # クールダウン管理: {user_id: last_response_timestamp}
        self._user_cooldowns: dict[int, float] = {}

        # [B] コンテキストキー単位のロック（同一会話で並行リクエストを防止）
        self._context_locks: dict[int | tuple, asyncio.Lock] = {}

        # [D] スレッドID → キャラクター名のキャッシュ（LRU方式、毎回Discord APIを叩かない）
        self._thread_char_cache: OrderedDict[int, dict] = OrderedDict()
        self._MAX_THREAD_CACHE = 200

    # =========================================================================
    # Concurrency Control
    # =========================================================================

    def _get_context_lock(self, context_key) -> asyncio.Lock:
        """コンテキストキー単位のロックを取得（なければ作成）"""
        if context_key not in self._context_locks:
            self._context_locks[context_key] = asyncio.Lock()
            # ロック辞書が肥大化しないよう上限管理
            if len(self._context_locks) > 200:
                unlocked = [k for k, v in self._context_locks.items() if not v.locked()]
                for k in unlocked[:50]:
                    del self._context_locks[k]
        return self._context_locks[context_key]

    # =========================================================================
    # History Management
    # =========================================================================

    def _get_history(self, context_key, char_name: str) -> list:
        """会話履歴を取得（LRU方式で管理）
        [A] キャラが変わった場合は履歴をリセットする
        """
        if context_key in self.history:
            self.history.move_to_end(context_key)
            entry = self.history[context_key]
            # キャラが変わった場合は履歴をリセット
            if entry["char_name"] != char_name:
                logger.info(f"[履歴] キャラ変更検知: {entry['char_name']} → {char_name}（履歴リセット）")
                entry["char_name"] = char_name
                entry["messages"] = []
            return entry["messages"]

        # 新規エントリ作成（上限を超えたら最も古いエントリを削除）
        if len(self.history) >= self.MAX_CONTEXTS:
            evicted_key, _ = self.history.popitem(last=False)
            logger.debug(f"[履歴] LRU削除: context_key={evicted_key}")

        self.history[context_key] = {"char_name": char_name, "messages": []}
        return self.history[context_key]["messages"]

    # =========================================================================
    # Character Detection
    # =========================================================================

    def _find_character(self, name: str, prefix_only: bool = False):
        """別名マッピングからキャラクターを検索

        prefix_only=True の場合、メッセージ先頭にキャラ名がある場合のみマッチ
        （メッセージ中の誤判定を防ぐ）
        """
        # 完全一致
        if name in CHARACTER_ALIASES:
            return CHARACTER_ALIASES[name]
        if prefix_only:
            # メッセージ先頭のキャラ名指定のみマッチ（例: "タケシ 今日のニュースは？"）
            for alias, char_data in CHARACTER_ALIASES.items():
                if name.startswith(alias):
                    return char_data
        else:
            # 部分一致（スレッド名など短いテキスト向け）
            for alias, char_data in CHARACTER_ALIASES.items():
                if alias in name:
                    return char_data
        return None

    async def _find_character_from_thread(self, thread: discord.Thread) -> dict | None:
        """スレッド内の直近Webhookメッセージからキャラクターを特定する
        [D] キャッシュ済みならAPI呼び出しをスキップ
        """
        # キャッシュチェック
        cached = self._thread_char_cache.get(thread.id)
        if cached is not None:
            return cached

        try:
            async for msg in thread.history(limit=20):
                if msg.webhook_id:
                    char = self._find_character(msg.author.display_name)
                    if char:
                        logger.debug(f"[スレッドキャラ特定] {char['name']} をWebhook履歴から検出")
                        self._thread_char_cache[thread.id] = char
                        self._thread_char_cache.move_to_end(thread.id)
                        # LRU方式: 上限を超えたら最も古いエントリを削除
                        while len(self._thread_char_cache) > self._MAX_THREAD_CACHE:
                            self._thread_char_cache.popitem(last=False)
                        return char
        except Exception as e:
            logger.warning(f"[スレッドキャラ特定] 履歴取得エラー: {e}")
        return None

    async def _get_referenced_message(self, message: discord.Message) -> discord.Message | None:
        """返信先メッセージを取得する（キャッシュ済みならそれを使用）"""
        if not message.reference or not message.reference.message_id:
            return None
        try:
            ref_msg = message.reference.resolved
            if ref_msg is None:
                ref_msg = await message.channel.fetch_message(message.reference.message_id)
            return ref_msg
        except Exception as e:
            logger.warning(f"[返信先取得] エラー: {e}")
            return None

    async def _build_reply_chain(self, message: discord.Message, limit: int = 5) -> list[dict]:
        """返信チェーンを遡って会話履歴を構築する。
        Discord の返信チェーン（A→B→C→...）を辿り、
        Webhook(キャラ)=model / ユーザー=user として時系列順の履歴を返す。
        """
        chain = []
        current = message

        for _ in range(limit):
            ref = await self._get_referenced_message(current)
            if not ref or not ref.content:
                break
            role = "model" if ref.webhook_id else "user"
            chain.append({"role": role, "content": ref.content})
            current = ref

        chain.reverse()  # 古い順にする
        logger.debug(f"[返信チェーン] 深さ={len(chain)} (limit={limit})")
        return chain

    async def _get_target_character(self, message_content: str, thread_name: str = "",
                                    thread: discord.Thread = None,
                                    ref_msg: discord.Message | None = None):
        """メッセージ内容またはスレッド名からキャラクターを特定する
        [B] ref_msg は呼び出し元で1回だけ取得して渡す
        """
        # 1. 返信先のWebhookメッセージからキャラクターを最優先で特定
        #    （ランダム雑談等のWebhook発言に返信した場合、そのキャラが応答すべき）
        if ref_msg is not None and ref_msg.webhook_id:
            char = self._find_character(ref_msg.author.display_name)
            if char:
                logger.debug(f"[返信先キャラ特定] {char['name']} を返信先Webhookから検出")
                return char

        # 2. スレッド内ではWebhook履歴からキャラクターを特定
        #    （キャラのWebhook発言が存在するスレッドでは、そのキャラが応答すべき）
        if thread is not None:
            char = await self._find_character_from_thread(thread)
            if char:
                return char

        # 3. スレッド名からの推測 (定時配信で作られたスレッドを想定)
        if thread_name:
            char = self._find_character(thread_name)
            if char:
                return char

        # 4. メッセージ先頭でのキャラ名指定からの推測（チャンネル直書き用）
        #    先頭一致のみにして、本文中の偶然の一致を防ぐ
        if message_content:
            char = self._find_character(message_content, prefix_only=True)
            if char:
                return char

        # 5. 指定がない場合はAIルーターによる自動振り分け
        routed_name = await self.gemini.determine_character(message_content)
        char = self._find_character(routed_name)
        if char:
            return char

        # フォールバック
        logger.info("[キャラ特定] 全手段で特定できず → デフォルト(タケシ)")
        return CHARACTERS["タケシ"]

    # =========================================================================
    # Message Handler
    # =========================================================================

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

        target_channel_id = self.bot.channel_id
        is_in_target_channel = message.channel.id == target_channel_id if not is_in_thread else message.channel.parent_id == target_channel_id

        # 対象チャンネル（直書き含む）、スレッド内、またはメンションされたら反応
        should_reply = is_mentioned or is_in_target_channel or (
            is_in_thread and
            message.channel.owner_id == self.bot.user.id
        )

        if not should_reply:
            return

        # クールダウンチェック（同一ユーザーからの連続リクエストを抑制）
        now = time.time()
        last_time = self._user_cooldowns.get(message.author.id, 0)
        if now - last_time < _COOLDOWN_SECONDS:
            return
        self._user_cooldowns[message.author.id] = now

        # 古いクールダウンエントリを定期的に掃除（100件超過時）
        if len(self._user_cooldowns) > 100:
            expired = [uid for uid, ts in self._user_cooldowns.items() if now - ts > 60]
            for uid in expired:
                del self._user_cooldowns[uid]

        thread_name = message.channel.name if is_in_thread else ""
        content_clean = message.clean_content.replace(f"@{self.bot.user.display_name}", "").strip()

        if not content_clean:
            return

        # [B] 返信先メッセージを1回だけ取得（キャラ特定 + コンテキスト注入で共有）
        ref_msg = await self._get_referenced_message(message)

        # キャラクターの特定（返信先Webhook → スレッド履歴 → AI Router の優先順）
        thread_obj = message.channel if is_in_thread else None
        target_char = await self._get_target_character(
            content_clean, thread_name, thread=thread_obj, ref_msg=ref_msg
        )

        # 会話コンテキストの管理キー
        # スレッド内: スレッドID（同一スレッド内で会話を共有）
        # チャンネル直書き（メンション）: チャンネルID + ユーザーID（ユーザーごとに分離）
        context_key = message.channel.id if is_in_thread else (message.channel.id, message.author.id)

        # [B] 同一コンテキスト内のリクエストを直列化（応答順序の保証）
        lock = self._get_context_lock(context_key)
        async with lock:
            # 返信チェーンがある場合: チェーンから会話履歴を構築（正確な文脈）
            # 返信なしの場合: 蓄積履歴を使用（従来通り）
            logger.debug(f"[会話] char={target_char['name']}, ref={'あり' if ref_msg else 'なし'}, ctx={context_key}")
            if ref_msg:
                chat_history = await self._build_reply_chain(message)
            else:
                chat_history = self._get_history(context_key, target_char["name"])

            async with message.channel.typing():
                try:
                    # Geminiから返答を取得
                    response_text = await self.gemini.generate_chat_response(
                        personality=target_char["personality"],
                        chat_history=chat_history,
                        user_message=content_clean
                    )

                    # 蓄積履歴にも追加（返信なしの後続メッセージ用）
                    stored_history = self._get_history(context_key, target_char["name"])
                    stored_history.append({"role": "user", "content": content_clean})
                    stored_history.append({"role": "model", "content": response_text})

                    # 履歴が長すぎる場合は古いものを削除
                    if len(stored_history) > self.MAX_HISTORY * 2:
                        del stored_history[:len(stored_history) - self.MAX_HISTORY * 2]

                    # Webhookでなりすまし送信
                    result = await send_as_character(message.channel, target_char, response_text)
                    if result is None:
                        logger.warning("send_as_character returned None, using fallback reply.")
                        await message.reply(response_text[:2000])

                except asyncio.TimeoutError:
                    logger.warning(f"Chat Cog Timeout: Gemini API did not respond in time")
                    await message.reply("ちょっと考え込んじゃった…もう一回聞いて！")
                except Exception as e:
                    logger.error(f"Chat Cog Error: {e}")
                    await message.reply("ごめん、今ちょっと返事ができないみたい…")

    # =========================================================================
    # Commands
    # =========================================================================

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
                # Webhookでなりすまし送信（失敗時は通常sendにフォールバック）
                result = await send_as_character(ctx.channel, target_char, response_text)
                if result is None:
                    await ctx.send(response_text[:2000])
            except Exception as e:
                logger.error(f"Ask Command Error: {e}")
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
                "`!ask {キャラ名} {質問}` — 特定のキャラに質問\n"
                "`!help` — このヘルプを表示"
            ),
            inline=False
        )

        embed.add_field(
            name="話しかけ方",
            value=(
                "- チャンネル内で自由に発言 → AIが最適なキャラを自動選択\n"
                "- スレッド内で返信 → そのスレッドのキャラが応答\n"
                "- Botをメンションして話しかける"
            ),
            inline=False
        )

        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(ChatCog(bot))
