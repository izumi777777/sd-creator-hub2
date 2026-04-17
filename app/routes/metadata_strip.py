"""ローカルフォルダの画像からメタデータを削除し、キャラ別に振り分ける。"""

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.models.character import Character
from app.services import image_metadata_service as meta_svc

bp = Blueprint("metadata_strip", __name__)


@bp.route("/")
def index():
    """メタデータ削除・振り分けフォーム。"""
    characters = Character.query.order_by(Character.name).all()
    return render_template("metadata_strip/index.html", characters=characters)


@bp.route("/run", methods=["POST"])
def run():
    """フォルダを指定してバッチ処理する。"""
    input_dir = (request.form.get("input_dir") or "").strip()
    output_dir = (request.form.get("output_dir") or "").strip()
    mode = request.form.get("mode", "single_character")
    recursive = bool(request.form.get("recursive"))
    character_id = request.form.get("character_id", type=int)

    if not input_dir or not output_dir:
        flash("インプットフォルダとアウトプットフォルダのパスを入力してください。", "error")
        return redirect(url_for("metadata_strip.index"))

    try:
        if mode == "subfolders":
            ok, errors, warnings = meta_svc.process_subfolders(
                input_dir, output_dir, recursive=recursive
            )
            for w in warnings:
                flash(w, "success")
            if errors:
                for msg in errors[:15]:
                    flash(msg, "error")
                if len(errors) > 15:
                    flash(f"ほか {len(errors) - 15} 件のエラーがあります。", "error")
            flash(f"処理完了: {ok} ファイルを書き出しました。", "success")
        else:
            if not character_id:
                flash("キャラクターを選択してください。", "error")
                return redirect(url_for("metadata_strip.index"))
            char = Character.query.get_or_404(character_id)
            ok, errors = meta_svc.process_single_character(
                input_dir,
                output_dir,
                char.name,
                recursive=recursive,
            )
            if errors:
                for msg in errors[:15]:
                    flash(msg, "error")
                if len(errors) > 15:
                    flash(f"ほか {len(errors) - 15} 件のエラーがあります。", "error")
            flash(
                f"処理完了: {ok} ファイルを「{char.name}」フォルダに書き出しました。",
                "success",
            )
    except ValueError as e:
        flash(str(e), "error")
    except Exception as e:
        flash(f"処理中にエラーが発生しました: {e}", "error")

    return redirect(url_for("metadata_strip.index"))
