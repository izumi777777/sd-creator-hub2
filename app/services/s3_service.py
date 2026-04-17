"""Amazon S3 へのアップロード・一覧・署名付き URL。"""

import logging
from collections.abc import Iterable
from typing import Any
from urllib.parse import quote, unquote, urlparse

import boto3
from botocore.exceptions import ClientError
from flask import current_app
from werkzeug.utils import secure_filename

logger = logging.getLogger(__name__)


def is_s3_configured() -> bool:
    """
    S3 利用に最低限必要な設定があるか。

    - バケット名は必須
    - 認証: AWS_PROFILE、またはアクセスキー組、または default クレデンシャルチェーン
    """
    if not current_app.config.get("AWS_S3_BUCKET"):
        return False
    if current_app.config.get("AWS_PROFILE"):
        return True
    if current_app.config.get("AWS_ACCESS_KEY_ID") and current_app.config.get(
        "AWS_SECRET_ACCESS_KEY"
    ):
        return True
    try:
        return boto3.Session().get_credentials() is not None
    except Exception:
        return False


def _s3_endpoint_url() -> str | None:
    raw = current_app.config.get("AWS_S3_ENDPOINT_URL")
    if raw is None:
        return None
    s = str(raw).strip()
    return s or None


def get_s3_client() -> Any:
    """S3 クライアントを取得する。"""
    bucket = current_app.config.get("AWS_S3_BUCKET")
    if not bucket:
        raise ValueError("AWS_S3_BUCKET が設定されていません。")

    region = current_app.config["AWS_S3_REGION"]
    profile = current_app.config.get("AWS_PROFILE")
    endpoint_url = _s3_endpoint_url()

    if profile:
        session = boto3.Session(profile_name=profile, region_name=region)
        return session.client("s3", endpoint_url=endpoint_url)

    key_id = current_app.config.get("AWS_ACCESS_KEY_ID")
    secret = current_app.config.get("AWS_SECRET_ACCESS_KEY")
    if key_id and secret:
        return boto3.client(
            "s3",
            aws_access_key_id=key_id,
            aws_secret_access_key=secret,
            region_name=region,
            endpoint_url=endpoint_url,
        )

    # 環境変数・コンテナロール・default プロファイルなどチェーンに任せる
    session = boto3.Session(region_name=region)
    if not session.get_credentials():
        raise ValueError(
            "S3 用の認証情報がありません。"
            " AWS_PROFILE を設定するか、AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY、"
            "または default クレデンシャルを設定してください。"
        )
    return session.client("s3", endpoint_url=endpoint_url)


def upload_image(file_obj: Any, s3_key: str, content_type: str = "image/png") -> str:
    """
    画像を S3 にアップロードし、公開 URL を返す。

    Args:
        file_obj: アップロードするファイルオブジェクト（ストリーム）
        s3_key: オブジェクトキー
        content_type: MIME タイプ

    Returns:
        バケットがパブリック読み取り前提の URL（プライベート時は presigned を利用）
    """
    return upload_file(file_obj, s3_key, content_type)


def upload_file(file_obj: Any, s3_key: str, content_type: str) -> str:
    """
    任意のバイナリを S3 に置き、公開 URL 文字列を返す（PDF・画像共通）。
    """
    s3 = get_s3_client()
    bucket = current_app.config["AWS_S3_BUCKET"]
    region = current_app.config["AWS_S3_REGION"]

    s3.upload_fileobj(
        file_obj,
        bucket,
        s3_key,
        ExtraArgs={"ContentType": content_type},
    )

    return f"https://{bucket}.s3.{region}.amazonaws.com/{s3_key}"


def list_images(prefix: str = "") -> list[dict[str, Any]]:
    """
    バケット内の画像オブジェクト一覧を返す（最大 200 件）。

    Returns:
        key, name, url, size, last_modified を持つ dict のリスト
    """
    s3 = get_s3_client()
    bucket = current_app.config["AWS_S3_BUCKET"]
    region = current_app.config["AWS_S3_REGION"]

    response = s3.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=200)

    images: list[dict[str, Any]] = []
    for obj in response.get("Contents", []):
        key = obj["Key"]
        if key.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
            images.append(
                {
                    "key": key,
                    "name": key.split("/")[-1],
                    "url": f"https://{bucket}.s3.{region}.amazonaws.com/{key}",
                    "size": obj["Size"],
                    "last_modified": obj["LastModified"].isoformat(),
                }
            )
    return images


def download_object_bytes(s3_key: str) -> bytes:
    """S3 オブジェクトの本文をバイト列で返す。"""
    if not s3_key or not str(s3_key).strip():
        raise ValueError("s3_key が空です。")
    s3 = get_s3_client()
    bucket = current_app.config["AWS_S3_BUCKET"]
    resp = s3.get_object(Bucket=bucket, Key=s3_key)
    return resp["Body"].read()


def _key_from_stored_s3_url(url: str, *, expected_bucket: str) -> str | None:
    """
    DB に保存された S3 公開 URL からオブジェクトキーを取り出す。

    仮想ホスト形式（bucket.s3.region.amazonaws.com/key）に加え、
    パス形式（s3.region.amazonaws.com/bucket/key および s3-region.amazonaws.com）も扱う。
    想定バケットと一致しないパス形式は無視する（誤候補を増やさない）。
    """
    raw = (url or "").strip()
    if not raw.lower().startswith("http"):
        return None
    bucket = (expected_bucket or "").strip()
    try:
        p = urlparse(raw)
        host = (p.hostname or "").lower()
        path = unquote((p.path or "").strip("/"))
        if not host or not path:
            return None

        # --- パス形式（先頭セグメントがバケット名）---
        if host == "s3.amazonaws.com":
            parts = path.split("/", 1)
            if len(parts) == 2 and parts[0] == bucket:
                return parts[1] or None
            return None
        if host.startswith("s3.") and not host.startswith("s3.amazonaws.com"):
            # s3.<region>.amazonaws.com
            parts = path.split("/", 1)
            if len(parts) == 2 and parts[0] == bucket:
                return parts[1] or None
            return None
        if host.startswith("s3-"):
            # s3-ap-northeast-1.amazonaws.com 等
            parts = path.split("/", 1)
            if len(parts) == 2 and parts[0] == bucket:
                return parts[1] or None
            return None

        # --- 仮想ホスト形式: <bucket>.s3...amazonaws.com/<key> ---
        if ".s3." not in host:
            return None
        bucket_from_host, _, _ = host.partition(".s3.")
        if not bucket_from_host or bucket_from_host == "s3":
            return None
        # 別バケットの URL でも、キー部分（パス）は同一レイアウトで移行されることが多い
        if bucket and bucket_from_host != bucket:
            logger.info(
                "s3_service: s3_url のホストバケットが設定と異なりますがキー候補としてパスを使います host_bucket=%r expected=%r",
                bucket_from_host,
                bucket,
            )
        return path or None
    except Exception:
        return None


def _dedupe_keys(keys: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for k in keys:
        k = (k or "").strip()
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(k)
    return out


def _extension_variant_keys(key: str) -> list[str]:
    """同一パスで拡張子だけ異なるキーを列挙（DB と実体の拡張子ズレ用）。"""
    key = (key or "").strip()
    if not key or "." not in key:
        return [key]
    stem, _, ext = key.rpartition(".")
    ext_l = ext.lower()
    alts = ["jpg", "jpeg", "png", "webp", "gif"]
    out = [key]
    for other in alts:
        if ext_l == other:
            continue
        nk = f"{stem}.{other}"
        if nk not in out:
            out.append(nk)
    return out


def portal_image_s3_key_try_list(
    primary_key: str,
    *,
    file_name: str | None = None,
    s3_url: str | None = None,
) -> list[str]:
    """
    DB の primary_key を起点に、取得を試す S3 キー候補を優先順で返す。
    （URL 由来・file_name 再構成・original/stripped 相互・拡張子違い）
    """
    pk = (primary_key or "").strip()
    if not pk:
        return []

    candidates: list[str] = [pk]
    bucket = (current_app.config.get("AWS_S3_BUCKET") or "").strip()
    url_key = (
        _key_from_stored_s3_url(s3_url or "", expected_bucket=bucket)
        if bucket
        else None
    )
    if url_key and url_key != pk:
        candidates.append(url_key)
    fn = (file_name or "").strip().lstrip("/")
    if fn:
        parent = pk.rsplit("/", 1)[0]
        if parent:
            composed = f"{parent}/{fn}"
            if composed not in candidates:
                candidates.append(composed)

    for c in list(candidates):
        if "/original/" in c:
            twin = c.replace("/original/", "/stripped/", 1)
            if twin not in candidates:
                candidates.append(twin)
        elif "/stripped/" in c:
            twin = c.replace("/stripped/", "/original/", 1)
            if twin not in candidates:
                candidates.append(twin)

    expanded: list[str] = []
    for c in _dedupe_keys(candidates):
        expanded.extend(_extension_variant_keys(c))
    return _dedupe_keys(expanded)


def _s3_object_exists_head_or_get_range(s3: Any, bucket: str, key: str) -> bool:
    """
    キーにオブジェクトが存在するか判定する。

    IAM で s3:HeadObject が付与されていないポリシーでは Head が 403 になり、
    従来実装は例外のままプレビューが 502 になっていた。s3:GetObject だけある場合は
    GetObject(Range=先頭1バイト) で代替確認する。
    """
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        err = e.response.get("Error") or {}
        code = str(err.get("Code", "") or "")
        status = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code in ("NoSuchKey", "404", "NotFound"):
            return False
        head_blocked = code in ("AccessDenied", "Forbidden") or status in (401, 403)
        if not head_blocked:
            raise
        logger.info(
            "s3_service: HeadObject が拒否のため GetObject(Range) で存在確認 key=%r code=%r",
            key,
            code or status,
        )
        try:
            resp = s3.get_object(Bucket=bucket, Key=key, Range="bytes=0-0")
            body = resp["Body"]
            try:
                body.read(1)
            finally:
                body.close()
            return True
        except ClientError as e2:
            err2 = e2.response.get("Error") or {}
            code2 = str(err2.get("Code", "") or "")
            status2 = e2.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if code2 in ("NoSuchKey", "404", "NotFound"):
                return False
            # 0 バイトオブジェクト等で Range が効かない場合
            if code2 == "InvalidRange" or status2 == 416:
                try:
                    resp = s3.get_object(Bucket=bucket, Key=key)
                    body = resp["Body"]
                    try:
                        body.read()
                    finally:
                        body.close()
                    return True
                except ClientError as e3:
                    c3 = str((e3.response.get("Error") or {}).get("Code", "") or "")
                    if c3 in ("NoSuchKey", "404", "NotFound"):
                        return False
                    raise
            raise


def find_existing_portal_image_s3_key(
    primary_key: str,
    *,
    file_name: str | None = None,
    s3_url: str | None = None,
) -> str | None:
    """HeadObject（または GetObject の軽い取得）で最初に存在するキーを返す。"""
    try_list = portal_image_s3_key_try_list(
        primary_key, file_name=file_name, s3_url=s3_url
    )
    if not try_list:
        return None
    s3 = get_s3_client()
    bucket = current_app.config["AWS_S3_BUCKET"]
    pk = (primary_key or "").strip()
    for k in try_list:
        if _s3_object_exists_head_or_get_range(s3, bucket, k):
            if k != pk:
                logger.warning(
                    "s3_service: DB の s3_key と実体が一致せず別キーで解決。db=%r actual=%r",
                    pk,
                    k,
                )
            return k
    return None


def download_object_bytes_with_image_fallbacks(
    primary_key: str,
    *,
    file_name: str | None = None,
    s3_url: str | None = None,
) -> bytes:
    """
    get_object を試し、NoSuchKey のときは URL 由来キー・file_name 再構成・拡張子違いを順に試す。

    焼き増し等で「DB のキーと実オブジェクトが微妙に違う」ケースの救済用。
    """
    pk = (primary_key or "").strip()
    if not pk:
        raise ValueError("s3_key が空です。")

    try_list = portal_image_s3_key_try_list(
        primary_key, file_name=file_name, s3_url=s3_url
    )

    s3 = get_s3_client()
    bucket = current_app.config["AWS_S3_BUCKET"]
    last: ClientError | None = None
    for k in try_list:
        try:
            resp = s3.get_object(Bucket=bucket, Key=k)
            data = resp["Body"].read()
            if k != pk:
                logger.warning(
                    "s3_service: primary key missing, used alternate key (prefix match). primary=%r actual=%r",
                    pk,
                    k,
                )
            return data
        except ClientError as e:
            last = e
            code = (e.response.get("Error") or {}).get("Code", "")
            if code in ("NoSuchKey", "404", "NotFound"):
                continue
            raise
    msg = (
        "S3 上に元画像が見つかりません（NoSuchKey）。"
        f" DB のキー例: {pk!r}。"
        " バケット内でオブジェクトが削除されていないか、別バケットに移っていないか確認してください。"
    )
    if last is not None:
        raise ValueError(msg) from last
    raise ValueError(msg)


def delete_object(s3_key: str) -> None:
    """S3 オブジェクトを削除する。"""
    if not s3_key or not str(s3_key).strip():
        raise ValueError("s3_key が空です。")
    s3 = get_s3_client()
    bucket = current_app.config["AWS_S3_BUCKET"]
    s3.delete_object(Bucket=bucket, Key=s3_key)


def get_presigned_url(s3_key: str, expiration: int = 900) -> str:
    """プライベートオブジェクト用の署名付き GET URL（秒）。"""
    s3 = get_s3_client()
    bucket = current_app.config["AWS_S3_BUCKET"]
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": s3_key},
        ExpiresIn=expiration,
    )


def batch_presigned_portal_image_view_urls(
    images: Iterable[Any],
    *,
    expiration: int = 3600,
    sync_resolved_key_to_db: bool = True,
) -> dict[int, str]:
    """
    一覧・ギャラリー描画用に、Image 行の id → 署名付き GET URL をまとめて返す。

    ブラウザが画像ごとに /image/<id>/preview を叩くと、その都度 S3 でキー解決が走る。
    本関数でページ描画時に一度だけ解決・署名して img に埋め込むと往復は減るが、
    画像件数ぶん S3 を直列で叩くため、呼び出し側は件数上限を設けること（全件は重い）。

    失敗した行は辞書に含めない（テンプレ側で preview ルートにフォールバック）。
    DB の s3_key と実体が異なる場合、sync_resolved_key_to_db が真なら解決後キーを DB に反映する。
    """
    if not is_s3_configured():
        return {}

    from app import db

    out: dict[int, str] = {}
    dirty = False
    for img in images:
        try:
            iid = getattr(img, "id", None)
            if iid is None:
                continue
            pk = (getattr(img, "s3_key", None) or "").strip()
            if not pk:
                continue
            resolved = find_existing_portal_image_s3_key(
                pk,
                file_name=getattr(img, "file_name", None),
                s3_url=getattr(img, "s3_url", None),
            )
            if not resolved:
                continue
            if sync_resolved_key_to_db and resolved != pk:
                img.s3_key = resolved
                dirty = True
            out[int(iid)] = get_presigned_url(resolved, expiration=expiration)
        except Exception:
            logger.exception(
                "batch_presigned_portal_image_view_urls: skip image id=%s",
                getattr(img, "id", "?"),
            )
            continue

    if dirty and sync_resolved_key_to_db:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception("batch_presigned_portal_image_view_urls: DB commit に失敗")

    return out


def get_presigned_download_url(
    s3_key: str,
    download_filename: str | None,
    expiration: int = 3600,
) -> str:
    """
    ブラウザで「ダウンロード」として扱う署名付き GET URL。

    ResponseContentDisposition に attachment を付与する。
    """
    raw = (download_filename or "").strip() or "image.bin"
    ascii_fn = secure_filename(raw) or "image.bin"
    disp = f'attachment; filename="{ascii_fn}"'
    try:
        star = quote(raw.encode("utf-8"), safe="")
        ascii_star = quote(ascii_fn.encode("utf-8"), safe="")
        if star != ascii_star:
            disp = f'attachment; filename="{ascii_fn}"; filename*=UTF-8\'\'{star}'
    except Exception:
        pass

    s3 = get_s3_client()
    bucket = current_app.config["AWS_S3_BUCKET"]
    return s3.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": bucket,
            "Key": s3_key,
            "ResponseContentDisposition": disp,
        },
        ExpiresIn=expiration,
    )
