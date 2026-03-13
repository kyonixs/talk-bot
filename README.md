# 雑談ニュースBot (News Bot)

個性豊かな4人のキャラクターが、Discordで雑談や株式レポートを届けてくれるBotです。
GCP Compute Engine (e2-micro Always Free) 上でのDocker運用を想定して設計されています。

---

## 特徴

### 雑談機能
- **ランダム雑談:** 90分ごとに30%の確率でキャラクターが自発的に話しかける（8〜21時JST、同日同キャラ重複なし）
- **AI Router:** Gemini 2.0 Flash Lite がユーザーの発言内容から最適なキャラクターを自動選択（タイムアウト: 10秒）
- **Webhook なりすまし:** キャラクターの名前・アイコンで送信し、リアルな友達グループ感を演出
- **スレッド会話:** Bot作成スレッドに返信すると、担当キャラの口調で返事がきます
- **メンション会話:** チャンネル内で `@Bot名` と話しかけることも可能
- **クールダウン:** 同一ユーザーからの連続リクエストを3秒間抑制（100件超で自動クリーンアップ）

### 株式レポート配信
- Google Sheetsの銘柄情報を元に、日米の株価とGeminiの分析を定期配信
- **主要指数の自動取得:** S&P500, NASDAQ, 日経平均, TOPIX, USD/JPY
- **Discord Embed:** 指数サマリー + 市場の上昇/下落に応じた色分けヘッダー
- **スレッド投稿:** Embedヘッダーをチャンネルに投稿 → 詳細レポートは自動作成スレッド内に投稿
- **NYSE祝日対応:** `holidays.NYSE()` でGood Friday等の市場固有休場日を正確に判定
- **配信スケジュール:**

  | レポート | 実行タイミング |
  |---|---|
  | 米国株 日次 | 平日 市場閉場30分後 JST（夏05:30 / 冬06:30） |
  | 日本株 日次 | 平日 15:30 JST |
  | 米国株 週次 | 土曜 15:00 JST |
  | 日本株 週次 | 土曜 14:00 JST |

### AI エンジン
- **Gemini 2.5 Flash:** Google Search Groundingを利用し、最新ニュース・株価分析を提供
- **重複防止:** Search Grounding使用時に複数partsが返る場合、最初のテキストpartのみを取得
- **タイムアウト制御:** 株式レポート120秒 / 雑談・会話30秒 / ルーター10秒
- **リトライ:** 株式レポート生成は最大3回・指数バックオフでリトライ

---

## プロジェクト構成

```
news-bot/
├── bot.py                      # エントリーポイント（NewsBot クラス）
├── docker-compose.yml          # Docker Compose 設定
├── Dockerfile                  # Python 3.12-slim ベース
├── requirements.txt            # 依存パッケージ
├── README.md
│
├── cogs/
│   ├── chat.py                 # チャット応答（on_message, !ask, !help）
│   ├── random_chat.py          # ランダム雑談（定期自発発言）
│   └── stock_report.py         # 株式レポート（スケジューラ + 配信）
│
├── config/
│   ├── characters.py           # 4キャラクター定義 + エイリアス
│   └── stock_config.py         # 株式スケジュール, 祝日判定, TZ定義
│
├── prompts/
│   └── stock_prompts.py        # 株式レポート用プロンプト (US/JP × 日次/週次)
│
└── services/
    ├── gemini_service.py       # Gemini API ラッパー (4メソッド)
    ├── secret_service.py       # GCP Secret Manager アクセス
    ├── sheets_service.py       # Google Sheets 銘柄読み取り
    ├── stock_service.py        # Yahoo Finance 株価・指数取得
    └── webhook_service.py      # Discord Webhook なりすまし送信
```

---

## キャラクター

| キャラ | 担当ジャンル | 性格 |
|---|---|---|
| **タケシ** | エンタメ・芸能、スポーツ | チャラい22歳。勢い重視 |
| **アカリ先輩** | 国内時事、テック・IT、料理 | 知的な32歳。要点→背景の順で伝える |
| **ゆうた** | 雑学・豆知識、テック、アニメ・ゲーム | オタクな25歳。好きな話題で早口になる |
| **れな** | 美容・ファッション、恋愛・占い | キャバ嬢ギャル24歳。何でも恋愛に絡める |

---

## 動作環境・依存関係

- **Python:** 3.12+
- **Docker:** Docker Compose v2
- **GCP:** Compute Engine e2-micro (Always Free)

### 主要パッケージ
| パッケージ | バージョン | 用途 |
|---|---|---|
| `discord.py` | 2.4.0 | Discord Bot フレームワーク |
| `google-genai` | 0.3.0 | Gemini API (生成AI) |
| `google-cloud-secret-manager` | 2.20.0 | シークレット管理 |
| `google-api-python-client` | >=2.100.0 | Google Sheets API |
| `aiohttp` | >=3.9.0 | 非同期HTTPクライアント |
| `beautifulsoup4` | >=4.12.0 | HTMLパース（日本株企業名取得） |
| `holidays` | >=0.40 | NYSE/JP 祝日判定 |

---

## VM / OS 初期セットアップ (GCP e2-micro)

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

## Bot のセットアップ

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
   | `DISCORD_BOT_TOKEN` | Discord Developer Portalで取得したBotのトークン |
   | `GEMINI_API_KEY_CHAT` | 雑談用：Google AI Studio等で取得したGeminiのAPIキー |
   | `GEMINI_API_KEY_STOCK` | 株式レポート用：用途分けのため別のキーを推奨 |
   | `DISCORD_WEBHOOK_URL_STOCK` | 株式レポート投稿先チャンネルのWebhook URL |
   | `DISCORD_CHANNEL_ID_CHAT` | 雑談Botを投稿したいDiscordチャンネルの数字ID |
   | `GOOGLE_SPREADSHEET_ID_STOCK` | Google Sheetsの銘柄管理スプレッドシートのID |

3. Botを動かすVM（Compute Engine）のサービスアカウントに以下の権限を付与してください:
   - **Secret Manager のシークレット アクセサー** (シークレット読み取り)
   - **Google Sheets API** の読み取り権限 (スプレッドシートアクセス)

> **注意:**
> - `GOOGLE_CLOUD_PROJECT` は環境変数で設定するか、GCP VM上では**メタデータサーバーから自動検出**されます。
> - Discord Developer Portal で Botの **`Message Content Intent`** を必ずONにしてください。
> - 株式レポートチャンネルでスレッド作成するため、Botに **`CREATE_PUBLIC_THREADS`** と **`SEND_MESSAGES_IN_THREADS`** 権限が必要です。

### 3. Docker Compose 設定
`docker-compose.yml` の `environment` セクションは `TZ=Asia/Tokyo` のみです。
シークレットはすべて Secret Manager 経由で取得されます。

```yaml
services:
  news-bot:
    build: .
    container_name: news-bot
    restart: always
    environment:
      - TZ=Asia/Tokyo
    mem_limit: 512m
    memswap_limit: 1g
```

---

## 起動・運用コマンド

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
```bash
git pull origin main
docker compose up -d --build
```

---

## 使い方 (Discordコマンド)

| コマンド/操作 | 説明 |
|---|---|
| `!ask キャラ名 質問の内容` | 特定のキャラクターを指名して単発の質問（例: `!ask アカリ先輩 今日の天気は？`） |
| `!help` | キャラ紹介とコマンド一覧を表示 |
| **チャンネル内発言** | 雑談チャンネル内で自由に発言 → AIが最適なキャラを自動選択して応答 |
| **スレッド返信** | Bot作成スレッドにそのまま書き込むと、そのスレッドのキャラが答えます |
| **メンション** | `@Bot名 これについて教えて` のように話しかけると最適なキャラが答えます |

---

## アーキテクチャ

```
Discord User
    │
    ▼
┌─────────────┐     ┌──────────────────┐     ┌──────────────┐
│  discord.py  │────▶│  ChatCog         │────▶│ GeminiService│
│  (Bot)       │     │  - on_message    │     │ (2.5 Flash)  │
│              │     │  - !ask          │     │              │
│              │     │  - AI Router     │────▶│ (2.0 Flash   │
│              │     │    (自動振り分け) │     │   Lite)      │
│              │     └──────────────────┘     └──────────────┘
│              │                                     │
│              │     ┌──────────────────┐             │ Google Search
│              │────▶│  RandomChatCog   │─────────────┘ Grounding
│              │     │  (90分ごと)      │
│              │     └──────────────────┘
│              │
│              │     ┌──────────────────┐     ┌──────────────┐
│              │────▶│  StockReportCog  │────▶│ Yahoo Finance│
│              │     │  (毎分チェック)  │     │ (v8 API)     │
│              │     │                  │     └──────────────┘
│              │     │                  │────▶┌──────────────┐
│              │     │                  │     │ Google Sheets│
│              │     │                  │     │ (銘柄リスト) │
│              │     └──────────────────┘     └──────────────┘
│              │            │
│              │            ▼
│              │     ┌──────────────────┐
│              │     │ Discord Webhook  │
│              │     │ (Embed + Thread) │
└─────────────┘     └──────────────────┘
        │
        ▼
┌──────────────┐     ┌──────────────────┐
│ Webhook      │     │ GCP Secret       │
│ Service      │     │ Manager (6 keys) │
│ (なりすまし) │     └──────────────────┘
└──────────────┘
```

### データフロー（株式レポート）
1. **毎分チェック** → スケジュール時刻と一致したらレポート生成開始
2. **Google Sheets** から保有銘柄・監視銘柄リストを取得（リトライ付き）
3. **Yahoo Finance v8 API** から全銘柄の株価 + 主要指数をセッション共有で並列取得
4. **stock_prompts** がシステム指示 + ユーザープロンプトをdict形式で構築
5. **Gemini 2.5 Flash** がSearch Groundingを使ってレポート本文を生成（最大120秒タイムアウト）
6. **Discord Webhook** でEmbedヘッダーを投稿 → スレッド自動作成 → 本文をチャンク送信（429リトライ付き）

---

## エラーハンドリング

| 箇所 | 対応 |
|---|---|
| Gemini API | 株式レポート: 最大3回リトライ（指数バックオフ）/ チャット: エラーメッセージ返却 |
| Yahoo Finance API | query1/query2 フォールバック + セッション所有権管理 |
| Google Sheets API | HttpError (429/5xx) + ネットワークエラーを最大3回リトライ |
| Discord Webhook | 429 Rate Limit: 最大3回リトライ / スレッド作成失敗: チャンネル直接送信にフォールバック |
| Webhook なりすまし失敗 | `message.reply()` でBotデフォルト名義のフォールバック送信 |
| 株式レポート全体 | 例外発生時にWebhook経由でDiscordにエラー通知（HttpErrorは詳細付き） |
