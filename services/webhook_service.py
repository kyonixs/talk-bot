import logging
import discord

logger = logging.getLogger(__name__)

# チャンネルID → Webhook のキャッシュ（プロセス内で再利用）
_webhook_cache: dict[int, discord.Webhook] = {}


async def get_or_create_webhook(channel: discord.TextChannel, webhook_name: str = "NewsBotWebhook") -> discord.Webhook:
    """チャンネルに紐づくWebhookを取得（なければ作成）。キャッシュ済みなら再利用。"""
    cached = _webhook_cache.get(channel.id)
    if cached is not None:
        return cached

    webhooks = await channel.webhooks()
    webhook = discord.utils.get(webhooks, name=webhook_name)
    if not webhook:
        webhook = await channel.create_webhook(name=webhook_name)

    _webhook_cache[channel.id] = webhook
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

        # チャット応答は2000文字で切り詰め（長文のチャンク分割はstock_report側で管理）
        truncated = content[:2000] if len(content) > 2000 else content
        sent_message = await webhook.send(
            content=truncated,
            username=character["name"],
            avatar_url=icon_url,
            thread=thread,
            wait=wait,
        )
        return sent_message

    except discord.Forbidden:
        logger.warning("Webhook permission denied (Forbidden). Falling back to normal reply.")
        return None
    except discord.NotFound:
        # Webhookが削除された可能性 → キャッシュを無効化して次回再取得
        _webhook_cache.pop(target_channel.id, None)
        logger.warning("Webhook not found (deleted?). Falling back to normal reply.")
        return None
    except Exception as e:
        logger.error(f"Webhook send error: {type(e).__name__}: {e}")
        return None
