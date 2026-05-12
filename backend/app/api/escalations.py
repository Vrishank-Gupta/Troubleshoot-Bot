from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.db_models import Escalation
from app.models.schemas import EscalationRead

router = APIRouter(prefix="/escalations", tags=["escalations"])


@router.get("/", response_model=list[EscalationRead])
def list_escalations(
    status: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    q = db.query(Escalation)
    if status:
        q = q.filter(Escalation.status == status)
    return q.order_by(Escalation.created_at.desc()).limit(limit).all()


@router.get("/{escalation_id}")
def get_escalation(escalation_id: str, db: Session = Depends(get_db)):
    esc = db.query(Escalation).filter(Escalation.id == escalation_id).first()
    if not esc:
        raise HTTPException(status_code=404, detail="Escalation not found")
    return {
        "id": esc.id,
        "conversation_id": esc.conversation_id,
        "customer_id": esc.customer_id,
        "product_name": esc.product_name,
        "issue_name": esc.issue_name,
        "sop_title": esc.sop_title,
        "last_completed_step": esc.last_completed_step,
        "failed_step": esc.failed_step,
        "summary": esc.summary,
        "recommended_action": esc.recommended_action,
        "full_transcript": esc.full_transcript,
        "status": esc.status,
        "created_at": esc.created_at,
    }


@router.patch("/{escalation_id}/status")
def update_status(escalation_id: str, status: str, db: Session = Depends(get_db)):
    valid = {"open", "assigned", "resolved", "closed"}
    if status not in valid:
        raise HTTPException(status_code=400, detail=f"status must be one of {valid}")
    esc = db.query(Escalation).filter(Escalation.id == escalation_id).first()
    if not esc:
        raise HTTPException(status_code=404, detail="Escalation not found")
    esc.status = status
    db.commit()
    return {"message": "Status updated", "status": status}
