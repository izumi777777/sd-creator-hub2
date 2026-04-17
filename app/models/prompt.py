"""プロンプトライブラリモデル。"""

from datetime import datetime

from app import db


class Prompt(db.Model):
    """プロンプトライブラリ。"""

    __tablename__ = "prompts"

    id = db.Column(db.Integer, primary_key=True)
    character_id = db.Column(db.Integer, db.ForeignKey("characters.id"), nullable=False)
    situation = db.Column(db.String(100))
    positive = db.Column(db.Text)
    negative = db.Column(db.Text)
    model = db.Column(db.String(100))
    notes = db.Column(db.Text)
    used_count = db.Column(db.Integer, default=0)
    is_starred = db.Column(db.Boolean, default=False)
    story_chapter_id = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
