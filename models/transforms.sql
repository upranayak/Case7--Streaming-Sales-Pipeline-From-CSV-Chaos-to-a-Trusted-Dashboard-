-- models/stg_sales.sql
-- Staging: parse types, compute line_revenue, drop nulls in critical cols

CREATE OR REPLACE VIEW stg_sales AS
SELECT
    order_id,
    TRY_CAST(order_timestamp AS TIMESTAMP) AS order_timestamp,
    customer_id,
    product_id,
    product_name,
    category,
    TRY_CAST(qty AS INTEGER)          AS qty,
    TRY_CAST(unit_price AS DOUBLE)    AS unit_price,
    COALESCE(TRY_CAST(discount_pct AS DOUBLE), 0.0) AS discount_pct,
    region,
    _source_file,
    _loaded_at
FROM raw_sales
WHERE order_id IS NOT NULL
  AND unit_price IS NOT NULL
  AND qty IS NOT NULL
  AND TRY_CAST(order_timestamp AS TIMESTAMP) IS NOT NULL;


-- models/fct_daily_revenue.sql
-- Fact: daily revenue aggregated

CREATE OR REPLACE TABLE fct_daily_revenue AS
SELECT
    DATE_TRUNC('day', order_timestamp)::DATE AS sale_date,
    COUNT(DISTINCT order_id)                  AS order_count,
    COUNT(DISTINCT customer_id)               AS unique_customers,
    ROUND(SUM(qty * unit_price * (1 - discount_pct)), 2) AS net_revenue,
    ROUND(SUM(qty * unit_price), 2)           AS gross_revenue,
    ROUND(AVG(qty * unit_price * (1 - discount_pct)), 2) AS avg_order_value
FROM stg_sales
GROUP BY 1
ORDER BY 1;


-- models/fct_product_summary.sql
-- Top products by revenue

CREATE OR REPLACE TABLE fct_product_summary AS
SELECT
    product_id,
    product_name,
    category,
    COUNT(DISTINCT order_id)                        AS order_count,
    SUM(qty)                                         AS total_units_sold,
    ROUND(SUM(qty * unit_price * (1 - discount_pct)), 2) AS net_revenue,
    ROUND(AVG(unit_price), 2)                        AS avg_unit_price,
    ROUND(AVG(discount_pct) * 100, 1)                AS avg_discount_pct
FROM stg_sales
GROUP BY 1, 2, 3
ORDER BY net_revenue DESC;


-- models/fct_region_summary.sql
-- Revenue by region

CREATE OR REPLACE TABLE fct_region_summary AS
SELECT
    region,
    COUNT(DISTINCT order_id)                             AS order_count,
    ROUND(SUM(qty * unit_price * (1 - discount_pct)), 2) AS net_revenue
FROM stg_sales
GROUP BY 1
ORDER BY 2 DESC;


-- models/dim_products_scd2.sql
-- SCD Type-2 product dimension (tracks price/name changes over time)

CREATE OR REPLACE TABLE dim_products_scd2 AS
WITH ranked AS (
    SELECT
        product_id,
        product_name,
        category,
        ROUND(AVG(unit_price), 2) AS avg_price,
        DATE_TRUNC('day', order_timestamp)::DATE AS effective_date,
        ROW_NUMBER() OVER (
            PARTITION BY product_id, DATE_TRUNC('day', order_timestamp)::DATE
            ORDER BY order_timestamp
        ) AS rn
    FROM stg_sales
    GROUP BY product_id, product_name, category,
             DATE_TRUNC('day', order_timestamp)::DATE, order_timestamp
),
daily_snapshot AS (
    SELECT product_id, product_name, category, avg_price, effective_date
    FROM ranked WHERE rn = 1
),
with_end AS (
    SELECT *,
        LEAD(effective_date) OVER (PARTITION BY product_id ORDER BY effective_date)
            AS expiry_date
    FROM daily_snapshot
)
SELECT
    product_id,
    product_name,
    category,
    avg_price,
    effective_date,
    COALESCE(expiry_date, DATE '9999-12-31') AS expiry_date,
    expiry_date IS NULL AS is_current
FROM with_end;
