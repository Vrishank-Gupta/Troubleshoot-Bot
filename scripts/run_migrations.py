"""Apply SQL migrations to the database."""
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
os.chdir(Path(__file__).parent.parent / "backend")

from app.config import get_settings
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


def run():
    settings = get_settings()
    dsn = settings.pg_dsn
    # Swap to psycopg2 DSN format if needed
    dsn = dsn.replace("postgresql://", "postgres://")

    print(f"Connecting to database...")
    conn = psycopg2.connect(dsn)
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()

    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    print(f"Found {len(migration_files)} migration file(s).\n")

    for mf in migration_files:
        print(f"─── Running: {mf.name}")
        sql = mf.read_text(encoding="utf-8")
        try:
            cur.execute(sql)
            print(f"    ✅ Done")
        except Exception as e:
            print(f"    ❌ Error: {e}")

    cur.close()
    conn.close()
    print("\n✅ Migrations complete.")


if __name__ == "__main__":
    run()
