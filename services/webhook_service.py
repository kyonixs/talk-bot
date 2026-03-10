import logging
import discord

logger = logging.getLogger(__name__)


async def get_or_create_webhook(channel: discord.TextChannel, webhook_name: str = "NewsBotWebhook") -> discord.Webhook:
    """チャンネルに紐づくWebhookを取得（なければ作成）"""
    webhooks = await channel.webhooks()
    webhook = discord.utils.get(webhooks, name=webhook_name)
    if not webhook:
        webhook = await channel.create_webhook(name=webhook_name)
    return webhook


async def send_as_character(
    channel: discord.abc.Messageable,
    character: dict,
    content: str,
    wait: bool = True,
) -> discord.WebhookMessage | None:
    """
    Webhookを使用してキャラクターになりすましてメッセージを送信する。
    スレッド対応済み。送信失敗時は None を返す。
    """
    target_channel = channel.parent if isinstance(channel, discord.Thread) else channel
    thread = channel if isinstance(channel, discord.Thread) else discord.utils.MISSING

    try:
        webhook = await get_or_create_webhook(target_channel)
        icon_url = character.get("icon_url")

        sent_message = None
        for i in range(0, len(content), 2000):
            sent_message = await webhook.send(
                content=content[i:i + 2000],
                username=character["name"],
                avatar_url=icon_url,
                thread=thread,
                wait=wait,
            )
        return sent_message

    except discord.Forbidden:
        logger.warning("Webhook creation forbidden. Falling back to normal reply.")
        return None
    except Exception as e:
        logger.error(f"Webhook send error: {e}")
        return None
