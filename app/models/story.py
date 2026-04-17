"""ストーリー管理モデル。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app import db


class Story(db.Model):
    """ストーリー管理。"""

    __tablename__ = "stories"

    SPEECH_PRESET_SLOTS = 10

    id = db.Column(db.Integer, primary_key=True)
    character_id = db.Column(db.Integer, db.ForeignKey("characters.id"), nullable=False)
    title = db.Column(db.String(200))
    overview = db.Column(db.Text)
    # 長文ストーリー本文（シーン見出し付きナレーション）
    narrative = db.Column(db.Text)
    # 全シーン共通の衣装・外見の日本語まとめ
    common_setting = db.Column(db.Text)
    genre = db.Column(db.String(100))
    tone = db.Column(db.String(100))
    premise = db.Column(db.Text)
    # 生成時に使ったベースプロンプト（ライブラリ要約・手入力）のスナップショット
    prompt_basis = db.Column(db.Text)
    chapters_json = db.Column(db.Text)
    # 画像焼き込み用のセリフ定型文（JSON 配列・最大 SPEECH_PRESET_SLOTS 要素）
    speech_presets_json = db.Column(db.Text)
    # Pixiv 等へそのまま貼る想定の投稿文案（Gemini 回答を整形して保存）
    pixiv_post_title = db.Column(db.String(500))
    pixiv_post_caption = db.Column(db.Text)
    pixiv_post_tags = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def get_chapters(self) -> list[dict]:
        """章データをリストで返す。不正な JSON の場合は空リスト。"""
        if not self.chapters_json:
            return []
        try:
            data = json.loads(self.chapters_json)
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []

    def set_chapters(self, chapters: list[dict]) -> None:
        """章データを JSON に変換して保存する。"""
        self.chapters_json = json.dumps(chapters, ensure_ascii=False)

    def get_speech_presets(self) -> list[str]:
        """セリフプリセットを長さ SPEECH_PRESET_SLOTS のリストで返す（未設定は空文字）。"""
        n = self.SPEECH_PRESET_SLOTS
        raw = (self.speech_presets_json or "").strip()
        if not raw:
            return [""] * n
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return [""] * n
        if not isinstance(data, list):
            return [""] * n
        out: list[str] = []
        for i in range(n):
            if i < len(data) and data[i] is not None:
                out.append(str(data[i]))
            else:
                out.append("")
        return out

    def set_speech_presets(self, lines: list[str]) -> None:
        """セリフプリセットを保存する（先頭 SPEECH_PRESET_SLOTS 件のみ保持）。"""
        n = self.SPEECH_PRESET_SLOTS
        normalized: list[str] = []
        for i in range(n):
            if i < len(lines) and lines[i] is not None:
                normalized.append(str(lines[i]))
            else:
                normalized.append("")
        self.speech_presets_json = json.dumps(normalized, ensure_ascii=False)

    def find_chapter_by_no(self, ch_no: int | None) -> dict[str, Any] | None:
        """シーン番号 no（または配列順）に一致する章 dict を返す。"""
        if ch_no is None or ch_no < 1:
            return None
        for i, ch in enumerate(self.get_chapters()):
            if not isinstance(ch, dict):
                continue
            no = ch.get("no")
            try:
                n = int(no) if no is not None else i + 1
            except (TypeError, ValueError):
                n = i + 1
            if n == ch_no:
                return ch
        return None


def get_chapter_speech_presets(chapter: dict[str, Any] | None) -> list[str]:
    """chapters_json の 1 要素からセリフプリセット10枠を返す（キー欠損時は空文字）。"""
    n = Story.SPEECH_PRESET_SLOTS
    if not isinstance(chapter, dict):
        return [""] * n
    raw = chapter.get("speech_presets")
    if raw is None:
        return [""] * n
    if not isinstance(raw, list):
        return [""] * n
    out: list[str] = []
    for i in range(n):
        if i < len(raw) and raw[i] is not None:
            out.append(str(raw[i]))
        else:
            out.append("")
    return out


def set_chapter_speech_presets(chapter: dict[str, Any], lines: list[str]) -> None:
    """章 dict に speech_presets を書き込む（全枠空ならキー削除）。"""
    n = Story.SPEECH_PRESET_SLOTS
    normalized: list[str] = []
    for i in range(n):
        if i < len(lines) and lines[i] is not None:
            normalized.append(str(lines[i]))
        else:
            normalized.append("")
    if not any(x.strip() for x in normalized):
        chapter.pop("speech_presets", None)
    else:
        chapter["speech_presets"] = normalized


def resolve_speech_bottom_override(
    story: Story,
    chapter: dict[str, Any] | None,
    preset_idx: int | None,
) -> str | None:
    """
    プリセット番号に対応する下段セリフ上書き文を返す。

    シーンの該当枠が空ならストーリー共通枠へフォールバック。
    両方空のときは None（呼び出し側で章／パターンの speech を使う）。
    """
    if preset_idx is None:
        return None
    n = Story.SPEECH_PRESET_SLOTS
    if preset_idx < 0 or preset_idx >= n:
        return None
    if isinstance(chapter, dict):
        cps = get_chapter_speech_presets(chapter)
        t = cps[preset_idx].strip()
        if t:
            return t
    t2 = story.get_speech_presets()[preset_idx].strip()
    return t2 if t2 else None
