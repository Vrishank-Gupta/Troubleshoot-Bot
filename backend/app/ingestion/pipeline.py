"""Full SOP ingestion pipeline: file → extract → parse → validate → store → embed."""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.ingestion.docx_extractor import extract_doc, extract_docx
from app.ingestion.pdf_extractor import extract_pdf
from app.ingestion.sop_validator import validate_and_report
from app.models.db_models import Issue, Product, SopChunk, SopFlow
from app.models.schemas import SopFlowSchema
from app.services.embedding_service import embed_batch
from app.services.llm_service import parse_sop_to_flow

logger = logging.getLogger(__name__)

PARSED_SOPS_DIR = Path(__file__).parent.parent.parent.parent / "data" / "parsed_sops"
PARSED_SOPS_DIR.mkdir(parents=True, exist_ok=True)


# ── Extraction ──────────────────────────────────────────────────────────────

def extract_text(file_path: str | Path) -> str:
    p = Path(file_path)
    suffix = p.suffix.lower()
    if suffix == ".pdf":
        return extract_pdf(p)
    if suffix == ".docx":
        return extract_docx(p)
    if suffix == ".doc":
        return extract_doc(p)
    raise ValueError(f"Unsupported file type: {suffix}")


# ── Slug generation ─────────────────────────────────────────────────────────

def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:80]


# ── Main pipeline ───────────────────────────────────────────────────────────

async def ingest_file(
    file_path: str | Path,
    db: Session,
    auto_publish: bool = False,
) -> dict[str, Any]:
    file_path = Path(file_path)
    logger.info("Ingesting %s", file_path.name)

    # 1. Extract text
    raw_text = extract_text(file_path)
    if not raw_text.strip():
        raise ValueError(f"No text extracted from {file_path.name}")

    # 2. Parse with LLM
    flow_dict = await parse_sop_to_flow(
        raw_text=raw_text,
        source_file=file_path.name,
        metadata_hint=f"filename={file_path.name}",
    )

    if "error" in flow_dict:
        raise RuntimeError(f"LLM parsing failed: {flow_dict.get('raw','')[:300]}")

    # Ensure required fields
    if not flow_dict.get("sop_id"):
        flow_dict["sop_id"] = _slugify(flow_dict.get("title", file_path.stem))
    flow_dict["source_file"] = file_path.name
    flow_dict["created_at"] = datetime.now(timezone.utc).isoformat()
    if auto_publish:
        flow_dict["status"] = "published"

    # 3. Validate
    sop = SopFlowSchema(**flow_dict)
    review = validate_and_report(sop)

    # 4. Save parsed JSON to disk
    out_path = PARSED_SOPS_DIR / f"{sop.sop_id}.json"
    out_path.write_text(json.dumps(flow_dict, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Saved parsed SOP to %s", out_path)

    # 5. Upsert to database
    sop_id = await _upsert_to_db(sop, db)

    # 6. Generate and store embeddings
    await _store_embeddings(sop, sop_id, db)

    return {
        "sop_id": sop.sop_id,
        "db_id": sop_id,
        "title": sop.title,
        "status": sop.status,
        "review_report": review,
        "parsed_file": str(out_path),
    }


async def _upsert_to_db(sop: SopFlowSchema, db: Session) -> str:
    """Upsert product, issue, and sop_flow. Returns sop_flow DB id."""
    # Product
    product = db.query(Product).filter(
        Product.name.ilike(sop.product.name)
    ).first()
    if not product and sop.product.name:
        product = Product(
            name=sop.product.name,
            category=sop.product.category or "",
            aliases=sop.product.model_aliases or [],
        )
        db.add(product)
        db.flush()

    # Issue
    issue = None
    if product and sop.issue.name:
        issue = db.query(Issue).filter(
            Issue.product_id == product.id,
            Issue.name.ilike(sop.issue.name),
        ).first()
        if not issue:
            issue = Issue(
                product_id=product.id,
                name=sop.issue.name,
                category=sop.issue.category or "",
                symptom_phrases=sop.issue.symptom_phrases or [],
                negative_phrases=sop.issue.negative_phrases or [],
            )
            db.add(issue)
            db.flush()

    # SopFlow
    existing = db.query(SopFlow).filter(SopFlow.sop_slug == sop.sop_id).first()
    if existing:
        existing.flow_json = sop.model_dump()
        existing.title = sop.title
        existing.status = sop.status
        existing.version = existing.version + 1
        existing.source_file = sop.source_file
        if product:
            existing.product_id = product.id
        if issue:
            existing.issue_id = issue.id
        db.flush()
        # Remove old chunks
        db.query(SopChunk).filter(SopChunk.sop_flow_id == existing.id).delete()
        db.flush()
        db.commit()
        return existing.id
    else:
        flow_db = SopFlow(
            product_id=product.id if product else None,
            issue_id=issue.id if issue else None,
            sop_slug=sop.sop_id,
            title=sop.title,
            version=1,
            status=sop.status,
            flow_json=sop.model_dump(),
            source_file=sop.source_file,
        )
        db.add(flow_db)
        db.flush()
        db.commit()
        db.refresh(flow_db)
        return flow_db.id


async def _store_embeddings(sop: SopFlowSchema, sop_flow_db_id: str, db: Session) -> None:
    """Create SopChunk records with embeddings for search."""
    settings = get_settings()

    # Fetch DB references
    sop_flow_db = db.query(SopFlow).filter(SopFlow.id == sop_flow_db_id).first()
    if not sop_flow_db:
        return

    chunks_data: list[tuple[str, str]] = []  # (text, type)

    # Title + product + issue chunk
    title_text = f"{sop.title} {sop.product.name} {sop.issue.name}"
    chunks_data.append((title_text, "title"))

    # Symptom phrases
    if sop.issue.symptom_phrases:
        symptom_text = " ".join(sop.issue.symptom_phrases)
        chunks_data.append((symptom_text, "symptom"))

    # Each step's customer message
    for step in sop.steps:
        if step.customer_message:
            chunks_data.append((step.customer_message, "step"))

    # Prerequisites
    if sop.prerequisites:
        prereq_text = " ".join(sop.prerequisites)
        chunks_data.append((prereq_text, "prerequisite"))

    if not chunks_data:
        return

    texts = [c[0] for c in chunks_data]
    try:
        embeddings = await embed_batch(texts)
    except Exception as e:
        logger.error("Embedding generation failed: %s", e)
        embeddings = [[0.0] * settings.embedding_dimensions] * len(texts)

    for (chunk_text, chunk_type), embedding in zip(chunks_data, embeddings):
        chunk = SopChunk(
            sop_flow_id=sop_flow_db_id,
            product_id=sop_flow_db.product_id,
            issue_id=sop_flow_db.issue_id,
            chunk_text=chunk_text,
            chunk_type=chunk_type,
            embedding=embedding,
            keywords=_extract_keywords(chunk_text),
        )
        db.add(chunk)

    db.commit()
    logger.info("Stored %d chunks for SOP %s", len(chunks_data), sop.sop_id)


def _extract_keywords(text: str) -> list[str]:
    words = re.findall(r"\b[a-zA-Z]{4,}\b", text.lower())
    stopwords = {"this", "that", "with", "have", "from", "your", "will", "when",
                 "then", "them", "they", "what", "which", "step", "please"}
    return list({w for w in words if w not in stopwords})[:20]
