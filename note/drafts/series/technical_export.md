# 【技術】PDF（fpdf2）・ZIP・署名付き URL【下書き】

**種別:** 実装メモ（開発者向け）  
**関連:** [feature_export.md](feature_export.md)

---

## 担当コード

- **Blueprint:** `app/routes/export.py`（プレフィックス `/export`）
- **PDF:** `app/services/pdf_service.py`（`generate_pdf`）
- **ZIP:** `app/services/zip_service.py`（`generate_zip`）
- **画像 URL 解決:** ルート内 `_fetch_url_for_image`（署名付き URL 優先）

---

## 設計の要点

- PDF 生成時は **URL から画像を取得**してバイナリ化する流れ（タイムアウト・大きさ制限に注意）。
- `send_file` で **メモリ上の BytesIO** を返すパターン（実装参照）。

---

## 注意点

- 同時選択枚数が多いと **メモリと処理時間**が増える。必要なら枚数上限や非同期化の検討。

*依存ライブラリは `requirements.txt` を参照。*
