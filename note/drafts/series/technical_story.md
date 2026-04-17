# 【技術】ストーリー生成：Gemini JSON・正規化・htmx【下書き】

**種別:** 実装メモ（開発者向け）  
**関連:** [feature_story.md](feature_story.md)

---

## 担当コード

- **Blueprint:** `app/routes/story.py`（プレフィックス `/story`）
- **プロンプト:** `app/prompts/story_prompt.py`（初回生成）、`app/prompts/story_revise_prompt.py`（加筆）
- **AI 呼び出し:** `app/services/gemini_service.py` の `call_gemini_json` 等
- **モデル:** `app/models/story.py`（章の格納方法はモデル・マイグレーション参照）

---

## 処理の流れ（概要）

1. フォームから **character_id、prompt_ids、ベース文言** を受け取る。
2. `_build_reference_prompt_block` で **ライブラリ本文を連結**し、不正な prompt_id（他キャラ）は除外。
3. Gemini に **システムプロンプト＋ユーザー文** を渡し、**JSON** を返させる。
4. `_normalize_gemini_story` で **章の `prompt` / `neg` 欠損を variants から補完**し、キーを揃える。
5. 保存時は **Story 行＋章** を DB に書く（詳細はルート内の保存処理）。
6. UI は **htmx** で生成ブロックだけ差し替え（テンプレートは `story/` 配下）。

---

## 注意点

- **トークン長:** 参照プロンプトが長いと入力が膨らむ。必要ならトリムや章数制限を検討。
- **JSON パース失敗:** サービス層・ルートでエラーハンドリングとフラッシュ表示を確認。

*エンドポイント名は `flask routes` や `story.py` の `@bp.route` で最新を確認。*
