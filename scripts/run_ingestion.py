"""Ingest all SOP files from data/sops/ folder."""
import asyncio
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
os.chdir(Path(__file__).parent.parent / "backend")

from app.database import SessionLocal
from app.ingestion.pipeline import ingest_file

SOPS_DIR = Path(__file__).parent.parent / "data" / "sops"
SUPPORTED = {".pdf", ".docx", ".doc"}


async def main():
    files = [f for f in SOPS_DIR.iterdir() if f.suffix.lower() in SUPPORTED]
    if not files:
        print(f"No PDF/DOCX/DOC files found in {SOPS_DIR}")
        return

    print(f"Found {len(files)} SOP file(s) to ingest.\n")
    db = SessionLocal()
    try:
        for f in files:
            print(f"─── Ingesting: {f.name}")
            try:
                result = await ingest_file(f, db, auto_publish=False)
                print(f"    ✅ {result['title']}")
                print(f"    Status: {result['status']}")
                issues = result["review_report"].get("issues", [])
                warnings = result["review_report"].get("warnings", [])
                if issues:
                    print(f"    ❌ Issues: {issues}")
                if warnings:
                    print(f"    ⚠️  Warnings: {warnings}")
                print(f"    Parsed JSON: {result['parsed_file']}")
            except Exception as e:
                print(f"    ❌ Failed: {e}")
            print()
    finally:
        db.close()

    print("✅ Ingestion complete. Review parsed SOPs in data/parsed_sops/ then publish via admin UI.")


if __name__ == "__main__":
    asyncio.run(main())
