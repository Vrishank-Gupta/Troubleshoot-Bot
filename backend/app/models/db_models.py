"""SQLAlchemy ORM models.

Uses plain SQLAlchemy types that work on both PostgreSQL (production)
and SQLite (testing). JSONB/ARRAY are mapped to Text on SQLite and
handled transparently via TypeDecorator helpers.
"""
import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Column, Text, Integer, Numeric, ForeignKey, DateTime, func, TypeDecorator, String, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base


def _uuid():
    return str(uuid.uuid4())


# ── Portable JSON column ────────────────────────────────────────────────────

class _JsonType(TypeDecorator):
    """JSONB on Postgres, Text-backed JSON on SQLite."""
    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import JSONB
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value, dialect):
        if dialect.name == "postgresql":
            return value
        return json.dumps(value, ensure_ascii=False) if value is not None else None

    def process_result_value(self, value, dialect):
        if dialect.name == "postgresql":
            return value
        if value is None:
            return None
        if isinstance(value, str):
            return json.loads(value)
        return value


class _ArrayType(TypeDecorator):
    """TEXT[] on Postgres, JSON array on SQLite."""
    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import ARRAY
            return dialect.type_descriptor(ARRAY(Text()))
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value, dialect):
        if dialect.name == "postgresql":
            return value
        return json.dumps(value or [], ensure_ascii=False)

    def process_result_value(self, value, dialect):
        if dialect.name == "postgresql":
            return value or []
        if not value:
            return []
        if isinstance(value, list):
            return value
        return json.loads(value)


class _VectorType(TypeDecorator):
    """pgvector on Postgres, TEXT on SQLite."""
    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            try:
                from pgvector.sqlalchemy import Vector
                return dialect.type_descriptor(Vector(1536))
            except Exception:
                pass
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value, dialect):
        if dialect.name == "postgresql":
            return value
        if value is None:
            return None
        return json.dumps(value)

    def process_result_value(self, value, dialect):
        if dialect.name == "postgresql":
            return value
        if not value:
            return None
        if isinstance(value, list):
            return value
        return json.loads(value)


# ── Product hierarchy ────────────────────────────────────────────────────────

class ProductCategory(Base):
    """Top-level product grouping, e.g. 'Smart Security Cameras', 'Dashcam'."""
    __tablename__ = "product_categories"

    id          = Column(Text, primary_key=True, default=_uuid)
    name        = Column(Text, nullable=False, unique=True)
    description = Column(Text, default="")
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    families  = relationship("ProductFamily", back_populates="category", cascade="all, delete-orphan")
    sop_flows = relationship("SopFlow", back_populates="category_obj",
                             foreign_keys="SopFlow.category_id")


class ProductFamily(Base):
    """Mid-level grouping, e.g. 'Indoor Cameras', 'Connected Dashcams'."""
    __tablename__ = "product_families"

    id          = Column(Text, primary_key=True, default=_uuid)
    category_id = Column(Text, ForeignKey("product_categories.id", ondelete="CASCADE"))
    name        = Column(Text, nullable=False)
    description = Column(Text, default="")
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("category_id", "name"),)

    category  = relationship("ProductCategory", back_populates="families")
    products  = relationship("Product", back_populates="family")
    sop_flows = relationship("SopFlow", back_populates="family_obj",
                             foreign_keys="SopFlow.family_id")


# ── ORM Models ──────────────────────────────────────────────────────────────

class Product(Base):
    __tablename__ = "products"

    id           = Column(Text, primary_key=True, default=_uuid)
    name         = Column(Text, nullable=False)
    category     = Column(Text)                      # legacy text field, keep for compat
    category_id  = Column(Text, ForeignKey("product_categories.id", ondelete="SET NULL"), nullable=True)
    family_id    = Column(Text, ForeignKey("product_families.id", ondelete="SET NULL"), nullable=True)
    model_number = Column(Text)
    aliases      = Column(_ArrayType, default=list)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())

    category_obj = relationship("ProductCategory")
    family       = relationship("ProductFamily", back_populates="products")
    issues       = relationship("Issue", back_populates="product", cascade="all, delete-orphan")
    sop_flows    = relationship("SopFlow", back_populates="product",
                                foreign_keys="SopFlow.product_id")


class Issue(Base):
    __tablename__ = "issues"

    id               = Column(Text, primary_key=True, default=_uuid)
    product_id       = Column(Text, ForeignKey("products.id", ondelete="CASCADE"))
    name             = Column(Text, nullable=False)
    category         = Column(Text)
    symptom_phrases  = Column(_ArrayType, default=list)
    negative_phrases = Column(_ArrayType, default=list)
    created_at       = Column(DateTime(timezone=True), server_default=func.now())

    product   = relationship("Product", back_populates="issues")
    sop_flows = relationship("SopFlow", back_populates="issue")


class SopFlow(Base):
    __tablename__ = "sop_flows"

    id          = Column(Text, primary_key=True, default=_uuid)
    product_id  = Column(Text, ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    issue_id    = Column(Text, ForeignKey("issues.id", ondelete="SET NULL"), nullable=True)
    # Hierarchy scope
    scope       = Column(Text, default="model")       # generic | category | family | model
    category_id = Column(Text, ForeignKey("product_categories.id", ondelete="SET NULL"), nullable=True)
    family_id   = Column(Text, ForeignKey("product_families.id", ondelete="SET NULL"), nullable=True)
    sop_slug    = Column(Text, unique=True, nullable=False)
    title       = Column(Text, nullable=False)
    version     = Column(Integer, default=1)
    status      = Column(Text, default="draft")
    flow_json   = Column(_JsonType, nullable=False)
    source_file = Column(Text)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    product      = relationship("Product", back_populates="sop_flows",
                                foreign_keys=[product_id])
    issue        = relationship("Issue", back_populates="sop_flows")
    category_obj = relationship("ProductCategory", back_populates="sop_flows",
                                foreign_keys=[category_id])
    family_obj   = relationship("ProductFamily", back_populates="sop_flows",
                                foreign_keys=[family_id])
    chunks       = relationship("SopChunk", back_populates="sop_flow", cascade="all, delete-orphan")
    overrides    = relationship("SopOverride", back_populates="base_sop", cascade="all, delete-orphan")


class SopOverride(Base):
    """Model-specific step overrides — avoids duplicating entire SOPs."""
    __tablename__ = "sop_overrides"

    id            = Column(Text, primary_key=True, default=_uuid)
    base_sop_id   = Column(Text, ForeignKey("sop_flows.id", ondelete="CASCADE"), nullable=False)
    product_id    = Column(Text, ForeignKey("products.id", ondelete="CASCADE"), nullable=True)
    step_id       = Column(Text, nullable=False)
    override_json = Column(_JsonType, nullable=False, default=dict)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())

    base_sop = relationship("SopFlow", back_populates="overrides")
    product  = relationship("Product")


class SopChunk(Base):
    __tablename__ = "sop_chunks"

    id          = Column(Text, primary_key=True, default=_uuid)
    sop_flow_id = Column(Text, ForeignKey("sop_flows.id", ondelete="CASCADE"))
    product_id  = Column(Text, ForeignKey("products.id", ondelete="CASCADE"), nullable=True)
    issue_id    = Column(Text, ForeignKey("issues.id", ondelete="CASCADE"), nullable=True)
    chunk_text  = Column(Text, nullable=False)
    chunk_type  = Column(Text)
    embedding   = Column(_VectorType)
    keywords    = Column(_ArrayType, default=list)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    sop_flow = relationship("SopFlow", back_populates="chunks")


class Conversation(Base):
    __tablename__ = "conversations"

    id              = Column(Text, primary_key=True, default=_uuid)
    customer_id     = Column(Text, nullable=False)
    channel         = Column(Text, default="web")
    product_id      = Column(Text, ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    issue_id        = Column(Text, ForeignKey("issues.id", ondelete="SET NULL"), nullable=True)
    sop_flow_id     = Column(Text, ForeignKey("sop_flows.id", ondelete="SET NULL"), nullable=True)
    current_step_id = Column(Text)
    status          = Column(Text, default="NEW")
    state_json      = Column(_JsonType, default=dict)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    updated_at      = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    events = relationship("ConversationEvent", back_populates="conversation", cascade="all, delete-orphan")


class ConversationEvent(Base):
    __tablename__ = "conversation_events"

    id               = Column(Text, primary_key=True, default=_uuid)
    conversation_id  = Column(Text, ForeignKey("conversations.id", ondelete="CASCADE"))
    event_type       = Column(Text, nullable=False)
    user_message     = Column(Text)
    bot_message      = Column(Text)
    detected_product = Column(Text)
    detected_issue   = Column(Text)
    confidence_score = Column(Numeric(5, 4))
    current_step_id  = Column(Text)
    extra_data       = Column(_JsonType, default=dict)
    created_at       = Column(DateTime(timezone=True), server_default=func.now())

    conversation = relationship("Conversation", back_populates="events")


class Escalation(Base):
    __tablename__ = "escalations"

    id                  = Column(Text, primary_key=True, default=_uuid)
    conversation_id     = Column(Text, ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True)
    customer_id         = Column(Text, nullable=False)
    product_name        = Column(Text)
    issue_name          = Column(Text)
    sop_title           = Column(Text)
    last_completed_step = Column(Text)
    failed_step         = Column(Text)
    summary             = Column(Text)
    full_transcript     = Column(_JsonType, default=list)
    recommended_action  = Column(Text)
    status              = Column(Text, default="open")
    created_at          = Column(DateTime(timezone=True), server_default=func.now())
    updated_at          = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AnalyticsEvent(Base):
    __tablename__ = "analytics_events"

    id              = Column(Text, primary_key=True, default=_uuid)
    conversation_id = Column(Text, nullable=True)
    event_name      = Column(Text, nullable=False)
    product_name    = Column(Text)
    issue_name      = Column(Text)
    sop_slug        = Column(Text)
    step_id         = Column(Text)
    confidence      = Column(Numeric(5, 4))
    extra_data      = Column(_JsonType, default=dict)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
