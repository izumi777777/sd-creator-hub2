# 【技術】キャラクター・作品モデルと CRUD ルート【下書き】

**種別:** 実装メモ（開発者向け）  
**関連:** [feature_character_work.md](feature_character_work.md)

---

## 担当コード

- **Blueprint:** `app/routes/character.py`（`/character`）、`app/routes/work.py`（`/work`）
- **モデル:** `app/models/character.py`、`app/models/work.py`（および `app/models` の関連定義）
- **DB:** Flask-SQLAlchemy、`Flask-Migrate` でスキーマ管理

---

## 設計の要点

- 作品は **character_id などでキャラに紐づく**想定（実際の外部キーはモデル定義を参照）。
- 削除時は **子レコード**（プロンプト・ストーリー等）の扱いに注意。カスケード or 制約はマイグレーションとモデルで確認。

---

## ストーリー・プロンプトとの接続

- ストーリー生成フォームでは **キャラ選択 → プロンプトライブラリ** が同一キャラに限定されるよう、ルート側でフィルタしている（`story.py` 等）。

*モデル変更時は本稿のファイルパスと制約説明を更新すること。*
