# 📊 Case 7: Streaming Sales Pipeline — From CSV Chaos to a Trusted Dashboard

**Author:** Pranayak Uniyal

> A lightweight, end-to-end sales data pipeline that ingests 30+ daily CSV files, enforces data quality checks, builds analytical fact/dimension tables, and serves a live Streamlit dashboard — all without a single external infrastructure dependency.

---

## Table of Contents

- [Quick Start](#quick-start)
- [Project Overview](#project-overview)
- [Architecture](#architecture)
- [Component Deep Dive](#component-deep-dive)
  - [1. Data Ingestion (`ingest.py`)](#1-data-ingestion-ingestpy)
  - [2. Transformations (`transform.py` + `transforms.sql`)](#2-transformations-transformpy--transformssql)
  - [3. Warehouse (`warehouse.duckdb`)](#3-warehouse-warehouseduckdb)
  - [4. Dashboard (`dashboard.py`)](#4-dashboard-dashboardpy)
- [Data Quality Framework](#data-quality-framework)
- [Data Model](#data-model)
- [Key Design Decisions](#key-design-decisions)
- [Supporting Documentation](#supporting-documentation)
- [File Reference](#file-reference)
- [Requirements](#requirements)

---

## Quick Start

Get the full pipeline running in under 5 minutes:

```bash
# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Place your CSV data
#    - 30 daily files go here:
cp your_files/*.csv data/case7_daily_sales/

#    - Late-arriving file goes in the subfolder:
cp sales_2025-03-18.csv data/case7_daily_sales/late_arrivals/

# 3. Run ingestion (loads raw data + runs DQ checks)
python pipeline/ingest.py

# 4. Run transformations (builds fact and dimension tables)
python pipeline/transform.py

# 5. Launch the dashboard
streamlit run dashboard/dashboard.py
```

The dashboard will be available at `http://localhost:8501` by default.

---

## Project Overview

This pipeline solves a common real-world problem: a finance or operations team receives 30 daily CSV files from various regional sales systems. These files have inconsistencies — duplicate records, late arrivals, schema changes, and data gaps. The goal is to:

1. **Ingest** all files reliably and idempotently (safe to re-run without double-counting)
2. **Detect** data quality issues automatically and log them
3. **Transform** raw data into clean, analytics-ready tables
4. **Serve** a CFO-grade dashboard with KPIs, trends, and a DQ audit panel

The entire stack runs locally with zero infrastructure. No Spark, no cloud warehouse, no BI server.

---

## Architecture

```
data/case7_daily_sales/
   ├── sales_2025-03-01.csv
   ├── sales_2025-03-02.csv
   ├── ...  (30 daily CSVs)
   └── late_arrivals/
       └── sales_2025-03-18.csv      ← Late file detected separately
              │
              ▼
   ┌─────────────────────────┐
   │   pipeline/ingest.py    │  ← Step 1: Load + DQ checks
   │                         │
   │  - MD5 deduplication    │
   │  - Schema validation    │
   │  - Null spike detection │
   │  - Duplicate order IDs  │
   └──────────┬──────────────┘
              │
              ▼
   ┌─────────────────────────────────┐
   │         warehouse.duckdb        │
   │                                 │
   │  raw_sales      ← Source truth  │
   │  dq_log         ← DQ audit log  │
   │  loaded_files   ← Idempotency   │
   └──────────┬──────────────────────┘
              │
              ▼
   ┌──────────────────────────┐
   │  pipeline/transform.py   │  ← Step 2: SQL model runner
   │  models/transforms.sql   │
   └──────────┬───────────────┘
              │
              ▼
   ┌──────────────────────────────────────┐
   │         warehouse.duckdb             │
   │                                      │
   │  stg_sales           ← Cleaned view  │
   │  fct_daily_revenue   ← Daily KPIs    │
   │  fct_product_summary ← By product    │
   │  fct_region_summary  ← By region     │
   │  dim_products_scd2   ← Price history │
   └──────────┬───────────────────────────┘
              │
              ▼
   ┌──────────────────────────┐
   │  dashboard/dashboard.py  │  ← Step 3: Streamlit app
   │                          │
   │  Revenue trends          │
   │  Product performance     │
   │  Regional breakdown      │
   │  DQ audit panel          │
   └──────────────────────────┘
```

---

## Component Deep Dive

### 1. Data Ingestion (`ingest.py`)

This is the entry point for all raw data. It handles both the primary daily files and any late-arriving files.

**What it does:**

- **Glob both paths:** Scans `data/case7_daily_sales/*.csv` and `data/case7_daily_sales/late_arrivals/*.csv` so late files are never missed.
- **MD5 fingerprinting:** Before loading any file, it computes an MD5 hash of its content and checks the `loaded_files` table. If the hash already exists, the file is skipped entirely — making the pipeline fully idempotent (safe to re-run at any time without creating duplicate records).
- **Schema validation:** Each file's columns are compared against the `EXPECTED_COLS` constant. Any missing or extra columns trigger a `SCHEMA_DRIFT` entry in `dq_log` and the file is quarantined rather than loaded.
- **Null spike detection:** For critical columns (e.g., `order_id`, `revenue`, `region`), the pipeline calculates the percentage of null values per column. If any exceed 5%, a `NULL_SPIKE` failure is written to `dq_log`.
- **Intra-file deduplication:** Within each file, `drop_duplicates()` removes exact duplicate rows before they touch the database.
- **Cross-file deduplication:** After loading, a SQL query checks for `order_id` values that already exist in `raw_sales` from a prior file, preventing cross-file duplicates.
- **DQ log writes:** Every check — pass or fail — is written to the `dq_log` table with a timestamp, file name, check type, and status.

**Idempotency guarantee:**

```
File A loaded on Monday → MD5 stored in loaded_files
File A re-run on Tuesday → MD5 match found → SKIP, no duplicate rows
```

### 2. Transformations (`transform.py` + `transforms.sql`)

`transform.py` acts as a lightweight SQL model runner. It reads `models/transforms.sql`, splits it into individual model definitions, and executes them in dependency order against `warehouse.duckdb`.

All transformation logic lives in pure SQL inside `transforms.sql`, making it easy to audit, version-control, and eventually migrate to dbt or another SQL-first tool.

**Models built:**

| Model | Type | Description |
|---|---|---|
| `stg_sales` | View | Casts columns to correct types, strips whitespace, filters nulls in critical fields |
| `fct_daily_revenue` | Table | Aggregates to daily level: total revenue, order count, average order value |
| `fct_product_summary` | Table | Revenue, units sold, and return rate per product |
| `fct_region_summary` | Table | Revenue breakdown and order volume per region |
| `dim_products_scd2` | Table | SCD Type-2 product dimension: tracks historical price changes with `valid_from` / `valid_to` dates |

**Why SCD Type-2 for products?**

Product prices change over time. If a product was sold in March at $50 and the price later changes to $60, historical revenue queries must use the price that was active at the time of sale — not today's price. SCD Type-2 preserves this history with effective date ranges, so revenue calculations are always accurate regardless of when the report is run.

### 3. Warehouse (`warehouse.duckdb`)

DuckDB serves as the local analytical warehouse. It is a single `.duckdb` file on disk — no server process, no installation, no configuration.

**Tables:**

| Table | Purpose |
|---|---|
| `raw_sales` | Immutable source of truth. Rows are appended here and never modified. |
| `dq_log` | Audit log for every data quality check. Each row has: `file`, `check_type`, `status`, `details`, `checked_at`. |
| `loaded_files` | Idempotency registry. Stores `filename` and `file_md5` for every successfully ingested file. |

**Why DuckDB?**

DuckDB is SQL-native, columnar, and extremely fast on CSV and in-memory analytical queries. It requires no external infrastructure, can be committed to version control alongside the code, and is trivially portable — anyone can clone the repo and run the pipeline without setting up a database server. It also natively reads CSVs, Parquet, and JSON, which makes the ingestion layer simpler.

### 4. Dashboard (`dashboard.py`)

A Streamlit application that connects directly to `warehouse.duckdb` and renders live analytical views.

**Panels:**

- **Revenue Overview:** Daily revenue trend chart, total revenue KPI card, and period-over-period comparison.
- **Product Performance:** Table and bar chart from `fct_product_summary` — sortable by revenue, units, or return rate.
- **Regional Breakdown:** Map-style or bar chart from `fct_region_summary` showing which regions are over- or under-performing.
- **Data Quality Audit Panel:** A table rendering the full `dq_log` — every check, its status (PASS / FAIL / WARN), and details. This gives analysts immediate visibility into any issues without querying the database manually.

Streamlit was chosen because it produces a shareable, interactive dashboard from pure Python — no BI server, no licensing, and it can be deployed to Streamlit Cloud with a single command for team-wide access.

---

## Data Quality Framework

The pipeline is designed to catch exactly 4 intentional data quality issues embedded in the dataset. All results are written to `dq_log` and surfaced in the dashboard.

| # | Issue | Detection Method | Outcome on Failure |
|---|---|---|---|
| 1 | **Duplicate `order_id`s** | `drop_duplicates()` within each file; cross-file SQL dedup on `raw_sales` | Duplicates dropped; count logged |
| 2 | **Late-arriving file** | Glob includes `late_arrivals/` subfolder alongside main directory | File ingested normally; source path flagged in log |
| 3 | **Schema drift** | Column set compared to `EXPECTED_COLS` constant on every file load | File quarantined; `SCHEMA_DRIFT` written to `dq_log` |
| 4 | **Null spike** | Per-column null % calculated; FAIL triggered if >5% in any critical column | `NULL_SPIKE` written to `dq_log`; file still loaded with warning |

**DQ Log schema:**

```
dq_log
├── id           INTEGER   Auto-increment primary key
├── file         TEXT      Source filename
├── check_type   TEXT      DUPLICATE_ORDER_ID | LATE_ARRIVAL | SCHEMA_DRIFT | NULL_SPIKE
├── status       TEXT      PASS | FAIL | WARN
├── details      TEXT      Human-readable description (e.g., "3 duplicate order_ids removed")
└── checked_at   TIMESTAMP UTC timestamp of the check
```

---

## Data Model

```
dim_products_scd2                    raw_sales
─────────────────                    ─────────
product_id  (PK)                     order_id
product_name                         sale_date
category                             product_id  ──→ dim_products_scd2.product_id
price                                region
valid_from                           quantity
valid_to                             revenue
is_current                           loaded_at
                                     source_file

         │                    │
         └────────────────────┘
                  │
                  ▼
         stg_sales (view)
         ──────────────────
         Cleaned + typed version of raw_sales
         Joins with dim_products_scd2 on
         product_id WHERE sale_date BETWEEN
         valid_from AND valid_to

                  │
         ┌────────┼────────┐
         ▼        ▼        ▼
fct_daily_revenue  fct_product_summary  fct_region_summary
```

---

## Key Design Decisions

**DuckDB over Postgres/SQLite**
DuckDB is columnar and purpose-built for analytical queries. On 30 daily CSV files it is orders of magnitude faster than SQLite for aggregations. Unlike Postgres, it requires zero setup. Unlike Pandas alone, it supports full SQL with window functions, CTEs, and joins.

**Plain Python + SQL over an orchestrator**
For a 30-file batch job, adding Airflow or Prefect would introduce significant operational overhead (web server, scheduler, worker, metadata DB) with no real benefit. `ingest.py` and `transform.py` can be trivially wrapped in a cron job or called by an orchestrator later if scale demands it.

**MD5-based idempotency over timestamp-based**
Timestamps are unreliable — files can be re-delivered with the same name but different content, or re-delivered after a system clock change. An MD5 hash of the file content is a content-addressable fingerprint: if the file changed, the hash changes and it re-ingests. If the file is identical, it skips.

**SCD Type-2 for product prices**
Historical revenue accuracy requires knowing what price was active at the time of each sale. SCD Type-2 preserves the full price history with `valid_from` / `valid_to` date ranges. A simple overwrite (SCD Type-1) would silently corrupt historical revenue numbers whenever a price changes.

**Streamlit over a BI tool**
Streamlit produces a fully interactive dashboard in pure Python. It can run locally or be deployed to Streamlit Cloud for free. There is no BI server to manage, no license to purchase, and the DQ audit panel (which surfaces `dq_log` data) would be difficult to build in most BI tools without custom SQL widgets.

**All SQL in `transforms.sql`**
Keeping transformation logic in a single `.sql` file makes it auditable, diff-able in git, and easy to migrate to dbt or any other SQL runner. `transform.py` is intentionally thin — it is just a runner, not a logic layer.

---

## Supporting Documentation

| File | Purpose |
|---|---|
| `DATA_CONTRACT.md` | Formal input specification: expected schema, column types, acceptable value ranges, DQ rules, and what happens on breach |
| `CFO_INVESTIGATION_GUIDE.md` | Step-by-step playbook for a CFO or analyst to investigate unexpected revenue changes in under 10 minutes |
| `DECISIONS.md` | Full trade-off log for every architectural and tooling choice made during the build |

---

## File Reference

```
├── pipeline/
│   ├── ingest.py           ← Ingestion entry point: file discovery, MD5 check,
│   │                         schema validation, null checks, dedup, raw_sales load
│   └── transform.py        ← SQL model runner: reads transforms.sql, executes
│                             models in order against warehouse.duckdb
│
├── models/
│   └── transforms.sql      ← All SQL transformations:
│                             stg_sales, fct_daily_revenue, fct_product_summary,
│                             fct_region_summary, dim_products_scd2
│
├── dashboard/
│   └── dashboard.py        ← Streamlit app: revenue trends, product/region
│                             performance, DQ audit panel
│
├── data/
│   └── case7_daily_sales/
│       ├── *.csv                    ← 30 daily sales files
│       └── late_arrivals/
│           └── sales_2025-03-18.csv ← Late file example
│
├── warehouse.duckdb         ← Single-file DuckDB warehouse (generated on run)
│
├── DATA_CONTRACT.md         ← Input spec + DQ rules + breach handling
├── CFO_INVESTIGATION_GUIDE.md ← 10-min revenue change playbook
├── DECISIONS.md             ← Trade-off log
└── requirements.txt         ← Python dependencies
```

---

## Requirements

**Python dependencies** (see `requirements.txt`):

| Package | Purpose |
|---|---|
| `duckdb` | Local analytical warehouse |
| `pandas` | CSV reading, intra-file deduplication |
| `streamlit` | Dashboard rendering |
| `hashlib` | MD5 fingerprinting for idempotency (stdlib) |

**Python version:** 3.9+

**No external services required.** The entire stack runs offline on a single machine.

---

*Pipeline designed and implemented by Pranayak Uniyal.*
