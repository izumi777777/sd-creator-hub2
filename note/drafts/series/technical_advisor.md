# 【技術】相談チャット：セッション履歴・ストーリー資料・Gemini【下書き】

**種別:** 実装メモ（開発者向け）  
**関連:** [feature_advisor.md](feature_advisor.md)

---

## 担当コード

- **Blueprint:** `app/routes/advisor_chat.py`（プレフィックス `/advisor`）
- **プロンプト:** `app/prompts/advisor_prompts.py`（`ADVISOR_SYSTEM_BY_CONTEXT`、許可コンテキスト一覧）
- **サービス:** `app/services/gemini_service.py` の `call_gemini_chat`
- **テンプレート:** `app/templates/partials/advisor_dock.html`、コンテキストプロセッサ `register_advisor_context_processor`

---

## 処理の流れ（概要）

1. **セッション**に会話履歴を保持（件数・文字数上限あり）。`clear_history` で削除。
2. `default_advisor_context_for_request()` が **request.endpoint** のプレフィックスから **相談モード既定値**を推測。
3. ストーリー資料: `story.detail` では DB の `Story`＋章から組み立て、否则は `session['advisor_draft_story']`。`format_story_bundle_from_dict` でプレーンテキスト化（長さ上限）。
4. `attach_story` かつ資料ありのとき、**ユーザー履歴は短く保ち**、**システムプロンプト末尾に資料を追記**して送信。
5. `POST /advisor/attach-draft` で生成 JSON をセッションに保存（一覧 → 相談への橋渡し）。
6. **POST の `story_context` サイズ上限**（改ざん対策）で異常値を 400。

---

## 注意点

- 履歴が長いと **トークンとコスト**が増える。上限定数は `advisor_chat.py` 先頭を参照。
- プロンプト変更は **`advisor_prompts.py` のみ**触ると追いやすい。

*エンドポイント追加時は `ALLOWED_ADVISOR_CONTEXTS` とテンプレの hidden を同期。*
