"""Creator Portal のエントリーポイント。"""

import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    # clone 直後などで flask db upgrade を忘れると no such table になるため、
    # 開発用の python run.py では未適用マイグレーションを自動で流す（gunicorn では通らない）。
    if not os.environ.get("SKIP_AUTO_MIGRATE"):
        with app.app_context():
            from flask_migrate import upgrade

            try:
                upgrade()
            except Exception as e:
                err = str(e)
                if "Can't locate revision" in err or "can't locate revision" in err:
                    import sys

                    sys.stderr.write(
                        "\n[マイグレーション] DB の alembic_version と migrations/versions の内容が一致しません。\n"
                        "  よくある原因: 別PCへソースをコピーしたとき migrations/versions/ の一部が欠けている、\n"
                        "  または instance の SQLite を「新しいDB」と「古いマイグレーション一式」で混在させた。\n"
                        "  対処:\n"
                        "  1) このリポジトリの migrations/versions を丸ごとコピーし直す（特に j3k4l5m6n7o8_*.py）。\n"
                        "  2) そのうえで flask db upgrade を再実行。\n"
                        "  3) 一時的に自動 migrate を止める場合は SKIP_AUTO_MIGRATE=1 python run.py\n"
                        "  詳細: https://alembic.sqlalchemy.org/en/latest/branches.html\n\n"
                    )
                raise
    # 他アプリと 5000 がぶつかる場合があるため、既定は 5050。PORT / FLASK_RUN_PORT で上書き。
    _port_raw = os.environ.get("PORT") or os.environ.get("FLASK_RUN_PORT") or "5050"
    try:
        _port = int(_port_raw)
    except ValueError as e:
        raise SystemExit(
            f"PORT / FLASK_RUN_PORT は整数で指定してください（現在: {_port_raw!r}）"
        ) from e
    _host = os.environ.get("FLASK_RUN_HOST", "127.0.0.1")
    app.run(debug=True, host=_host, port=_port)
