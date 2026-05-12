"""Analytics event recording and summary aggregation."""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.models.db_models import AnalyticsEvent, Conversation

logger = logging.getLogger(__name__)


def record(
    db: Session,
    event_name: str,
    conversation_id: Optional[str] = None,
    product_name: Optional[str] = None,
    issue_name: Optional[str] = None,
    sop_slug: Optional[str] = None,
    step_id: Optional[str] = None,
    confidence: Optional[float] = None,
    metadata: Optional[dict] = None,
) -> None:
    try:
        ev = AnalyticsEvent(
            event_name=event_name,
            conversation_id=conversation_id,
            product_name=product_name,
            issue_name=issue_name,
            sop_slug=sop_slug,
            step_id=step_id,
            confidence=confidence,
            extra_data=metadata or {},
        )
        db.add(ev)
        db.commit()
    except Exception as e:
        logger.warning("Analytics record failed (non-fatal): %s", e)
        db.rollback()


def get_summary(db: Session) -> dict:
    total = db.query(Conversation).count()
    resolved = db.query(Conversation).filter(Conversation.status == "RESOLVED").count()
    escalated = db.query(Conversation).filter(Conversation.status == "ESCALATED").count()
    abandoned = db.query(Conversation).filter(Conversation.status == "ABANDONED").count()

    # Use portable SQL (SQLite + Postgres compatible)
    is_pg = db.bind.dialect.name == "postgresql"

    if is_pg:
        top_products = db.execute(text("""
            SELECT product_name, count(*) AS cnt
            FROM analytics_events
            WHERE event_name = 'product_selected' AND product_name IS NOT NULL
            GROUP BY product_name ORDER BY cnt DESC LIMIT 10
        """)).fetchall()
        top_issues = db.execute(text("""
            SELECT issue_name, count(*) AS cnt
            FROM analytics_events
            WHERE event_name = 'issue_detected' AND issue_name IS NOT NULL
            GROUP BY issue_name ORDER BY cnt DESC LIMIT 10
        """)).fetchall()
        sop_resolution = db.execute(text("""
            SELECT sop_slug,
                   count(*) FILTER (WHERE event_name = 'conversation_resolved') AS resolved,
                   count(*) FILTER (WHERE event_name = 'sop_selected') AS started
            FROM analytics_events
            WHERE sop_slug IS NOT NULL AND event_name IN ('conversation_resolved','sop_selected')
            GROUP BY sop_slug ORDER BY started DESC LIMIT 20
        """)).fetchall()
        step_dropoff = db.execute(text("""
            SELECT step_id, count(*) AS cnt
            FROM analytics_events
            WHERE event_name = 'step_failed' AND step_id IS NOT NULL
            GROUP BY step_id ORDER BY cnt DESC LIMIT 10
        """)).fetchall()
    else:
        # SQLite compatible
        top_products = db.execute(text("""
            SELECT product_name, count(*) AS cnt
            FROM analytics_events
            WHERE event_name = 'product_selected' AND product_name IS NOT NULL
            GROUP BY product_name ORDER BY cnt DESC LIMIT 10
        """)).fetchall()
        top_issues = db.execute(text("""
            SELECT issue_name, count(*) AS cnt
            FROM analytics_events
            WHERE event_name = 'issue_detected' AND issue_name IS NOT NULL
            GROUP BY issue_name ORDER BY cnt DESC LIMIT 10
        """)).fetchall()
        sop_resolution = []
        step_dropoff = db.execute(text("""
            SELECT step_id, count(*) AS cnt
            FROM analytics_events
            WHERE event_name = 'step_failed' AND step_id IS NOT NULL
            GROUP BY step_id ORDER BY cnt DESC LIMIT 10
        """)).fetchall()

    return {
        "total_conversations": total,
        "resolved_count": resolved,
        "escalated_count": escalated,
        "abandoned_count": abandoned,
        "top_products": [{"product": r[0], "count": r[1]} for r in top_products],
        "top_issues": [{"issue": r[0], "count": r[1]} for r in top_issues],
        "sop_resolution_rate": [
            {"sop": r[0], "resolved": r[1], "started": r[2],
             "rate": round(r[1] / r[2], 2) if r[2] else 0}
            for r in sop_resolution
        ],
        "step_dropoff": [{"step": r[0], "count": r[1]} for r in step_dropoff],
    }
