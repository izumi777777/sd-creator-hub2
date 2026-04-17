"""ストーリー生成向け：月×4週の季節・イベントテンプレ（運用フレーム）。"""

from __future__ import annotations

from datetime import date

# 各月 [第1週, 第2週, 第3週, 第4週] の推奨シチュ（ユーザー定義の早見表に準拠）
_MONTH_WEEK_THEMES: list[tuple[str, str, str, str]] = [
    (
        "お正月・初詣（振袖・着物）",
        "冬の街角（ロングコート・マフラー）",
        "お正月休み（こたつ・みかん・はんてん）",
        "和風ファンタジー（巫女・陰陽師・妖怪）",
    ),
    (
        "バレンタイン（フリルエプロン）",
        "冬のデート（ダッフルコート・手袋）",
        "お菓子作り（お泊り会・もこもこパジャマ）",
        "スウィーツの国（お菓子モチーフの妖精）",
    ),
    (
        "卒業・旅立ち（袴・セーラー服）",
        "春一番（スプリングコート・風になびく）",
        "引っ越し・模様替え（ジャージ・まとめ髪）",
        "魔法学園（制服アレンジ・魔法使いの弟子）",
    ),
    (
        "イースター（うさ耳・パステル）",
        "お花見・ピクニック（春ワンピ・カーデ）",
        "新生活の朝（オーバーサイズシャツ・寝起き）",
        "エルフ・森の住人（花冠・自然界の精霊）",
    ),
    (
        "GW・こどもの日（スポーティ・キャップ）",
        "初夏のカフェ（ブラウス・薄手スカート）",
        "五月病を癒やす（クッション・だらだら）",
        "SF・サイバーパンク（ネオン・近未来装備）",
    ),
    (
        "ジューンブライド（ウェディングドレス）",
        "梅雨・紫陽花（透明傘・レインコート）",
        "雨の日の読書（窓辺・メガネ・ネグリジェ）",
        "マーメイド（水中の世界・人魚姫）",
    ),
    (
        "七夕・夏祭り（浴衣・うちわ）",
        "アーリーサマー（Tシャツ・ショートパンツ）",
        "夏の夜・納涼（キャミソール・扇風機・アイス）",
        "アラビアンナイト（踊り子・砂漠のオアシス）",
    ),
    (
        "夏休み（リゾート水着・浮き輪）",
        "ひまわり畑（麦わら帽子・ノースリーブ）",
        "お盆・帰省（縁側・すいか・虫取り網）",
        "海賊・パイレーツ（冒険家・財宝）",
    ),
    (
        "お月見（バニーガール）",
        "秋の気配（秋色ブラウス・ベレー帽）",
        "おうちカフェ（エプロン・コーヒー・読書）",
        "スチームパンク（歯車・ゴーグル・レトロ）",
    ),
    (
        "ハロウィン（魔女・ヴァンパイア）",
        "秋の行楽（トレンチコート・紅葉）",
        "秋の夜長（ランタン・もこもこソックス）",
        "ダークファンタジー（ゴシックロリータ）",
    ),
    (
        "いい肉の日？（チャイナドレス等）",
        "温泉旅行（浴衣・足湯・食べ歩き）",
        "冬支度（厚手ニット・ホットココア）",
        "アニマル・ケモミミ（キツネ耳・猫耳・森の動物）",
    ),
    (
        "クリスマス（サンタコス・トナカイ）",
        "イルミネーション（白ニット・ファー）",
        "クリパ・年越し（パーティドレス・シャンパン）",
        "雪の女王・天使（氷の魔法・白い羽根）",
    ),
]

_WEEK_PHASES: tuple[tuple[str, str, str], ...] = (
    (
        "第1週：シーズン・イベント",
        "非日常／華やか",
        "その月を象徴する行事やコスプレ感のある衣装。月初のアイキャッチ。「今月はこの季節だ」と伝える。",
    ),
    (
        "第2週：リアルクローズ・お出かけ",
        "日常／ファッション",
        "季節ならではの私服（デート服）で外へ。ファッション誌のようなおしゃれさと疑似デート感。",
    ),
    (
        "第3週：インドア・リラックス",
        "日常／親近感",
        "部屋着・パジャマ・趣味の時間など室内。こたつ・扇風機など小物で季節感と親密さ。",
    ),
    (
        "第4週：IF設定・ファンタジー",
        "非日常／変化球",
        "季節要素を少し取り入れた現代以外の世界観や職業モチーフ。月末のマンネリ打破。",
    ),
)


def week_of_month(d: date | None = None) -> int:
    """月内の週番号 1〜4（1〜7日→1、8〜14→2、15〜21→3、22日以降→4）。"""
    d = d or date.today()
    return min(4, max(1, (d.day - 1) // 7 + 1))


def clamp_month_week(month: int, week: int) -> tuple[int, int]:
    m = max(1, min(12, month))
    w = max(1, min(4, week))
    return m, w


def seasonal_summary_line(month: int, week: int) -> str:
    m, w = clamp_month_week(month, week)
    return f"{m}月・第{w}週（{_WEEK_PHASES[w - 1][0]}）"


def build_seasonal_user_addon(
    month: int,
    week: int,
    rotation_note: str | None = None,
) -> str:
    """
    Gemini ユーザーメッセージに付与する季節テンプレブロック（日本語）。
    """
    m, w = clamp_month_week(month, week)
    phase_title, phase_axis, phase_desc = _WEEK_PHASES[w - 1]
    themes = _MONTH_WEEK_THEMES[m - 1]
    current_theme = themes[w - 1]

    lines = [
        "【季節・月間テンプレ（制作運用フレーム）】",
        "以下は「毎月4週の型」に季節要素を当てはめたガイドです。",
        f"- 今回の指定: **{m}月・第{w}週** — {phase_title}（{phase_axis}）",
        f"- この週の狙い: {phase_desc}",
        f"- **この週の推奨シチュ（衣装・背景の核）**: {current_theme}",
        "",
        f"（参考）{m}月の4週シチュ早見:",
        f"  第1週: {themes[0]}",
        f"  第2週: {themes[1]}",
        f"  第3週: {themes[2]}",
        f"  第4週: {themes[3]}",
        "",
        "【生成への反映】",
        "- 章立て・各シーンの衣装・背景・小物は、上記の「今週の推奨シチュ」とフェーズの雰囲気に**優先的に**寄せる。",
        "- ベースプロンプト・キャラ固定要素と矛盾しない範囲で、季節・イベント要素を narrative / common_setting / 各章の prompt に織り込む。",
        "- 章数はユーザ指定の目安を守りつつ、今週のテーマが伝わるシーン構成にする。",
    ]
    note = (rotation_note or "").strip()
    if note:
        lines.extend(
            [
                "",
                "【キャラローテ・主役メモ（ユーザー入力。参照してシーン配分やペアを考慮）】",
                note,
            ]
        )
    return "\n".join(lines)


def parse_seasonal_form(
    enabled: bool,
    month_raw: str | None,
    week_raw: str | None,
    today: date | None = None,
) -> tuple[bool, int, int]:
    """
    フォーム値を解釈。月・週が空または auto のときは今日の日付から補う。
    month_raw / week_raw: "" または "auto" で自動。数値文字列で 1〜12 / 1〜4。
    """
    if not enabled:
        return False, 1, 1
    today = today or date.today()
    m_default = today.month
    w_default = week_of_month(today)

    mr = (month_raw or "").strip().lower()
    wr = (week_raw or "").strip().lower()

    if not mr or mr == "auto":
        month = m_default
    else:
        try:
            month = int(mr)
        except ValueError:
            month = m_default

    if not wr or wr == "auto":
        week = w_default
    else:
        try:
            week = int(wr)
        except ValueError:
            week = w_default

    month, week = clamp_month_week(month, week)
    return True, month, week
