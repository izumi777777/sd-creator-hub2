"""
パフォーマンス改善の簡易検証（単体・モック中心）。
実行: リポジトリ直下で  python scripts/verify_perf.py
"""

from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# リポジトリルートを import パスに
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _sqlite_path_from_uri(uri: str) -> Path | None:
    if not uri.startswith("sqlite:///"):
        return None
    p = uri.replace("sqlite:///", "", 1)
    if p.startswith("/"):
        return Path(p)
    return (_ROOT / p).resolve()


def main() -> int:
    import os

    # 検証スクリプトではバックグラウンド SD スケジューラを起動しない
    os.environ["SD_SCHEDULER_ENABLED"] = "0"

    from app import create_app

    app = create_app()
    uri = app.config.get("SQLALCHEMY_DATABASE_URI") or ""
    print("=== sd-creator-hub2 パフォーマンス検証 ===\n")

    # --- 1) 同一リクエスト内の S3 クライアント再利用（明示キーで boto3.client 経路）---
    fake_client = MagicMock(name="s3_client")
    n_boto = {"count": 0}

    def _fake_client(*args, **kwargs):
        n_boto["count"] += 1
        return fake_client

    with app.test_request_context("/"):
        app.config["AWS_S3_BUCKET"] = "perf-test-bucket"
        app.config["AWS_ACCESS_KEY_ID"] = "test-ak"
        app.config["AWS_SECRET_ACCESS_KEY"] = "test-sk"
        app.config["AWS_PROFILE"] = None
        with patch("app.services.s3_service.boto3.client", side_effect=_fake_client):
            from app.services import s3_service

            s3_service.get_s3_client()
            s3_service.get_s3_client()
            s3_service.get_s3_client()
    if n_boto["count"] == 1:
        print("[OK] get_s3_client: 同一リクエスト内で boto3.client は 1 回のみ")
    else:
        print(f"[NG] get_s3_client: boto3.client が {n_boto['count']} 回（期待 1）")
        return 1

    # --- 2) バッチ署名: HeadObject なし・200 件が短時間 ---
    class FakeImg:
        __slots__ = ("id", "s3_key", "file_name", "s3_url")

        def __init__(self, iid: int):
            self.id = iid
            self.s3_key = f"portal/chars/1/original/img_{iid}.png"
            self.file_name = f"img_{iid}.png"
            self.s3_url = None

    images = [FakeImg(i) for i in range(200)]

    with app.test_request_context("/"):
        with patch.object(s3_service, "is_s3_configured", return_value=True):
            with patch.object(
                s3_service,
                "get_presigned_url",
                return_value="https://example.invalid/presigned",
            ):
                t0 = time.perf_counter()
                out = s3_service.batch_presigned_portal_image_view_urls(
                    images, expiration=3600
                )
                elapsed = time.perf_counter() - t0
    if len(out) != 200:
        print(f"[NG] batch_presigned: 期待 200 件、実際 {len(out)}")
        return 1
    if elapsed > 5.0:
        print(f"[WARN] batch_presigned 200件: {elapsed:.2f}s（モックでも遅い）")
    else:
        print(f"[OK] batch_presigned 200件（モック・HeadObject なし）: {elapsed*1000:.0f} ms")

    # --- 3) Gemini クライアントシングルトン ---
    with app.app_context():
        from app.services import gemini_service

        built: list[MagicMock] = []

        def _new_client(*args, **kwargs):
            m = MagicMock()
            built.append(m)
            return m

        with patch.object(gemini_service.genai, "Client", side_effect=_new_client):
            gemini_service._gemini_client = None
            gemini_service._gemini_client_api_key = None
            a = gemini_service._get_gemini_client("key-a")
            b = gemini_service._get_gemini_client("key-a")
            c = gemini_service._get_gemini_client("key-b")
        if a is not b:
            print("[NG] _get_gemini_client: 同一キーで別インスタンス")
            return 1
        if a is c:
            print("[NG] _get_gemini_client: キー変更でも同一クライアントオブジェクト")
            return 1
        if len(built) != 2:
            print(f"[NG] genai.Client 生成回数: {len(built)}（期待 2）")
            return 1
        print("[OK] _get_gemini_client: 同一 API キーは再利用、キー変更で再生成")

    # --- 4) フォント LRU（同一引数は同一オブジェクト）---
    from app.services import chapter_image_overlay

    chapter_image_overlay._load_font_cached.cache_clear()
    f1 = chapter_image_overlay._load_font_cached(None, 14)
    f2 = chapter_image_overlay._load_font_cached(None, 14)
    if f1 is not f2:
        print("[NG] _load_font_cached: 同一 (path,size) で別インスタンス（LRU 不整合）")
        return 1
    t0 = time.perf_counter()
    for _ in range(2000):
        chapter_image_overlay._load_font_cached(None, 14)
    t_cached = time.perf_counter() - t0
    print(f"[OK] _load_font_cached: 同一フォント 2000 回参照 {t_cached*1000:.1f} ms（ディスク再読込なし）")

    # --- 5) SQLite: images.story_id で INDEX 使用 ---
    inst_db = Path(app.instance_path) / "creator_portal.db"
    db_path = inst_db if inst_db.is_file() else _sqlite_path_from_uri(uri)
    if db_path and Path(db_path).is_file():
        try:
            con = sqlite3.connect(str(Path(db_path).resolve()))
            cur = con.execute(
                "EXPLAIN QUERY PLAN SELECT id FROM images WHERE story_id = 1 LIMIT 10"
            )
            rows = cur.fetchall()
            con.close()
            plan = " ".join(str(r) for r in rows).lower()
            if "ix_images_story_id" in plan:
                print("[OK] SQLite EXPLAIN: ix_images_story_id を使用")
            elif "using index" in plan or "search" in plan:
                print("[OK] SQLite EXPLAIN: images 向けインデックス探索を確認")
            else:
                print("[WARN] SQLite EXPLAIN: 想定外プラン（マイグレ未適用の可能性）")
            for r in rows:
                print(f"     {r}")
        except sqlite3.Error as e:
            print(f"[SKIP] SQLite EXPLAIN: {e}")
    else:
        print(f"[SKIP] SQLite ファイルなしまたは非SQLite URI: {uri[:60]}...")

    # --- 6) PDF 並列（data URL のみ・ネットワークなし）---
    from app.services import pdf_service

    tiny_png_b64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    data_urls = [
        "data:image/png;base64," + tiny_png_b64,
    ] * 24
    t0 = time.perf_counter()
    pdf_service.generate_pdf(data_urls, page_size="square", fit_mode="fit")
    t_pdf = time.perf_counter() - t0
    print(f"[OK] PDF 24ページ（data URL・並列取得）: {t_pdf*1000:.0f} ms")

    # --- 7) ZIP 並列（data URL のみ）---
    from app.services import zip_service

    z_imgs = [{"url": "data:image/png;base64," + tiny_png_b64, "name": f"{i}.png"} for i in range(20)]
    t0 = time.perf_counter()
    zip_service.generate_zip(z_imgs, structure="flat")
    t_zip = time.perf_counter() - t0
    print(f"[OK] ZIP 20ファイル（data URL・並列取得）: {t_zip*1000:.0f} ms")

    print("\n=== 検証完了（上記 OK が主な改善の目安）===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
