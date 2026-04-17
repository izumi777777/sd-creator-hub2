"""EC2 起停・SSM 経由の sd-webui 再起動（ポータル /ops 用）。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError
from flask import current_app

from app.services import ec2_pricing_estimate

logger = logging.getLogger(__name__)


def _format_duration_seconds(total_seconds: int) -> str:
    """経過秒を日本語のざっくり表記にする。"""
    s = max(0, int(total_seconds))
    days, s = divmod(s, 86400)
    hours, s = divmod(s, 3600)
    minutes, secs = divmod(s, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}日")
    if hours:
        parts.append(f"{hours}時間")
    if minutes:
        parts.append(f"{minutes}分")
    if not parts:
        parts.append(f"{secs}秒")
    elif secs and days == 0 and hours == 0:
        parts.append(f"{secs}秒")
    return "".join(parts)


def _billing_hints(
    state: str,
    *,
    is_spot: bool,
    uptime_seconds: int | None,
) -> tuple[str, str, list[str]]:
    """
    UI 用の課金目安。

    Returns:
        (tone, title, bullet_lines)  … tone は running | stopped | transition | other
    """
    if state == "running":
        lines = [
            "EC2 は「起動している秒」に近い単位でインスタンス課金が発生するのが一般的です（オンデマンド／リザーブドの契約に依存）。",
            "GPU 系インスタンスは停止中に比べ単価が高いことが多いです。",
            "EBS（ルートボリューム等）・Elastic IP の保持も別途課金対象になり得ます。",
        ]
        if uptime_seconds is not None:
            lines.insert(
                0,
                f"起動時刻（LaunchTime）からの経過の目安: 約 {_format_duration_seconds(uptime_seconds)}。"
                "停止→再開すると LaunchTime は更新されます。",
            )
        if is_spot:
            lines.append(
                "スポットインスタンスです。割当が維持されている間の料金体系はオンデマンドと異なります（中断時は再起動で別課金単位になる場合があります）。"
            )
        return "running", "稼働中 — インスタンス時間課金が発生している可能性が高い", lines
    if state == "stopped":
        return (
            "stopped",
            "停止中 — インスタンス時間課金は通常かからない",
            [
                "一般的に「停止した」EC2 にはインスタンス時間料金はかかりません（請求はリージョン・アカウント設定に依存）。",
                "EBS ストレージ・未解放の Elastic IP などには課金が続くことがあります。",
            ],
        )
    if state in ("pending", "stopping", "shutting-down"):
        return (
            "transition",
            "状態遷移中 — 課金は状態に依存",
            [
                "pending: 起動処理中。running になればインスタンス課金が始まるのが一般的です。",
                "stopping / shutting-down: 停止処理中。完全に stopped になるまで時間課金が続く場合があります。",
            ],
        )
    return (
        "other",
        f"状態「{state}」— 課金は AWS の定義に従います",
        ["料金の詳細は AWS Billing / Cost Explorer で確認してください。"],
    )


def _boto_session(region: str) -> boto3.Session:
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


def describe_instance(instance_id: str, region: str) -> dict[str, Any] | None:
    """
    対象インスタンスの状態を返す。
    None はインスタンス未検出など。
    """
    try:
        ec2 = _boto_session(region).client("ec2")
        r = ec2.describe_instances(InstanceIds=[instance_id])
        res = (r.get("Reservations") or [{}])[0].get("Instances") or []
        if not res:
            return None
        inst = res[0]
        state = (inst.get("State") or {}).get("Name") or "unknown"
        name = ""
        for t in inst.get("Tags") or []:
            if t.get("Key") == "Name":
                name = str(t.get("Value") or "")
                break
        pub = inst.get("PublicIpAddress") or ""
        priv = inst.get("PrivateIpAddress") or ""
        instance_type = str(inst.get("InstanceType") or "")
        lifecycle = inst.get("InstanceLifecycle")
        is_spot = lifecycle == "spot"

        lt: datetime | None = inst.get("LaunchTime")
        uptime_seconds: int | None = None
        launch_time_display = "—"
        if isinstance(lt, datetime):
            if lt.tzinfo is None:
                lt = lt.replace(tzinfo=timezone.utc)
            launch_time_display = lt.strftime("%Y-%m-%d %H:%M UTC")
            # 経過時間は running のときだけ「この起動からの目安」として意味がある
            if state == "running":
                now = datetime.now(timezone.utc)
                uptime_seconds = max(0, int((now - lt).total_seconds()))

        tone, billing_title, billing_lines = _billing_hints(
            state, is_spot=is_spot, uptime_seconds=uptime_seconds
        )

        out: dict[str, Any] = {
            "instance_id": instance_id,
            "state": state,
            "name": name,
            "public_ip": pub,
            "private_ip": priv,
            "instance_type": instance_type,
            "is_spot": is_spot,
            "launch_time_display": launch_time_display,
            "uptime_seconds": uptime_seconds,
            "uptime_human": _format_duration_seconds(uptime_seconds)
            if uptime_seconds is not None
            else "—",
            "billing_tone": tone,
            "billing_title": billing_title,
            "billing_lines": billing_lines,
        }
        ec2_pricing_estimate.attach_cost_estimate(out, region)
        return out
    except ClientError as e:
        logger.warning("describe_instance: %s", e)
        return None


def start_instance(instance_id: str, region: str) -> tuple[bool, str]:
    try:
        ec2 = _boto_session(region).client("ec2")
        ec2.start_instances(InstanceIds=[instance_id])
        return True, "起動リクエストを送信しました。しばらくすると running になります。"
    except ClientError as e:
        return False, str(e)


def stop_instance(instance_id: str, region: str) -> tuple[bool, str]:
    try:
        ec2 = _boto_session(region).client("ec2")
        ec2.stop_instances(InstanceIds=[instance_id])
        return True, "停止リクエストを送信しました。"
    except ClientError as e:
        return False, str(e)


def restart_sd_webui_via_ssm(instance_id: str, region: str) -> tuple[str | None, str | None]:
    """
    SSM Run Command で sd-webui.service を再起動する。

    Returns:
        (command_id, None) 成功
        (None, error_message) 失敗
    """
    try:
        ssm = _boto_session(region).client("ssm")
        r = ssm.send_command(
            InstanceIds=[instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={
                "commands": [
                    "set -e",
                    "sudo systemctl restart sd-webui.service",
                    "sudo systemctl is-active sd-webui.service || true",
                ]
            },
            Comment="Creator Portal ops: restart sd-webui",
        )
        cid = r["Command"]["CommandId"]
        logger.info("SSM restart sd-webui sent command_id=%s instance=%s", cid, instance_id)
        return cid, None
    except ClientError as e:
        logger.warning("restart_sd_webui_via_ssm: %s", e)
        return None, str(e)
