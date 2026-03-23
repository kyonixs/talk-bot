FROM python:3.12-slim

WORKDIR /app

# 必要なパッケージをコピーしてインストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションのコードをすべてコピー
COPY . .

# timezoneを環境変数で上書きできるようにしつつ、デフォルトをJSTに
ENV TZ=Asia/Tokyo

# ヘルスチェック: ハートビートファイルが直近90秒以内に更新されているか確認
#  - bot.py が Discord に接続中の場合のみ30秒ごとにファイルを更新する
HEALTHCHECK --interval=60s --timeout=5s --retries=3 \
    CMD python -c "import os, time; assert time.time() - os.path.getmtime('/tmp/bot_heartbeat') < 90" || exit 1

# Botの起動
CMD ["python", "bot.py"]
