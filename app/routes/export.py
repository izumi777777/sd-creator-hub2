"""PDF / ZIP エクスポート。"""

import io

from flask import Blueprint, flash, redirect, render_template, request, send_file, url_for

from app.models.image import Image
from app.services import s3_service
from app.services.pdf_service import generate_pdf
from app.services.zip_service import generate_zip


def _fetch_url_for_image(img: Image) -> str | None:
    """プライベートバケット向けに署名付き URL を優先する。"""
    if img.s3_key:
        try:
            return s3_service.get_presigned_url(img.s3_key, expiration=7200)
        except Exception:
            return img.s3_url
    return img.s3_url

bp = Blueprint("export", __name__)


@bp.route("/")
def index():
    """エクスポート用に画像を選択。"""
    images = Image.query.order_by(Image.created_at.desc()).all()
    return render_template("export/index.html", images=images)


@bp.route("/pdf", methods=["POST"])
def create_pdf():
    """選択画像から PDF をダウンロード。"""
    image_ids = request.form.getlist("image_ids", type=int)
    page_size = request.form.get("page_size", "a4")
    fit_mode = request.form.get("fit_mode", "fit")
    bg_color = request.form.get("bg_color", "white")
    filename = request.form.get("filename", "作品.pdf") or "作品.pdf"

    images = []
    for iid in image_ids:
        row = Image.query.get(iid)
        if row and (row.s3_key or row.s3_url):
            images.append(row)

    urls = [u for img in images if (u := _fetch_url_for_image(img))]

    if not urls:
        flash("S3 に紐づく画像を選択してください。", "error")
        return redirect(url_for("export.index"))

    try:
        pdf_bytes = generate_pdf(urls, page_size, fit_mode, bg_color)  # type: ignore[arg-type]
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename,
        )
    except Exception as e:
        flash(f"PDF 生成エラー: {e}", "error")
        return redirect(url_for("export.index"))


@bp.route("/zip", methods=["POST"])
def create_zip():
    """選択画像から ZIP をダウンロード。"""
    image_ids = request.form.getlist("image_ids", type=int)
    structure = request.form.get("structure", "flat")
    filename = request.form.get("filename", "画像素材.zip") or "画像素材.zip"

    images_data = []
    for iid in image_ids:
        img = Image.query.get(iid)
        u = _fetch_url_for_image(img) if img else None
        if img and u:
            images_data.append(
                {
                    "url": u,
                    "name": img.file_name or f"image_{img.id}.png",
                    "character_name": img.character.name if img.character else "unknown",
                }
            )

    if not images_data:
        flash("S3 に紐づく画像を選択してください。", "error")
        return redirect(url_for("export.index"))

    try:
        zip_bytes = generate_zip(images_data, structure)  # type: ignore[arg-type]
        return send_file(
            io.BytesIO(zip_bytes),
            mimetype="application/zip",
            as_attachment=True,
            download_name=filename,
        )
    except Exception as e:
        flash(f"ZIP 生成エラー: {e}", "error")
        return redirect(url_for("export.index"))
