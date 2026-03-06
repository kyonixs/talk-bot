import os
import random
import asyncio
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
        self.tz = datetime.timezone(datetime.timedelta(hours=9))  # JST固定

        # ランダム雑談で今日すでに話しかけたキャラを記録
        self._today_chatted = set()  # キャラ名のセット
        self._today_date = None      # 日付追跡用

        # 定時実行タスクの開始
        self.scheduled_news.start()
        self.random_chat.start()

    def cog_unload(self):
        self.scheduled_news.cancel()
        self.random_chat.cancel()

    async def _get_or_create_webhook(self, channel):
        """チャンネルに紐づくWebhookを取得（なければ作成）"""
        webhooks = await channel.webhooks()
        webhook = discord.utils.get(webhooks, name="NewsBotWebhook")
        if not webhook:
            webhook = await channel.create_webhook(name="NewsBotWebhook")
        return webhook

    async def _send_via_webhook(self, channel, character: dict, content: str):
        """Webhookを使用してキャラクターになりすましてメッセージを送信する"""
        try:
            webhook = await self._get_or_create_webhook(channel)
            icon_url = character.get("icon_url", None)

            # 2000文字制限に対応
            chunks = [content[i:i + 2000] for i in range(0, len(content), 2000)]
            sent_message = None
            for chunk in chunks:
                sent_message = await webhook.send(
                    content=chunk,
                    username=character["name"],
                    avatar_url=icon_url,
                    wait=True  # メッセージオブジェクトを返す（スレッド作成用）
                )
            return sent_message
        except Exception as e:
            print(f"Webhook send error: {e}")
            return None

    # --- 定時ニュース配信（毎日 8:00 / 18:00 JST） ---

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

    # --- ランダム雑談（キャラクターが自発的に話しかける） ---

    @tasks.loop(minutes=90)
    async def random_chat(self):
        """ランダムなタイミングでキャラクターが自発的に話しかける（8〜21時JST限定）"""
        await self.bot.wait_until_ready()

        if not self.channel_id:
            return

        # 現在のJST時刻を取得
        now_jst = datetime.datetime.now(self.tz)

        # 8:00〜21:00 の範囲外なら何もしない
        if not (8 <= now_jst.hour < 21):
            print(f"[ランダム雑談] 時間外のためスキップ ({now_jst.strftime('%H:%M')})")
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
            print("[ランダム雑談] 全キャラが今日すでに発言済み。スキップ。")
            return

        # ランダムにキャラクターを1人選ぶ
        char_data = random.choice(available_chars)
        print(f"[ランダム雑談] {char_data['name']} が話しかけます...")

        channel = self.bot.get_channel(self.channel_id)
        if not channel:
            return

        try:
            # 雑談用のプロンプト（自然な口調を誘導）
            prompts = [
                "「そういえばさ〜」みたいな感じで、最近気になったことや面白い話を友達にふと話しかけるように1〜2文（80文字以内）で書いて。ニュース紹介ではなく日常のひとこと。",
                "「ちょっと聞いてよ〜」みたいなノリで、友達のグループチャットにふと思いついたことを投げかけるように1〜2文（80文字以内）で書いて。",
                "「ねぇ知ってる？」みたいな感じで、最近知ったこととか気になってることを友達に軽く共有するように1〜2文（80文字以内）で書いて。",
                "「あ〜暇だな〜」みたいなテンションで、友達にどうでもいい雑談を振るような1〜2文（80文字以内）を書いて。",
            ]
            prompt = random.choice(prompts)

            response = await self.gemini.generate_chat_response(
                personality=char_data["personality"],
                chat_history=[],
                user_message=prompt
            )

            await self._send_via_webhook(channel, char_data, response)

            # 今日発言済みとして記録
            self._today_chatted.add(char_data["name"])

        except Exception as e:
            print(f"[ランダム雑談] エラー: {e}")

    @random_chat.before_loop
    async def before_random_chat(self):
        await self.bot.wait_until_ready()
        # 起動直後に発火しないよう、少し待つ
        await asyncio.sleep(300)  # 5分待機

    # --- コマンド ---

    @commands.command(name="news")
    async def force_news(self, ctx):
        """手動で全キャラのニュースを配信するコマンド (!news)"""
        await ctx.send("📡 ニュースを取得してくるからちょっと待ってね！")
        await self._send_all_characters_news(ctx.channel)

    # --- 内部メソッド ---

    async def _send_all_characters_news(self, channel):
        """全キャラクター分のニュースを取得し、Webhook経由で投稿してスレッドを作成する"""
        for char_key, char_data in CHARACTERS.items():
            try:
                print(f"[{char_data['name']}] 担当ジャンルのニュースを生成中...")
                content = await self.gemini.generate_news(
                    personality=char_data["personality"],
                    topics=char_data["description"]
                )

                # Webhook経由でキャラクターとして送信
                sent_message = await self._send_via_webhook(channel, char_data, content)

                # スレッドの自動作成
                if sent_message:
                    thread_name = f"{char_data['name']}と話す💭"
                    await sent_message.create_thread(
                        name=thread_name,
                        auto_archive_duration=1440  # 24時間
                    )

            except Exception as e:
                print(f"[{char_key}] ニュース配信中にエラーが発生しました: {e}")


async def setup(bot):
    await bot.add_cog(NewsCog(bot))
