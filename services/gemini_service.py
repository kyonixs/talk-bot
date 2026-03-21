import asyncio
import logging
import random
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

# Gemini APIリクエストのタイムアウト（秒）
_GEMINI_TIMEOUT_STOCK = 120  # 株式レポート（長文生成のため長め）
_GEMINI_TIMEOUT_CHAT = 30    # 雑談・会話
_GEMINI_TIMEOUT_ROUTER = 10  # ルーター（短い応答のみ）


class GeminiService:
    def __init__(self, api_key: str):
        # 実行時に渡されたAPIキーを使用して初期化する
        if not api_key:
            raise ValueError("API key must be provided to initialize GeminiService.")

        self.client = genai.Client(api_key=api_key)
        self.model_name = "gemini-2.5-flash"
        self.router_model_name = "gemini-2.0-flash-lite"  # Router用軽量モデル

    async def generate_stock_report(self, prompt_data: dict) -> dict:
        """
        株式レポート生成用。Google Search Grounding を使用。
        prompt_data: {"system_instruction": str, "user_prompt": str}
        """
        max_retries = 3
        retry_delay = 5

        system_instruction = prompt_data.get("system_instruction")
        user_prompt = prompt_data.get("user_prompt")

        for attempt in range(max_retries):
            try:
                response = await asyncio.wait_for(
                    self.client.aio.models.generate_content(
                        model=self.model_name,
                        contents=user_prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=system_instruction,
                            tools=[{"google_search": {}}],
                            temperature=0.3,
                            max_output_tokens=8192
                        )
                    ),
                    timeout=_GEMINI_TIMEOUT_STOCK,
                )

                # 重複防止: 最初のテキストパートを取得
                text = ""
                if response.candidates and response.candidates[0].content.parts:
                    for part in response.candidates[0].content.parts:
                        if part.text:
                            text = part.text.strip()
                            break
                if not text:
                    try:
                        text = response.text
                    except (ValueError, AttributeError):
                        raise RuntimeError("Gemini returned no valid text in response")

                # finish_reasonがMAX_TOKENSで途切れたか判定
                is_truncated = False
                try:
                    if response.candidates and response.candidates[0].finish_reason:
                        reason = str(response.candidates[0].finish_reason).upper()
                        if "MAX_TOKENS" in reason:
                            is_truncated = True
                except Exception:
                    pass

                return {"text": text, "truncated": is_truncated}

            except Exception as e:
                logger.error(f"Gemini API Error (Attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    raise e

    async def generate_random_chat(self, personality: str, topics: str, trending_context: str = "") -> str | None:
        """
        ランダム雑談用。Google Search Grounding で最新の話題を1つ拾い、
        友達にふと話しかけるような自然な雑談メッセージを生成する。
        trending_context が渡された場合、バズっている話題を優先的に選ぶ。
        """
        prompt_parts = [
            f"今日は日本の現在の日付です。Google検索を使って、以下のトピックに関連する最新の話題やニュースを1つだけ調べてください:\n"
            f"{topics}\n"
        ]

        if trending_context:
            prompt_parts.append(
                f"\n以下は今まさにネットでバズっている話題のリストです。"
                f"この中から、あなたの担当ジャンル（{topics}）に関係するものを1つ選んで話題にしてください。"
                f"リストにピッタリなものがなければ、Google検索で見つけた別の話題でもOKです:\n\n"
                f"{trending_context}\n"
            )

        prompt_parts.append(
            "\n調べた結果をもとに、友達のグループチャットにふと話しかけるような自然な雑談メッセージを書いてください。\n"
            "ルール:\n"
            "- ネタは1つだけピックアップする\n"
            "- 「そういえばさ〜」「ちょっと聞いてよ」「ねぇ知ってる？」のような自然な切り出し方をする\n"
            "- 「今日のニュースは」「本日のトピックは」のようなアナウンサー的な言い回しは絶対に使わない\n"
            "- 友達にLINEで話しかけるようなテンポ感で、1〜3文で書く\n"
            "- **全体で100〜200文字に収めること（厳守）**\n"
            "- URLは不要。つけない\n"
            "- ニュースの正確性は調べた結果に忠実にすること\n"
            "- できるだけ「今バズっている」「みんな話題にしている」系のホットな話題を選ぶこと\n"
            "- **【重要】思考プロセス、検索結果の解説、文字数確認、ドラフトなどは一切出力せず、最終的なチャットメッセージの本文のみを直接出力してください。**\n"
        )

        prompt = "".join(prompt_parts)

        try:
            response = await asyncio.wait_for(
                self.client.aio.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=personality,
                        tools=[{"google_search": {}}],
                        temperature=0.8  # 雑談なので少しクリエイティブに
                    )
                ),
                timeout=_GEMINI_TIMEOUT_CHAT,
            )

            # Google Search Grounding使用時、response.text は複数partsを
            # 連結するため内容が重複することがある。最初のテキストpartだけを取得する。
            if response.candidates and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if part.text:
                        return part.text.strip()

            # フォールバック: partsが取れない場合はresponse.textを使用
            try:
                return response.text
            except (ValueError, AttributeError):
                logger.warning("Gemini returned no valid text for random chat")
                return None
        except Exception as e:
            logger.error(f"Error calling Gemini API for random chat: {e}")
            return None  # エラー時はNoneを返し、呼び出し元で処理

    async def generate_chat_response(self, personality: str, chat_history: list[dict], user_message: str) -> str:
        """
        スレッドやメンションでの会話用。
        chat_history: [{"role": "user" or "model", "content": "..."}] のリスト形式
        エラー時は例外をraiseする（呼び出し元で処理すること）。
        """
        # historyの構築
        contents = []
        for msg in chat_history:
            role = "user" if msg["role"] == "user" else "model"
            contents.append(
                types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=msg["content"])]
                )
            )

        # 最新のユーザーメッセージを追加
        contents.append(
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=user_message)]
            )
        )

        response = await asyncio.wait_for(
            self.client.aio.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=(
                        personality + "\n\n"
                        "【重要なルール】\n"
                        "- 返答は簡潔に。1〜3文（100文字程度）で返すこと。\n"
                        "- 長文で解説しない。友達とのLINEやチャットのテンポ感を意識する。\n"
                        "- 聞かれたことに端的に答え、必要なら一言感想を添える程度。\n"
                        "- **【重要】思考プロセスや解説、ドラフトなどは一切出力せず、チャットの返答本文のみを直接出力すること。**\n"
                    ),
                    tools=[{"google_search": {}}],
                    temperature=0.7
                )
            ),
            timeout=_GEMINI_TIMEOUT_CHAT,
        )

        # Google Search Grounding使用時の重複防止: 最初のテキストpartだけを取得
        if response.candidates and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if part.text:
                    return part.text.strip()

        try:
            return response.text
        except (ValueError, AttributeError):
            raise RuntimeError("Gemini returned no valid text for chat response")

    async def determine_character(self, user_message: str) -> str:
        """
        ユーザーのメッセージ内容から、最も適任なキャラクター名を判定する。
        """
        valid_names = ["タケシ", "アカリ先輩", "ゆうた", "れな"]

        system_instruction = (
            "あなたはチャットボットのルーターです。ユーザーのメッセージ内容を分析し、以下の4人のうち最も返答に適したキャラクターの名前を1つだけ出力してください。\n"
            "- タケシ (エンタメ、芸能、スポーツ担当。チャラい)\n"
            "- アカリ先輩 (国内時事、テクノロジー、料理・レシピ担当。知的)\n"
            "- ゆうた (アニメ、ゲーム、サブカル、豆知識担当。オタク)\n"
            "- れな (美容、恋愛、ファッション、人間関係担当。ギャル)\n\n"
            "出力ルール:\n"
            "「タケシ」「アカリ先輩」「ゆうた」「れな」のいずれか1つの文字列のみを出力すること。理由や余計な記号は含めないでください。\n\n"
            "振り分けルール:\n"
            "- メッセージの話題が各キャラの担当ジャンルに該当する場合は、そのキャラを選ぶこと。\n"
            "- どのキャラの担当ジャンルにも明確に該当しない一般的な雑談の場合は、4人の中からランダムに選ぶこと。特定のキャラに偏らないようにすること。\n"
            "- 挨拶や短い相槌（「おはよう」「ただいま」「暇だ」等）は一般的な雑談として扱い、毎回異なるキャラを選ぶこと。\n"
        )

        try:
            response = await asyncio.wait_for(
                self.client.aio.models.generate_content(
                    model=self.router_model_name,
                    contents=user_message,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.5,  # 一般的な雑談での多様性を確保
                    )
                ),
                timeout=_GEMINI_TIMEOUT_ROUTER,
            )
            result = response.text.strip()
            logger.info(f"[AIルーター] 入力: '{user_message[:50]}' → 結果: '{result}'")

            for name in valid_names:
                if name in result:
                    return name

            # ルーターが有効な名前を返さなかった場合、ランダムに選択
            logger.warning(f"[AIルーター] 有効な名前が含まれていません: '{result}' → ランダム選択")
            return random.choice(valid_names)
        except Exception as e:
            logger.error(f"[AIルーター] エラー: {e} → ランダム選択にフォールバック")
            return random.choice(valid_names)

