"""アプリケーション設定を読み込むモジュール。"""

import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

# カレントディレクトリに依存しないよう、リポジトリ直下の .env を優先して読む
_root = Path(__file__).resolve().parent
load_dotenv(_root / ".env")
load_dotenv()  # 環境変数が既にあればそちらを優先

# Flask の慣例どおり、DATABASE_URL 未指定時は instance 配下の SQLite（cwd に依存しない）
_instance_dir = _root / "instance"
_instance_dir.mkdir(parents=True, exist_ok=True)
_default_sqlite_path = (_instance_dir / "creator_portal.db").resolve()
_DEFAULT_DATABASE_URL = f"sqlite:///{_default_sqlite_path.as_posix()}"


class Config:
    """アプリケーション設定。"""

    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev-key-change-in-production")
    _configured_db_url = os.environ.get("DATABASE_URL", _DEFAULT_DATABASE_URL)
    SQLALCHEMY_DATABASE_URI = _configured_db_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # ブラウザが多数の /image/*/preview を同時に叩くと、S3 待ちのあいだ接続がプールを占有しやすい。
    # SQLite は既定のまま（pool_pre_ping のみ）。Postgres / MySQL 等はプールを広げる。
    _db_scheme = (_configured_db_url or "").strip().split(":", 1)[0].lower()
    if _db_scheme.startswith("sqlite"):
        SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    else:
        try:
            _pool_size = int(os.environ.get("DB_POOL_SIZE", "10"))
        except ValueError:
            _pool_size = 10
        try:
            _max_overflow = int(os.environ.get("DB_MAX_OVERFLOW", "30"))
        except ValueError:
            _max_overflow = 30
        try:
            _pool_timeout = float(os.environ.get("DB_POOL_TIMEOUT", "60"))
        except ValueError:
            _pool_timeout = 60.0
        SQLALCHEMY_ENGINE_OPTIONS = {
            "pool_pre_ping": True,
            "pool_size": max(1, min(_pool_size, 50)),
            "max_overflow": max(0, min(_max_overflow, 100)),
            "pool_timeout": max(5.0, min(_pool_timeout, 300.0)),
        }
    # Google Gemini（AI Studio の API キー。GOOGLE_API_KEY でも可）
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
    GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
    # 既定は Flash（コスト・速度向け）。gemini.google.com の「Gemini 3.1 Pro」に API でも揃える場合は
    # 公式 ID の gemini-3.1-pro-preview を .env の GEMINI_MODEL に指定する（課金・レート枠は別途確認）。
    # 一覧: https://ai.google.dev/gemini-api/docs/models
    GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")
    # ストーリー生成・加筆修正は chapters + narrative など JSON が大きくなりやすい。8192 では途中切断しがち。
    # モデル上限内で調整（Gemini 3.1 Pro は出力 65536 まで。環境で下げたい場合は数値を指定）。
    _story_tok_raw = os.environ.get("GEMINI_STORY_MAX_OUTPUT_TOKENS", "65536")
    try:
        _stv = int(_story_tok_raw)
        GEMINI_STORY_MAX_OUTPUT_TOKENS = max(4096, min(_stv, 65536))
    except ValueError:
        GEMINI_STORY_MAX_OUTPUT_TOKENS = 65536
    # ログレベル（DEBUG / INFO / WARNING …）。Gemini 生成の試行ログは INFO。
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

    AWS_PROFILE = os.environ.get("AWS_PROFILE")
    AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY")
    AWS_S3_BUCKET = os.environ.get(
        "AWS_S3_BUCKET", "stable-diffusion-ai-illustration-media"
    )
    AWS_S3_REGION = os.environ.get("AWS_S3_REGION", "ap-northeast-1")
    # MinIO / LocalStack / PrivateLink 等（未設定なら AWS 本番向け既定エンドポイント）
    _ep = (os.environ.get("AWS_S3_ENDPOINT_URL") or "").strip()
    AWS_S3_ENDPOINT_URL = _ep or None

    # AUTOMATIC1111（EC2 等）の REST API。未設定なら章からの API 生成は無効。
    SD_WEBUI_BASE_URL = (os.environ.get("SD_WEBUI_BASE_URL") or "").strip().rstrip("/")
    _timeout_raw = os.environ.get("SD_WEBUI_TIMEOUT", "600")
    try:
        SD_WEBUI_TIMEOUT = max(30.0, float(_timeout_raw))
    except ValueError:
        SD_WEBUI_TIMEOUT = 600.0
    SD_WEBUI_DEFAULT_CHECKPOINT = (
        os.environ.get("SD_WEBUI_DEFAULT_CHECKPOINT") or ""
    ).strip()
    # txt2img の幅・高さを何ピクセル単位で揃えるか。空=自動（ckpt 名に xl/sdxl 等が含まれるとき 64、それ以外 8）。
    # SDXL 系で Web UI より崩れる場合は SD_TXT2IMG_GRID_ALIGN=64 を明示。
    SD_TXT2IMG_GRID_ALIGN = (os.environ.get("SD_TXT2IMG_GRID_ALIGN") or "").strip()
    # 1（既定）でキャラの LoRA をプロンプト末尾に自動付与。Web UI と同じ文言にしたい場合は 0。
    SD_TXT2IMG_APPEND_LORA = os.environ.get(
        "SD_TXT2IMG_APPEND_LORA", "1"
    ).strip().lower() not in ("0", "false", "no", "off")
    # 章画像（今すぐ生成・予約）: title+scene を上段、speech を下段に焼き込む。0 で無効。
    STORY_IMAGE_TEXT_OVERLAY = os.environ.get(
        "STORY_IMAGE_TEXT_OVERLAY", "1"
    ).strip().lower() not in ("0", "false", "no", "off")
    # 任意。未設定なら Windows の Meiryo 等を自動検出。
    _overlay_font = (os.environ.get("STORY_OVERLAY_FONT_PATH") or "").strip()
    STORY_OVERLAY_FONT_PATH = _overlay_font or None
    # ギャラリー用のまとめ署名（描画時に S3 でキー解決＋署名）。件数が多いとページが重くなるため上限を設ける。
    # ストーリー一覧は画像が全ストーリー分まとまるため既定はオフ（1/true で有効化）。
    STORY_INDEX_GALLERY_PRESIGN = os.environ.get(
        "STORY_INDEX_GALLERY_PRESIGN", ""
    ).strip().lower() in ("1", "true", "yes", "on")
    _idx_presign_max = os.environ.get("STORY_INDEX_GALLERY_PRESIGN_MAX", "48")
    try:
        STORY_INDEX_GALLERY_PRESIGN_MAX = max(0, min(int(_idx_presign_max), 200))
    except ValueError:
        STORY_INDEX_GALLERY_PRESIGN_MAX = 48
    _detail_presign_max = os.environ.get("STORY_DETAIL_GALLERY_PRESIGN_MAX", "72")
    try:
        STORY_DETAIL_GALLERY_PRESIGN_MAX = max(0, min(int(_detail_presign_max), 500))
    except ValueError:
        STORY_DETAIL_GALLERY_PRESIGN_MAX = 72
    _img_list_presign_max = os.environ.get("IMAGE_LIST_GALLERY_PRESIGN_MAX", "120")
    try:
        IMAGE_LIST_GALLERY_PRESIGN_MAX = max(0, min(int(_img_list_presign_max), 500))
    except ValueError:
        IMAGE_LIST_GALLERY_PRESIGN_MAX = 120
    # 予約生成: 1 のとき run.py / gunicorn 起動中にバックグラウンドで期限到来ジョブを実行
    SD_SCHEDULER_ENABLED = os.environ.get("SD_SCHEDULER_ENABLED", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    _poll_raw = os.environ.get("SD_SCHEDULER_POLL_SECONDS", "60")
    try:
        SD_SCHEDULER_POLL_SECONDS = max(15, min(int(_poll_raw), 3600))
    except ValueError:
        SD_SCHEDULER_POLL_SECONDS = 60
    # datetime-local（オフセットなし）をどの地域時刻として解釈し UTC に直すか（IANA）。サーバが UTC のとき必須。
    SD_SCHEDULER_TIMEZONE = (os.environ.get("SD_SCHEDULER_TIMEZONE") or "Asia/Tokyo").strip()
    _stale_run = os.environ.get("SD_SCHEDULER_STALE_RUNNING_MINUTES", "180")
    try:
        SD_SCHEDULER_STALE_RUNNING_MINUTES = max(30, min(int(_stale_run), 1440))
    except ValueError:
        SD_SCHEDULER_STALE_RUNNING_MINUTES = 180

    # --- インフラ操作コンソール（/ops）---
    OPS_CONSOLE_TOKEN = (os.environ.get("OPS_CONSOLE_TOKEN") or "").strip()
    OPS_EC2_INSTANCE_ID = (os.environ.get("OPS_EC2_INSTANCE_ID") or "").strip()
    OPS_EC2_REGION = (
        os.environ.get("OPS_EC2_REGION") or os.environ.get("AWS_S3_REGION") or "ap-northeast-1"
    ).strip()
    # ナビ表示: トークン・インスタンス ID・OPS_INFRA_NAV・ローカル無認証のいずれか。
    _ops_infra_nav_flag = os.environ.get("OPS_INFRA_NAV", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    # ローカル専用: 1 のとき OPS_CONSOLE_TOKEN なしで /ops を利用可（本番では絶対に付けないこと）
    OPS_CONSOLE_NO_PASSWORD = os.environ.get("OPS_CONSOLE_NO_PASSWORD", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    OPS_INFRA_NAV_VISIBLE = (
        bool(OPS_CONSOLE_TOKEN)
        or bool(OPS_EC2_INSTANCE_ID)
        or _ops_infra_nav_flag
        or OPS_CONSOLE_NO_PASSWORD
    )
    OPS_CONSOLE_ENABLED = bool(OPS_CONSOLE_TOKEN) or OPS_CONSOLE_NO_PASSWORD

    # セッション寿命（長期運用で SD フォーム用キーが増え続ける対策と併用）
    _perm_sess_s = os.environ.get("PERMANENT_SESSION_LIFETIME_SECONDS", "86400")
    try:
        _perm_sess = int(_perm_sess_s)
    except ValueError:
        _perm_sess = 86400
    PERMANENT_SESSION_LIFETIME = timedelta(seconds=max(300, min(_perm_sess, 2592000)))
    # 本番 HTTPS では SESSION_COOKIE_SECURE=1 を推奨（未設定時はローカル HTTP 向けに False）
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    # インフラ画面の USD→JPY 表示用（任意。未設定なら円は出さない）
    _ops_jpy_raw = (os.environ.get("OPS_BILLING_USD_TO_JPY") or "").strip()
    try:
        OPS_BILLING_USD_TO_JPY = float(_ops_jpy_raw) if _ops_jpy_raw else None
    except ValueError:
        OPS_BILLING_USD_TO_JPY = None
