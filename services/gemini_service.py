import os
from google import genai
from google.genai import types

class GeminiService:
    def __init__(self):
        # 実行時に環境変数から取得する
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set in environment variables.")
        
        self.client = genai.Client(api_key=api_key)
        self.model_name = "gemini-2.5-flash"

    async def generate_news(self, personality: str, topics: str) -> str:
        """
        指定されたキャラクターの性格(personality)とトピック(topics)に基づいて、
        Google Search Groundingを利用してニュース紹介文を生成する
        """
        prompt = (
            f"今日は日本の現在の日付です。Google検索を使って、以下のトピックの最新ニュースを調べてください:\n"
            f"{topics}\n\n"
            "調べた結果をもとに、友達に話しかけるような雑談メッセージを書いてください。\n"
            "ルール:\n"
            "- 2〜3本のニュースをピックアップして紹介\n"
            "- 各ニュースについて2〜3文で紹介し、自分の感想やツッコミも入れる\n"
            "- ニュース記事のURLや情報ソースURLがあれば自然な形で文末などに含める\n"
            "- 全体で300〜500文字程度\n"
            "- 朝または夕方にふさわしい挨拶から始める\n"
            "- ニュースの正確性は調べた結果に忠実にすること\n"
        )

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=personality,
                    tools=[{"google_search": {}}],
                    temperature=0.7 # 少しクリエイティビティを持たせる
                )
            )
            return response.text
        except Exception as e:
            print(f"Error calling Gemini API for news: {e}")
            return "ごめん！ニュース調べるの失敗しちゃったみたい。後でもう一回聞いて！"

    async def generate_chat_response(self, personality: str, chat_history: list[dict], user_message: str) -> str:
        """
        スレッドやメンションでの会話用。
        chat_history: [{"role": "user" or "model", "parts": [{"text": "..."}]}] のリスト形式
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

            response = self.client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=personality,
                    tools=[{"google_search": {}}], # 会話時も一応検索ツールを持たせておく
                    temperature=0.7
                )
            )
            return response.text
        except Exception as e:
            print(f"Error calling Gemini API for chat: {e}")
            return "ごめんね、今ちょっと頭回ってないかも。もう一回言ってくれる？"
