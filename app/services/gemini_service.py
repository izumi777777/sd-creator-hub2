"""Google Gemini API の呼び出しを集約する（JSON 応答想定）。google-genai SDK 使用。"""

import json
import logging
import time
from typing import Any

from flask import current_app
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

# Gemini クライアントをシングルトン化（都度 new/close のオーバーヘッドを避ける）
_gemini_client: Any | None = None
_gemini_client_api_key: str | None = None
# 成功したモデル名をキャッシュし、次回以降の試行順を短くする
_last_successful_model: str | None = None


def _get_gemini_client(api_key: str) -> Any:
    """Gemini クライアントをシングルトンで返す。API キーが変わったときだけ再作成する。"""
    global _gemini_client, _gemini_client_api_key
    if _gemini_client is None or _gemini_client_api_key != api_key:
        _gemini_client = genai.Client(api_key=api_key)
        _gemini_client_api_key = api_key
    return _gemini_client

_FINISH_OK = frozenset(
    (
        "FinishReason.STOP",
        "STOP",
        "stop",
        "FinishReason.FINISH_REASON_UNSPECIFIED",
        "FINISH_REASON_UNSPECIFIED",
        # 出力上限で止まっても本文は返ることがあり、JSON 切り詰め検知用に許可する
        "FinishReason.MAX_TOKENS",
        "MAX_TOKENS",
        "max_tokens",
    )
)


def _response_finish_reason_str(response: Any) -> str:
    """candidates[0].finish_reason を文字列化（無ければ空）。"""
    cands = getattr(response, "candidates", None) or []
    if not cands:
        return ""
    fr = getattr(cands[0], "finish_reason", None)
    return str(fr) if fr is not None else ""


def _extract_response_text(response: Any) -> str:
    """generate_content の本文を取り出す（JSON モードで .text が空のときのフォールバック）。"""
    t = getattr(response, "text", None)
    if t is not None and str(t).strip():
        return str(t).strip()
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, dict):
        return json.dumps(parsed, ensure_ascii=False)
    chunks: list[str] = []
    if getattr(response, "candidates", None):
        cand = response.candidates[0]
        parts = getattr(cand.content, "parts", None) or []
        for p in parts:
            pt = getattr(p, "text", None)
            if pt:
                chunks.append(pt)
    if chunks:
        return "".join(chunks).strip()
    if getattr(response, "candidates", None):
        cand = response.candidates[0]
        finish = getattr(cand, "finish_reason", None)
        fr = str(finish)
        if fr not in _FINISH_OK:
            raise ValueError(
                f"Gemini が通常終了しませんでした（finish_reason={finish}）。"
                " プロンプト内容や安全フィルタを確認してください。"
            )
    return ""


def _gemini_errors_user_hint(errors: list[str]) -> str:
    """429 / 404 / 切り詰め 等が含まれるとき、原因別の短い日本語ヒントを返す。"""
    joined = "\n".join(errors)
    joined_lower = joined.lower()
    parts: list[str] = []
    if "429" in joined or "RESOURCE_EXHAUSTED" in joined:
        parts.append(
            "【API クォータ】無料枠のリクエスト数・トークン上限に達しています（しばらく待つ、"
            "AI Studio で利用状況・請求プランを確認する、別モデルを .env の GEMINI_MODEL で指定する）。"
        )
    if "unterminated string" in joined_lower or "unexpected end" in joined_lower:
        parts.append(
            "【出力が途中で切断】長いストーリー JSON は max_output_tokens 不足で切れ、JSON 解析に失敗することがあります。"
            "既定ではストーリー用に 65536 まで許可しています。.env の GEMINI_STORY_MAX_OUTPUT_TOKENS で調整できます。"
        )
    if "no longer available" in joined_lower:
        parts.append(
            "【旧モデル】API が「新規ユーザー向けに提供終了」と返したモデルが試行に含まれています。"
            "アプリを最新に pull するか、.env の GEMINI_MODEL を新しい ID にしてください。"
        )
    elif "404" in joined or "NOT_FOUND" in joined:
        parts.append(
            "【モデル ID】一覧にない・非対応のモデル名です。https://ai.google.dev/gemini-api/docs/models "
            "の利用可能 ID に合わせて GEMINI_MODEL を更新してください。"
        )
    return "\n".join(parts)


def _short_err(exc: BaseException, limit: int = 300) -> str:
    s = f"{type(exc).__name__}: {exc}"
    return s if len(s) <= limit else s[: limit - 3] + "..."


def _usage_metadata_summary(response: Any) -> str:
    """generate_content のレスポンスから利用状況の要約（無ければ '-'）。"""
    um = getattr(response, "usage_metadata", None)
    if um is None:
        return "-"
    try:
        pt = getattr(um, "prompt_token_count", None)
        ct = getattr(um, "candidates_token_count", None)
        tt = getattr(um, "total_token_count", None)
        bits: list[str] = []
        if pt is not None:
            bits.append(f"prompt={pt}")
        if ct is not None:
            bits.append(f"candidates={ct}")
        if tt is not None:
            bits.append(f"total={tt}")
        return " ".join(bits) if bits else repr(um)[:120]
    except Exception:
        return repr(um)[:120]


def _gemini_model_names() -> list[str]:
    configured = (current_app.config.get("GEMINI_MODEL") or "").strip()
    # gemini-2.0-flash-001 は新規 API キーでは 404 になりやすいためフォールバックから除外。
    fallback_models = [
        m
        for m in (
            configured,
            "gemini-3-flash-preview",
            "gemini-2.5-flash",
            "gemini-2.0-flash",
        )
        if m
    ]
    seen: set[str] = set()
    out: list[str] = []
    if _last_successful_model and _last_successful_model not in seen:
        seen.add(_last_successful_model)
        out.append(_last_successful_model)
    for m in fallback_models:
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def call_gemini_text(
    system: str,
    user_message: str,
    max_tokens: int = 2048,
    *,
    log_label: str = "gemini.chat",
) -> str:
    """
    Gemini をプレーンテキストで呼び出し、本文を返す（相談チャット用）。
    """
    global _last_successful_model
    api_key = current_app.config.get("GEMINI_API_KEY") or current_app.config.get(
        "GOOGLE_API_KEY"
    )
    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY（または GOOGLE_API_KEY）が設定されていません。.env を確認してください。"
        )

    model_names = _gemini_model_names()
    logger.info(
        "%s: Gemini プレーンテキスト処理シーケンス開始 max_output_tokens=%s 試行順=%s "
        "user_chars=%d system_chars=%d",
        log_label,
        max_tokens,
        model_names,
        len(user_message),
        len(system),
    )

    client = _get_gemini_client(api_key)
    errors: list[str] = []
    for model_name in model_names:
        logger.info(
            "%s: Gemini 処理中（プレーンテキスト）model=%s → Google API generate_content 送信",
            log_label,
            model_name,
        )
        try:
            cfg = types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=max_tokens,
            )
            t0 = time.perf_counter()
            response = client.models.generate_content(
                model=model_name,
                contents=user_message,
                config=cfg,
            )
            wall_ms = (time.perf_counter() - t0) * 1000
            finish_s = _response_finish_reason_str(response)
            logger.info(
                "%s: Gemini API 応答受信 model=%s wall_ms=%.0f finish_reason=%r usage=%s",
                log_label,
                model_name,
                wall_ms,
                finish_s,
                _usage_metadata_summary(response),
            )
            text = _extract_response_text(response)
        except Exception as e:
            errors.append(f"{model_name}: {e}")
            logger.warning(
                "%s: 試行失敗 model=%s %s",
                log_label,
                model_name,
                _short_err(e),
            )
            continue

        if text and text.strip():
            logger.info(
                "%s: 成功 model=%s 応答_chars≈%d（抽出後）",
                log_label,
                model_name,
                len(text),
            )
            _last_successful_model = model_name
            return text.strip()

        errors.append(f"{model_name}: 空の応答")
        logger.warning("%s: 空の応答 model=%s", log_label, model_name)

    detail = "\n".join(errors[:15])
    if len(errors) > 15:
        detail += f"\n… ほか {len(errors) - 15} 件"
    hint = _gemini_errors_user_hint(errors)
    head = (
        "Gemini からテキスト応答を得られませんでした。"
        f" 試したモデル: {', '.join(model_names)}。"
    )
    if hint:
        head = hint + "\n\n" + head
    else:
        head += " .env の GEMINI_MODEL やネットワークを確認してください。"
    logger.error("%s: 全試行失敗 attempts=%d", log_label, len(errors))
    raise ValueError(f"{head}\n----\n{detail}")


def call_gemini_chat(
    system: str,
    contents: list,
    max_tokens: int = 2048,
    *,
    log_label: str = "gemini.chat",
) -> str:
    """
    マルチターン会話用。contents は google.genai.types.Content のリスト（user / model 交互）。
    """
    global _last_successful_model
    api_key = current_app.config.get("GEMINI_API_KEY") or current_app.config.get(
        "GOOGLE_API_KEY"
    )
    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY（または GOOGLE_API_KEY）が設定されていません。.env を確認してください。"
        )
    if not contents:
        raise ValueError("会話 contents が空です。")

    model_names = _gemini_model_names()
    hist_chars = sum(
        len(getattr(p, "text", "") or "")
        for c in contents
        for p in (getattr(c, "parts", None) or [])
    )
    logger.info(
        "%s: Gemini チャット処理シーケンス開始 turns=%d history_chars≈%s max_output_tokens=%s 試行順=%s",
        log_label,
        len(contents),
        hist_chars,
        max_tokens,
        model_names,
    )

    client = _get_gemini_client(api_key)
    errors: list[str] = []
    for model_name in model_names:
        logger.info(
            "%s: Gemini 処理中（マルチターン）model=%s → Google API generate_content 送信",
            log_label,
            model_name,
        )
        try:
            cfg = types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=max_tokens,
            )
            t0 = time.perf_counter()
            response = client.models.generate_content(
                model=model_name,
                contents=contents,
                config=cfg,
            )
            wall_ms = (time.perf_counter() - t0) * 1000
            finish_s = _response_finish_reason_str(response)
            logger.info(
                "%s: Gemini API 応答受信 model=%s wall_ms=%.0f finish_reason=%r usage=%s",
                log_label,
                model_name,
                wall_ms,
                finish_s,
                _usage_metadata_summary(response),
            )
            text = _extract_response_text(response)
        except Exception as e:
            errors.append(f"{model_name}: {e}")
            logger.warning(
                "%s: 試行失敗 model=%s %s",
                log_label,
                model_name,
                _short_err(e),
            )
            continue

        if text and text.strip():
            logger.info(
                "%s: 成功 model=%s 応答_chars≈%d（抽出後）",
                log_label,
                model_name,
                len(text),
            )
            _last_successful_model = model_name
            return text.strip()

        errors.append(f"{model_name}: 空の応答")
        logger.warning("%s: 空の応答 model=%s", log_label, model_name)

    detail = "\n".join(errors[:15])
    if len(errors) > 15:
        detail += f"\n… ほか {len(errors) - 15} 件"
    hint = _gemini_errors_user_hint(errors)
    head = (
        "Gemini からテキスト応答を得られませんでした。"
        f" 試したモデル: {', '.join(model_names)}。"
    )
    if hint:
        head = hint + "\n\n" + head
    else:
        head += " .env の GEMINI_MODEL やネットワークを確認してください。"
    logger.error("%s: 全試行失敗 attempts=%d", log_label, len(errors))
    raise ValueError(f"{head}\n----\n{detail}")


def call_gemini_json(
    system: str,
    user_message: str,
    max_tokens: int = 1000,
    *,
    log_label: str = "gemini",
) -> dict[str, Any]:
    """
    Gemini を呼び出し、単一の JSON オブジェクトを dict で返す。

    期待するレスポンス: response_mime_type=application/json、
    またはテキスト本文が ```json フェンス付きの JSON オブジェクト。

    Args:
        system: システム指示
        user_message: ユーザーメッセージ
        max_tokens: 最大出力トークン（max_output_tokens）
        log_label: ログに付与するラベル（どの画面の生成か識別用）

    Returns:
        json.loads 済みの dict

    Raises:
        ValueError: API キー未設定・JSON パース失敗・応答がオブジェクトでない場合
    """
    global _last_successful_model
    api_key = current_app.config.get("GEMINI_API_KEY") or current_app.config.get(
        "GOOGLE_API_KEY"
    )
    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY（または GOOGLE_API_KEY）が設定されていません。.env を確認してください。"
        )

    model_names = _gemini_model_names()

    logger.info(
        "%s: Gemini JSON 処理シーケンス開始 max_output_tokens=%s 試行順=%s "
        "user_chars=%d system_chars=%d（モデル×json/plain の順で試行）",
        log_label,
        max_tokens,
        model_names,
        len(user_message),
        len(system),
    )

    client = _get_gemini_client(api_key)
    errors: list[str] = []
    for model_name in model_names:
        for use_json in (True, False):
            label = "json" if use_json else "plain"
            logger.info(
                "%s: Gemini 処理中（JSON モード試行）model=%s mode=%s → Google API generate_content 送信",
                log_label,
                model_name,
                label,
            )
            try:
                kwargs: dict[str, Any] = {
                    "system_instruction": system,
                    "max_output_tokens": max_tokens,
                }
                if use_json:
                    kwargs["response_mime_type"] = "application/json"
                cfg = types.GenerateContentConfig(**kwargs)
                t0 = time.perf_counter()
                response = client.models.generate_content(
                    model=model_name,
                    contents=user_message,
                    config=cfg,
                )
                wall_ms = (time.perf_counter() - t0) * 1000
                finish_s = _response_finish_reason_str(response)
                logger.info(
                    "%s: Gemini API 応答受信 model=%s mode=%s wall_ms=%.0f finish_reason=%r usage=%s",
                    log_label,
                    model_name,
                    label,
                    wall_ms,
                    finish_s,
                    _usage_metadata_summary(response),
                )
                text = _extract_response_text(response)
            except Exception as e:
                err_line = f"{model_name} ({label}): {e}"
                errors.append(err_line)
                logger.warning(
                    "%s: 試行失敗 model=%s mode=%s %s",
                    log_label,
                    model_name,
                    label,
                    _short_err(e),
                )
                continue

            if not text:
                errors.append(f"{model_name} ({label}): 空の応答")
                logger.warning(
                    "%s: 空の応答 model=%s mode=%s", log_label, model_name, label
                )
                continue

            clean_text = text.replace("```json", "").replace("```", "").strip()
            try:
                parsed: Any = json.loads(clean_text)
            except json.JSONDecodeError as e:
                trunc = ""
                if "MAX_TOKENS" in finish_s or "LENGTH" in finish_s:
                    trunc = "（finish_reason が出力上限のため JSON が切れている可能性が高いです）"
                elif len(clean_text) > 8000:
                    trunc = "（応答が長いため max_output_tokens 不足で切れた可能性があります）"
                errors.append(f"{model_name} ({label}): JSON 解析失敗 — {e}{trunc}")
                logger.warning(
                    "%s: JSON 解析失敗 model=%s mode=%s finish=%s %s",
                    log_label,
                    model_name,
                    label,
                    finish_s,
                    _short_err(e),
                )
                continue

            if isinstance(parsed, dict):
                keys = list(parsed.keys())
                logger.info(
                    "%s: 成功（JSON オブジェクト確定）model=%s mode=%s keys=%s raw_chars=%d",
                    log_label,
                    model_name,
                    label,
                    keys,
                    len(clean_text),
                )
                _last_successful_model = model_name
                return parsed
            errors.append(f"{model_name} ({label}): トップレベルが JSON オブジェクトではない")
            logger.warning(
                "%s: JSON がオブジェクトでない model=%s mode=%s",
                log_label,
                model_name,
                label,
            )

    detail = "\n".join(errors[:15])
    if len(errors) > 15:
        detail += f"\n… ほか {len(errors) - 15} 件"
    hint = _gemini_errors_user_hint(errors)
    head = (
        "Gemini から期待どおりの JSON オブジェクトを得られませんでした。"
        f" 試したモデル: {', '.join(model_names)}。"
    )
    if hint:
        head = hint + "\n\n" + head
    else:
        head += " .env の GEMINI_MODEL やネットワークを確認してください。"
    logger.error(
        "%s: 全試行失敗 attempts=%d models=%s",
        log_label,
        len(errors),
        model_names,
    )
    raise ValueError(f"{head}\n----\n{detail}")
