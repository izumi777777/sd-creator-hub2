"""請求書・PDF などポータルに保存するドキュメント（S3）。"""

from datetime import datetime

from app import db


class StoredDocument(db.Model):
    """アップロードした PDF / 画像スキャン等のメタデータ。"""

    __tablename__ = "stored_documents"

    CATEGORY_INVOICE = "invoice"
    CATEGORY_RECEIPT = "receipt"
    CATEGORY_CONTRACT = "contract"
    CATEGORY_OTHER = "other"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200))
    doc_category = db.Column(db.String(20), nullable=False, default=CATEGORY_OTHER)
    # 売上メモと揃える任意の月（YYYY-MM）
    related_month = db.Column(db.String(7))
    file_name = db.Column(db.String(255), nullable=False)
    s3_key = db.Column(db.String(500), nullable=False)
    s3_url = db.Column(db.String(500))
    mime_type = db.Column(db.String(120))
    file_size = db.Column(db.Integer)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def category_label(self) -> str:
        return {
            self.CATEGORY_INVOICE: "請求書",
            self.CATEGORY_RECEIPT: "領収書",
            self.CATEGORY_CONTRACT: "契約・覚書",
            self.CATEGORY_OTHER: "その他",
        }.get(self.doc_category, self.doc_category)
