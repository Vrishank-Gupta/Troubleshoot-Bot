"""Ingest SOP documents from a specified folder (or data/sops/ by default).

Usage:
    python scripts/run_ingestion.py                          # uses data/sops/
    python scripts/run_ingestion.py C:/path/to/my/docs      # custom folder
    python scripts/run_ingestion.py --publish C:/path/docs  # auto-publish after ingestion
    python scripts/run_ingestion.py --recursive             # include subfolders

Supported formats: PDF, DOCX, DOC
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
os.chdir(Path(__file__).parent.parent / "backend")
sys.stdout.reconfigure(encoding="utf-8")

from app.database import Base, engine, SessionLocal
import app.models.db_models  # noqa: ensure all tables registered
from app.ingestion.pipeline import ingest_file

SUPPORTED = {".pdf", ".docx", ".doc"}
DEFAULT_DIR = Path(__file__).parent.parent / "data" / "sops"


def collect_files(folder: Path, recursive: bool) -> list[Path]:
    if recursive:
        files = [f for f in folder.rglob("*") if f.suffix.lower() in SUPPORTED]
    else:
        files = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in SUPPORTED]
    return sorted(files)


async def run(folder: Path, auto_publish: bool, recursive: bool):
    if not folder.exists():
        print(f"Folder not found: {folder}")
        sys.exit(1)
    if not folder.is_dir():
        print(f"Path is not a folder: {folder}")
        sys.exit(1)

    files = collect_files(folder, recursive)
    if not files:
        print(f"No PDF/DOCX/DOC files found in {folder}" + (" (recursive)" if recursive else ""))
        return

    print(f"Folder  : {folder}")
    print(f"Files   : {len(files)}")
    print(f"Publish : {'yes' if auto_publish else 'no (draft — review in data/parsed_sops/ then publish via admin)'}")
    print(f"Recurse : {'yes' if recursive else 'no'}")
    print()

    # Ensure DB schema exists
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    passed = failed = 0
    try:
        for f in files:
            rel = f.relative_to(folder) if f.is_relative_to(folder) else f.name
            print(f"--- {rel}")
            try:
                result = await ingest_file(f, db, auto_publish=auto_publish)
                status_tag = "PUBLISHED" if result["status"] == "published" else "DRAFT"
                print(f"    [{status_tag}] {result['title']}")
                issues   = result["review_report"].get("issues", [])
                warnings = result["review_report"].get("warnings", [])
                if issues:
                    print(f"    ISSUES   : {', '.join(issues)}")
                if warnings:
                    print(f"    WARNINGS : {', '.join(warnings)}")
                print(f"    JSON     : {result['parsed_file']}")
                passed += 1
            except Exception as e:
                print(f"    FAILED   : {e}")
                failed += 1
            print()
    finally:
        db.close()

    print(f"Done. {passed} succeeded, {failed} failed.")
    if not auto_publish:
        print("Review parsed SOPs in data/parsed_sops/ then publish via:")
        print("  PATCH /admin/sops/{id}/scope   (set scope + status=published)")


def main():
    parser = argparse.ArgumentParser(
        description="Ingest SOP documents into the chatbot database.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "folder",
        nargs="?",
        default=None,
        help=f"Path to folder containing SOP files (default: {DEFAULT_DIR})",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Auto-publish SOPs after ingestion (default: leave as draft)",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Scan subfolders recursively",
    )
    args = parser.parse_args()

    folder = Path(args.folder).expanduser().resolve() if args.folder else DEFAULT_DIR
    asyncio.run(run(folder, auto_publish=args.publish, recursive=args.recursive))


if __name__ == "__main__":
    main()
