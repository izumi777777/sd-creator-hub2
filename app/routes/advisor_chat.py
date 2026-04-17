"""全ページ共通の Gemini 相談チャット（htmx・セッション会話履歴）。"""

import json
import logging

from flask import Blueprint, render_template, request, session
from google.genai import types

from app import db
from app.prompts.advisor_prompts import (
    ADVISOR_CONTEXT_LABELS,
    ADVISOR_SYSTEM_BY_CONTEXT,
    ALLOWED_ADVISOR_CONTEXTS,
)
from app.services.gemini_service import call_gemini_chat

bp = Blueprint("advisor", __name__)
logger = logging.getLogger(__name__)

_MAX_MESSAGE_CHARS = 12000
_SESSION_KEY = "advisor_chat"
# user/model 交互で1ターン=2要素。長文対策で文字数も上限。
_MAX_HISTORY_ITEMS = 24
_MAX_HISTORY_CHARS = 28000
_SESSION_DRAFT_KEY = "advisor_draft_story"
_MAX_STORY_BUNDLE_CHARS = 38000
_MAX_STORY_CONTEXT_IN_REQUEST = 42000

_HISTORY_HINT = (
    "\n\n【会話モード】このリクエストには、これまでのユーザーとあなたの発話が時系列で渡されます。"
    "直前の文脈を踏まえ、指摘や提案の一貫性を保って答えてください。"
    "初回のみの発話でも通常どおり答えてください。"
)


def default_advisor_context_for_request() -> str:
    """現在の URL（endpoint）から相談モードの既定値を推測する。"""
    ep = request.endpoint or ""
    rules = (
        ("story.", "story"),
        ("text_gen.", "text_gen"),
        ("prompt.", "prompt"),
        ("image.", "image"),
        ("export.", "export"),
        ("sales.", "sales"),
        ("character.", "character"),
        ("work.", "work"),
        ("metadata_strip.", "metadata"),
    )
    for prefix, key in rules:
        if ep.startswith(prefix):
            return key
    return "general"


def format_story_bundle_from_dict(data: dict) -> str:
    """相談用にストーリー JSON（生成結果と同型）をプレーンテキスト化する。"""
    parts: list[str] = []
    t = (data.get("title") or "").strip()
    o = (data.get("overview") or "").strip()
    n = (data.get("narrative") or "").strip()
    cs = (data.get("common_setting") or "").strip()
    if t:
        parts.append(f"【タイトル】\n{t}")
    if o:
        parts.append(f"【短い概要】\n{o}")
    if n:
        parts.append(f"【ストーリー本文】\n{n}")
    if cs:
        parts.append(f"【共通設定（ビジュアル）】\n{cs}")
    chs = data.get("chapters")
    if isinstance(chs, list) and chs:
        parts.append("【シーン一覧（描写・SDプロンプト抜粋）】")
        for ch in chs:
            if not isinstance(ch, dict):
                continue
            no = ch.get("no")
            ti = (ch.get("title") or "").strip()
            sc = (ch.get("scene") or "").strip()[:500]
            pr = (ch.get("prompt") or "").strip()[:400]
            line = f"- シーン{no}: {ti}"
            if sc:
                line += f"\n  描写: {sc}"
            if pr:
                line += f"\n  Positive(抜粋): {pr}"
            parts.append(line)
    text = "\n\n".join(parts).strip()
    if len(text) > _MAX_STORY_BUNDLE_CHARS:
        text = text[:_MAX_STORY_BUNDLE_CHARS] + "\n\n…（長いため省略）"
    return text or "（ストーリー本文なし）"


def _advisor_story_context_for_template() -> tuple[str | None, str | None]:
    """
    相談フォームに載せるストーリー資料とラベル。
    優先: ストーリー詳細ページの保存済み → セッションの生成ドラフト。
    """
    if request.endpoint == "story.detail":
        sid = (request.view_args or {}).get("sid")
        if sid is not None:
            from app.models.story import Story

            st = db.session.get(Story, sid)
            if st is not None:
                bundle = format_story_bundle_from_dict(
                    {
                        "title": st.title,
                        "overview": st.overview,
                        "narrative": st.narrative,
                        "common_setting": st.common_setting,
                        "chapters": st.get_chapters(),
                    }
                )
                label = f"保存済み「{(st.title or '無題')[:36]}{'…' if st.title and len(st.title) > 36 else ''}」"
                return bundle, label
    draft = session.get(_SESSION_DRAFT_KEY)
    if isinstance(draft, str) and draft.strip():
        return draft.strip(), "生成ドラフト（一覧で『相談に渡す』した内容）"
    return None, None


def _history_char_count(turns: list) -> int:
    return sum(len(str(t[1])) for t in turns if len(t) > 1)


def _trim_turns(turns: list) -> list:
    t = [list(x) for x in turns]
    while len(t) > _MAX_HISTORY_ITEMS:
        t = t[2:]
    while _history_char_count(t) > _MAX_HISTORY_CHARS and len(t) > 1:
        t = t[2:]
    return t


def _turns_to_contents(turns: list) -> list:
    out: list = []
    for row in turns:
        role, text = row[0], row[1]
        api_role = "user" if role == "user" else "model"
        out.append(
            types.Content(
                role=api_role,
                parts=[types.Part(text=str(text))],
            )
        )
    return out


@bp.route("/ask", methods=["POST"])
def ask():
    """相談メッセージを送り、会話履歴を踏まえた回答を返す（htmx）。"""
    message = (request.form.get("message") or "").strip()
    ctx = (request.form.get("context") or "general").strip()
    if ctx not in ALLOWED_ADVISOR_CONTEXTS:
        ctx = "general"

    if not message:
        return '<p class="text-red-600 text-sm p-2">メッセージを入力してください。</p>', 400
    if len(message) > _MAX_MESSAGE_CHARS:
        return (
            f'<p class="text-red-600 text-sm p-2">メッセージが長すぎます（最大 {_MAX_MESSAGE_CHARS} 文字）。</p>',
            400,
        )

    raw_state = session.get(_SESSION_KEY)
    if not isinstance(raw_state, dict):
        raw_state = {}
    prev_ctx = raw_state.get("context")
    prev_turns = raw_state.get("turns")
    if not isinstance(prev_turns, list):
        prev_turns = []
    if prev_ctx != ctx:
        prev_turns = []

    turns_for_api = _trim_turns(prev_turns + [["user", message]])
    contents = _turns_to_contents(turns_for_api)

    system = ADVISOR_SYSTEM_BY_CONTEXT[ctx] + _HISTORY_HINT
    attach = request.form.get("attach_story") == "1"
    story_ctx = (request.form.get("story_context") or "").strip()
    if attach and len(story_ctx) > _MAX_STORY_CONTEXT_IN_REQUEST:
        return (
            '<p class="text-red-600 text-sm p-2">ストーリー資料が大きすぎます。ページを再読み込みしてください。</p>',
            400,
        )
    if attach and story_ctx:
        system += (
            "\n\n【参考資料: ユーザーのストーリー作品（タイトル・本文・シーン・プロンプト抜粋）】\n"
            + story_ctx
            + "\n\n（以上は参考。Pixiv のタイトル・キャプション・タグ案など、依頼に応じて内容に沿って提案すること。）"
        )

    logger.info(
        "advisor.ask: context=%s message_chars=%d history_items=%d attach_story=%s endpoint=%s",
        ctx,
        len(message),
        len(contents),
        attach,
        request.endpoint,
    )

    try:
        reply = call_gemini_chat(
            system,
            contents,
            max_tokens=2048,
            log_label=f"advisor.{ctx}",
        )
        new_turns = _trim_turns(turns_for_api + [["model", reply]])
        session[_SESSION_KEY] = {"context": ctx, "turns": new_turns}
        session.modified = True
        return render_template(
            "advisor/response_partial.html",
            reply=reply,
            context_key=ctx,
            history_rounds=len(new_turns) // 2,
        )
    except Exception as e:
        logger.exception("advisor.ask: 失敗 context=%s", ctx)
        return f'<p class="text-red-600 text-sm p-2">エラー: {e}</p>', 500


@bp.route("/clear", methods=["POST"])
def clear_history():
    """会話履歴をセッションから削除する。"""
    session.pop(_SESSION_KEY, None)
    session.pop(_SESSION_DRAFT_KEY, None)
    session.modified = True
    return (
        '<p class="text-xs text-gray-500 p-2 border border-gray-100 rounded-lg bg-gray-50">'
        "会話履歴と、相談に載せていた生成ドラフトをリセットしました。"
        "</p>"
    )


@bp.route("/attach-draft", methods=["POST"])
def attach_draft():
    """生成直後のストーリーをセッションに載せ、相談ドックから参照できるようにする。"""
    raw = (request.form.get("story_snapshot") or "").strip()
    if not raw:
        return '<p class="text-red-600 text-xs p-2">ストーリーデータがありません。</p>', 400
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return '<p class="text-red-600 text-xs p-2">データの形式が不正です。</p>', 400
    if not isinstance(data, dict):
        return '<p class="text-red-600 text-xs p-2">ストーリーデータが不正です。</p>', 400

    text = format_story_bundle_from_dict(data)
    session[_SESSION_DRAFT_KEY] = text
    session.modified = True
    logger.info("advisor.attach_draft: chars=%d", len(text))
    return (
        '<p class="text-xs text-green-800 p-2 border border-green-100 rounded-lg bg-green-50">'
        "相談ドックに載せました。画面下の「Gemini に相談」を開き、"
        "<strong>ストーリー資料を添付</strong>にチェックを入れたまま、"
        "モードを「販売文・キャプション」にして Pixiv 用のタイトル・キャプション・タグを依頼してください。"
        "</p>"
    )


def register_advisor_context_processor(app):
    """テンプレートに相談 UI 用の既定コンテキストとラベル一覧を渡す。"""

    @app.context_processor
    def _inject_advisor():
        st_text, st_label = _advisor_story_context_for_template()
        default_ctx = default_advisor_context_for_request()
        if st_text:
            default_ctx = "text_gen"
        return {
            "advisor_context_default": default_ctx,
            "advisor_context_labels": ADVISOR_CONTEXT_LABELS,
            "advisor_story_context_text": st_text,
            "advisor_story_context_label": st_label,
        }
