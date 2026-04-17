"""Flask CLI コマンド登録。"""

import click
from flask import Flask


def register_cli(app: Flask) -> None:
    """アプリに CLI コマンドを付与する。"""

    @app.cli.command("seed-characters")
    def seed_characters() -> None:
        """既存運用キャラ（オーナー定義の11名）を DB に追加。同名はスキップ。"""
        from app.seed_characters import seed_default_characters

        added, skipped = seed_default_characters()
        click.echo(f"キャラクター: {added} 件を追加、{skipped} 件はスキップ（既存同名）。")
