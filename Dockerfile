FROM python:3.12-slim

WORKDIR /app

# 必要なパッケージをコピーしてインストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションのコードをすべてコピー
COPY . .

# timezoneを環境変数で上書きできるようにしつつ、デフォルトをJSTに
ENV TZ=Asia/Tokyo

# Botの起動
CMD ["python", "bot.py"]
