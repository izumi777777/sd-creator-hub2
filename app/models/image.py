"""画像管理モデル。"""

from datetime import datetime

from app import db

# S3 上のキャラ配下サブフォルダ（メタデータあり＝原本 / なし＝配布用）
STORAGE_ORIGINAL = "original"
STORAGE_STRIPPED = "stripped"
# 既存画像を元に章の title/scene/speech を焼き増しした別ファイル（元画像は残す）
STORAGE_TEXT_OVERLAY = "text_overlay"


class Image(db.Model):
    """生成画像のメタデータ（S3 連携）。"""

    __tablename__ = "images"

    id = db.Column(db.Integer, primary_key=True)
    character_id = db.Column(db.Integer, db.ForeignKey("characters.id"), nullable=False)
    work_id = db.Column(db.Integer, db.ForeignKey("works.id"))
    story_id = db.Column(db.Integer, db.ForeignKey("stories.id", ondelete="SET NULL"))
    # original / stripped。NULL は移行前などキーにサブフォルダが無いレコード
    storage_folder = db.Column(db.String(20))
    s3_key = db.Column(db.String(500))
    s3_url = db.Column(db.String(500))
    file_name = db.Column(db.String(200))
    file_size = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    story = db.relationship("Story", backref=db.backref("images", lazy=True))
