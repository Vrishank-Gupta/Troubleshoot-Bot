"""Hybrid search: keyword + vector similarity over SOP chunks.

SOP selection priority (highest wins):
  1. model-level published SOP
  2. family-level published SOP
  3. category-level published SOP
  4. generic SOP

Falls back gracefully to keyword-only on SQLite (local dev / tests).
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.middleware import latency as lat
from app.models.db_models import Product, ProductCategory, ProductFamily, Issue, SopFlow, SopChunk
from app.models.schemas import SearchResponse, SopCandidate
from app.services.embedding_service import embed_text

logger = logging.getLogger(__name__)

_SCOPE_PRIORITY = {"model": 4, "family": 3, "category": 2, "generic": 1}


def _is_postgres(db: Session) -> bool:
    return db.bind.dialect.name == "postgresql"


# ── Hierarchy resolution ─────────────────────────────────────────────────────

def resolve_hierarchy(
    db: Session,
    product_text: str,
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Return (product_id, family_id, category_id) for the best matching product text."""
    if not product_text:
        return None, None, None
    txt = product_text.lower()

    # 1. Exact / alias product match (model level)
    for p in db.query(Product).all():
        candidates = [p.name.lower()] + [a.lower() for a in (p.aliases or [])]
        if any(c and c in txt or txt in c for c in candidates):
            return p.id, p.family_id, p.category_id

    # 2. Family match
    for f in db.query(ProductFamily).all():
        if f.name.lower() in txt or txt in f.name.lower():
            return None, f.id, f.category_id

    # 3. Category match
    for c in db.query(ProductCategory).all():
        if c.name.lower() in txt or txt in c.name.lower():
            return None, None, c.id

    return None, None, None


# ── Main search entry ────────────────────────────────────────────────────────

async def search_sops(
    db: Session,
    product_text: str = "",
    issue_text: str = "",
    customer_message: str = "",
    product_id: Optional[str] = None,
    category_id: Optional[str] = None,
    family_id: Optional[str] = None,
) -> SearchResponse:
    settings = get_settings()
    combined_query = f"{product_text} {issue_text} {customer_message}".strip()

    with lat.measure(lat.STAGE_RETRIEVE):
        # Resolve hierarchy if not already provided
        if not product_id and not family_id and not category_id and product_text:
            product_id, family_id, category_id = resolve_hierarchy(db, product_text)

        keyword_scores: dict[str, float] = {}
        vector_scores:  dict[str, float] = {}

        # Keyword search
        if combined_query:
            if _is_postgres(db):
                for row in _pg_keyword_search(db, combined_query, product_id, family_id, category_id):
                    sid = str(row["sop_id"])
                    keyword_scores[sid] = keyword_scores.get(sid, 0.0) + float(row["score"])
            else:
                for sid in _sqlite_keyword_search(db, combined_query, product_id, family_id, category_id):
                    keyword_scores[sid] = keyword_scores.get(sid, 0.0) + 1.0

        # Vector search (Postgres only)
        if _is_postgres(db) and combined_query:
            try:
                vec = await embed_text(combined_query)
                for row in _pg_vector_search(db, vec, product_id, settings.search_top_k):
                    sid = str(row["sop_id"])
                    vector_scores[sid] = vector_scores.get(sid, 0.0) + float(row["sim"])
            except Exception as e:
                logger.warning("Vector search failed: %s", e)

        # Combine scores + apply scope priority boost
        all_ids = set(keyword_scores) | set(vector_scores)
        combined: dict[str, float] = {}
        for sid in all_ids:
            kw = keyword_scores.get(sid, 0.0)
            vk = vector_scores.get(sid, 0.0)
            base = kw * 0.4 + vk * 0.6 if vk else kw
            # boost by scope priority so model SOP always beats family/category for same product
            sop = db.query(SopFlow).filter(SopFlow.id == sid).first()
            scope_boost = _SCOPE_PRIORITY.get(sop.scope if sop else "generic", 1) * 0.05
            combined[sid] = base + scope_boost

        sorted_ids = sorted(combined.items(), key=lambda x: x[1], reverse=True)[:settings.search_top_k]

    if not sorted_ids:
        return SearchResponse(
            candidates=[],
            needs_clarification=True,
            clarification_question="Could you please tell me which product you need assistance with?",
        )

    candidates: list[SopCandidate] = []
    for sop_id, score in sorted_ids:
        sop = db.query(SopFlow).filter(SopFlow.id == sop_id, SopFlow.status == "published").first()
        if not sop:
            continue
        product_name = sop.product.name if sop.product else ""
        issue_name   = sop.issue.name   if sop.issue   else ""
        reasons      = _build_reasons(keyword_scores.get(sop_id, 0), vector_scores.get(sop_id, 0))
        candidates.append(SopCandidate(
            sop_flow_id=sop_id,
            product=product_name,
            issue=issue_name,
            title=sop.title,
            score=round(score, 4),
            scope=sop.scope or "model",
            match_reasons=reasons,
        ))

    if not candidates:
        return SearchResponse(
            candidates=[],
            needs_clarification=True,
            clarification_question="I was unable to find a matching guide. Could you describe the problem in a different way?",
        )

    top_score = candidates[0].score
    needs_clarification = (
        len(candidates) > 1
        and top_score > 0
        and (candidates[1].score / top_score) > 0.8
    )

    return SearchResponse(
        candidates=candidates,
        needs_clarification=needs_clarification,
        clarification_question="",
    )


# ── DB helpers ───────────────────────────────────────────────────────────────

def _pg_keyword_search(
    db: Session,
    query: str,
    product_id: Optional[str],
    family_id: Optional[str],
    category_id: Optional[str],
) -> list[dict]:
    sql = text("""
        SELECT sf.id AS sop_id,
               ts_rank(
                   to_tsvector('english',
                       coalesce(sf.title,'') || ' ' ||
                       coalesce(p.name,'') || ' ' ||
                       coalesce(i.name,'')
                   ),
                   plainto_tsquery('english', :query)
               ) AS score
        FROM sop_flows sf
        LEFT JOIN products p ON p.id = sf.product_id
        LEFT JOIN issues   i ON i.id = sf.issue_id
        WHERE sf.status = 'published'
          AND to_tsvector('english',
                  coalesce(sf.title,'') || ' ' || coalesce(p.name,'') || ' ' || coalesce(i.name,'')
              ) @@ plainto_tsquery('english', :query)
          AND (
               (:product_id  IS NULL OR sf.product_id  = :product_id)
            OR (:family_id   IS NULL OR sf.family_id   = :family_id)
            OR (:category_id IS NULL OR sf.category_id = :category_id)
            OR sf.scope = 'generic'
          )
        ORDER BY score DESC
        LIMIT 10
    """)
    rows = db.execute(sql, {
        "query": query, "product_id": product_id,
        "family_id": family_id, "category_id": category_id,
    }).fetchall()
    return [{"sop_id": r[0], "score": r[1]} for r in rows]


def _sqlite_keyword_search(
    db: Session,
    query: str,
    product_id: Optional[str],
    family_id: Optional[str],
    category_id: Optional[str],
) -> list[str]:
    """Simple substring match for SQLite (tests / local dev)."""
    keywords = [w.lower() for w in query.split() if len(w) > 2]
    results = []
    q = db.query(SopFlow).filter(SopFlow.status == "published")
    # Include SOPs matching product OR family OR category OR generic scope
    if product_id or family_id or category_id:
        from sqlalchemy import or_
        filters = [SopFlow.scope == "generic"]
        if product_id:
            filters.append(SopFlow.product_id == product_id)
        if family_id:
            filters.append(SopFlow.family_id == family_id)
        if category_id:
            filters.append(SopFlow.category_id == category_id)
        q = q.filter(or_(*filters))
    for sop in q.all():
        text_blob = (
            f"{sop.title} "
            f"{sop.product.name if sop.product else ''} "
            f"{sop.issue.name if sop.issue else ''}"
        ).lower()
        if any(kw in text_blob for kw in keywords):
            results.append(sop.id)
    return results


def _pg_vector_search(
    db: Session,
    embedding: list[float],
    product_id: Optional[str],
    top_k: int,
) -> list[dict]:
    vec_str = "[" + ",".join(str(v) for v in embedding) + "]"
    sql = text("""
        SELECT sc.sop_flow_id AS sop_id,
               1 - (sc.embedding <=> :vec::vector) AS sim
        FROM sop_chunks sc
        JOIN sop_flows sf ON sf.id = sc.sop_flow_id
        WHERE sf.status = 'published'
          AND (:product_id IS NULL OR sc.product_id = :product_id)
          AND sc.embedding IS NOT NULL
        ORDER BY sc.embedding <=> :vec::vector
        LIMIT :top_k
    """)
    rows = db.execute(sql, {"vec": vec_str, "product_id": product_id, "top_k": top_k}).fetchall()
    return [{"sop_id": r[0], "sim": r[1]} for r in rows]


def _build_reasons(kw_score: float, vec_score: float) -> list[str]:
    reasons = []
    if kw_score > 0.0:
        reasons.append("keyword_match")
    if vec_score > 0.7:
        reasons.append("semantic_match")
    elif vec_score > 0.4:
        reasons.append("partial_semantic_match")
    return reasons or ["low_confidence"]
