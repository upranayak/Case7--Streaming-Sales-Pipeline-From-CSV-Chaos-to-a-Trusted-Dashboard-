# DECISIONS.md — Trade-offs & Assumptions

**Candidate:** Pranayak Uniyal  
**Case:** 7 — Streaming Sales Pipeline

---

## Technology Choices

### DuckDB over Postgres/BigQuery
- **Why:** Zero setup, single-file warehouse, full SQL, columnar for analytics. For 30 CSVs (~19MB) this is overkill in the best way. Postgres would need a server; BigQuery needs a GCP account. DuckDB just works.
- **Trade-off:** Not a production-scale distributed system. For 10M+ rows/day, swap to BigQuery/Redshift — the SQL models are portable.

### Plain Python over Airflow/Prefect/Dagster
- **Why:** The task is a 30-file historical backfill, not a streaming system. Adding Airflow for this would be 200 lines of boilerplate for 2 tasks. The pipeline is trivially wrappable in any orchestrator via a bash operator.
- **Trade-off:** No built-in scheduling/retry UI. For production, I'd add a Prefect flow decorator around `ingest.py` in ~15 minutes.

### Streamlit over Metabase/Superset
- **Why:** One Python file, no server, DQ panel baked in, shareable as a link. Metabase requires Docker + Postgres metadata store.
- **Trade-off:** Not a full BI tool. No drag-and-drop. Acceptable for an engineering demo.

### SQL models in a single file over dbt
- **Why:** dbt is fantastic for teams; for a solo case submission it adds a `profiles.yml`, `dbt_project.yml`, and package installs. The SQL is identical. Migrating to dbt would be a `cp` and a rename.
- **Trade-off:** No dbt docs, no lineage graph auto-generation.

---

## Data Quality Assumptions

1. **Null spike threshold = 5%** — arbitrary but defensible. In production, this would be configurable per-column.
2. **Duplicate strategy = keep first** — "first" means first seen in the CSV. For cross-file deduplication, first loaded wins. This is idempotent.
3. **Late arrivals are valid** — a file in `late_arrivals/` is treated as authoritative. No penalty applied to the revenue for that day.
4. **Revenue formula** — `qty × unit_price × (1 − discount_pct)`. Assumes `discount_pct` is a fraction (0.15 = 15%), not a percentage (15 = 15%).

---

## SCD Type-2 Assumptions

- A "version" of a product is defined by a daily snapshot of its average price.
- Price drift across the same day is smoothed into an average (not worth tracking sub-daily).
- `is_current = TRUE` for the most recent record per `product_id`.

---

## What I'd Do With More Time

1. Add **Prefect flow** with retry and alerting (Slack webhook on DQ FAIL).
2. Add **data lineage diagram** (Mermaid or hand-drawn showing CSV → raw → stg → fct).
3. Add **column-level profiling** (min/max/stddev per numeric column, per file).
4. Add **unit tests** for the transform SQL using dbt's `dbt test` or pytest + DuckDB in-memory.
5. Deploy to **Streamlit Cloud** for a live demo link.
