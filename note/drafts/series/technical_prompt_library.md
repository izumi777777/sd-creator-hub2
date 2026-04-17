# 【技術】プロンプトライブラリ CRUD とキャラ整合【下書き】

**種別:** 実装メモ（開発者向け）  
**関連:** [feature_prompt_library.md](feature_prompt_library.md)

---

## 担当コード

- **Blueprint:** `app/routes/prompt.py`（プレフィックス `/prompt`）
- **モデル:** `app/models/prompt.py`（`character_id` でキャラに紐づく）

---

## 設計の要点

- 作成・更新時に **character_id** を必ず検証し、**他人のキャラ**にプロンプトが付かないようにする。
- ストーリー側では `Prompt.query.get(pid)` と **`p.character_id != character_id` ならスキップ**（`story.py` の参照ブロック構築）。

---

## 拡張アイデア

- タグ・並び順・お気に入り
- 画像ページから「この画像のプロンプトをライブラリに保存」

*ルート名は `prompt.py` を参照。*
