# 【技術】テキスト生成ルートとプロンプトテンプレ【下書き】

**種別:** 実装メモ（開発者向け）  
**関連:** [feature_text_gen.md](feature_text_gen.md)

---

## 担当コード

- **Blueprint:** `app/routes/text_gen.py`（プレフィックス `/text-gen`）
- **プロンプト:** `app/prompts/text_gen_prompt.py`（`PIXIV_PROMPT` / `DLSITE_PROMPT` / `PICTSPACE_PROMPT`）
- **サービス:** `app/services/gemini_service.py` の `call_gemini_json`（プラットフォーム別にプロンプトを切替）

---

## 設計の要点

- **相談ドック**（`advisor`）とプロンプト資産を共有したい場合、`advisor_prompts.py` のコンテキストキーと揃えると一貫しやすい。
- htmx で **生成ブロックのみ更新**しているなら、フォームの `hx-*` 属性と部分テンプレートを確認。

*実装詳細は `text_gen.py` と対応テンプレートをソース優先で追記すること。*
