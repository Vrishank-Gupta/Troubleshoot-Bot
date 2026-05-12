"""SOP management endpoints — ingest, list, view, publish."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.ingestion.pipeline import ingest_file
from app.models.db_models import Product, SopFlow
from app.models.schemas import SopListItem, SearchRequest, SearchResponse
from app.services.search_service import search_sops

router = APIRouter(prefix="/sops", tags=["sops"])

UPLOAD_DIR = Path(__file__).parent.parent.parent.parent / "data" / "sops"
PARSED_DIR = Path(__file__).parent.parent.parent.parent / "data" / "parsed_sops"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@router.get("/", response_model=list[SopListItem])
def list_sops(
    status: Optional[str] = None,
    product_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(SopFlow)
    if status:
        q = q.filter(SopFlow.status == status)
    if product_id:
        q = q.filter(SopFlow.product_id == product_id)
    flows = q.order_by(SopFlow.created_at.desc()).all()
    result = []
    for f in flows:
        result.append(SopListItem(
            id=f.id,
            sop_slug=f.sop_slug,
            title=f.title,
            status=f.status,
            product=f.product.name if f.product else None,
            issue=f.issue.name if f.issue else None,
            version=f.version,
            created_at=f.created_at,
            updated_at=f.updated_at,
        ))
    return result


@router.get("/{sop_id}")
def get_sop(sop_id: str, db: Session = Depends(get_db)):
    flow = db.query(SopFlow).filter(
        (SopFlow.id == sop_id) | (SopFlow.sop_slug == sop_id)
    ).first()
    if not flow:
        raise HTTPException(status_code=404, detail="SOP not found")
    return {
        "id": flow.id,
        "slug": flow.sop_slug,
        "title": flow.title,
        "status": flow.status,
        "version": flow.version,
        "product": flow.product.name if flow.product else None,
        "issue": flow.issue.name if flow.issue else None,
        "flow_json": flow.flow_json,
        "source_file": flow.source_file,
        "created_at": flow.created_at,
        "updated_at": flow.updated_at,
    }


@router.get("/{sop_id}/parsed")
def get_parsed_json(sop_id: str, db: Session = Depends(get_db)):
    """Return the raw parsed JSON file from disk."""
    flow = db.query(SopFlow).filter(
        (SopFlow.id == sop_id) | (SopFlow.sop_slug == sop_id)
    ).first()
    if not flow:
        raise HTTPException(status_code=404, detail="SOP not found")
    parsed_file = PARSED_DIR / f"{flow.sop_slug}.json"
    if not parsed_file.exists():
        return {"message": "Parsed file not on disk", "flow_json": flow.flow_json}
    return json.loads(parsed_file.read_text(encoding="utf-8"))


@router.post("/upload")
async def upload_sop(
    file: UploadFile = File(...),
    auto_publish: bool = False,
    db: Session = Depends(get_db),
):
    """Upload a PDF/DOCX/DOC file and trigger ingestion."""
    suffix = Path(file.filename).suffix.lower()
    if suffix not in (".pdf", ".docx", ".doc"):
        raise HTTPException(status_code=400, detail="Only PDF, DOCX, DOC files are supported.")

    dest = UPLOAD_DIR / file.filename
    content = await file.read()
    dest.write_bytes(content)

    try:
        result = await ingest_file(dest, db, auto_publish=auto_publish)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return result


@router.post("/{sop_id}/publish")
def publish_sop(sop_id: str, db: Session = Depends(get_db)):
    flow = db.query(SopFlow).filter(
        (SopFlow.id == sop_id) | (SopFlow.sop_slug == sop_id)
    ).first()
    if not flow:
        raise HTTPException(status_code=404, detail="SOP not found")
    flow.status = "published"
    # Update flow_json status too
    fj = dict(flow.flow_json)
    fj["status"] = "published"
    flow.flow_json = fj
    db.commit()
    return {"message": "SOP published", "id": flow.id, "slug": flow.sop_slug}


@router.post("/{sop_id}/unpublish")
def unpublish_sop(sop_id: str, db: Session = Depends(get_db)):
    flow = db.query(SopFlow).filter(
        (SopFlow.id == sop_id) | (SopFlow.sop_slug == sop_id)
    ).first()
    if not flow:
        raise HTTPException(status_code=404, detail="SOP not found")
    flow.status = "reviewed"
    fj = dict(flow.flow_json)
    fj["status"] = "reviewed"
    flow.flow_json = fj
    db.commit()
    return {"message": "SOP unpublished", "id": flow.id}


@router.delete("/{sop_id}")
def delete_sop(sop_id: str, db: Session = Depends(get_db)):
    flow = db.query(SopFlow).filter(
        (SopFlow.id == sop_id) | (SopFlow.sop_slug == sop_id)
    ).first()
    if not flow:
        raise HTTPException(status_code=404, detail="SOP not found")
    db.delete(flow)
    db.commit()
    return {"message": "SOP deleted"}


@router.post("/search", response_model=SearchResponse)
async def search(request: SearchRequest, db: Session = Depends(get_db)):
    """Test hybrid search — useful for admin/debug."""
    return await search_sops(
        db,
        product_text=request.product_text,
        issue_text=request.issue_text,
        customer_message=request.customer_message,
        product_id=request.product_id,
    )
