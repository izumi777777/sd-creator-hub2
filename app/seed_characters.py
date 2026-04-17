"""
オーナー既存の制作キャラクター（チェックポイント・LoRA はローカルで確定済み想定）。

ポータル上では名前のひな形を登録し、sd_model / lora_name / tags は各キャラの編集画面で追記する。
"""

from __future__ import annotations

from typing import Any

# 運用中キャラ（表示用に絵文字だけ差し替え。本質は name）
DEFAULT_OWNER_CHARACTERS: list[dict[str, Any]] = [
    {"name": "さゆたそ", "emoji": "🧸"},
    {"name": "あーりゃ", "emoji": "🐱"},
    {"name": "いろは", "emoji": "🍃"},
    {"name": "かなを", "emoji": "🎧"},
    {"name": "まどか", "emoji": "⭐"},
    {"name": "まひる", "emoji": "☀️"},
    {"name": "かおるこ", "emoji": "🌸"},
    {"name": "えみりあ", "emoji": "💎"},
    {"name": "かぐや", "emoji": "🌙"},
    {"name": "かるいざわけい", "emoji": "📚"},
    {"name": "もも", "emoji": "🍑"},
]

DEFAULT_CHARACTER_NOTE = (
    "既存のイラスト制作で継続利用中。チェックポイント・LoRA はローカルで確定済み。"
    " 利用モデル名・LoRA名・タグはこのポータルの「編集」にメモすると、"
    "ストーリー／プロンプト生成や作品管理と一箇所で揃えられる。"
)


def seed_default_characters() -> tuple[int, int]:
    """
    デフォルトキャラを DB に追加する。同名が既にあればスキップ。

    Returns:
        (追加件数, スキップ件数)
    """
    from app import db
    from app.models.character import Character

    added = 0
    skipped = 0

    for row in DEFAULT_OWNER_CHARACTERS:
        name = row["name"]
        if Character.query.filter_by(name=name).first():
            skipped += 1
            continue

        c = Character(
            name=name,
            emoji=row.get("emoji", "🎨"),
            color=row.get("color", "purple"),
            notes=DEFAULT_CHARACTER_NOTE,
        )
        db.session.add(c)
        added += 1

    if added:
        db.session.commit()
    return added, skipped
