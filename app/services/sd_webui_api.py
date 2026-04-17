"""AUTOMATIC1111 Web UI の /sdapi/v1/txt2img（標準ライブラリのみ）。"""

from __future__ import annotations

import base64
import json
import logging
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)


def _webui_connect_hints(base_url: str, exc: BaseException) -> str:
    """URLError / タイムアウト時に、よくある原因のチェック項目を日本語で付与する。"""
    raw = f"{exc}"
    low = raw.lower()
    lines: list[str] = [raw]
    if (
        "10060" in raw
        or "timed out" in low
        or "timeout" in low
        or isinstance(getattr(exc, "reason", None), TimeoutError)
    ):
        lines.append(
            "【想定される原因】この PC から EC2 の TCP 7860 へ届いていないか、"
            "返答が返る前にタイムアウトしています。"
        )
        lines.append(
            "· EC2 のセキュリティグループでインバウンド TCP 7860 を、"
            "ポータルを実行しているマシンのグローバル IP（変わる場合は都度）から許可する。"
        )
        lines.append(
            "· ブラウザで次と同じ URL が開けるか確認する: "
            f"{base_url.rstrip('/')}/ （または /docs）。開けなければポータルからも接続できません。"
        )
        lines.append(
            "· EC2 上で Web UI が `--api` 付きで起動し、0.0.0.0 で待ち受けているか "
            "（127.0.0.1 のみだと外部から届きません）。"
        )
    elif "10061" in raw or "actively refused" in low or "connection refused" in low:
        lines.append(
            "【想定される原因】パケットは届いているがポートで拒否されています。"
            "Web UI が起動しておらず、または別ポートで待ち受けている可能性があります。"
        )
    elif "getaddrinfo" in low or "name or service not known" in low:
        lines.append(
            "【想定される原因】ホスト名の解決に失敗しています。"
            "SD_WEBUI_BASE_URL のスペル・IP の取り違え（インスタンス再起動後の IP 変更など）を確認してください。"
        )
    return "\n".join(lines)


def txt2img(
    base_url: str,
    payload: dict[str, Any],
    *,
    timeout: float = 600.0,
) -> dict[str, Any]:
    """POST /sdapi/v1/txt2img。応答は images（base64 リスト）等を含む JSON。"""
    url = base_url.rstrip("/") + "/sdapi/v1/txt2img"
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        logger.warning("sd_webui txt2img HTTP %s: %s", e.code, detail[:2000])
        raise RuntimeError(f"Web UI API HTTP {e.code}: {detail[:4000]}") from e
    except urllib.error.URLError as e:
        logger.warning("sd_webui txt2img URL error: %s", e)
        detail = _webui_connect_hints(base_url, e)
        raise RuntimeError(f"Web UI に接続できません（POST {url}）。\n{detail}") from e
    return json.loads(raw.decode("utf-8"))


def first_image_png_bytes(data: dict[str, Any]) -> bytes:
    """応答から先頭の画像を PNG/JPEG いずれかのバイト列で返す。"""
    all_b = all_image_bytes(data)
    return all_b[0]


def all_image_bytes(data: dict[str, Any]) -> list[bytes]:
    """応答の images（base64 配列）をすべてバイト列にデコードする。"""
    if data.get("error"):
        raise RuntimeError(json.dumps(data, ensure_ascii=False)[:4000])
    imgs = data.get("images") or []
    if not imgs:
        raise RuntimeError("応答に images がありません")
    return [base64.b64decode(b64) for b64 in imgs]
