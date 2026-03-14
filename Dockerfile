FROM python:3.12-slim

WORKDIR /app

# 必要なパッケージをコピーしてインストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションのコードをすべてコピー
COPY . .

# timezoneを環境変数で上書きできるようにしつつ、デフォルトをJSTに
ENV TZ=Asia/Tokyo

# ヘルスチェック: PID 1 (bot.py) の生存確認（追加パッケージ不要）
HEALTHCHECK --interval=60s --timeout=5s --retries=3 \
    CMD python -c "import os; os.kill(1, 0)" || exit 1

# Botの起動
CMD ["python", "bot.py"]
