"""Admin endpoints — conversations, products, hierarchy, debug."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.db_models import (
    Conversation, ConversationEvent, Product, Issue,
    ProductCategory, ProductFamily, SopFlow,
)

router = APIRouter(prefix="/admin", tags=["admin"])


# ── Conversations ────────────────────────────────────────────────────────────

@router.get("/conversations")
def list_conversations(
    status: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    q = db.query(Conversation)
    if status:
        q = q.filter(Conversation.status == status)
    convs = q.order_by(Conversation.created_at.desc()).limit(limit).all()
    return [
        {
            "id": c.id,
            "customer_id": c.customer_id,
            "status": c.status,
            "current_step_id": c.current_step_id,
            "sop_flow_id": c.sop_flow_id,
            "created_at": c.created_at,
            "updated_at": c.updated_at,
        }
        for c in convs
    ]


@router.get("/conversations/{conversation_id}/events")
def get_conversation_events(conversation_id: str, db: Session = Depends(get_db)):
    events = (
        db.query(ConversationEvent)
        .filter(ConversationEvent.conversation_id == conversation_id)
        .order_by(ConversationEvent.created_at)
        .all()
    )
    return [
        {
            "id": e.id,
            "event_type": e.event_type,
            "user_message": e.user_message,
            "bot_message": e.bot_message,
            "current_step_id": e.current_step_id,
            "confidence_score": e.confidence_score,
            "extra_data": e.extra_data,
            "created_at": e.created_at,
        }
        for e in events
    ]


# ── Product hierarchy ────────────────────────────────────────────────────────

@router.get("/hierarchy")
def get_hierarchy(db: Session = Depends(get_db)):
    """Full category → family → product tree."""
    categories = db.query(ProductCategory).all()
    result = []
    for cat in categories:
        families_data = []
        for fam in cat.families:
            products_data = [
                {"id": p.id, "name": p.name, "model_number": p.model_number, "aliases": p.aliases or []}
                for p in fam.products
            ]
            families_data.append({
                "id": fam.id, "name": fam.name,
                "description": fam.description, "products": products_data,
            })
        result.append({
            "id": cat.id, "name": cat.name,
            "description": cat.description, "families": families_data,
        })
    return result


@router.post("/categories")
def create_category(name: str, description: str = "", db: Session = Depends(get_db)):
    existing = db.query(ProductCategory).filter(ProductCategory.name == name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Category already exists")
    cat = ProductCategory(name=name, description=description)
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return {"id": cat.id, "name": cat.name}


@router.post("/families")
def create_family(
    name: str,
    category_id: str,
    description: str = "",
    db: Session = Depends(get_db),
):
    cat = db.query(ProductCategory).filter(ProductCategory.id == category_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    fam = ProductFamily(name=name, category_id=category_id, description=description)
    db.add(fam)
    db.commit()
    db.refresh(fam)
    return {"id": fam.id, "name": fam.name, "category_id": category_id}


@router.get("/products")
def list_products(
    category_id: Optional[str] = None,
    family_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(Product)
    if category_id:
        q = q.filter(Product.category_id == category_id)
    if family_id:
        q = q.filter(Product.family_id == family_id)
    return [
        {
            "id": p.id, "name": p.name, "category": p.category,
            "category_id": p.category_id, "family_id": p.family_id,
            "model_number": p.model_number, "aliases": p.aliases,
        }
        for p in q.all()
    ]


@router.post("/products")
def create_product(
    name: str,
    category: str = "",
    category_id: Optional[str] = None,
    family_id: Optional[str] = None,
    model_number: Optional[str] = None,
    aliases: str = "",
    db: Session = Depends(get_db),
):
    alias_list = [a.strip() for a in aliases.split(",") if a.strip()] if aliases else []
    product = Product(
        name=name, category=category,
        category_id=category_id, family_id=family_id,
        model_number=model_number, aliases=alias_list,
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return {"id": product.id, "name": product.name}


@router.get("/issues")
def list_issues(product_id: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(Issue)
    if product_id:
        q = q.filter(Issue.product_id == product_id)
    return [
        {
            "id": i.id, "product_id": i.product_id,
            "name": i.name, "category": i.category,
            "symptom_phrases": i.symptom_phrases,
        }
        for i in q.all()
    ]


# ── SOP scope management ─────────────────────────────────────────────────────

@router.get("/sops")
def list_sops(
    scope: Optional[str] = None,
    status: Optional[str] = None,
    category_id: Optional[str] = None,
    family_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(SopFlow)
    if scope:
        q = q.filter(SopFlow.scope == scope)
    if status:
        q = q.filter(SopFlow.status == status)
    if category_id:
        q = q.filter(SopFlow.category_id == category_id)
    if family_id:
        q = q.filter(SopFlow.family_id == family_id)
    sops = q.order_by(SopFlow.created_at.desc()).limit(100).all()
    return [
        {
            "id": s.id, "sop_slug": s.sop_slug, "title": s.title,
            "status": s.status, "scope": s.scope, "version": s.version,
            "product_id": s.product_id, "category_id": s.category_id,
            "family_id": s.family_id, "created_at": s.created_at,
        }
        for s in sops
    ]


@router.patch("/sops/{sop_id}/scope")
def update_sop_scope(
    sop_id: str,
    scope: str,
    category_id: Optional[str] = None,
    family_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    valid_scopes = {"generic", "category", "family", "model"}
    if scope not in valid_scopes:
        raise HTTPException(status_code=422, detail=f"scope must be one of {valid_scopes}")
    sop = db.query(SopFlow).filter(SopFlow.id == sop_id).first()
    if not sop:
        raise HTTPException(status_code=404, detail="SOP not found")
    sop.scope = scope
    if category_id is not None:
        sop.category_id = category_id
    if family_id is not None:
        sop.family_id = family_id
    db.commit()
    return {"id": sop_id, "scope": scope}


@router.get("/sops/{sop_id}/inherited")
def get_inherited_sops(sop_id: str, db: Session = Depends(get_db)):
    """Show which more-specific SOPs override this SOP for particular models."""
    sop = db.query(SopFlow).filter(SopFlow.id == sop_id).first()
    if not sop:
        raise HTTPException(status_code=404, detail="SOP not found")

    overrides = []
    if sop.scope in ("generic", "category"):
        # Find family/model SOPs with same issue
        narrower = db.query(SopFlow).filter(
            SopFlow.issue_id == sop.issue_id,
            SopFlow.scope.in_(["family", "model"]),
            SopFlow.status == "published",
        ).all()
        overrides = [{"id": s.id, "title": s.title, "scope": s.scope} for s in narrower]

    return {"base": {"id": sop.id, "title": sop.title, "scope": sop.scope}, "overridden_by": overrides}


# ── Debug / latency ──────────────────────────────────────────────────────────

@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/debug/latency")
def debug_latency():
    """p50/p95/p99 latency per stage across all requests since startup."""
    from app.middleware.latency import get_stats
    return get_stats()
