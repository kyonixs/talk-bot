# 🗞️ 雑談ニュースBot (News Bot)

個性豊かな4人のキャラクターが、Discordで毎日ニュースを配信し、雑談にも応じてくれるBotです。
GCP Compute Engine (e2-micro Always Free) 上でのDocker運用を想定して設計されています。

## ✨ 特徴
- **定時配信:** 毎日 朝8:00 と 夕方18:00（JST）にニュースを配信
- **スレッド会話:** ニュース配信スレッドに返信すると、担当キャラの口調で返事がきます
- **メンション会話:** チャンネル内で `@Bot名 タケシ 最近のサッカーについて` と話しかけることも可能
- **Gemini 2.5 Flash:** Google Search Groundingを利用し、最新ニュースをキャラブレなしで提供

---

## 🚀 動作環境・構成
- Python 3.12+
- `discord.py` (v2)
- `google-genai` SDK
- Docker & Docker Compose

---

## 🛠️ VM / OS 初期セットアップ (GCP e2-micro を想定)

e2-micro (1GB RAM) でDockerを安定稼働させるため、**Swap（スワップ領域）の設定**を推奨します。

```bash
# 1. system update
sudo apt-get update && sudo apt-get upgrade -y

# 2. Swapの設定 (2GB)
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# 3. Docker のインストール (Ubuntuの場合)
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker $USER

# 再ログインして groups コマンドで docker グループに入っているか確認してください。
```

---

## ⚙️ Bot のセットアップ

### 1. リポジトリの準備
```bash
git clone <your-repository-url>
cd news-bot
```

### 2. 環境変数の設定
`.env.example` をコピーして `.env` を作成し、中身を編集します。
```bash
cp .env.example .env
nano .env
```

`.env` の内容：
```env
DISCORD_TOKEN=your_discord_bot_token_here
GEMINI_API_KEY=your_gemini_api_key_here
CHANNEL_ID=123456789012345678
TZ=Asia/Tokyo
```

> **注意:** Discord Developer Portal で Botの **`Message Content Intent`** を必ずONにしてください。

---

## ▶️ 起動・運用コマンド

### 基本操作 (Docker Compose)
```bash
# バックグラウンドで起動
docker compose up -d

# ログをリアルタイム確認
docker compose logs -f news-bot

# Botの停止
docker compose down

# 再起動
docker compose restart news-bot
```

### ソースコード更新時の手順
ソースコードを変更、または `git pull` した後は再ビルドが必要です。
```bash
git pull origin main
docker compose up -d --build
```

---

## 💬 使い方 (Discordコマンド)

| コマンド/操作 | 説明 |
|---|---|
| `!news` | 定時配信を待たずに、今すぐ全キャラのニュースを手動配信します。 |
| `!ask キャラ名 質問の内容` | 特定のキャラクターを指名して単発の質問ができます。（例: `!ask アカリ先輩 今日の天気は？`） |
| `!help` | Botのデフォルトヘルプを表示します。 |
| **スレッド返信** | 定時ニュースのスレッドにそのまま書き込むと、そのニュースの担当キャラが答えます。 |
| **メンション** | `@Botキャラ名 これについて教えて` のように話しかけると一番近いキャラが答えます。 |
