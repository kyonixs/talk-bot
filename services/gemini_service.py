import asyncio
import logging
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

    async def generate_stock_report(self, prompt: str) -> dict:
        """
        株式レポート生成用。Google Search Grounding を使用し、
        エラー時は最大3回までリトライする。長文出力用に上限を調整。
        戻り値: {"text": str, "truncated": bool}
        """
        max_retries = 3
        retry_delay = 5 # 初回リトライ待ち時間(秒)

        for attempt in range(max_retries):
            try:
                response = await asyncio.wait_for(
                    self.client.aio.models.generate_content(
                        model=self.model_name,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            tools=[{"google_search": {}}],
                            temperature=0.3, # レポートなので事実ベースを強めるため低めに設定
                            max_output_tokens=8192
                        )
                    ),
                    timeout=_GEMINI_TIMEOUT_STOCK,
                )

                # finish_reasonがMAX_TOKENSで途切れたか判定
                is_truncated = False
                try:
                    if response.candidates and response.candidates[0].finish_reason:
                        # enum値か大文字文字列で返る場合がある
                        reason = str(response.candidates[0].finish_reason).upper()
                        if "MAX_TOKENS" in reason:
                            is_truncated = True
                except Exception:
                    pass

                return {"text": response.text, "truncated": is_truncated}

            except Exception as e:
                logger.error(f"Gemini API Error (Attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2 # 指数バックオフ
                else:
                    logger.error("Max retries reached. Reporting failure.")
                    raise e

    async def generate_random_chat(self, personality: str, topics: str) -> str | None:
        """
        ランダム雑談用。Google Search Grounding で最新の話題を1つ拾い、
        友達にふと話しかけるような自然な雑談メッセージを生成する。
        """
        prompt = (
            f"今日は日本の現在の日付です。Google検索を使って、以下のトピックに関連する最新の話題やニュースを1つだけ調べてください:\n"
            f"{topics}\n\n"
            "調べた結果をもとに、友達のグループチャットにふと話しかけるような自然な雑談メッセージを書いてください。\n"
            "ルール:\n"
            "- ネタは1つだけピックアップする\n"
            "- 「そういえばさ〜」「ちょっと聞いてよ」「ねぇ知ってる？」のような自然な切り出し方をする\n"
            "- 「今日のニュースは」「本日のトピックは」のようなアナウンサー的な言い回しは絶対に使わない\n"
            "- 友達にLINEで話しかけるようなテンポ感で、1〜3文で書く\n"
            "- **全体で100〜200文字に収めること（厳守）**\n"
            "- URLは不要。つけない\n"
            "- ニュースの正確性は調べた結果に忠実にすること\n"
        )

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
            return response.text
        except Exception as e:
            logger.error(f"Error calling Gemini API for random chat: {e}")
            return None  # エラー時はNoneを返し、呼び出し元で処理

    async def generate_chat_response(self, personality: str, chat_history: list[dict], user_message: str) -> str:
        """
        スレッドやメンションでの会話用。
        chat_history: [{"role": "user" or "model", "content": "..."}] のリスト形式
        """
        try:
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

            return response.text
        except Exception as e:
            logger.error(f"Error calling Gemini API for chat: {e}")
            return "ごめんね、今ちょっと頭回ってないかも。もう一回言ってくれる？"

    async def determine_character(self, user_message: str) -> str:
        """
        ユーザーのメッセージ内容から、最も適任なキャラクター名を判定する。
        """
        system_instruction = (
            "あなたはチャットボットのルーターです。ユーザーのメッセージ内容を分析し、以下の4人のうち最も返答に適したキャラクターの名前を1つだけ出力してください。\n"
            "- タケシ (エンタメ、芸能、スポーツ担当。チャラい)\n"
            "- アカリ先輩 (国内時事、テクノロジー、料理・レシピ担当。知的)\n"
            "- ゆうた (アニメ、ゲーム、サブカル、豆知識担当。オタク)\n"
            "- れな (美容、恋愛、ファッション、人間関係担当。ギャル)\n\n"
            "出力ルール:\n"
            "「タケシ」「アカリ先輩」「ゆうた」「れな」のいずれか1つの文字列のみを出力すること。理由や余計な記号は含めないでください。\n"
            "どれにも当てはまらない一般的な雑談の場合は、テンションや相性に最も近いものを選んでください。"
        )

        try:
            response = await asyncio.wait_for(
                self.client.aio.models.generate_content(
                    model=self.router_model_name,
                    contents=user_message,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.2, # クリエイティビティは低くして決定論的にする
                    )
                ),
                timeout=_GEMINI_TIMEOUT_ROUTER,
            )
            result = response.text.strip()
            
            valid_names = ["タケシ", "アカリ先輩", "ゆうた", "れな"]
            for name in valid_names:
                if name in result:
                    return name
            return "タケシ" # デフォルト
        except Exception as e:
            logger.error(f"Router Error: {e}")
            return "タケシ"
