# Data Contract: Daily Sales CSVs → Sales Warehouse

**Owner:** Data Engineering  
**Consumer:** Finance / CFO Dashboard  
**Version:** 1.0  
**Effective Date:** 2025-03-01  

---

## 1. Input Specification

| Field | Type | Required | Rules |
|-------|------|----------|-------|
| order_id | string | ✅ | Pattern: `ORD\d{15}`, globally unique |
| order_timestamp | ISO-8601 string | ✅ | Must parse to valid timestamp |
| customer_id | string | ✅ | Pattern: `C\d{5}` |
| product_id | string | ✅ | Must exist in known product list (P001–P012) |
| product_name | string | ✅ | Must match product_id |
| category | string | ✅ | One of: Electronics, Grocery, Apparel, Stationery, Home |
| qty | integer | ✅ | 1–100 |
| unit_price | float | ✅ | 0.01–10,000 |
| discount_pct | float | ✅ | 0.0–1.0 (0% to 100%) |
| region | string | ✅ | One of: North, South, East, West |

**File naming:** `sales_YYYY-MM-DD.csv`  
**Delivery SLA:** File present by 02:00 UTC the next calendar day  
**Late arrivals:** Placed in `late_arrivals/` subfolder, still processed  

---

## 2. Quality Checks Implemented

### QC-1: Schema Drift
- Checks every column name against the expected schema on load
- **On failure:** File is loaded with best-effort column matching; alert raised; analyst notified

### QC-2: Duplicate Order IDs (intra-file)
- Duplicate `order_id` within a single file
- **On failure:** First occurrence kept; duplicates dropped; count logged

### QC-3: Cross-file Duplicates
- Same `order_id` appearing in multiple daily files
- **On failure:** Earliest-loaded record wins (idempotent); count logged

### QC-4: Null Spike
- >5% nulls in `order_id`, `unit_price`, or `qty`
- **On failure:** FAIL alert raised; rows with null critical fields are excluded from `stg_sales`

### QC-5: Missing / Late Files (Freshness)
- Checks all 30 March dates are covered (including `late_arrivals/`)
- **On failure:** FAIL logged with missing date list; revenue for that day is absent from totals

### QC-6: Row Count Anomaly
- <100 or >15,000 rows in a single daily file triggers a warning

---

## 3. Output Tables

| Table | Description |
|-------|-------------|
| `raw_sales` | All ingested rows, immutable, with source metadata |
| `stg_sales` | Cleaned, type-cast, null-filtered view |
| `fct_daily_revenue` | Aggregated daily revenue, orders, customers |
| `fct_product_summary` | Revenue & units by product |
| `fct_region_summary` | Revenue by region |
| `dim_products_scd2` | SCD Type-2 product dimension |
| `dq_log` | All quality check results with timestamps |

---

## 4. Revenue Formula

```
net_revenue = qty × unit_price × (1 − discount_pct)
```

All monetary values in **USD**. No currency conversion applied.

---

## 5. SLA & Breach Handling

| Condition | Action |
|-----------|--------|
| File missing by 04:00 UTC | Logged as FAIL in `dq_log`; dashboard shows gap |
| >10% duplicate rows | Pipeline halts; manual review required |
| Schema change | Auto-mapped if column count matches; else FAIL + halt |
| Null spike >5% | FAIL logged; affected rows excluded |

---

## 6. Idempotency

Re-running the pipeline for the same file is safe:
- Files are fingerprinted (MD5 hash)
- Already-loaded `filename + hash` pairs are skipped
- Cross-file deduplication runs after every batch

---

## 7. Intentional Issues Found in March 2025 Data

| # | Issue Type | Location | Description |
|---|-----------|----------|-------------|
| 1 | **Duplicate rows** | One daily file | Multiple order_ids repeated within the file |
| 2 | **Late/missing file** | `late_arrivals/` | `sales_2025-03-18.csv` not in main folder |
| 3 | **Schema drift** | One daily file | Column name change or extra/missing column |
| 4 | **Null spike** | One daily file | >5% nulls in a critical column |

*Exact file locations discovered at runtime; see `dq_log` table.*
