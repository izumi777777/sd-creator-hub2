"""インフラ操作コンソール（EC2 起停・SD Web UI 再起動）。別 URL プレフィックス /ops 。"""

from __future__ import annotations

import secrets
from functools import wraps

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from app.services import ec2_ops_service

bp = Blueprint("ops", __name__, url_prefix="/ops")

_SESSION_OK = "ops_console_ok"


@bp.context_processor
def _ops_template_globals():
    return {
        "ops_no_password": bool(current_app.config.get("OPS_CONSOLE_NO_PASSWORD")),
    }


def _safe_ops_redirect_path(url: str) -> bool:
    u = (url or "").strip()
    return u == "/ops" or u.startswith("/ops/")


def _ops_enabled() -> bool:
    return bool(current_app.config.get("OPS_CONSOLE_ENABLED"))


def _no_password_mode() -> bool:
    return bool(current_app.config.get("OPS_CONSOLE_NO_PASSWORD"))


def _infra_nav_visible() -> bool:
    return bool(current_app.config.get("OPS_INFRA_NAV_VISIBLE"))


def _require_ops_console(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not _infra_nav_visible():
            abort(404)
        if not _ops_enabled():
            return redirect(url_for("ops.setup"))
        if not _no_password_mode() and not session.get(_SESSION_OK):
            return redirect(url_for("ops.login", next=request.path))
        return f(*args, **kwargs)

    return wrapper


@bp.route("/setup")
def setup():
    """トークン未設定時の案内（ナビ表示用）。無パスワードモードではダッシュボードへ。"""
    if not _infra_nav_visible():
        abort(404)
    if _ops_enabled():
        return redirect(url_for("ops.dashboard"))
    return render_template("ops/not_configured.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if not _infra_nav_visible():
        abort(404)
    if _no_password_mode():
        return redirect(url_for("ops.dashboard"))
    if not _ops_enabled():
        return redirect(url_for("ops.setup"))
    if session.get(_SESSION_OK):
        nxt = (request.args.get("next") or "").strip()
        if _safe_ops_redirect_path(nxt):
            return redirect(nxt)
        return redirect(url_for("ops.dashboard"))
    if request.method == "POST":
        raw = (request.form.get("token") or "").strip()
        expected = (current_app.config.get("OPS_CONSOLE_TOKEN") or "").strip()
        if not expected:
            abort(404)
        if len(raw) == len(expected) and secrets.compare_digest(raw, expected):
            session[_SESSION_OK] = True
            flash("インフラコンソールに入りました。", "success")
            nxt = (request.form.get("next") or request.args.get("next") or "").strip()
            if _safe_ops_redirect_path(nxt):
                return redirect(nxt)
            return redirect(url_for("ops.dashboard"))
        flash("トークンが違います。", "error")
    next_url = (request.args.get("next") or "").strip()
    if not _safe_ops_redirect_path(next_url):
        next_url = ""
    return render_template("ops/login.html", next_url=next_url)


@bp.route("/logout", methods=["POST"])
def logout():
    if not _infra_nav_visible():
        abort(404)
    if not _ops_enabled():
        return redirect(url_for("ops.setup"))
    if _no_password_mode():
        flash("パスワード無効モード（ローカル用）ではログアウトは不要です。", "info")
        return redirect(url_for("ops.dashboard"))
    session.pop(_SESSION_OK, None)
    flash("ログアウトしました。", "success")
    return redirect(url_for("ops.login"))


@bp.route("/")
@_require_ops_console
def dashboard():
    iid = (current_app.config.get("OPS_EC2_INSTANCE_ID") or "").strip()
    region = (current_app.config.get("OPS_EC2_REGION") or "ap-northeast-1").strip()
    info = None
    err = None
    if iid:
        info = ec2_ops_service.describe_instance(iid, region)
        if info is None:
            err = "インスタンスを取得できませんでした。ID・リージョン・IAM 権限を確認してください。"
    else:
        err = ".env の OPS_EC2_INSTANCE_ID が未設定です。"
    return render_template(
        "ops/dashboard.html",
        instance_info=info,
        config_error=err,
        instance_id=iid,
        region=region,
    )


@bp.route("/ec2/action", methods=["POST"])
@_require_ops_console
def ec2_action():
    iid = (current_app.config.get("OPS_EC2_INSTANCE_ID") or "").strip()
    region = (current_app.config.get("OPS_EC2_REGION") or "ap-northeast-1").strip()
    if not iid:
        flash("OPS_EC2_INSTANCE_ID が未設定です。", "error")
        return redirect(url_for("ops.dashboard"))

    action = (request.form.get("action") or "").strip().lower()
    if action == "start":
        ok, msg = ec2_ops_service.start_instance(iid, region)
        flash(msg, "success" if ok else "error")
    elif action == "stop":
        ok, msg = ec2_ops_service.stop_instance(iid, region)
        flash(msg, "success" if ok else "error")
    elif action == "restart_sd":
        info = ec2_ops_service.describe_instance(iid, region)
        if not info or info.get("state") != "running":
            flash("running のときのみ Stable Diffusion（systemd）を再起動できます。", "error")
            return redirect(url_for("ops.dashboard"))
        cmd_id, err = ec2_ops_service.restart_sd_webui_via_ssm(iid, region)
        if err:
            flash(f"SSM 送信に失敗しました: {err}", "error")
        else:
            flash(
                f"再起動コマンドを SSM で送信しました。コマンド ID: {cmd_id} "
                f"（数分かかることがあります。AWS コンソールの Run Command で状況を確認できます。）",
                "success",
            )
    else:
        flash("不正な操作です。", "error")
    return redirect(url_for("ops.dashboard"))
