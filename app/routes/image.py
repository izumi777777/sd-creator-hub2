"""画像のアップロード（S3）と DB 登録・一覧。"""

import io
import uuid
from typing import Any

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

from app import db
from app.models.character import Character
from app.models.image import (
    Image,
    STORAGE_ORIGINAL,
    STORAGE_STRIPPED,
    STORAGE_TEXT_OVERLAY,
)
from app.models.story import Story
from app.models.work import Work
from app.services import s3_service

bp = Blueprint("image", __name__)


def delete_portal_image(img: Image) -> tuple[bool, str | None]:
    """
    Image 行を削除し、s3_key があって S3 が有効ならオブジェクトも削除する。

    Returns:
        (True, None) 成功
        (False, message) S3 削除失敗（DB は変更しない）
    """
    key = (img.s3_key or "").strip()
    if key and s3_service.is_s3_configured():
        try:
            s3_service.delete_object(key)
        except Exception as e:
            return False, str(e)
    db.session.delete(img)
    db.session.commit()
    return True, None


_MAX_UPLOAD_FILES = 40
_MAX_BYTES_PER_FILE = 35 * 1024 * 1024
_ALLOWED_STORAGE = frozenset({STORAGE_ORIGINAL, STORAGE_STRIPPED})

# XHR アップロード＋進捗バー用（クライアントが付与）
_JSON_UPLOAD_HEADER = "X-Portal-Image-Upload"


def _guess_content_type(filename: str) -> str:
    """拡張子から簡易 Content-Type。"""
    lower = filename.lower()
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if lower.endswith(".webp"):
        return "image/webp"
    if lower.endswith(".gif"):
        return "image/gif"
    return "application/octet-stream"


@bp.route("/")
def index():
    """登録済み画像一覧。"""
    character_id = request.args.get("character_id", type=int)
    story_id = request.args.get("story_id", type=int)
    storage_folder = (request.args.get("storage_folder") or "").strip()
    q = Image.query
    if character_id:
        q = q.filter_by(character_id=character_id)
    if story_id:
        q = q.filter_by(story_id=story_id)

    filter_storage_folder = (
        storage_folder
        if storage_folder in _ALLOWED_STORAGE or storage_folder == "__legacy__"
        else ""
    )

    images_split = False
    images_original: list[Image] = []
    images_stripped: list[Image] = []
    images_text_overlay: list[Image] = []
    images_legacy: list[Image] = []

    if storage_folder in _ALLOWED_STORAGE:
        q = q.filter_by(storage_folder=storage_folder)
        images = q.order_by(Image.created_at.desc()).all()
    elif storage_folder == "__legacy__":
        q = q.filter(Image.storage_folder.is_(None))
        images = q.order_by(Image.created_at.desc()).all()
    else:
        images_all = q.order_by(Image.created_at.desc()).all()
        images_original = [i for i in images_all if i.storage_folder == STORAGE_ORIGINAL]
        images_stripped = [i for i in images_all if i.storage_folder == STORAGE_STRIPPED]
        images_text_overlay = [
            i for i in images_all if i.storage_folder == STORAGE_TEXT_OVERLAY
        ]
        images_legacy = [i for i in images_all if i.storage_folder is None]
        images = images_all
        images_split = True

    characters = Character.query.order_by(Character.name).all()
    works = Work.query.order_by(Work.title).all()
    s3_configured = s3_service.is_s3_configured()
    return render_template(
        "image/index.html",
        images=images,
        images_split=images_split,
        images_original=images_original,
        images_stripped=images_stripped,
        images_text_overlay=images_text_overlay,
        images_legacy=images_legacy,
        characters=characters,
        works=works,
        filter_character_id=character_id,
        filter_story_id=story_id,
        filter_storage_folder=filter_storage_folder,
        s3_configured=s3_configured,
    )


def _upload_wants_json() -> bool:
    return (request.headers.get(_JSON_UPLOAD_HEADER) or "").strip() == "1"


@bp.route("/upload", methods=["POST"])
def upload():
    """ローカルファイルを S3 に送り Image レコードを作成（複数ファイル可・元形式のまま）。"""
    json_mode = _upload_wants_json()

    def json_err(msg: str, status: int = 400, extra: dict | None = None):
        payload: dict = {"ok": False, "message": msg}
        if extra:
            payload["redirect"] = url_for("image.index", **extra)
        return jsonify(payload), status

    def html_err(msg: str, extra: dict | None = None):
        flash(msg, "error")
        return redirect(url_for("image.index", **(extra or {})))

    if not Character.query.first():
        msg = "先にキャラクターを登録してください。"
        if json_mode:
            return json_err(msg)
        flash(msg, "error")
        return redirect(url_for("image.index"))

    character_id = request.form.get("character_id", type=int)
    work_id = request.form.get("work_id", type=int) or None
    story_id = request.form.get("story_id", type=int) or None
    storage_folder = (request.form.get("storage_folder") or "").strip()
    if storage_folder not in _ALLOWED_STORAGE:
        storage_folder = STORAGE_ORIGINAL

    raw_files = request.files.getlist("file")
    files = [f for f in raw_files if f and f.filename and f.filename.strip()]

    if not character_id or not files:
        msg = "キャラクターとファイルを指定してください。"
        if json_mode:
            return json_err(msg)
        return html_err(msg)

    if len(files) > _MAX_UPLOAD_FILES:
        msg = f"一度にアップロードできるのは {_MAX_UPLOAD_FILES} 枚までです。"
        if json_mode:
            return json_err(msg)
        flash(msg, "error")
        return redirect(url_for("image.index"))

    character = Character.query.get(character_id)
    if not character:
        msg = "キャラクターが見つかりません。"
        if json_mode:
            return json_err(msg, status=404)
        abort(404)

    if story_id:
        st = Story.query.get(story_id)
        if not st or st.character_id != character_id:
            msg = "ストーリーは選択したキャラクターに属するものを選んでください。"
            if json_mode:
                return json_err(msg, extra={"character_id": character_id})
            return html_err(msg, {"character_id": character_id})

    if work_id:
        w = Work.query.get(work_id)
        if not w or w.character_id != character_id:
            msg = "作品は選択したキャラクターに属するものを選んでください。"
            if json_mode:
                return json_err(msg, extra={"character_id": character_id})
            return html_err(msg, {"character_id": character_id})

    prefix = secure_filename(character.name) or f"char_{character.id}"

    ok = 0
    failures: list[str] = []
    mb_limit = _MAX_BYTES_PER_FILE // (1024 * 1024)

    for file in files:
        safe_name = secure_filename(file.filename)
        if not safe_name:
            failures.append("（無効なファイル名）")
            continue

        data = file.read()
        size = len(data)
        if size == 0:
            failures.append(f"{safe_name}: 空ファイル")
            continue
        if size > _MAX_BYTES_PER_FILE:
            failures.append(f"{safe_name}: {mb_limit}MB 超")
            continue

        unique_key = f"{uuid.uuid4().hex[:12]}_{safe_name}"
        s3_key = f"{prefix}/{storage_folder}/{unique_key}"
        buf = io.BytesIO(data)
        try:
            content_type = _guess_content_type(safe_name)
            url = s3_service.upload_image(buf, s3_key, content_type=content_type)
        except ValueError as e:
            failures.append(f"{safe_name}: {e}")
            continue
        except Exception as e:
            failures.append(f"{safe_name}: S3 失敗 ({e})")
            continue

        img = Image(
            character_id=character_id,
            work_id=work_id,
            story_id=story_id,
            storage_folder=storage_folder,
            s3_key=s3_key,
            s3_url=url,
            file_name=safe_name,
            file_size=size,
        )
        db.session.add(img)
        try:
            db.session.commit()
            ok += 1
        except Exception as e:
            db.session.rollback()
            failures.append(f"{safe_name}: DB 失敗 ({e})")

    redir_kw: dict = {"character_id": character_id}
    if story_id:
        redir_kw["story_id"] = story_id
    redir_kw["storage_folder"] = storage_folder
    next_url = url_for("image.index", **redir_kw)

    if ok and not failures:
        msg = f"{ok} 件の画像をアップロードして登録しました。"
        flash(msg, "success")
    elif ok:
        tail = "; ".join(failures[:5])
        if len(failures) > 5:
            tail += " …"
        msg = f"{ok} 件を登録しました。スキップ・失敗: {tail}"
        flash(msg, "warning")
    else:
        tail = "; ".join(failures[:8])
        msg = f"登録できませんでした: {tail}"
        flash(msg, "error")

    if json_mode:
        return (
            jsonify(
                {
                    "ok": ok > 0,
                    "redirect": next_url,
                    "message": msg,
                }
            ),
            200,
        )

    return redirect(next_url)


@bp.route("/<int:iid>/preview")
def preview(iid: int):
    """
    ブラウザ用プレビュー。プライベートバケットでも表示できるよう署名付き URL へリダイレクトする。
    DB のキーと S3 実体がずれる場合は head_object で解決できるキーへフォールバックする。
    """
    img = Image.query.get_or_404(iid)
    if not img.s3_key:
        abort(404)
    try:
        key = s3_service.find_existing_portal_image_s3_key(
            img.s3_key,
            file_name=img.file_name,
            s3_url=img.s3_url,
        )
        if not key:
            abort(404)
        url = s3_service.get_presigned_url(key, expiration=3600)
        return redirect(url, code=302)
    except HTTPException:
        raise
    except Exception:
        current_app.logger.exception("image preview: S3 解決または署名付き URL 生成に失敗 iid=%s", iid)
        abort(502)


@bp.route("/<int:iid>/download")
def download(iid: int):
    """署名付き URL へリダイレクトし、ブラウザでファイル保存として扱わせる。"""
    img = Image.query.get_or_404(iid)
    if not img.s3_key:
        abort(404)
    hint = (img.file_name or "").strip() or f"portal_image_{iid}.png"
    try:
        key = s3_service.find_existing_portal_image_s3_key(
            img.s3_key,
            file_name=img.file_name,
            s3_url=img.s3_url,
        )
        if not key:
            abort(404)
        url = s3_service.get_presigned_download_url(
            key, download_filename=hint, expiration=3600
        )
        return redirect(url, code=302)
    except HTTPException:
        raise
    except Exception:
        current_app.logger.exception("image download: S3 解決または署名付き URL 生成に失敗 iid=%s", iid)
        abort(502)


def _redirect_image_index_from_bulk_form() -> Any:
    """一括削除後、フィルタを維持して画像一覧へ戻す。"""
    kw: dict[str, Any] = {}
    c = request.form.get("redirect_character_id", type=int)
    s = request.form.get("redirect_story_id", type=int)
    sf = (request.form.get("redirect_storage_folder") or "").strip()
    if c:
        kw["character_id"] = c
    if s:
        kw["story_id"] = s
    if sf in _ALLOWED_STORAGE or sf == "__legacy__":
        kw["storage_folder"] = sf
    return redirect(url_for("image.index", **kw))


_MAX_BULK_IMAGE_DELETE = 80


@bp.route("/bulk-delete", methods=["POST"])
def bulk_delete():
    """チェックした複数 Image を S3＋DB から削除する。"""
    raw = request.form.getlist("image_ids")
    ids: list[int] = []
    for x in raw:
        try:
            ids.append(int(x))
        except (TypeError, ValueError):
            continue
    ids = list(dict.fromkeys(ids))[:_MAX_BULK_IMAGE_DELETE]
    if not ids:
        flash("削除する画像を選択してください。", "warning")
        return _redirect_image_index_from_bulk_form()

    deleted = 0
    failed: list[str] = []
    for iid in ids:
        img = Image.query.get(iid)
        if not img:
            failed.append(f"ID{iid}: 見つかりません")
            continue
        ok, err = delete_portal_image(img)
        if ok:
            deleted += 1
        else:
            failed.append(f"ID{iid}: {err}")

    if deleted:
        flash(f"{deleted} 件の画像を削除しました（S3 オブジェクトも削除済みのものがあります）。", "success")
    if failed:
        tail = "; ".join(failed[:12])
        if len(failed) > 12:
            tail += " …"
        flash(f"削除できなかった項目: {tail}", "error" if deleted == 0 else "warning")
    return _redirect_image_index_from_bulk_form()


@bp.route("/<int:iid>/delete", methods=["POST"])
def delete(iid: int):
    """DB から画像レコードを削除し、S3 キーがあればオブジェクトも削除する。"""
    img = Image.query.get_or_404(iid)
    ok, err = delete_portal_image(img)
    if not ok:
        flash(
            f"S3 の削除に失敗しました（DB レコードは削除しませんでした）: {err}",
            "error",
        )
        return redirect(url_for("image.index"))
    flash("画像を削除しました（S3 のオブジェクトも削除済みです）。", "success")
    return redirect(url_for("image.index"))
