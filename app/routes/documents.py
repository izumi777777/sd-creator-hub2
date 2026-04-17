"""請求書・PDF などのドキュメントアップロード（S3）。"""

import io
import uuid

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

from app import db
from app.models.stored_document import StoredDocument
from app.services import s3_service

bp = Blueprint("documents", __name__)

_MAX_BYTES = 30 * 1024 * 1024
_ALLOWED_EXT = frozenset({".pdf", ".png", ".jpg", ".jpeg", ".webp"})

_CATEGORIES = {
    StoredDocument.CATEGORY_INVOICE,
    StoredDocument.CATEGORY_RECEIPT,
    StoredDocument.CATEGORY_CONTRACT,
    StoredDocument.CATEGORY_OTHER,
}


def _mime_for_filename(name: str) -> str:
    lower = name.lower()
    if lower.endswith(".pdf"):
        return "application/pdf"
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if lower.endswith(".webp"):
        return "image/webp"
    return "application/octet-stream"


@bp.route("/")
def index():
    """一覧・フィルタ・アップロードフォーム。"""
    month = (request.args.get("month") or "").strip()
    q = StoredDocument.query
    if month and len(month) == 7 and month[4] == "-":
        q = q.filter_by(related_month=month)
    docs = q.order_by(StoredDocument.created_at.desc()).all()
    s3_ok = s3_service.is_s3_configured()
    return render_template(
        "documents/index.html",
        documents=docs,
        filter_month=month,
        s3_configured=s3_ok,
    )


@bp.route("/upload", methods=["POST"])
def upload():
    """S3 に保存し DB に登録。"""
    if not s3_service.is_s3_configured():
        flash("S3 が未設定です。.env の AWS_S3_BUCKET 等を確認してください。", "error")
        return redirect(url_for("documents.index"))

    file = request.files.get("file")
    if not file or not file.filename or not file.filename.strip():
        flash("ファイルを選択してください。", "error")
        return redirect(url_for("documents.index"))

    safe_name = secure_filename(file.filename)
    if not safe_name:
        flash("ファイル名が無効です。", "error")
        return redirect(url_for("documents.index"))

    ext = ""
    if "." in safe_name:
        ext = "." + safe_name.rsplit(".", 1)[-1].lower()
    if ext not in _ALLOWED_EXT:
        flash("対応形式: PDF, PNG, JPG, JPEG, WEBP のみです。", "error")
        return redirect(url_for("documents.index"))

    data = file.read()
    size = len(data)
    if size == 0:
        flash("空のファイルはアップロードできません。", "error")
        return redirect(url_for("documents.index"))
    if size > _MAX_BYTES:
        flash("ファイルは 30MB 以下にしてください。", "error")
        return redirect(url_for("documents.index"))

    title = (request.form.get("title") or "").strip()[:200] or safe_name
    cat = (request.form.get("doc_category") or "").strip()
    if cat not in _CATEGORIES:
        cat = StoredDocument.CATEGORY_OTHER

    related_month = (request.form.get("related_month") or "").strip()
    if related_month and (len(related_month) != 7 or related_month[4] != "-"):
        related_month = None

    notes = (request.form.get("notes") or "").strip() or None

    unique = f"{uuid.uuid4().hex[:12]}_{safe_name}"
    s3_key = f"documents/{unique}"
    mime = _mime_for_filename(safe_name)
    buf = io.BytesIO(data)
    try:
        url = s3_service.upload_file(buf, s3_key, content_type=mime)
    except Exception as e:
        flash(f"S3 アップロードに失敗しました: {e}", "error")
        return redirect(url_for("documents.index"))

    doc = StoredDocument(
        title=title,
        doc_category=cat,
        related_month=related_month,
        file_name=safe_name,
        s3_key=s3_key,
        s3_url=url,
        mime_type=mime,
        file_size=size,
        notes=notes,
    )
    db.session.add(doc)
    db.session.commit()
    flash("ドキュメントを保存しました。一覧からダウンロードできます。", "success")
    redir = url_for("documents.index")
    if related_month:
        redir = url_for("documents.index", month=related_month)
    return redirect(redir)


@bp.route("/<int:did>/download")
def download(did: int):
    """署名付き URL へリダイレクト（プライベートバケット対応）。"""
    doc = StoredDocument.query.get_or_404(did)
    if not doc.s3_key:
        abort(404)
    try:
        url = s3_service.get_presigned_url(doc.s3_key, expiration=3600)
        return redirect(url, code=302)
    except Exception:
        abort(502)


@bp.route("/<int:did>/delete", methods=["POST"])
def delete(did: int):
    doc = StoredDocument.query.get_or_404(did)
    db.session.delete(doc)
    db.session.commit()
    flash("書類の登録を削除しました（S3 上のファイルは手動削除が必要な場合があります）。", "success")
    return redirect(url_for("documents.index"))
