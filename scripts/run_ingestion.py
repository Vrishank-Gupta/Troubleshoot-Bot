"""Ingest SOP documents from a specified folder (or data/sops/ by default).

Usage:
    python scripts/run_ingestion.py                          # uses data/sops/
    python scripts/run_ingestion.py C:/path/to/my/docs      # custom folder
    python scripts/run_ingestion.py --publish C:/path/docs  # auto-publish after ingestion
    python scripts/run_ingestion.py --recursive             # include subfolders
    python scripts/run_ingestion.py --force                 # re-process even if already ingested
    python scripts/run_ingestion.py --failed-only           # retry only previously failed files

Supported formats: PDF, DOCX, DOC

Skip logic (saves LLM cost on reruns):
  - Already in DB by filename      → skipped entirely (no LLM call)
  - Parsed JSON exists on disk     → re-imports from JSON (no LLM call)
  - Neither                        → full ingest with LLM parse
  Use --force to bypass both checks.
"""
import argparse
import asyncio
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
os.chdir(Path(__file__).parent.parent / "backend")
sys.stdout.reconfigure(encoding="utf-8")

from app.database import Base, engine, SessionLocal
import app.models.db_models  # noqa: ensure all tables registered
from app.ingestion.pipeline import ingest_file, check_already_ingested, PARSED_SOPS_DIR

SUPPORTED = {".pdf", ".docx", ".doc"}
DEFAULT_DIR = Path(__file__).parent.parent / "data" / "sops"
FAILED_LOG  = Path(__file__).parent.parent / "data" / "ingestion_failures.log"


def collect_files(folder: Path, recursive: bool) -> list[Path]:
    if recursive:
        return sorted(f for f in folder.rglob("*") if f.suffix.lower() in SUPPORTED)
    return sorted(f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in SUPPORTED)


def load_failed_log() -> set[str]:
    """Return filenames that failed in a previous run."""
    if not FAILED_LOG.exists():
        return set()
    return {
        line.split("|")[0].strip()
        for line in FAILED_LOG.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }


def _has_cached_json(file_path: Path) -> bool:
    from app.ingestion.pipeline import _cached_json_path
    return _cached_json_path(file_path) is not None


async def run(folder: Path, auto_publish: bool, recursive: bool, force: bool, failed_only: bool):
    if not folder.exists() or not folder.is_dir():
        print(f"Folder not found: {folder}")
        sys.exit(1)

    all_files = collect_files(folder, recursive)
    if not all_files:
        print(f"No PDF/DOCX/DOC files found in {folder}")
        return

    # Ensure DB schema is current
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    # Filter to only previously failed files if requested
    if failed_only:
        previously_failed = load_failed_log()
        files = [f for f in all_files if f.name in previously_failed]
        print(f"--failed-only: {len(files)} of {len(all_files)} files previously failed")
    else:
        files = all_files

    if not files:
        print("Nothing to process.")
        db.close()
        return

    print(f"Folder  : {folder}")
    print(f"Files   : {len(files)}")
    print(f"Publish : {'yes (auto)' if auto_publish else 'no — review drafts then publish via admin'}")
    print(f"Force   : {'yes (re-process all)' if force else 'no — will skip already-ingested files'}")
    print()

    passed = skipped_db = skipped_cache = failed = 0
    failure_lines: list[str] = []

    try:
        for f in files:
            rel = str(f.relative_to(folder)) if f.is_relative_to(folder) else f.name

            # ── Pre-flight skip checks (shown before calling ingest_file) ────
            if not force:
                existing = check_already_ingested(f, db)
                if existing:
                    print(f"  SKIP (already in DB)  {rel}")
                    skipped_db += 1
                    continue

                if _has_cached_json(f):
                    print(f"  CACHED (reuse JSON)   {rel}  [no LLM call]")
                else:
                    print(f"  INGEST (LLM parse)    {rel}")
            else:
                print(f"  FORCE REINGEST        {rel}")

            try:
                result = await ingest_file(f, db, auto_publish=auto_publish, force=force)

                if result.get("skipped"):
                    # Should not happen given pre-flight above, but handle gracefully
                    print(f"    -> skipped ({result.get('skip_reason')})")
                    skipped_db += 1
                    continue

                scope_tag  = f"  scope={result.get('scope','model')}"
                status_tag = "PUBLISHED" if result["status"] == "published" else "DRAFT"
                llm_tag    = "" if result.get("llm_used", True) else "  [no LLM — used cache]"
                print(f"    [{status_tag}]{llm_tag}  {result['title']}{scope_tag}")

                issues   = result["review_report"].get("issues", [])
                warnings = result["review_report"].get("warnings", [])
                if issues:
                    print(f"    ISSUES   : {', '.join(issues)}")
                if warnings:
                    print(f"    WARNINGS : {', '.join(warnings)}")
                print(f"    JSON     : {result['parsed_file']}")
                passed += 1

            except Exception as exc:
                short = str(exc)
                full  = traceback.format_exc()
                print(f"    FAILED   : {short}")
                print(f"    REASON   : {_classify_error(exc)}")
                failure_lines.append(f"{f.name} | {short[:200]}")
                failed += 1

            print()
    finally:
        db.close()

    # ── Write failure log ────────────────────────────────────────────────────
    if failure_lines:
        FAILED_LOG.parent.mkdir(parents=True, exist_ok=True)
        with FAILED_LOG.open("w", encoding="utf-8") as fh:
            fh.write(f"# Ingestion failures — {datetime.now().isoformat()}\n")
            for line in failure_lines:
                fh.write(line + "\n")
        print(f"Failure log written to: {FAILED_LOG}")

    # ── Summary ──────────────────────────────────────────────────────────────
    print(f"Results: {passed} ingested, {skipped_db} skipped (already in DB), "
          f"{failed} failed.")
    if not auto_publish and passed:
        print("Review parsed SOPs in data/parsed_sops/, then publish:")
        print("  PATCH /admin/sops/{id}/scope   (set scope + status to published)")
    if failed:
        print(f"\nTo retry only the failed files:")
        print(f"  python scripts/run_ingestion.py --failed-only \"{folder}\"")


def _classify_error(exc: Exception) -> str:
    """Give a plain-English reason for common failures."""
    msg = str(exc).lower()
    if "no text" in msg or "no text extracted" in msg:
        return (
            "Empty text — likely a scanned/image PDF with no selectable text. "
            "Run OCR (e.g. Adobe Acrobat, tesseract) to make it machine-readable first."
        )
    if "llm failed" in msg or "parse_failed" in msg:
        return (
            "LLM could not produce valid JSON — document may be too short, badly formatted, "
            "or in a language the model struggled with. Check data/parsed_sops/ for the raw output."
        )
    if "timeout" in msg or "timed out" in msg:
        return "OpenAI API timed out — document may be too large. Try splitting it."
    if "rate limit" in msg or "429" in msg:
        return "OpenAI rate limit hit — wait a minute then re-run with --failed-only."
    if "authentication" in msg or "401" in msg or "api key" in msg:
        return "Invalid OpenAI API key — check OPENAI_API_KEY in backend/.env."
    if "unsupported file" in msg:
        return "File format not supported — only PDF, DOCX, and DOC are accepted."
    if "unicodedecodeerror" in msg or "encoding" in msg:
        return "File encoding error — document may be corrupted."
    return "Unexpected error — run with --verbose for full traceback."


def main():
    parser = argparse.ArgumentParser(
        description="Ingest SOP documents into the chatbot database.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "folder", nargs="?", default=None,
        help=f"Folder containing SOP files (default: data/sops/)",
    )
    parser.add_argument("--publish",    action="store_true", help="Auto-publish after ingestion")
    parser.add_argument("--recursive",  action="store_true", help="Scan subfolders recursively")
    parser.add_argument("--force",      action="store_true", help="Re-process files already in DB")
    parser.add_argument("--failed-only",action="store_true", help="Retry only files that failed last run",
                        dest="failed_only")
    args = parser.parse_args()

    folder = Path(args.folder).expanduser().resolve() if args.folder else DEFAULT_DIR
    asyncio.run(run(
        folder,
        auto_publish=args.publish,
        recursive=args.recursive,
        force=args.force,
        failed_only=args.failed_only,
    ))


if __name__ == "__main__":
    main()
