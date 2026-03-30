import asyncio
import logging
import anthropic

logger = logging.getLogger(__name__)

_CLAUDE_MODEL = "claude-sonnet-4-6"
_CLAUDE_TIMEOUT = 120  # 株式レポート生成タイムアウト（秒）


class ClaudeService:
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("API key must be provided to initialize ClaudeService.")
        self.client = anthropic.AsyncAnthropic(api_key=api_key)

    async def generate_stock_report(self, prompt_data: dict) -> dict:
        """
        株式レポート生成（推論・考察フェーズ）。
        prompt_data: {"system_instruction": str, "user_prompt": str}
        Gemini が収集したニュース事実 + 価格データを受け取り、
        理由付け・連結・アクション提案を行う。
        """
        system_instruction = prompt_data.get("system_instruction", "")
        user_prompt = prompt_data.get("user_prompt", "")

        max_retries = 3
        retry_delay = 5

        for attempt in range(max_retries):
            try:
                logger.info(
                    f"[Claude] Stock report generation "
                    f"(attempt {attempt + 1}/{max_retries}, prompt={len(user_prompt)} chars)"
                )
                message = await asyncio.wait_for(
                    self.client.messages.create(
                        model=_CLAUDE_MODEL,
                        max_tokens=8192,
                        system=system_instruction,
                        messages=[{"role": "user", "content": user_prompt}],
                    ),
                    timeout=_CLAUDE_TIMEOUT,
                )

                text = ""
                for block in message.content:
                    if hasattr(block, "text"):
                        text += block.text

                if not text.strip():
                    raise RuntimeError("Claude returned no text in response")

                is_truncated = message.stop_reason == "max_tokens"
                logger.info(f"[Claude] Report generated ({len(text)} chars, truncated={is_truncated})")
                return {"text": text.strip(), "truncated": is_truncated}

            except Exception as e:
                logger.error(f"[Claude] API Error (Attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    raise
