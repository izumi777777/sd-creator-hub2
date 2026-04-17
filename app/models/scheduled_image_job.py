"""ストーリー章の画像生成を指定日時に実行する予約。"""

from datetime import datetime

from app import db


class ScheduledImageJob(db.Model):
    """Web UI 経由の txt2img を、scheduled_at 以降にバックグラウンドで実行する予約。"""

    __tablename__ = "scheduled_image_jobs"

    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_DONE = "done"
    STATUS_FAILED = "failed"
    STATUS_CANCELLED = "cancelled"

    id = db.Column(db.Integer, primary_key=True)
    story_id = db.Column(
        db.Integer, db.ForeignKey("stories.id", ondelete="CASCADE"), nullable=False
    )
    character_id = db.Column(
        db.Integer, db.ForeignKey("characters.id"), nullable=False
    )
    ch_no = db.Column(db.Integer, nullable=False)
    variant_index = db.Column(db.Integer, nullable=True)
    steps = db.Column(db.Integer, nullable=False, default=20)
    width = db.Column(db.Integer, nullable=False, default=512)
    height = db.Column(db.Integer, nullable=False, default=768)
    batch_size = db.Column(db.Integer, nullable=False, default=1)
    n_iter = db.Column(db.Integer, nullable=False, default=1)
    cfg_scale = db.Column(db.Float, nullable=False, default=7.0)
    sampler_name = db.Column(db.String(80), nullable=False, default="Euler a")
    enable_hr = db.Column(db.Boolean, nullable=False, default=False)
    hr_scale = db.Column(db.Float, nullable=False, default=2.0)
    hr_denoising_strength = db.Column(db.Float, nullable=False, default=0.5)
    hr_second_pass_steps = db.Column(db.Integer, nullable=False, default=0)
    hr_upscaler = db.Column(db.String(120), nullable=True)
    seed = db.Column(db.Integer, nullable=True)
    # 画像テキスト焼き込み: 0 のとき上段（title/scene）を省略
    overlay_include_top_story = db.Column(db.Boolean, nullable=False, default=True)
    # 画像テキスト焼き込み: 0 のとき下段のセリフ（speech）のみ省略（上段は設定に従う）
    overlay_include_speech = db.Column(db.Boolean, nullable=False, default=True)
    # NULL=章の speech。0〜9=ストーリー speech_presets_json の該当枠（空なら章にフォールバック）
    speech_preset_index = db.Column(db.Integer, nullable=True)
    scheduled_at = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), nullable=False, default=STATUS_PENDING)
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    story = db.relationship("Story", backref=db.backref("scheduled_image_jobs", lazy=True))
