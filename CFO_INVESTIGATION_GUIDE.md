# If the CFO Asks: "Why Did Monday's Number Change by 3%?"

**How I'd find the answer in under 10 minutes.**

---

## Step 1 — Check the DQ Log First (1 min)

```sql
SELECT * FROM dq_log
WHERE run_ts >= (SELECT MAX(run_ts) FROM dq_log) - INTERVAL 2 DAYS
  AND status IN ('FAIL', 'WARN')
ORDER BY run_ts DESC;
```

**What to look for:** Any FAIL on the day in question. A schema drift, null spike,
or late file would directly reduce that day's counted revenue.

---

## Step 2 — Compare the Two Runs (2 min)

```sql
-- Run A (before the change)
SELECT sale_date, net_revenue FROM fct_daily_revenue WHERE sale_date = 'YYYY-MM-DD';

-- Check if raw row counts changed
SELECT _source_file, COUNT(*) AS rows, MAX(_loaded_at) AS loaded_at
FROM raw_sales
WHERE _source_file LIKE '%YYYY-MM-DD%'
GROUP BY 1;
```

If `rows` changed between runs → a late-arriving file was added, or dedup removed records.

---

## Step 3 — Check for Late Arrivals (2 min)

```sql
SELECT filename, loaded_at FROM loaded_files
WHERE filename LIKE '%YYYY-MM-DD%'
ORDER BY loaded_at;
```

If the file was loaded *after* Monday's run but *before* Tuesday's run, the
late file is the culprit. Revenue went **up** 3%. This is expected — correct behavior.

---

## Step 4 — Check for Deduplication Impact (2 min)

```sql
SELECT check, detail FROM dq_log
WHERE check LIKE '%Dup%'
  AND detail NOT LIKE '%0 duplicate%'
ORDER BY run_ts DESC;
```

If dedup removed rows on that date, revenue went **down**. The first run double-counted;
the second run is the correct number.

---

## Step 5 — Inspect the Revenue Formula (1 min)

```sql
SELECT
    order_id,
    qty,
    unit_price,
    discount_pct,
    ROUND(qty * unit_price * (1 - discount_pct), 2) AS line_revenue
FROM stg_sales
WHERE order_timestamp::DATE = 'YYYY-MM-DD'
ORDER BY line_revenue DESC
LIMIT 20;
```

Look for any abnormal `unit_price` or `discount_pct` values that weren't there before
(e.g., a 90% discount appearing for the first time = schema/data corruption).

---

## Step 6 — Explain to CFO (1 min)

Draft answer template:

> "The 3% change on Monday was caused by **[late file arrival / duplicate removal / null exclusion]**.
> Specifically, **[sales_2025-03-XX.csv]** arrived in the `late_arrivals/` folder after Monday's
> run. Our pipeline correctly ingested it on Tuesday, adding **$X,XXX** in net revenue.
> The Tuesday number is the authoritative figure. I can share the `dq_log` entry if needed."

---

## Quick Reference: Revenue Audit Query

```sql
-- Full daily audit trail
SELECT
    d.sale_date,
    d.net_revenue,
    d.order_count,
    l.loaded_at         AS file_loaded_at,
    l.filename          AS source_file,
    (SELECT COUNT(*) FROM dq_log dq
     WHERE dq.status = 'FAIL'
       AND dq.file = l.filename) AS dq_failures
FROM fct_daily_revenue d
JOIN loaded_files l ON l.filename LIKE '%' || d.sale_date::VARCHAR || '%'
ORDER BY d.sale_date;
```

**Total time: ~10 minutes, no Excel, no Slack threads.**
