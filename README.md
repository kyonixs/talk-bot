# 🗞️ 雑談ニュースBot (News Bot)

個性豊かな4人のキャラクターが、Discordで毎日ニュースを配信し、雑談にも応じてくれるBotです。
GCP Compute Engine (e2-micro Always Free) 上でのDocker運用を想定して設計されています。

## ✨ 特徴
- **定時雑談配信:** 毎日 朝8:00 と 夕方18:00（JST）にニュースを配信
- **株式レポート配信（新機能）:** Google Sheetsの銘柄情報を元に、日米の株価とGeminiの分析を定期配信
  - 米国株 日次: 平日 06:30 JST (夏時間05:30 JST)
  - 日本株 日次: 平日 15:30 JST
  - 米国株 週次: 土曜 15:00 JST / 日本株 週次: 土曜 14:00 JST
- **スレッド会話:** ニュース配信スレッドに返信すると、担当キャラの口調で返事がきます
- **メンション会話:** チャンネル内で `@Bot名 タケシ 最近のサッカーについて` と話しかけることも可能
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
2. 以下の**4つ**のシークレットを作成し、値を設定してください。
   - `DISCORD_TOKEN_SECRET` （Discord Developer Portalで取得したBotのトークン）
   - `GEMINI_API_KEY_SECRET` （雑談用：Google AI Studio等で取得したGeminiのAPIキー）
   - `GEMINI_API_KEY_STOCK` （株式レポート用：用途分けのため別のキーを推奨）
   - `DISCORD_WEBHOOK_STOCK` （株式レポート投稿先チャンネルのWebhook URL）
3. Botを動かすVM（Compute Engine）のサービスアカウントに、**「Secret Manager のシークレット アクセサー」** 権限が付与されていることを確認してください。

### 3. 環境変数の設定 (docker-compose.yml)
`docker-compose.yml` を開き、以下の `environment` セクションをご自身の設定に合わせて書き換えてください。
```yaml
    environment:
      - CHANNEL_ID=雑談Botを投稿したいチャンネルの数字ID
      - TZ=Asia/Tokyo
      - GOOGLE_CLOUD_PROJECT=ご自身のGCPプロジェクトID
```

> **注意:**
> - Discord Developer Portal で Botの **`Message Content Intent`** を必ずONにしてください。
> - 株式レポートは `DISCORD_WEBHOOK_STOCK` で指定したWebhook URLへ直接POSTされるため、環境変数でのチャンネルID指定は不要です。

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
