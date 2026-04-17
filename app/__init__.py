"""Flask アプリケーションのファクトリ。"""

import logging
import sqlite3
import time

from flask import Flask, got_request_exception, g, has_request_context, request
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from sqlalchemy.engine import Engine

from config import Config

db = SQLAlchemy()
migrate = Migrate()


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    """SQLite 接続時に WAL 等の PRAGMA を付与（PostgreSQL 等では何もしない）。"""
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA cache_size=-65536")
    cursor.execute("PRAGMA temp_store=MEMORY")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _configure_logging(app: Flask) -> None:
    """コンソールへアプリ／AI 生成処理のログを出す。"""
    raw = (app.config.get("LOG_LEVEL") or "INFO").upper()
    level = getattr(logging, raw, logging.INFO)

    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))
        root.addHandler(handler)
        root.setLevel(level)
    else:
        root.setLevel(level)

    app.logger.setLevel(level)

    logging.getLogger("boto3").setLevel(logging.WARNING)
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("s3transfer").setLevel(logging.WARNING)
    logging.getLogger("google").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    app.logger.info("=" * 60)
    app.logger.info("Creator Portal 起動")
    app.logger.info("LOG_LEVEL = %s", raw)
    app.logger.info("=" * 60)


def _should_skip_http_access_log() -> bool:
    """静的アセット等はアクセスログを出さない（ターミナルが埋まるのを防ぐ）。"""
    if not has_request_context():
        return True
    if (request.endpoint or "") == "static":
        return True
    p = request.path or ""
    if p.startswith("/static/") or p == "/favicon.ico":
        return True
    return False


def _register_request_logging(app: Flask) -> None:
    """リクエストの開始・終了と所要時間（遅いページの特定に使う）。"""

    @app.before_request
    def _log_request_start():
        g.request_start_time = time.perf_counter()
        if request.path.startswith("/static") or request.path == "/favicon.ico":
            return
        app.logger.debug(
            "→ %s %s",
            request.method,
            request.path,
        )

    @app.after_request
    def _log_request_end(response):
        if request.path.startswith("/static") or request.path == "/favicon.ico":
            return response
        start = getattr(g, "request_start_time", None)
        if start is not None:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            level = logging.WARNING if elapsed_ms > 3000 else logging.INFO
            app.logger.log(
                level,
                "← %s %s [%d] %dms",
                request.method,
                request.path,
                response.status_code,
                elapsed_ms,
            )
        return response

    def _portal_request_exception(sender, exc: BaseException, **_kwargs):
        if has_request_context() and not _should_skip_http_access_log():
            sender.logger.exception(
                "http: 未処理例外 %s %s endpoint=%s",
                request.method,
                request.path,
                request.endpoint,
            )
        else:
            sender.logger.exception("http: 未処理例外: %s", exc)

    got_request_exception.connect(_portal_request_exception, app)


def create_app() -> Flask:
    """Flask アプリを初期化して返す。"""
    app = Flask(__name__)
    app.config.from_object(Config)
    # Config で既定化済み。ここでは明示的に Flask の永続セッション期限へ反映する。
    app.permanent_session_lifetime = app.config["PERMANENT_SESSION_LIFETIME"]
    _configure_logging(app)

    db.init_app(app)
    migrate.init_app(app, db)

    # モデルを読み込む（マイグレーション検出用）
    from app import models  # noqa: F401

    from app.routes.advisor_chat import (
        bp as advisor_bp,
        register_advisor_context_processor,
    )
    from app.routes.character import bp as character_bp
    from app.routes.dashboard import bp as dashboard_bp
    from app.routes.documents import bp as documents_bp
    from app.routes.export import bp as export_bp
    from app.routes.flow import bp as flow_bp
    from app.routes.image import bp as image_bp
    from app.routes.metadata_strip import bp as metadata_strip_bp
    from app.routes.prompt import bp as prompt_bp
    from app.routes.sales import bp as sales_bp
    from app.routes.story import bp as story_bp
    from app.routes.text_gen import bp as text_gen_bp
    from app.routes.work import bp as work_bp
    from app.routes.ops_console import bp as ops_bp

    @app.context_processor
    def _inject_ops_nav():
        from flask import has_request_context, request

        ui_theme = "light"
        if has_request_context():
            raw = (request.cookies.get("portal_ui_theme") or "light").strip().lower()
            ui_theme = "dark" if raw == "dark" else "light"
        return {
            "ops_console_nav_visible": bool(app.config.get("OPS_INFRA_NAV_VISIBLE")),
            "ui_theme": ui_theme,
        }

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(documents_bp, url_prefix="/documents")
    app.register_blueprint(flow_bp)
    app.register_blueprint(story_bp, url_prefix="/story")
    app.register_blueprint(text_gen_bp, url_prefix="/text-gen")
    app.register_blueprint(image_bp, url_prefix="/image")
    app.register_blueprint(metadata_strip_bp, url_prefix="/metadata-strip")
    app.register_blueprint(export_bp, url_prefix="/export")
    app.register_blueprint(character_bp, url_prefix="/character")
    app.register_blueprint(work_bp, url_prefix="/work")
    app.register_blueprint(prompt_bp, url_prefix="/prompt")
    app.register_blueprint(sales_bp, url_prefix="/sales")
    app.register_blueprint(advisor_bp, url_prefix="/advisor")
    app.register_blueprint(ops_bp)

    register_advisor_context_processor(app)

    from app.cli import register_cli

    register_cli(app)

    if app.config.get("SD_SCHEDULER_ENABLED"):
        from app.services.scheduler_runner import start_background_scheduler

        start_background_scheduler(app)

    _register_request_logging(app)

    return app
