"""キャラクターマスタモデル。"""

from datetime import datetime

from app import db


class Character(db.Model):
    """キャラクターマスタ。"""

    __tablename__ = "characters"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    tags = db.Column(db.Text)
    sd_model = db.Column(db.String(200))
    lora_name = db.Column(db.String(200))
    lora_weight = db.Column(db.Float, default=0.8)
    emoji = db.Column(db.String(10), default="🎨")
    color = db.Column(db.String(20), default="purple")
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    works = db.relationship("Work", backref="character", lazy=True)
    prompts = db.relationship("Prompt", backref="character", lazy=True)
    stories = db.relationship("Story", backref="character", lazy=True)
    images = db.relationship("Image", backref="character", lazy=True)

    def tags_list(self) -> list[str]:
        """タグをリストで返す。"""
        if not self.tags:
            return []
        return [t.strip() for t in self.tags.split(",") if t.strip()]
