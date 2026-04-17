"""Gemini 等の Markdown 回答を Pixiv 貼り付け向けに整える。"""

from __future__ import annotations

import re


def sanitize_markdown_for_pixiv(text: str) -> str:
    """
    *, >, #, ** などの Markdown を除き、Pixiv の説明欄に近いプレーンテキストにする。
    完璧な CommonMark 対応ではなく、投稿文案でよく出る記号を重点的に除去する。
    """
    if not text or not text.strip():
        return ""

    lines: list[str] = []
    for line in text.splitlines():
        s = line.rstrip()
        stripped = s.strip()
        if stripped in ("---", "***", "___", "- - -"):
            continue
        # 引用
        while stripped.startswith(">"):
            stripped = stripped[1:].lstrip()
        # 見出し # / 全角＃
        stripped = re.sub(r"^[#＃]{1,6}\s*", "", stripped)
        # 番号付きリスト
        stripped = re.sub(r"^\d+\.\s+", "", stripped)
        # 箇条書き
        stripped = re.sub(r"^[\*\-+・]\s+", "", stripped)
        # ネスト箇条書き（先頭の空白+記号）
        stripped = re.sub(r"^\s{1,8}[\*\-+・]\s+", "", stripped)
        # 太字・斜体（同一行内、貪欲でない）
        stripped = re.sub(r"\*\*([^*]+)\*\*", r"\1", stripped)
        stripped = re.sub(r"\*([^*]+)\*", r"\1", stripped)
        stripped = re.sub(r"__([^_]+)__", r"\1", stripped)
        stripped = re.sub(r"_([^_]+)_", r"\1", stripped)
        lines.append(stripped.rstrip())

    out = "\n".join(lines)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def split_gemini_pixiv_sections(raw: str) -> dict[str, str]:
    """
    「### 1. タイトル」「### 2. キャプション」「### 3. タグ」形式のブロックをざっくり分割。
    マッチしない場合は空文字。
    """
    result = {"titles": "", "caption": "", "tags": ""}
    if not raw or not raw.strip():
        return result

    text = raw.strip()
    # ### 1. ... / ## 1. / 1. タイトル など
    pattern = re.compile(
        r"(?:^|\n)(#{1,6}\s*\d+\.\s*[^\n]*|(?<!\d)\d+\.\s*[^\n]*)",
        re.MULTILINE,
    )
    matches = list(pattern.finditer(text))
    if not matches:
        return result

    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        header_line = m.group(0).strip()
        block = text[m.end() : end].strip()
        head_lower = header_line.lower()
        head_compact = re.sub(r"[#＃\s\d\.]", "", header_line)
        if "タイトル" in head_compact or "title" in head_lower:
            result["titles"] = block
        elif "キャプション" in head_compact or "caption" in head_lower:
            result["caption"] = block
        elif "タグ" in head_compact or "tag" in head_lower:
            result["tags"] = block

    return result


def first_japanese_title_candidate(titles_block: str) -> str:
    """タイトル節から最初の「…」形式の候補を返す。"""
    if not titles_block:
        return ""
    m = re.search(r"「[^」]{1,200}」", titles_block)
    if m:
        return m.group(0)
    # 行頭の短い候補（記号のみの行は除外）
    for line in titles_block.splitlines():
        s = line.strip()
        if 2 <= len(s) <= 120 and not s.startswith("*") and "http" not in s.lower():
            if re.match(r"^[\[【（「].*[」）】\]]$", s) or "「" in s:
                return s
    return ""


def tags_block_to_pixiv_lines(tags_block: str) -> str:
    """タグ節をサニタイズ後、1行1タグっぽく整形（空行除去）。"""
    s = sanitize_markdown_for_pixiv(tags_block)
    lines = []
    for line in s.splitlines():
        t = line.strip()
        if not t or t.startswith("（") and "解説" in t:
            continue
        # 先頭の・や-を落とす（sanitize済みでも残る場合）
        t = re.sub(r"^[・\-\*]\s*", "", t)
        if t:
            lines.append(t)
    return "\n".join(lines)
