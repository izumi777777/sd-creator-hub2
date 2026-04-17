# .cursorrules — Creator Portal (Python / Flask)

## プロジェクトの本質

このプロジェクトは **AI画像生成クリエイターの副業収益化を支援するポータルアプリ** である。

オーナーはStable Diffusionで生成したオリジナルキャラクター画像をPixiv・PictSpace・DLsiteで販売しており、月間売上¥4,500・Pixivフォロワー2,500人超の実績を持つ個人クリエイター。現在は手作業で行っている以下の全工程をこのPortalで完結させることが目的である。

> ストーリー作成 → プロンプト生成 → 画像管理 → 投稿・販売テキスト作成 → PDF/ZIP書き出し

---

## ビジネスコンテキスト

### 収益構造

| プラットフォーム | 役割 | 現状 | 目標 |
|---|---|---|---|
| Pixiv | 無料投稿による集客・ファン獲得 | フォロワー2,543人 | 5,000人 |
| PictSpace | 有料イラスト集の販売 | 月¥3,000 / 10作品 | 月¥6,000 |
| DLsite | 有料PDF作品の販売 | 月¥1,500 / 4作品 | 月¥4,000 |

### 制作ワークフロー（このPortalが代替するフロー）

1. キャラクターを決める
2. AIにストーリー・世界観を相談して章構成を作る
3. 章ごとのSDプロンプトをAIに生成させる
4. Stable Diffusionで画像を生成してローカル保存
5. 生成画像をAmazon S3にアップロード
6. Pixivへの投稿タイトル・キャプションをAIに作らせる
7. DLsite/PictSpaceの商品説明をAIに作らせる
8. 画像を並び替えてPDF化（DLsite・PictSpace用）
9. 画像をZIP圧縮（DLsiteアップロード用）

### 重要な前提

- 個人運営のためインフラコストは最小限にする
- オーナーはPythonに慣れており、TypeScriptは不慣れなためバックエンドはPythonで統一する
- 技術的に高度すぎる構成は避ける（個人で保守できること）
- UIはJinja2テンプレート + Tailwind CSSで構築し、フロントのJSは最小限にする
- キャラクターIPは自社オリジナル（著作権はオーナー）

---

## 技術スタック

```
バックエンド  : Python 3.11+ / Flask
テンプレート  : Jinja2（Flask標準）
スタイリング  : Tailwind CSS (CDN)
フロント JS   : Vanilla JS（最小限）/ htmx（非同期処理）
DB           : SQLite（開発）→ PostgreSQL（本番）
ORM          : SQLAlchemy + Flask-SQLAlchemy
マイグレーション: Flask-Migrate
AI API       : Anthropic Python SDK (anthropic)
画像Storage  : Amazon S3 (boto3)
PDF生成      : ReportLab または fpdf2
ZIP生成      : Python標準ライブラリ (zipfile)
認証         : Flask-Login
デプロイ     : Render.com または Railway（無料枠あり）
```

---

## コーディング規約

### 全般

- Python 3.11以上を使用する
- 型ヒント（Type Hints）を積極的に使用する
- 関数・クラスには日本語docstringを書く
- `requirements.txt` で依存パッケージを管理する
- シークレット情報は `.env` ファイルで管理し、`python-dotenv` で読み込む
- エラーハンドリングは必ず実装し、ユーザーにはフラッシュメッセージで通知する

### 命名規則

| 対象 | 規則 | 例 |
|---|---|---|
| 関数・変数 | snake_case | `generate_story()` |
| クラス | PascalCase | `StoryGenerator` |
| 定数 | UPPER_SNAKE_CASE | `MAX_CHAPTERS` |
| Flaskルート | snake_case | `/story/generate` |
| テンプレートファイル | snake_case.html | `story_generator.html` |

### コメント

- **日本語コメントを積極的に使用する**（オーナーが読めるように）
- 複雑なビジネスロジックには必ず意図を説明するコメントを書く
- Claude API呼び出し部分には期待するレスポンス形式をコメントで記載する

### AI API利用

- Claude APIの呼び出しは `app/services/claude_service.py` に集約する
- system promptは `app/prompts/` ディレクトリに `.py` ファイルとして管理する
- APIレスポンスは必ず `json.loads` の try-except で保護する
- ストリーミングは使わずシンプルに `client.messages.create` を使う

---

## ディレクトリ構造

```
creator-portal/
├── app/
│   ├── __init__.py          # Flaskアプリ初期化
│   ├── models/              # SQLAlchemyモデル
│   │   ├── character.py
│   │   ├── work.py
│   │   ├── prompt.py
│   │   ├── story.py
│   │   ├── image.py
│   │   └── sales.py
│   ├── routes/              # Flaskルート（Blueprint）
│   │   ├── dashboard.py
│   │   ├── story.py
│   │   ├── text_gen.py
│   │   ├── image.py
│   │   ├── export.py
│   │   ├── character.py
│   │   ├── work.py
│   │   ├── prompt.py
│   │   └── sales.py
│   ├── services/            # ビジネスロジック
│   │   ├── claude_service.py   # Claude API
│   │   ├── s3_service.py       # Amazon S3
│   │   ├── pdf_service.py      # PDF生成
│   │   └── zip_service.py      # ZIP生成
│   ├── prompts/             # Claude system prompts
│   │   ├── story_prompt.py
│   │   ├── text_gen_prompt.py
│   │   └── sd_prompt.py
│   └── templates/           # Jinja2テンプレート
│       ├── base.html
│       ├── dashboard/
│       ├── story/
│       ├── text_gen/
│       ├── image/
│       ├── export/
│       ├── character/
│       ├── work/
│       ├── prompt/
│       └── sales/
├── static/
│   ├── css/
│   └── js/
├── migrations/              # Flask-Migrate
├── tests/
├── .env                     # シークレット（gitignore）
├── .env.example             # 環境変数のサンプル
├── config.py                # アプリ設定
├── requirements.txt
└── run.py                   # エントリーポイント
```

---

## UX原則

- **シンプルなフォーム操作** — 複雑なSPAは作らず、フォーム送信とJinja2レンダリングを基本にする
- **htmxで非同期化** — ページ遷移を減らしたい箇所だけ htmx を使う（AI生成など）
- **コピーしやすさ** — プロンプトや生成テキストはワンクリックでコピーできること
- **フィードバック** — 全ての処理にflashメッセージまたはローディング表示を実装する
- **モバイル対応** — Tailwind CSSでレスポンシブ対応する

---

## やってはいけないこと

- ❌ `.env` ファイルをGitにコミットすること
- ❌ APIキー・AWSシークレットをコードにハードコードすること
- ❌ 過度に複雑なアーキテクチャ（マイクロサービス等）の採用
- ❌ フロントエンドにReact/Vue/Angularを使うこと（Jinja2 + htmxで十分）
- ❌ エラーハンドリングの省略
- ❌ データベース直接操作（必ずSQLAlchemy ORM経由で行う）
