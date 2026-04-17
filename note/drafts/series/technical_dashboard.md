# 【技術】ダッシュボードの集計とテンプレート【下書き】

**種別:** 実装メモ（開発者向け）  
**関連:** [feature_dashboard.md](feature_dashboard.md)

---

## 担当コード

- **Blueprint:** `app/routes/dashboard.py`（ルート名 `dashboard`）
- **テンプレート:** `app/templates/dashboard/` 配下
- **データ:** 各モデルの `count()`、直近の `Work` / `Story`（各5件）、`SalesRecord` 直近6ヶ月、`Work.total_revenue` の合計（実装はルート参照）

---

## 設計の要点

- **N+1:** 直近リストは件数が少ないのでシンプルなまま。`total_revenue_works` は全 `Work` を読むため、件数増大時は集約クエリへの置き換えを検討。
- 表示は **サーバー側レンダリング（Jinja2）** 。部分更新は不要な画面。

---

## 拡張アイデア

- 「下書きストーリー件数」などステータス別カウント
- 売上は既に `sales_rows` があるので、グラフ化・前年比など

*リポジトリ変更後はクエリとテンプレート変数名を再確認すること。*
