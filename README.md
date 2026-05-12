# Case 7: Streaming Sales Pipeline — From CSV Chaos to a Trusted Dashboard

**Candidate:** Pranayak Uniyal

---

## Quick Start (< 5 minutes)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Place CSV data
#    Copy the 30 daily files to:  data/case7_daily_sales/*.csv
#    Late arrival goes to:         data/case7_daily_sales/late_arrivals/sales_2025-03-18.csv

# 3. Run the pipeline
python pipeline/ingest.py      # Ingest + DQ checks → warehouse.duckdb
python pipeline/transform.py   # Build fact/dim tables

# 4. Launch dashboard
streamlit run dashboard/dashboard.py
```

---

## Architecture

```
data/case7_daily_sales/
        │  (30 CSVs + late_arrivals/)
        ▼
pipeline/ingest.py          ← Ingest, DQ checks, idempotent load
        │
        ▼
warehouse.duckdb
  ├── raw_sales              ← Immutable source of truth
  ├── dq_log                 ← All quality check results
  └── loaded_files           ← Idempotency registry
        │
pipeline/transform.py       ← SQL model runner
        │
        ▼
  ├── stg_sales              ← Cleaned, typed view
  ├── fct_daily_revenue      ← Daily KPIs
  ├── fct_product_summary    ← Product performance
  ├── fct_region_summary     ← Regional breakdown
  └── dim_products_scd2      ← SCD Type-2 product history
        │
        ▼
dashboard/dashboard.py      ← Streamlit dashboard
```

---

## The 4 Data Quality Issues

The pipeline is designed to catch exactly the 4 intentional issues in the dataset:

| # | Check | Detection Method |
|---|-------|-----------------|
| 1 | **Duplicate order_ids** | `drop_duplicates` intra-file + cross-file dedup SQL |
| 2 | **Late-arriving file** | File in `late_arrivals/` subfolder; glob both paths |
| 3 | **Schema drift** | Column set comparison vs `EXPECTED_COLS` on every load |
| 4 | **Null spike** | Per-column null % check; FAIL if >5% in critical columns |

All results written to `dq_log` table and surfaced in the dashboard.

---

## Key Design Choices

- **DuckDB** — zero-infrastructure warehouse; single file, SQL-native, fast on CSVs
- **Plain Python + SQL** — no orchestrator overhead for a 30-file batch; Airflow/Prefect can wrap `ingest.py` trivially
- **Idempotency via MD5** — same file run twice = no double-count, guaranteed
- **SCD Type-2** on products — price history preserved for historical revenue accuracy
- **Streamlit** — shareable, no BI server needed, DQ panel built-in

---

## Files

```
├── pipeline/
│   ├── ingest.py           ← Main ingestion + DQ
│   └── transform.py        ← SQL model runner
├── models/
│   └── transforms.sql      ← All SQL transforms (stg, fct, dim)
├── dashboard/
│   └── dashboard.py        ← Streamlit app
├── DATA_CONTRACT.md        ← Input spec + DQ rules + breach handling
├── CFO_INVESTIGATION_GUIDE.md  ← 10-min revenue change playbook
├── DECISIONS.md            ← Trade-offs
└── requirements.txt
```
