"""制作フロー用の手動タスク（生成・投稿など）。"""

from datetime import datetime

from app import db


class FlowTask(db.Model):
    """カレンダー／リストに載せるユーザー定義タスク。"""

    __tablename__ = "flow_tasks"

    CATEGORY_GENERATE = "generate"
    CATEGORY_POST = "post"
    CATEGORY_OTHER = "other"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(20), nullable=False, default=CATEGORY_OTHER)
    story_id = db.Column(db.Integer, db.ForeignKey("stories.id", ondelete="SET NULL"))
    due_date = db.Column(db.Date, nullable=True)
    done = db.Column(db.Boolean, nullable=False, default=False)
    done_at = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    story = db.relationship("Story", backref=db.backref("flow_tasks", lazy=True))

    @property
    def category_label(self) -> str:
        return {
            self.CATEGORY_GENERATE: "生成",
            self.CATEGORY_POST: "投稿・販売",
            self.CATEGORY_OTHER: "その他",
        }.get(self.category, self.category)
