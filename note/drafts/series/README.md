# 機能解説シリーズ（下書き置き場）

**既存の日付記事**（[../2026-04-05.md](../2026-04-05.md)・[../2026-04-04.md](../2026-04-04.md)）は**そのまま**エッセイ／動機メモとして残します。  
本フォルダは、**各機能を読者向けに分解した記事**と、**実装の仕組みを書く記事**のペアです。

## 記事の種類

| 種類 | パス | 想定読者 | 内容の例 |
|------|------|----------|----------|
| **機能** | `feature_*.md` | アプリ利用者・同業クリエイター | 何ができるか、画面の流れ、注意点 |
| **技術** | `technical_*.md` | 自分・エンジニア寄り | Blueprint、DB、外部 API、htmx、プロンプトの置き場所 |

note に出すときは、**機能だけ公開**／**技術だけ公開**／**同一記事に前後編**のどれでもよいです。ペアでファイルを分けてあるので、編集しやすいだけです。

## ファイル対応表（ペア）

| テーマ | 機能記事 | 技術記事 |
|--------|----------|----------|
| ダッシュボード | [feature_dashboard.md](feature_dashboard.md) | [technical_dashboard.md](technical_dashboard.md) |
| キャラクター・作品 | [feature_character_work.md](feature_character_work.md) | [technical_character_work.md](technical_character_work.md) |
| ストーリー生成 | [feature_story.md](feature_story.md) | [technical_story.md](technical_story.md) |
| プロンプトライブラリ | [feature_prompt_library.md](feature_prompt_library.md) | [technical_prompt_library.md](technical_prompt_library.md) |
| テキスト生成 | [feature_text_gen.md](feature_text_gen.md) | [technical_text_gen.md](technical_text_gen.md) |
| 画像・メタデータ除去 | [feature_image.md](feature_image.md) | [technical_image.md](technical_image.md) |
| PDF / ZIP エクスポート | [feature_export.md](feature_export.md) | [technical_export.md](technical_export.md) |
| 売上メモ | [feature_sales.md](feature_sales.md) | [technical_sales.md](technical_sales.md) |
| Gemini 相談ドック | [feature_advisor.md](feature_advisor.md) | [technical_advisor.md](technical_advisor.md) |

## 執筆メモ

- 機能記事は **スクショ前提**（個人情報・バケット名は消す）。
- 技術記事は **ファイル名・エンドポイントはリポジトリと照合**して更新する（リネームしたらここも直す）。
- 親ディレクトリの [../note.md](../note.md) に、シリーズへのリンクを1行足すと迷子になりにくいです。
