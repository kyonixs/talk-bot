"""Gemini API の設定値
モデル名・温度・トークン上限・思考予算をここで一元管理する。
"""

GEMINI_CONFIG = {
    "stock_report": {
        "model": "gemini-2.5-flash",
        "temperature": 0.3,
        "max_output_tokens": 8192,
        "thinking_budget": 2048,  # 株式レポートは分析思考を許可
        "timeout": 120,
    },
    "chat": {
        "model": "gemini-2.5-flash",
        "temperature": 0.7,
        "max_output_tokens": None,  # デフォルト
        "thinking_budget": 0,
        "timeout": 30,
    },
    "random_chat": {
        "model": "gemini-2.5-flash",
        "temperature": 0.8,
        "max_output_tokens": None,
        "thinking_budget": 0,
        "timeout": 30,
    },
    "router": {
        "model": "gemini-2.0-flash-lite",
        "temperature": 0.5,
        "max_output_tokens": None,
        "thinking_budget": None,  # 思考機能なし
        "timeout": 10,
    },
}
