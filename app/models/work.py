"""作品管理モデル。"""

from datetime import datetime

from app import db


class Work(db.Model):
    """作品管理。"""

    __tablename__ = "works"

    STATUS_GENERATING = "generating"
    STATUS_COMPLETED = "completed"
    STATUS_PIXIV = "pixiv"
    STATUS_SALE = "sale"

    id = db.Column(db.Integer, primary_key=True)
    character_id = db.Column(db.Integer, db.ForeignKey("characters.id"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(20), default=STATUS_GENERATING)
    price = db.Column(db.Integer, default=0)
    pixiv_url = db.Column(db.String(500))
    pict_url = db.Column(db.String(500))
    dl_url = db.Column(db.String(500))
    sales_pict = db.Column(db.Integer, default=0)
    sales_dl = db.Column(db.Integer, default=0)
    story_id = db.Column(db.Integer, db.ForeignKey("stories.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    story = db.relationship(
        "Story", backref=db.backref("works", lazy=True), foreign_keys=[story_id]
    )
    images = db.relationship("Image", backref="work", lazy=True)

    @property
    def total_revenue(self) -> int:
        """売上合計を返す（販売数×単価の簡易集計）。"""
        return (self.sales_pict + self.sales_dl) * self.price

    @property
    def status_label(self) -> str:
        """ステータスの日本語ラベルを返す。"""
        labels = {
            "generating": "生成中",
            "completed": "完成",
            "pixiv": "Pixiv投稿済",
            "sale": "販売中",
        }
        return labels.get(self.status, self.status)
