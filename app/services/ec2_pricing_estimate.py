"""EC2 オンデマンド料金の参考値（AWS Price List API）。USD 中心。JPY は表示用レートで換算。"""

from __future__ import annotations

import json
import logging
from typing import Any

import boto3
from botocore.exceptions import ClientError
from flask import current_app

logger = logging.getLogger(__name__)

# EC2 Public 料金 API の location 値（https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/using-price-list.html）
REGION_TO_PRICE_LOCATION: dict[str, str] = {
    "ap-northeast-1": "Asia Pacific (Tokyo)",
    "ap-northeast-2": "Asia Pacific (Seoul)",
    "ap-northeast-3": "Asia Pacific (Osaka)",
    "us-east-1": "US East (N. Virginia)",
    "us-east-2": "US East (Ohio)",
    "us-west-1": "US West (N. California)",
    "us-west-2": "US West (Oregon)",
    "eu-west-1": "EU (Ireland)",
    "eu-central-1": "EU (Frankfurt)",
    "ap-southeast-1": "Asia Pacific (Singapore)",
    "ap-southeast-2": "Asia Pacific (Sydney)",
}


def _boto_session_for_pricing() -> boto3.Session:
    """Price List API は us-east-1 のみ。認証は他サービスと同じ。"""
    region = "us-east-1"
    profile = current_app.config.get("AWS_PROFILE")
    if profile:
        return boto3.Session(profile_name=profile, region_name=region)
    key_id = current_app.config.get("AWS_ACCESS_KEY_ID")
    secret = current_app.config.get("AWS_SECRET_ACCESS_KEY")
    if key_id and secret:
        return boto3.Session(
            aws_access_key_id=key_id,
            aws_secret_access_key=secret,
            region_name=region,
        )
    return boto3.Session(region_name=region)


def _extract_usd_per_hour_from_product(doc: dict[str, Any]) -> float | None:
    """get_products の 1 件 JSON から Linux オンデマンドの USD/h を拾う。"""

    def walk(o: Any) -> float | None:
        if isinstance(o, dict):
            pu = o.get("pricePerUnit")
            if isinstance(pu, dict) and "USD" in pu:
                try:
                    v = float(pu["USD"])
                    if v > 0:
                        return v
                except (TypeError, ValueError):
                    pass
            for v in o.values():
                r = walk(v)
                if r is not None:
                    return r
        if isinstance(o, list):
            for it in o:
                r = walk(it)
                if r is not None:
                    return r
        return None

    return walk(doc)


def fetch_linux_ondemand_usd_per_hour(instance_type: str, region_code: str) -> tuple[float | None, str | None]:
    """
    Linux / 共有テナンシー / Used / OnDemand の時間単価（USD）を Price List から取得。

    Returns:
        (usd_per_hour, None) または (None, error_message)
    """
    location = REGION_TO_PRICE_LOCATION.get(region_code.strip())
    if not location:
        return None, f"リージョン {region_code} は料金マップ未対応です（Price List の location が必要）。"

    base_filters: list[dict[str, str]] = [
        {"Type": "TERM_MATCH", "Field": "ServiceCode", "Value": "AmazonEC2"},
        {"Type": "TERM_MATCH", "Field": "capacitystatus", "Value": "Used"},
        {"Type": "TERM_MATCH", "Field": "location", "Value": location},
        {"Type": "TERM_MATCH", "Field": "tenancy", "Value": "Shared"},
        {"Type": "TERM_MATCH", "Field": "operatingSystem", "Value": "Linux"},
        {"Type": "TERM_MATCH", "Field": "preInstalledSw", "Value": "NA"},
        {"Type": "TERM_MATCH", "Field": "instanceType", "Value": instance_type.strip()},
        {"Type": "TERM_MATCH", "Field": "termType", "Value": "OnDemand"},
    ]

    try:
        sess = _boto_session_for_pricing()
        pricing = sess.client("pricing", region_name="us-east-1")
    except Exception as e:
        return None, f"Pricing クライアント初期化失敗: {e}"

    for variant in (base_filters, [f for f in base_filters if f["Field"] != "preInstalledSw"]):
        try:
            resp = pricing.get_products(ServiceCode="AmazonEC2", Filters=variant, MaxResults=25)
        except ClientError as e:
            return None, f"pricing:GetProducts が拒否されました（IAM に pricing:GetProducts が必要な場合があります）: {e}"
        except Exception as e:
            return None, f"料金 API エラー: {e}"

        for raw in resp.get("PriceList") or []:
            try:
                doc = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                continue
            rate = _extract_usd_per_hour_from_product(doc)
            if rate is not None:
                return rate, None

    return None, "該当するオンデマンド料率が見つかりませんでした（インスタンスタイプ・リージョンの組み合わせ）。"


def attach_cost_estimate(info: dict[str, Any], region_code: str) -> None:
    """
    describe_instance の dict に参考金額を付与する（インプレース）。

    - running かつ instance_type があるときのみ試行。
    - EBS・データ転送・割引・スポット実価は含まない。
    """
    if (info.get("state") or "") != "running":
        return
    itype = (info.get("instance_type") or "").strip()
    uptime_sec = info.get("uptime_seconds")
    if not itype or uptime_sec is None:
        return

    hourly, err = fetch_linux_ondemand_usd_per_hour(itype, region_code)
    if err or hourly is None:
        info["pricing_error"] = err or "料率不明"
        return

    hours = max(0.0, float(uptime_sec) / 3600.0)
    session_usd = round(hours * hourly, 4)

    info["estimated_ondemand_hourly_usd"] = round(hourly, 6)
    info["estimated_session_usd"] = session_usd
    info["pricing_source"] = (
        "AWS Price List API（Linux / Shared / Used / OnDemand の公開料金。EBS・転送・割引は含みません）"
    )

    jpy_rate = current_app.config.get("OPS_BILLING_USD_TO_JPY")
    try:
        if jpy_rate is not None:
            jr = float(jpy_rate)
            if jr > 0:
                info["estimated_session_jpy"] = int(round(session_usd * jr))
                info["estimated_hourly_jpy"] = int(round(hourly * jr))
    except (TypeError, ValueError):
        pass

    if info.get("is_spot"):
        info["pricing_spot_note"] = (
            "スポットインスタンスのため、実際の課金はオンデマンド料金より低いことがほとんどです（変動）。"
        )
