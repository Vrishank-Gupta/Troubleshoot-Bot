"""Load seed SOP JSON files directly into the database (no LLM needed)."""
import json
import sys
import os
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
os.chdir(Path(__file__).parent.parent / "backend")

# Set stdout to UTF-8 so print works on Windows
sys.stdout.reconfigure(encoding="utf-8")

from app.config import get_settings
from app.database import SessionLocal, Base, engine
from app.models.db_models import Product, Issue, SopFlow, SopChunk
import app.models.db_models  # noqa: ensure all models registered before create_all
from app.models.schemas import SopFlowSchema
from app.ingestion.pipeline import _upsert_to_db

SEEDS_DIR = Path(__file__).parent.parent / "data" / "seeds"


def load_seed(db, file_path: Path):
    print(f"\nLoading seed: {file_path.name}")
    data = json.loads(file_path.read_text(encoding="utf-8"))
    sop = SopFlowSchema(**data)

    existing = db.query(SopFlow).filter(SopFlow.sop_slug == sop.sop_id).first()
    if existing:
        print(f"  Already exists (id={existing.id}), skipping.")
        return

    import asyncio

    async def do_upsert():
        return await _upsert_to_db(sop, db)

    sop_id = asyncio.run(do_upsert())
    print(f"  Created SOP: {sop.title} (db_id={sop_id})")
    return sop_id


def main():
    # Ensure schema is up to date before seeding
    print("Ensuring database schema is current...")
    Base.metadata.create_all(bind=engine)
    print("Schema ready.")

    db = SessionLocal()
    try:
        seed_files = list(SEEDS_DIR.glob("*.json"))
        if not seed_files:
            print("No seed files found in data/seeds/")
            return
        print(f"Found {len(seed_files)} seed file(s).")
        for f in sorted(seed_files):
            load_seed(db, f)
        print("\nSeed data loaded successfully.")
    except Exception as e:
        print(f"\nError: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
