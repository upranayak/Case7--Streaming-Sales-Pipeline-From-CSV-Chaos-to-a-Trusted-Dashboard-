"""
transform.py — Run SQL models against DuckDB warehouse
"""
import duckdb
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "warehouse.duckdb"
MODELS_FILE = Path(__file__).parent.parent / "models" / "transforms.sql"


def run():
    con = duckdb.connect(str(DB_PATH))
    sql = MODELS_FILE.read_text()

    # Split on double-newline between statements
    statements = [s.strip() for s in sql.split(";\n\n") if s.strip()]
    for stmt in statements:
        if stmt.startswith("--"):
            header = stmt.split("\n")[0]
            print(f"\nRunning: {header}")
            stmt = "\n".join(stmt.split("\n")[1:])
        try:
            con.execute(stmt)
            print("  ✓ OK")
        except Exception as e:
            print(f"  ✗ ERROR: {e}")

    con.close()
    print("\nTransforms complete.")


if __name__ == "__main__":
    run()
