# 🗞️ 雑談ニュースBot (News Bot)

個性豊かな4人のキャラクターが、Discordで雑談や株式レポートを届けてくれるBotです。
GCP Compute Engine (e2-micro Always Free) 上でのDocker運用を想定して設計されています。

## ✨ 特徴
- **ランダム雑談:** 90分ごとに30%の確率でキャラクターが自発的に話しかける（8〜21時JST、同日重複なし）
- **AI Router:** Gemini 2.0 Flash Lite がユーザーの発言内容から最適なキャラクターを自動選択
- **Webhook なりすまし:** キャラクターの名前・アイコンで送信し、リアルな友達グループ感を演出
- **株式レポート配信:** Google Sheetsの銘柄情報を元に、日米の株価とGeminiの分析を定期配信
  - 米国株 日次: 平日 06:30 JST (夏時間05:30 JST)
  - 日本株 日次: 平日 15:30 JST
  - 米国株 週次: 土曜 15:00 JST / 日本株 週次: 土曜 14:00 JST
- **スレッド会話:** Bot作成スレッドに返信すると、担当キャラの口調で返事がきます
- **メンション会話:** チャンネル内で `@Bot名` と話しかけることも可能
- **Gemini 2.5 Flash:** Google Search Groundingを利用し、最新ニュース・株価分析を提供

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

### 2. GCP Secret Manager の設定
このBotはパスワードを安全に管理するため、**GCP Secret Manager**を利用します。
`.env` ファイルは使用しません。

1. [GCPコンソール](https://console.cloud.google.com/) で「Secret Manager」を開き、APIを有効にします。
2. 以下の**6つ**のシークレットを作成し、値を設定してください。

   | シークレット名 | 用途 |
   |---|---|
   | `DISCORD_TOKEN_SECRET` | Discord Developer Portalで取得したBotのトークン |
   | `GEMINI_API_KEY_SECRET` | 雑談用：Google AI Studio等で取得したGeminiのAPIキー |
   | `GEMINI_API_KEY_STOCK` | 株式レポート用：用途分けのため別のキーを推奨 |
   | `DISCORD_WEBHOOK_STOCK` | 株式レポート投稿先チャンネルのWebhook URL |
   | `CHANNEL_ID` | 雑談Botを投稿したいDiscordチャンネルの数字ID |
   | `SPREADSHEET_ID` | Google Sheetsの銘柄管理スプレッドシートのID |

3. Botを動かすVM（Compute Engine）のサービスアカウントに、**「Secret Manager のシークレット アクセサー」** 権限が付与されていることを確認してください。

> **注意:**
> - `GOOGLE_CLOUD_PROJECT` は環境変数で設定するか、GCP VM上では**メタデータサーバーから自動検出**されます。
> - Discord Developer Portal で Botの **`Message Content Intent`** を必ずONにしてください。
> - 株式レポートは `DISCORD_WEBHOOK_STOCK` で指定したWebhook URLへ直接POSTされます。

### 3. 環境変数の設定 (docker-compose.yml)
`docker-compose.yml` の `environment` セクションは基本的に `TZ=Asia/Tokyo` のみです。
`CHANNEL_ID` や `SPREADSHEET_ID` は Secret Manager で管理されるため、環境変数への記載は不要です。

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
| `!ask キャラ名 質問の内容` | 特定のキャラクターを指名して単発の質問ができます。（例: `!ask アカリ先輩 今日の天気は？`） |
| `!help` | キャラ紹介とコマンド一覧を表示します。 |
| **チャンネル内発言** | 雑談チャンネル内で自由に発言 → AIが最適なキャラを自動選択して応答 |
| **スレッド返信** | Bot作成スレッドにそのまま書き込むと、そのスレッドのキャラが答えます。 |
| **メンション** | `@Bot名 これについて教えて` のように話しかけると最適なキャラが答えます。 |
