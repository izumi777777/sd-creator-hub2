"""日時予約ジョブの時刻解釈（datetime-local と UTC 比較の整合）。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo


def scheduler_zoneinfo(tz_name: str | None) -> tzinfo:
    """
    IANA タイムゾーン名から tzinfo を返す。

    Windows 等で PEP 615 の tz データ（tzdata パッケージ）が無いと
    ZoneInfo が一切使えないため、主要ゾーンは固定オフセットにフォールバックする。
    """
    raw = (tz_name or "").strip() or "Asia/Tokyo"
    r = raw.lower()

    try:
        return ZoneInfo(raw)
    except Exception:
        pass

    if r in ("utc", "gmt", "etc/utc", "etc/gmt", "etc/gmt+0", "etc/gmt-0", "z"):
        return timezone.utc

    # 日本標準時（DST なし）— tzdata なしでも予約の壁時計解釈に使える
    if raw in ("Asia/Tokyo", "Japan"):
        return timezone(timedelta(hours=9), "JST")

    try:
        return ZoneInfo("UTC")
    except Exception:
        return timezone.utc


def utc_now_naive() -> datetime:
    """DB 比較用の UTC 壁時計（naive）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def parse_scheduled_at_to_utc_naive(raw: str, tz_name: str | None) -> datetime | None:
    """
    HTML datetime-local 等の文字列を UTC naive に変換する。

    - 末尾 Z またはオフセット付き ISO: そのタイムゾーンから UTC へ。
    - オフセットなしの YYYY-MM-DDTHH:MM: tz_name（既定 Asia/Tokyo）のローカル壁時計として解釈。
    """
    s = (raw or "").strip()
    if not s:
        return None
    tz = scheduler_zoneinfo(tz_name)

    def _to_utc_naive(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            raise ValueError("internal")
        return dt.astimezone(timezone.utc).replace(tzinfo=None)

    try:
        if s.endswith("Z") and "T" in s:
            aware = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return _to_utc_naive(aware)
        if len(s) >= 16 and s[4] == "-" and s[7] == "-" and s[10] == "T":
            local = datetime.strptime(s[:16], "%Y-%m-%dT%H:%M")
            return _to_utc_naive(local.replace(tzinfo=tz))
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is not None:
            return _to_utc_naive(dt)
        return _to_utc_naive(dt.replace(tzinfo=tz))
    except ValueError:
        return None


def _self_check() -> None:
    """Flask なしで検証: python -m app.services.schedule_timezone"""
    tz_tokyo = "Asia/Tokyo"
    u = parse_scheduled_at_to_utc_naive("2026-04-18T10:00", tz_tokyo)
    assert u is not None
    assert u.isoformat(sep=" ") == "2026-04-18 01:00:00"
    u2 = parse_scheduled_at_to_utc_naive("2026-04-18T10:00:00+09:00", tz_tokyo)
    assert u2 is not None
    assert u2 == u


if __name__ == "__main__":
    _self_check()
    print("schedule_timezone: self-check OK")
