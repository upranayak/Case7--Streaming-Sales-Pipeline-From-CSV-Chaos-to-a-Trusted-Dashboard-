"""
ingest.py — Idempotent CSV ingestion into DuckDB
Handles: duplicates, late arrivals, schema drift, null spikes
"""
import os, glob, hashlib, logging
from pathlib import Path
from datetime import datetime
import pandas as pd
import duckdb

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data" / "case7_daily_sales"
DB_PATH  = BASE_DIR / "warehouse.duckdb"

EXPECTED_COLS = {
    "order_id", "order_timestamp", "customer_id",
    "product_id", "product_name", "category",
    "qty", "unit_price", "discount_pct", "region"
}

DQ_RESULTS = []


def log_dq(check, status, detail, file=None):
    DQ_RESULTS.append({"check": check, "status": status, "detail": detail, "file": str(file or "")})
    level = logging.WARNING if status == "FAIL" else logging.INFO
    log.log(level, f"[DQ:{status}] {check} | {detail}")


def file_hash(path):
    return hashlib.md5(Path(path).read_bytes()).hexdigest()


def collect_csv_files():
    """Collect all CSVs including late_arrivals subfolder."""
    files = glob.glob(str(DATA_DIR / "*.csv"))
    files += glob.glob(str(DATA_DIR / "late_arrivals" / "*.csv"))
    return sorted(files)


def check_missing_dates(files):
    """DQ Check 1: Freshness / missing date files."""
    found_dates = set()
    for f in files:
        name = Path(f).stem  # sales_2025-03-01
        try:
            date_str = name.split("_", 1)[1]
            found_dates.add(date_str)
        except Exception:
            pass

    all_march = {f"2025-03-{d:02d}" for d in range(1, 32)
                 if datetime(2025, 3, d).month == 3}
    missing = sorted(all_march - found_dates)
    if missing:
        log_dq("Freshness/Missing Files", "FAIL", f"Missing dates: {missing}")
    else:
        log_dq("Freshness/Missing Files", "PASS", "All 30 March files present")
    return missing


def load_and_validate(filepath, con):
    """Load one CSV, run per-file DQ checks, return cleaned DataFrame."""
    fname = Path(filepath).name
    try:
        df = pd.read_csv(filepath)
    except Exception as e:
        log_dq("Parse", "FAIL", str(e), fname)
        return None

    # DQ Check 2: Schema drift
    actual_cols = set(df.columns.str.strip())
    extra   = actual_cols - EXPECTED_COLS
    missing = EXPECTED_COLS - actual_cols
    if extra or missing:
        log_dq("Schema Drift", "FAIL",
               f"Extra={extra or '{}'} Missing={missing or '{}'}", fname)
        # Attempt recovery: rename if close match
        df.columns = [c.strip() for c in df.columns]
    else:
        log_dq("Schema Drift", "PASS", "Schema OK", fname)

    # DQ Check 3: Null spike (>5% nulls in critical columns)
    critical = ["order_id", "unit_price", "qty"]
    for col in critical:
        if col in df.columns:
            null_pct = df[col].isna().mean()
            if null_pct > 0.05:
                log_dq("Null Spike", "FAIL",
                       f"{col} has {null_pct:.1%} nulls", fname)
            elif null_pct > 0:
                log_dq("Null Spike", "WARN",
                       f"{col} has {null_pct:.1%} nulls", fname)

    # DQ Check 4: Duplicate order_ids within file
    if "order_id" in df.columns:
        dup_count = df.duplicated(subset=["order_id"]).sum()
        if dup_count:
            log_dq("Duplicates (intra-file)", "FAIL",
                   f"{dup_count} duplicate order_ids", fname)
            df = df.drop_duplicates(subset=["order_id"], keep="first")
        else:
            log_dq("Duplicates (intra-file)", "PASS", "No intra-file dups", fname)

    # Row count sanity
    if len(df) < 100:
        log_dq("Row Count", "WARN", f"Only {len(df)} rows — suspiciously low", fname)
    elif len(df) > 15000:
        log_dq("Row Count", "WARN", f"{len(df)} rows — suspiciously high", fname)

    # Add source metadata
    df["_source_file"] = fname
    df["_file_hash"]   = file_hash(filepath)
    df["_loaded_at"]   = datetime.utcnow().isoformat()

    return df


def init_db(con):
    con.execute("""
    CREATE TABLE IF NOT EXISTS raw_sales (
        order_id        VARCHAR,
        order_timestamp VARCHAR,
        customer_id     VARCHAR,
        product_id      VARCHAR,
        product_name    VARCHAR,
        category        VARCHAR,
        qty             INTEGER,
        unit_price      DOUBLE,
        discount_pct    DOUBLE,
        region          VARCHAR,
        _source_file    VARCHAR,
        _file_hash      VARCHAR,
        _loaded_at      VARCHAR
    )
    """)
    con.execute("""
    CREATE TABLE IF NOT EXISTS dq_log (
        run_ts   VARCHAR,
        check    VARCHAR,
        status   VARCHAR,
        detail   VARCHAR,
        file     VARCHAR
    )
    """)
    con.execute("""
    CREATE TABLE IF NOT EXISTS loaded_files (
        filename  VARCHAR PRIMARY KEY,
        file_hash VARCHAR,
        loaded_at VARCHAR
    )
    """)


def already_loaded(con, fname, fhash):
    """Idempotency: skip if same file+hash already loaded."""
    row = con.execute(
        "SELECT file_hash FROM loaded_files WHERE filename=?", [fname]
    ).fetchone()
    return row is not None and row[0] == fhash


def upsert_file_registry(con, fname, fhash):
    con.execute("""
        INSERT INTO loaded_files VALUES (?, ?, ?)
        ON CONFLICT(filename) DO UPDATE SET file_hash=excluded.file_hash, loaded_at=excluded.loaded_at
    """, [fname, fhash, datetime.utcnow().isoformat()])


def cross_file_dedup(con):
    """DQ Check: remove cross-file duplicate order_ids, keep earliest."""
    before = con.execute("SELECT COUNT(*) FROM raw_sales").fetchone()[0]
    con.execute("""
    DELETE FROM raw_sales
    WHERE rowid NOT IN (
        SELECT MIN(rowid) FROM raw_sales GROUP BY order_id
    )
    """)
    after = con.execute("SELECT COUNT(*) FROM raw_sales").fetchone()[0]
    removed = before - after
    if removed:
        log_dq("Duplicates (cross-file)", "FAIL",
               f"Removed {removed} cross-file duplicate order_ids")
    else:
        log_dq("Duplicates (cross-file)", "PASS", "No cross-file duplicates")


def save_dq_log(con, run_ts):
    rows = [(run_ts, r["check"], r["status"], r["detail"], r["file"])
            for r in DQ_RESULTS]
    con.executemany("INSERT INTO dq_log VALUES (?,?,?,?,?)", rows)


def run():
    con = duckdb.connect(str(DB_PATH))
    init_db(con)

    files = collect_csv_files()
    log.info(f"Found {len(files)} CSV files")

    check_missing_dates(files)

    loaded = 0
    for f in files:
        fname = Path(f).name
        fhash = file_hash(f)
        if already_loaded(con, fname, fhash):
            log.info(f"SKIP (already loaded): {fname}")
            continue

        df = load_and_validate(f, con)
        if df is not None and len(df) > 0:
            con.execute("INSERT INTO raw_sales SELECT * FROM df")
            upsert_file_registry(con, fname, fhash)
            loaded += 1
            log.info(f"Loaded {fname} — {len(df)} rows")

    cross_file_dedup(con)

    run_ts = datetime.utcnow().isoformat()
    save_dq_log(con, run_ts)

    log.info(f"Done. Loaded {loaded} new files. Total rows: "
             f"{con.execute('SELECT COUNT(*) FROM raw_sales').fetchone()[0]}")
    con.close()


if __name__ == "__main__":
    run()
