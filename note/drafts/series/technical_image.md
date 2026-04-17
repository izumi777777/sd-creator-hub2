# 【技術】画像アップロード・S3・Image モデル【下書き】

**種別:** 実装メモ（開発者向け）  
**関連:** [feature_image.md](feature_image.md)

---

## 担当コード

- **Blueprint:** `app/routes/image.py`（プレフィックス `/image`）
- **S3:** `app/services/s3_service.py`（設定検知・アップロード・署名付き URL 等）
- **モデル:** `app/models/image.py`
- **メタデータ除去:** `app/routes/metadata_strip.py`（プレフィックス `/metadata-strip`）

---

## 設計の要点

- `secure_filename` でファイル名を正規化。**Content-Type** は拡張子から `_guess_content_type` で推定。
- DB には **s3_key / s3_url** 等を保存し、プライベートバケットでは **署名付き URL** で参照（エクスポート側の `_fetch_url_for_image` と同様の考え方）。

---

## メタデータ除去

- 画像バイナリを読み、Pillow 等で **再エンコードしてメタデータを落とす**パターンが多い（実装は `metadata_strip` ルートとサービスを参照）。

*環境変数名は `.env.example` と `config.py` を照合。公開文書に値を書かない。*
