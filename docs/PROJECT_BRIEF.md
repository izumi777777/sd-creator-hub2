# Creator Portal — プロジェクト仕様書（Python / Flask版）

> **Cursorへの指示** — コードを生成・修正するときは必ずこのドキュメントを参照し、ビジネスの文脈を理解した上で実装すること。バックエンドはPython/Flask、テンプレートはJinja2で統一すること。

---

## 1. プロジェクト概要

### 何を作るか

AI画像生成クリエイターが使う **副業収益化ポータルアプリ**。Stable Diffusionでキャラクター画像を生成し、Pixiv・PictSpace・DLsiteで販売する個人クリエイターの全業務フローをブラウザ1つで完結させる。

### なぜ作るか

**現状の課題（すべて手作業）**

| 作業 | 現状 | Portalで解決すること |
|---|---|---|
| ストーリー・プロンプト作成 | AIに都度コピペで依頼 | Portal内で完結・保存 |
| 生成画像の管理 | ローカルフォルダ（検索困難） | S3連携で一元管理 |
| 投稿タイトル・販売説明文 | AIに都度コピペで依頼 | Portal内で1クリック生成 |
| PDF・ZIP作成 | 別ツールで手作業 | Portal内で完結 |
| 売上管理 | スプレッドシート（使わなくなった） | ダッシュボードで可視化 |

**目標: 月2〜3時間かかる作業を30分以内にする。**

### 現在のビジネス実績

| 指標 | 現状 | 目標 |
|---|---|---|
| Pixivフォロワー | 2,543人 | 5,000人 |
| PictSpace月売上 | ¥3,000（10作品） | ¥6,000 |
| DLsite月売上 | ¥1,500（4作品） | ¥4,000 |
| 月間作業時間 | 2〜3時間 | 30分以内 |

---

## 2. 技術選定の理由

| 技術 | 理由 |
|---|---|
| Python / Flask | オーナーがPythonに慣れているため。TypeScriptは不慣れ |
| Jinja2テンプレート | Flaskの標準機能。Python的な書き方でHTMLを生成できる |
| SQLAlchemy ORM | SQLを直接書かずにDBを操作できる。Pythonらしい書き方 |
| SQLite → PostgreSQL | 開発はファイル1つで完結するSQLite。本番移行も容易 |
| htmx | JavaScriptをほとんど書かずにAjax的な動作を実現できる |
| boto3 | AWSの公式Pythonライブラリ。S3操作の実績が豊富 |
| ReportLab / fpdf2 | PythonでPDFを生成できるライブラリ |

---

## 3. 環境セットアップ

### インストール手順

```bash
# プロジェクト作成
mkdir creator-portal && cd creator-portal
python -m venv venv
source venv/bin/activate  # Windowsは venv\Scripts\activate

# パッケージインストール
pip install flask flask-sqlalchemy flask-migrate flask-login
pip install anthropic boto3 python-dotenv
pip install fpdf2 pillow
pip install gunicorn  # 本番用

# requirements.txtに書き出す
pip freeze > requirements.txt
```

### .env ファイル（ルートに作成）

```env
# Flask
FLASK_SECRET_KEY=your-secret-key-here
FLASK_ENV=development

# データベース
DATABASE_URL=sqlite:///creator_portal.db

# Anthropic Claude API
ANTHROPIC_API_KEY=your_anthropic_api_key

# Amazon S3
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_S3_BUCKET=your-bucket-name
AWS_S3_REGION=ap-northeast-1
```

### run.py（エントリーポイント）

```python
from app import create_app

app = create_app()

if __name__ == '__main__':
    app.run(debug=True)
```

### config.py

```python
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    """アプリケーション設定"""
    SECRET_KEY = os.environ.get('FLASK_SECRET_KEY', 'dev-key')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///creator_portal.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')
    AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')
    AWS_S3_BUCKET = os.environ.get('AWS_S3_BUCKET')
    AWS_S3_REGION = os.environ.get('AWS_S3_REGION', 'ap-northeast-1')
```

### app/__init__.py

```python
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from config import Config

db = SQLAlchemy()
migrate = Migrate()

def create_app():
    """Flaskアプリを初期化する"""
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    migrate.init_app(app, db)

    # Blueprintを登録する
    from app.routes.dashboard import bp as dashboard_bp
    from app.routes.story import bp as story_bp
    from app.routes.text_gen import bp as text_gen_bp
    from app.routes.image import bp as image_bp
    from app.routes.export import bp as export_bp
    from app.routes.character import bp as character_bp
    from app.routes.work import bp as work_bp
    from app.routes.prompt import bp as prompt_bp
    from app.routes.sales import bp as sales_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(story_bp, url_prefix='/story')
    app.register_blueprint(text_gen_bp, url_prefix='/text-gen')
    app.register_blueprint(image_bp, url_prefix='/image')
    app.register_blueprint(export_bp, url_prefix='/export')
    app.register_blueprint(character_bp, url_prefix='/character')
    app.register_blueprint(work_bp, url_prefix='/work')
    app.register_blueprint(prompt_bp, url_prefix='/prompt')
    app.register_blueprint(sales_bp, url_prefix='/sales')

    return app
```

---

## 4. データベースモデル

### app/models/character.py

```python
from app import db
from datetime import datetime

class Character(db.Model):
    """キャラクターマスタ"""
    __tablename__ = 'characters'

    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(100), nullable=False)   # キャラ名
    tags       = db.Column(db.Text)                          # カンマ区切りタグ
    sd_model   = db.Column(db.String(200))                   # 使用SDモデル
    lora_name  = db.Column(db.String(200))                   # LoRA名
    lora_weight = db.Column(db.Float, default=0.8)           # LoRAウェイト
    emoji      = db.Column(db.String(10), default='🎨')
    color      = db.Column(db.String(20), default='purple')  # UIカラー
    notes      = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # リレーション
    works   = db.relationship('Work', backref='character', lazy=True)
    prompts = db.relationship('Prompt', backref='character', lazy=True)
    stories = db.relationship('Story', backref='character', lazy=True)
    images  = db.relationship('Image', backref='character', lazy=True)

    def tags_list(self) -> list[str]:
        """タグをリストで返す"""
        return [t.strip() for t in self.tags.split(',')] if self.tags else []
```

### app/models/work.py

```python
from app import db
from datetime import datetime

class Work(db.Model):
    """作品管理"""
    __tablename__ = 'works'

    # ステータスの選択肢
    STATUS_GENERATING = 'generating'  # 生成中
    STATUS_COMPLETED  = 'completed'   # 完成
    STATUS_PIXIV      = 'pixiv'       # Pixiv投稿済み
    STATUS_SALE       = 'sale'        # 販売中

    id           = db.Column(db.Integer, primary_key=True)
    character_id = db.Column(db.Integer, db.ForeignKey('characters.id'), nullable=False)
    title        = db.Column(db.String(200), nullable=False)
    status       = db.Column(db.String(20), default=STATUS_GENERATING)
    price        = db.Column(db.Integer, default=0)
    pixiv_url    = db.Column(db.String(500))
    pict_url     = db.Column(db.String(500))
    dl_url       = db.Column(db.String(500))
    sales_pict   = db.Column(db.Integer, default=0)   # PictSpace販売数
    sales_dl     = db.Column(db.Integer, default=0)   # DLsite販売数
    story_id     = db.Column(db.Integer, db.ForeignKey('stories.id'))
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def total_revenue(self) -> int:
        """売上合計を返す"""
        return (self.sales_pict + self.sales_dl) * self.price

    @property
    def status_label(self) -> str:
        """ステータスの日本語ラベルを返す"""
        labels = {
            'generating': '生成中',
            'completed': '完成',
            'pixiv': 'Pixiv投稿済',
            'sale': '販売中'
        }
        return labels.get(self.status, self.status)
```

### app/models/story.py

```python
from app import db
from datetime import datetime
import json

class Story(db.Model):
    """ストーリー管理"""
    __tablename__ = 'stories'

    id           = db.Column(db.Integer, primary_key=True)
    character_id = db.Column(db.Integer, db.ForeignKey('characters.id'), nullable=False)
    title        = db.Column(db.String(200))
    overview     = db.Column(db.Text)
    genre        = db.Column(db.String(100))
    tone         = db.Column(db.String(100))
    premise      = db.Column(db.Text)       # ユーザーが入力したあらすじ
    chapters_json = db.Column(db.Text)      # 章データをJSONで保存
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    def get_chapters(self) -> list[dict]:
        """章データをリストで返す"""
        return json.loads(self.chapters_json) if self.chapters_json else []

    def set_chapters(self, chapters: list[dict]):
        """章データをJSONに変換して保存する"""
        self.chapters_json = json.dumps(chapters, ensure_ascii=False)
```

### app/models/prompt.py

```python
from app import db
from datetime import datetime

class Prompt(db.Model):
    """プロンプトライブラリ"""
    __tablename__ = 'prompts'

    id               = db.Column(db.Integer, primary_key=True)
    character_id     = db.Column(db.Integer, db.ForeignKey('characters.id'), nullable=False)
    situation        = db.Column(db.String(100))   # シチュエーション（例: 魔法、戦闘）
    positive         = db.Column(db.Text)           # SD positive prompt
    negative         = db.Column(db.Text)           # SD negative prompt
    model            = db.Column(db.String(100))    # 使用SDモデル
    notes            = db.Column(db.Text)           # 制作メモ（日本語）
    used_count       = db.Column(db.Integer, default=0)
    is_starred       = db.Column(db.Boolean, default=False)
    story_chapter_id = db.Column(db.Integer)        # ストーリーの何章から生成したか
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)
```

### app/models/image.py

```python
from app import db
from datetime import datetime

class Image(db.Model):
    """画像管理"""
    __tablename__ = 'images'

    id           = db.Column(db.Integer, primary_key=True)
    character_id = db.Column(db.Integer, db.ForeignKey('characters.id'), nullable=False)
    work_id      = db.Column(db.Integer, db.ForeignKey('works.id'))
    s3_key       = db.Column(db.String(500))    # S3のオブジェクトキー
    s3_url       = db.Column(db.String(500))    # 表示用URL
    file_name    = db.Column(db.String(200))
    file_size    = db.Column(db.Integer)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
```

### app/models/sales.py

```python
from app import db
from datetime import datetime

class SalesRecord(db.Model):
    """月次売上記録"""
    __tablename__ = 'sales_records'

    id           = db.Column(db.Integer, primary_key=True)
    month        = db.Column(db.String(7), nullable=False)  # 例: "2026-03"
    pict_revenue = db.Column(db.Integer, default=0)
    dl_revenue   = db.Column(db.Integer, default=0)
    followers    = db.Column(db.Integer, default=0)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def total(self) -> int:
        return self.pict_revenue + self.dl_revenue
```

---

## 5. Claude APIサービス

### app/services/claude_service.py

```python
import anthropic
import json
from flask import current_app

def call_claude(system: str, user_message: str, max_tokens: int = 1000) -> dict:
    """
    Claude APIを呼び出してJSONレスポンスを返す。

    Args:
        system: システムプロンプト
        user_message: ユーザーメッセージ
        max_tokens: 最大トークン数

    Returns:
        パースされたJSONデータ（dict）

    Raises:
        ValueError: JSONパースに失敗した場合
        anthropic.APIError: API呼び出しに失敗した場合
    """
    client = anthropic.Anthropic(api_key=current_app.config['ANTHROPIC_API_KEY'])

    response = client.messages.create(
        model='claude-sonnet-4-20250514',
        max_tokens=max_tokens,
        system=system,
        messages=[{'role': 'user', 'content': user_message}]
    )

    # テキストを取り出してJSONパースする
    text = response.content[0].text
    clean_text = text.replace('```json', '').replace('```', '').strip()

    try:
        return json.loads(clean_text)
    except json.JSONDecodeError as e:
        raise ValueError(f'Claude APIのレスポンスをJSONとして解析できませんでした: {e}')
```

---

## 6. 各機能の実装仕様

### 6-1. ストーリー生成

#### ルート（app/routes/story.py）

```python
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from app.models.story import Story
from app.models.character import Character
from app.services.claude_service import call_claude
from app.prompts.story_prompt import STORY_SYSTEM_PROMPT
from app import db

bp = Blueprint('story', __name__)

@bp.route('/')
def index():
    """ストーリー一覧ページ"""
    characters = Character.query.all()
    stories = Story.query.order_by(Story.created_at.desc()).all()
    return render_template('story/index.html', characters=characters, stories=stories)

@bp.route('/generate', methods=['POST'])
def generate():
    """AIでストーリーとプロンプトを生成する（htmxから呼ばれる）"""
    character_id = request.form.get('character_id', type=int)
    premise = request.form.get('premise', '').strip()
    genres = request.form.getlist('genres')
    tones = request.form.getlist('tones')
    num_chapters = request.form.get('num_chapters', 5, type=int)

    if not premise:
        return '<p class="text-red-500">あらすじを入力してください</p>', 400

    character = Character.query.get_or_404(character_id)

    # ユーザーメッセージを組み立てる
    user_message = f"""
キャラクター名: {character.name}
キャラクターの特徴: {character.tags}
使用SDモデル: {character.sd_model or '未設定'}
ジャンル: {', '.join(genres) or 'ファンタジー'}
トーン: {', '.join(tones) or 'ドラマチック'}
あらすじ: {premise}
章の数: {num_chapters}
    """.strip()

    try:
        result = call_claude(STORY_SYSTEM_PROMPT, user_message, max_tokens=2500)
        # 生成結果をHTMLとして返す（htmxでページの一部に差し込む）
        return render_template(
            'story/result_partial.html',
            story=result,
            character=character
        )
    except Exception as e:
        return f'<p class="text-red-500">生成エラー: {str(e)}</p>', 500

@bp.route('/save', methods=['POST'])
def save():
    """生成したストーリーをDBに保存する"""
    character_id = request.form.get('character_id', type=int)
    title = request.form.get('title')
    overview = request.form.get('overview')
    chapters_json = request.form.get('chapters_json')
    genre = request.form.get('genre')

    story = Story(
        character_id=character_id,
        title=title,
        overview=overview,
        genre=genre,
        chapters_json=chapters_json
    )
    db.session.add(story)
    db.session.commit()

    flash('ストーリーを保存しました', 'success')
    return redirect(url_for('story.index'))
```

#### system prompt（app/prompts/story_prompt.py）

```python
STORY_SYSTEM_PROMPT = """
あなたはアニメ・イラスト作品のストーリーライターとStable Diffusionプロンプト
エンジニアを兼任するエキスパートです。
キャラクター情報とあらすじを受け取り、章ごとのシーンとSDプロンプトを生成します。

SDプロンプトのルール:
- positive promptは必ず "masterpiece, best quality, 1girl, solo" で始める
- キャラクターの特徴（髪色・目の色・服装等）を必ず含める
- シーンの状況・背景・光源・雰囲気を英語タグで表現する

レスポンスは必ず以下のJSON形式のみで返すこと。説明文やmarkdownは含めないこと:
{
  "title": "作品タイトル（日本語）",
  "overview": "あらすじ2〜3文（日本語）",
  "chapters": [
    {
      "no": 1,
      "title": "章タイトル（日本語）",
      "scene": "シーン描写2〜3文（日本語・ビジュアルと感情を重視）",
      "prompt": "masterpiece, best quality, 1girl, solo, ...",
      "neg": "lowres, bad anatomy, bad hands, ..."
    }
  ]
}
"""
```

---

### 6-2. テキスト生成

3プラットフォーム（Pixiv / DLsite / PictSpace）に特化した投稿・販売テキストをAIで生成する。

#### ルート（app/routes/text_gen.py）

```python
from flask import Blueprint, render_template, request
from app.models.character import Character
from app.models.work import Work
from app.services.claude_service import call_claude
from app.prompts.text_gen_prompt import PIXIV_PROMPT, DLSITE_PROMPT, PICTSPACE_PROMPT

bp = Blueprint('text_gen', __name__)

@bp.route('/')
def index():
    characters = Character.query.all()
    works = Work.query.all()
    return render_template('text_gen/index.html', characters=characters, works=works)

@bp.route('/generate', methods=['POST'])
def generate():
    """プラットフォーム別テキストを生成する（htmxから呼ばれる）"""
    platform = request.form.get('platform')  # pixiv / dlsite / pictspace
    character_id = request.form.get('character_id', type=int)
    overview = request.form.get('overview', '').strip()

    if not overview:
        return '<p class="text-red-500">作品の概要を入力してください</p>', 400

    character = Character.query.get_or_404(character_id)

    # プラットフォームに応じたsystem promptを選択する
    prompts = {
        'pixiv': PIXIV_PROMPT,
        'dlsite': DLSITE_PROMPT,
        'pictspace': PICTSPACE_PROMPT
    }
    system_prompt = prompts.get(platform, PIXIV_PROMPT)

    user_message = f"""
キャラクター名: {character.name}
キャラクターの特徴: {character.tags}
作品の概要: {overview}
    """.strip()

    try:
        result = call_claude(system_prompt, user_message, max_tokens=1500)
        return render_template(
            'text_gen/result_partial.html',
            result=result,
            platform=platform
        )
    except Exception as e:
        return f'<p class="text-red-500">生成エラー: {str(e)}</p>', 500
```

#### system prompts（app/prompts/text_gen_prompt.py）

```python
PIXIV_PROMPT = """
Pixivへの投稿用メタデータを日本語で生成してください。
必ず以下のJSON形式のみで返すこと:
{
  "title": "投稿タイトル（50文字以内）",
  "caption": "キャプション（150〜300文字。ストーリーの魅力と見どころを伝える）",
  "tags": ["タグ1", "タグ2", ...（15個、日英混合）]
}
"""

DLSITE_PROMPT = """
DLsiteの商品ページ用テキストを日本語で生成してください。
購買意欲を高めるキャッチーな表現を使うこと。
必ず以下のJSON形式のみで返すこと:
{
  "title": "商品タイトル（60文字以内、キャッチー）",
  "genre": "ジャンル（2〜3個）",
  "overview": "作品概要（100〜150文字）",
  "description": "詳細説明（300〜500文字。ストーリーと見どころを丁寧に紹介）",
  "tags": ["タグ1", "タグ2", ...（10個）],
  "age_rating": "全年齢 または R-15 または 18禁"
}
"""

PICTSPACE_PROMPT = """
PictSpaceの商品ページ用テキストを日本語で生成してください。
必ず以下のJSON形式のみで返すこと:
{
  "title": "商品タイトル（50文字以内）",
  "description": "商品説明（200〜350文字）",
  "tags": ["タグ1", "タグ2", ...（12個）]
}
"""
```

---

### 6-3. S3連携

#### app/services/s3_service.py

```python
import boto3
from botocore.exceptions import ClientError
from flask import current_app

def get_s3_client():
    """S3クライアントを取得する"""
    return boto3.client(
        's3',
        aws_access_key_id=current_app.config['AWS_ACCESS_KEY_ID'],
        aws_secret_access_key=current_app.config['AWS_SECRET_ACCESS_KEY'],
        region_name=current_app.config['AWS_S3_REGION']
    )

def upload_image(file_obj, s3_key: str, content_type: str = 'image/png') -> str:
    """
    画像をS3にアップロードして公開URLを返す。

    Args:
        file_obj: アップロードするファイルオブジェクト
        s3_key: S3のオブジェクトキー（例: アリサ/001_scene1.png）
        content_type: MIMEタイプ

    Returns:
        アップロード先のURL
    """
    s3 = get_s3_client()
    bucket = current_app.config['AWS_S3_BUCKET']
    region = current_app.config['AWS_S3_REGION']

    s3.upload_fileobj(
        file_obj,
        bucket,
        s3_key,
        ExtraArgs={'ContentType': content_type}
    )

    url = f'https://{bucket}.s3.{region}.amazonaws.com/{s3_key}'
    return url

def list_images(prefix: str = '') -> list[dict]:
    """
    S3バケット内の画像一覧を取得する。

    Args:
        prefix: フィルタリングするプレフィックス（例: 'アリサ/'）

    Returns:
        画像情報のリスト
    """
    s3 = get_s3_client()
    bucket = current_app.config['AWS_S3_BUCKET']
    region = current_app.config['AWS_S3_REGION']

    response = s3.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=200)

    images = []
    for obj in response.get('Contents', []):
        key = obj['Key']
        # 画像ファイルのみ対象にする
        if key.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
            images.append({
                'key': key,
                'name': key.split('/')[-1],
                'url': f'https://{bucket}.s3.{region}.amazonaws.com/{key}',
                'size': obj['Size'],
                'last_modified': obj['LastModified'].isoformat()
            })

    return images

def get_presigned_url(s3_key: str, expiration: int = 900) -> str:
    """
    署名付きURL（15分有効）を生成して返す。
    プライベートバケットの画像を安全に表示するために使用する。
    """
    s3 = get_s3_client()
    bucket = current_app.config['AWS_S3_BUCKET']

    url = s3.generate_presigned_url(
        'get_object',
        Params={'Bucket': bucket, 'Key': s3_key},
        ExpiresIn=expiration
    )
    return url
```

---

### 6-4. PDF生成

#### app/services/pdf_service.py

```python
import io
from fpdf import FPDF
from PIL import Image as PILImage
from typing import Literal

PageSize = Literal['a4', 'a5', 'b5', 'square']
FitMode = Literal['fit', 'fill', 'full']

# ページサイズ定義（mm単位）
PAGE_SIZES = {
    'a4':     (210, 297),
    'a5':     (148, 210),
    'b5':     (176, 250),
    'square': (150, 150),
}

def generate_pdf(
    image_urls: list[str],
    page_size: PageSize = 'a4',
    fit_mode: FitMode = 'fit',
    bg_color: str = 'white'
) -> bytes:
    """
    画像リストからPDFを生成してバイト列で返す。

    Args:
        image_urls: 画像URLまたはBase64データのリスト
        page_size: ページサイズ（a4/a5/b5/square）
        fit_mode: 画像の配置方法（fit/fill/full）
        bg_color: 背景色（white/black）

    Returns:
        PDFのバイト列（Flaskのsend_fileで返すことを想定）
    """
    pw, ph = PAGE_SIZES.get(page_size, PAGE_SIZES['a4'])
    bg_rgb = (0, 0, 0) if bg_color == 'black' else (255, 255, 255)

    pdf = FPDF(orientation='P', unit='mm', format=(pw, ph))
    pdf.set_auto_page_break(False)

    for i, url in enumerate(image_urls):
        pdf.add_page()

        # 背景色を塗る
        pdf.set_fill_color(*bg_rgb)
        pdf.rect(0, 0, pw, ph, 'F')

        # 画像を読み込む（URLの場合はrequestsで取得）
        img_data = _load_image(url)
        if img_data is None:
            continue

        # 配置を計算する
        x, y, w, h = _calc_position(img_data, pw, ph, fit_mode)

        # 一時ファイルとしてPDFに追加する
        with io.BytesIO(img_data) as img_buffer:
            pdf.image(img_buffer, x=x, y=y, w=w, h=h)

    return pdf.output(dest='S').encode('latin-1')

def _load_image(source: str) -> bytes | None:
    """URLまたはBase64から画像バイト列を取得する"""
    import requests, base64

    try:
        if source.startswith('data:'):
            # Base64データの場合
            header, data = source.split(',', 1)
            return base64.b64decode(data)
        else:
            # URLの場合
            response = requests.get(source, timeout=10)
            response.raise_for_status()
            return response.content
    except Exception:
        return None

def _calc_position(img_data: bytes, pw: float, ph: float, fit_mode: str):
    """画像の配置位置とサイズを計算する"""
    with PILImage.open(io.BytesIO(img_data)) as img:
        iw, ih = img.size
    ratio = iw / ih

    if fit_mode == 'fit':
        w = pw
        h = pw / ratio
        if h > ph:
            h = ph
            w = ph * ratio
        x = (pw - w) / 2
        y = (ph - h) / 2
    elif fit_mode == 'fill':
        w = pw
        h = pw / ratio
        if h < ph:
            h = ph
            w = ph * ratio
        x = (pw - w) / 2
        y = (ph - h) / 2
    else:  # full
        x, y, w, h = 0, 0, pw, ph

    return x, y, w, h
```

---

### 6-5. ZIP生成

#### app/services/zip_service.py

```python
import io
import zipfile
import requests
from typing import Literal

FolderStructure = Literal['flat', 'by_character', 'numbered']

def generate_zip(
    images: list[dict],
    structure: FolderStructure = 'flat'
) -> bytes:
    """
    画像リストからZIPファイルを生成してバイト列で返す。

    Args:
        images: 画像情報のリスト。各要素は {'url': str, 'name': str, 'character_name': str}
        structure: フォルダ構成（flat/by_character/numbered）

    Returns:
        ZIPのバイト列
    """
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for i, image in enumerate(images):
            # 画像を取得する
            img_data = _fetch_image(image['url'])
            if img_data is None:
                continue

            # ファイルパスを決定する
            file_path = _build_path(image, i, structure)
            zf.writestr(file_path, img_data)

    zip_buffer.seek(0)
    return zip_buffer.getvalue()

def _fetch_image(url: str) -> bytes | None:
    """URLから画像バイト列を取得する"""
    try:
        if url.startswith('data:'):
            import base64
            _, data = url.split(',', 1)
            return base64.b64decode(data)
        else:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.content
    except Exception:
        return None

def _build_path(image: dict, index: int, structure: str) -> str:
    """ZIPファイル内のパスを組み立てる"""
    name = image.get('name', f'image_{index + 1}.png')
    char = image.get('character_name', 'unknown')

    if structure == 'flat':
        return name
    elif structure == 'by_character':
        return f'{char}/{name}'
    elif structure == 'numbered':
        return f'{str(index + 1).zfill(3)}_{name}'
    return name
```

---

### 6-6. エクスポートルート

#### app/routes/export.py

```python
from flask import Blueprint, render_template, request, send_file, flash
from app.models.image import Image
from app.models.character import Character
from app.services.pdf_service import generate_pdf
from app.services.zip_service import generate_zip
import io

bp = Blueprint('export', __name__)

@bp.route('/')
def index():
    images = Image.query.order_by(Image.created_at.desc()).all()
    characters = Character.query.all()
    return render_template('export/index.html', images=images, characters=characters)

@bp.route('/pdf', methods=['POST'])
def create_pdf():
    """PDFを生成してダウンロードさせる"""
    image_ids = request.form.getlist('image_ids', type=int)
    page_size = request.form.get('page_size', 'a4')
    fit_mode = request.form.get('fit_mode', 'fit')
    bg_color = request.form.get('bg_color', 'white')
    filename = request.form.get('filename', '作品.pdf')

    # 選択された画像を順番通りに取得する
    images = [Image.query.get(id) for id in image_ids if Image.query.get(id)]
    urls = [img.s3_url for img in images if img.s3_url]

    if not urls:
        flash('画像を選択してください', 'error')
        return redirect(url_for('export.index'))

    try:
        pdf_bytes = generate_pdf(urls, page_size, fit_mode, bg_color)
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype='application/pdf',
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        flash(f'PDF生成エラー: {str(e)}', 'error')
        return redirect(url_for('export.index'))

@bp.route('/zip', methods=['POST'])
def create_zip():
    """ZIPファイルを生成してダウンロードさせる"""
    image_ids = request.form.getlist('image_ids', type=int)
    structure = request.form.get('structure', 'flat')
    filename = request.form.get('filename', '画像素材.zip')

    images_data = []
    for id in image_ids:
        img = Image.query.get(id)
        if img:
            images_data.append({
                'url': img.s3_url,
                'name': img.file_name,
                'character_name': img.character.name if img.character else 'unknown'
            })

    if not images_data:
        flash('画像を選択してください', 'error')
        return redirect(url_for('export.index'))

    try:
        zip_bytes = generate_zip(images_data, structure)
        return send_file(
            io.BytesIO(zip_bytes),
            mimetype='application/zip',
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        flash(f'ZIP生成エラー: {str(e)}', 'error')
        return redirect(url_for('export.index'))
```

---

## 7. テンプレート基底（app/templates/base.html）

```html
<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{% block title %}Creator Portal{% endblock %}</title>
  <!-- Tailwind CSS CDN -->
  <script src="https://cdn.tailwindcss.com"></script>
  <!-- htmx（非同期処理用） -->
  <script src="https://unpkg.com/htmx.org@1.9.12"></script>
</head>
<body class="bg-gray-50 text-gray-900">

  <!-- ナビゲーションバー -->
  <nav class="bg-white border-b border-gray-200 px-6 py-3 flex items-center gap-6">
    <span class="font-semibold text-sm">Creator Portal</span>
    {% set nav_items = [
      ('dashboard.index', 'ダッシュボード'),
      ('story.index', 'ストーリー'),
      ('text_gen.index', 'テキスト生成'),
      ('image.index', '画像'),
      ('export.index', 'PDF/ZIP'),
      ('character.index', 'キャラ'),
      ('work.index', '作品'),
      ('prompt.index', 'プロンプト'),
      ('sales.index', '売上'),
    ] %}
    {% for endpoint, label in nav_items %}
    <a href="{{ url_for(endpoint) }}"
       class="text-sm {% if request.endpoint and request.endpoint.startswith(endpoint.split('.')[0]) %}text-gray-900 font-medium border-b-2 border-gray-900{% else %}text-gray-500 hover:text-gray-900{% endif %}">
      {{ label }}
    </a>
    {% endfor %}
  </nav>

  <!-- フラッシュメッセージ -->
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
      <div class="max-w-6xl mx-auto px-6 mt-4">
        {% for category, message in messages %}
          <div class="px-4 py-3 rounded-lg text-sm mb-2
            {% if category == 'success' %}bg-green-50 text-green-800
            {% elif category == 'error' %}bg-red-50 text-red-800
            {% else %}bg-blue-50 text-blue-800{% endif %}">
            {{ message }}
          </div>
        {% endfor %}
      </div>
    {% endif %}
  {% endwith %}

  <!-- メインコンテンツ -->
  <main class="max-w-6xl mx-auto px-6 py-6">
    {% block content %}{% endblock %}
  </main>

</body>
</html>
```

---

## 8. 実装優先順位

### Phase 1 — MVP（最優先）

1. `app/__init__.py`・`config.py`・`run.py` の初期設定
2. 全モデル定義 + `flask db init && flask db migrate && flask db upgrade`
3. キャラクター管理 CRUD
4. ストーリー生成（Claude API）
5. プロンプトライブラリ（AI生成 + 手動）

### Phase 2

6. テキスト生成（Pixiv / DLsite / PictSpace）
7. 作品管理 CRUD
8. ダッシュボード
9. 売上管理

### Phase 3

10. S3連携（画像アップロード・一覧取得）
11. PDF書き出し（fpdf2）
12. ZIP書き出し（zipfile）

---

## 9. デプロイ（Render.com 推奨）

```bash
# Render.comの設定
# Build Command:
pip install -r requirements.txt && flask db upgrade

# Start Command:
gunicorn run:app

# 環境変数（Render.comのダッシュボードで設定）:
# FLASK_SECRET_KEY, DATABASE_URL, ANTHROPIC_API_KEY,
# AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_S3_BUCKET, AWS_S3_REGION
```

---

## 10. Cursorへの指示例

```
@PROJECT_BRIEF.md の6-1ストーリー生成の仕様に基づいて、
app/routes/story.py と app/templates/story/index.html を実装してください。
htmxを使ってAI生成結果をページ遷移なしで表示してください。
```

```
@PROJECT_BRIEF.md の4章のモデル定義をすべてapp/models/に実装して、
flask db migrate用のマイグレーションファイルも生成してください。
```

```
@PROJECT_BRIEF.md の6-4 PDF生成サービスをapp/services/pdf_service.pyに
実装してください。fpdf2とPillowを使用してください。
```
