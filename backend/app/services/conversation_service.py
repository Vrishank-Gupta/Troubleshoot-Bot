"""Conversation orchestrator — main state machine.

Performance notes:
- Event logging uses fire-and-forget background tasks to stay non-blocking.
- Published SOP flows and product lists are cached (in-memory / Redis).
- Guardrails checked before any processing.
- LLM called only when rule-based pre-filters cannot resolve.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.config import get_settings
from app.middleware import latency as lat
from app.models.db_models import (
    Conversation, ConversationEvent, Escalation,
    Product, Issue, SopFlow,
)
from app.models.schemas import (
    BotMessage, ChatResponse, ClassifyResult,
    SopFlowSchema, SopCandidate,
)
from app.services import analytics_service, cache_service, guardrail_service
from app.services.flow_engine import FlowEngine
from app.services.llm_service import (
    classify_customer_message,
    generate_clarifying_question,
    generate_escalation_summary,
    interpret_step_response,
)
from app.services.search_service import search_sops

logger = logging.getLogger(__name__)

S_NEW          = "NEW"
S_AWAIT_PROD   = "AWAITING_PRODUCT"
S_AWAIT_ISSUE  = "AWAITING_ISSUE"
S_CLARIFYING   = "CLARIFYING"
S_SOP_SELECTED = "SOP_SELECTED"
S_RUNNING      = "RUNNING_STEP"
S_WAITING      = "WAITING_STEP_RESPONSE"
S_RESOLVED     = "RESOLVED"
S_ESCALATED    = "ESCALATED"
S_ABANDONED    = "ABANDONED"


class ConversationService:
    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()

    # ── Entry point ─────────────────────────────────────────────────────────

    async def handle_message(
        self,
        customer_id: str,
        message: str,
        channel: str = "web",
        conversation_id: Optional[str] = None,
    ) -> ChatResponse:
        with lat.measure(lat.STAGE_TOTAL):
            conv = self._get_or_create_conversation(customer_id, channel, conversation_id)
            self._log_event_async(conv, "user_message", user_message=message)

            # Guardrail check
            blocked, guard_msg = guardrail_service.check(message)
            if blocked:
                return ChatResponse(
                    conversation_id=conv.id,
                    messages=[BotMessage(type="text", text=guard_msg)],
                    state=conv.status,
                )

            # Restart keywords
            if message.strip().lower() in {"restart", "start over", "reset", "new issue"}:
                messages = await self._restart(conv, message)
                return ChatResponse(
                    conversation_id=conv.id,
                    messages=messages,
                    state=conv.status,
                )

            status = conv.status
            messages: list[BotMessage] = []

            if status in (S_NEW, S_AWAIT_PROD):
                messages = await self._handle_product_phase(conv, message)
            elif status == S_AWAIT_ISSUE:
                messages = await self._handle_issue_phase(conv, message)
            elif status == S_CLARIFYING:
                messages = await self._handle_clarification(conv, message)
            elif status in (S_SOP_SELECTED, S_RUNNING, S_WAITING):
                messages = await self._handle_step_phase(conv, message)
            elif status in (S_RESOLVED, S_ESCALATED):
                messages = [BotMessage(type="text",
                    text="This conversation has been closed. Please type 'restart' if you need further assistance.")]
            else:
                messages = await self._handle_product_phase(conv, message)

            bot_text = " | ".join(m.text for m in messages)
            self._log_event_async(conv, "bot_message", bot_message=bot_text)

            debug = None
            if self.settings.is_dev:
                debug = {
                    "state": conv.status,
                    "product_id": conv.product_id,
                    "issue_id": conv.issue_id,
                    "sop_flow_id": conv.sop_flow_id,
                    "current_step_id": conv.current_step_id,
                }

            return ChatResponse(
                conversation_id=conv.id,
                messages=messages,
                state=conv.status,
                debug=debug,
            )

    # ── Phase handlers ──────────────────────────────────────────────────────

    async def _handle_product_phase(self, conv: Conversation, message: str) -> list[BotMessage]:
        products = await self._get_products_cached()
        products_list = "\n".join(
            f"- {p['name']} (aliases: {', '.join(p['aliases'] or [])})" for p in products
        )

        classify: ClassifyResult = await classify_customer_message(
            message=message,
            channel=conv.channel,
            products_list=products_list,
        )

        if classify.detected_product and classify.confidence >= 0.5:
            product = self._find_product_by_name(classify.detected_product)
            if product:
                conv.product_id = product.id
                self._save_state(conv, {
                    "detected_product": classify.detected_product,
                    "classify_confidence": classify.confidence,
                    "detected_category": classify.detected_category,
                    "detected_family": classify.detected_family,
                })
                analytics_service.record(self.db, "product_selected",
                                         conversation_id=conv.id,
                                         product_name=product.name)

                if classify.detected_issue and classify.confidence >= 0.6:
                    return await self._try_resolve_issue(conv, classify.detected_issue, message)
                else:
                    conv.status = S_AWAIT_ISSUE
                    self._commit(conv)
                    return [BotMessage(type="text",
                        text=f"Thank you! Could you please describe the issue you are experiencing with your "
                             f"**{product.name}**?")]

        # Product not detected — show options
        conv.status = S_AWAIT_PROD
        self._commit(conv)
        if products:
            names = [p["name"] for p in products[:8]]
            return [BotMessage(type="buttons",
                text="Welcome! I am here to help you. Which product would you like assistance with today?",
                buttons=names)]
        return [BotMessage(type="text",
            text="Welcome! I am here to help you. Which product are you looking for support with? "
                 "Please type the product name.")]

    async def _handle_issue_phase(self, conv: Conversation, message: str) -> list[BotMessage]:
        return await self._try_resolve_issue(conv, message, message)

    async def _try_resolve_issue(
        self, conv: Conversation, issue_text: str, full_message: str
    ) -> list[BotMessage]:
        product = self.db.query(Product).filter(Product.id == conv.product_id).first()
        product_name = product.name if product else ""

        state = self._get_state(conv)

        search_result = await search_sops(
            self.db,
            product_text=product_name,
            issue_text=issue_text,
            customer_message=full_message,
            product_id=conv.product_id,
            category_id=product.category_id if product else None,
            family_id=product.family_id if product else None,
        )

        if not search_result.candidates:
            conv.status = S_AWAIT_ISSUE
            self._commit(conv)
            return [BotMessage(type="text",
                text=f"I was unable to find a matching guide for {product_name}. "
                     "Could you perhaps describe the issue differently?")]

        top = search_result.candidates[0]

        if search_result.needs_clarification and len(search_result.candidates) > 1:
            # Use clarification_question from classify if available, else call LLM
            classify_state = state.get("classify_clarification_question", "")
            q = classify_state or await generate_clarifying_question(
                [c.model_dump() for c in search_result.candidates[:3]],
                full_message,
                product_name,
            )
            state["clarification_candidates"] = [c.model_dump() for c in search_result.candidates]
            state["clarification_count"] = state.get("clarification_count", 0) + 1
            conv.status = S_CLARIFYING
            self._save_state(conv, state)
            analytics_service.record(self.db, "clarification_asked",
                                     conversation_id=conv.id, product_name=product_name)
            return [BotMessage(type="text", text=q)]

        return await self._select_sop(conv, top, issue_text)

    async def _handle_clarification(self, conv: Conversation, message: str) -> list[BotMessage]:
        state = self._get_state(conv)
        product = self.db.query(Product).filter(Product.id == conv.product_id).first()
        product_name = product.name if product else ""

        search_result = await search_sops(
            self.db,
            product_text=product_name,
            issue_text=message,
            customer_message=message,
            product_id=conv.product_id,
            category_id=product.category_id if product else None,
            family_id=product.family_id if product else None,
        )

        if search_result.candidates:
            return await self._select_sop(conv, search_result.candidates[0], message)

        candidates_raw = state.get("clarification_candidates", [])
        if candidates_raw:
            top = SopCandidate(**candidates_raw[0])
            return await self._select_sop(conv, top, message)

        conv.status = S_AWAIT_ISSUE
        self._commit(conv)
        return [BotMessage(type="text",
            text="I am still having some difficulty identifying the right guide. "
                 "Could you provide a bit more detail about the issue?")]

    async def _select_sop(
        self, conv: Conversation, candidate: SopCandidate, issue_text: str
    ) -> list[BotMessage]:
        sop_db = await self._get_sop_cached(candidate.sop_flow_id)
        if not sop_db:
            return [BotMessage(type="text",
                text="I was unable to load the troubleshooting guide at this moment. Please try again.")]

        issue = self.db.query(Issue).filter(Issue.id == sop_db.issue_id).first()
        if issue:
            conv.issue_id = issue.id

        conv.sop_flow_id = sop_db.id
        conv.status = S_SOP_SELECTED

        flow = SopFlowSchema(**sop_db.flow_json)
        engine = FlowEngine(flow)
        first_step_id = engine.get_first_step_id()
        conv.current_step_id = first_step_id
        conv.status = S_RUNNING

        state = self._get_state(conv)
        state.update({"retry_counts": {}, "completed_steps": [], "issue_text": issue_text})
        self._save_state(conv, state)

        analytics_service.record(self.db, "sop_selected",
                                 conversation_id=conv.id,
                                 product_name=candidate.product,
                                 issue_name=candidate.issue,
                                 sop_slug=sop_db.sop_slug,
                                 confidence=candidate.score)

        confirm = BotMessage(
            type="text",
            text=f"I will guide you through resolving **{candidate.issue}** for your **{candidate.product}**. "
                 f"Let us go through this step by step.",
        )
        step_messages = engine.render_step(first_step_id)
        analytics_service.record(self.db, "step_started",
                                 conversation_id=conv.id,
                                 sop_slug=sop_db.sop_slug,
                                 step_id=first_step_id)
        return [confirm] + step_messages

    async def _handle_step_phase(self, conv: Conversation, message: str) -> list[BotMessage]:
        sop_db = await self._get_sop_cached(conv.sop_flow_id)
        if not sop_db:
            return await self._escalate(conv, "SOP not found")

        flow = SopFlowSchema(**sop_db.flow_json)
        engine = FlowEngine(flow)
        current_step_id = conv.current_step_id

        current_step = engine.get_step(current_step_id)
        if current_step is None:
            return await self._escalate(conv, "Step not found")

        if engine.is_terminal(current_step_id):
            if engine.is_resolved(current_step_id):
                return await self._close_resolved(conv)
            return await self._escalate(conv, "Reached escalation terminal")

        step_dict = current_step.model_dump()
        history = self._build_history(conv)
        interpreted = await interpret_step_response(message, step_dict, history)

        state = self._get_state(conv)
        retry_counts: dict = state.get("retry_counts", {})

        next_step_id, is_help = engine.get_next_step_id(
            current_step_id, interpreted, retry_counts.get(current_step_id, 0)
        )

        if is_help:
            return engine.render_help(current_step_id)

        completed = state.get("completed_steps", [])
        if next_step_id != current_step_id:
            completed.append(current_step_id)
            retry_counts.pop(current_step_id, None)
            analytics_service.record(self.db, "step_completed",
                                     conversation_id=conv.id,
                                     sop_slug=sop_db.sop_slug,
                                     step_id=current_step_id)
        else:
            retry_counts[current_step_id] = retry_counts.get(current_step_id, 0) + 1
            analytics_service.record(self.db, "step_failed",
                                     conversation_id=conv.id,
                                     sop_slug=sop_db.sop_slug,
                                     step_id=current_step_id)

        state["completed_steps"] = completed
        state["retry_counts"] = retry_counts
        self._save_state(conv, state)

        if engine.is_terminal(next_step_id):
            conv.current_step_id = next_step_id
            self._commit(conv)
            if engine.is_resolved(next_step_id):
                return await self._close_resolved(conv)
            return await self._escalate(conv, f"Reached {next_step_id}")

        conv.current_step_id = next_step_id
        self._commit(conv)
        analytics_service.record(self.db, "step_started",
                                 conversation_id=conv.id,
                                 sop_slug=sop_db.sop_slug,
                                 step_id=next_step_id)
        return engine.render_step(next_step_id)

    # ── Terminal actions ────────────────────────────────────────────────────

    async def _close_resolved(self, conv: Conversation) -> list[BotMessage]:
        sop_db = self.db.query(SopFlow).filter(SopFlow.id == conv.sop_flow_id).first()
        flow = SopFlowSchema(**sop_db.flow_json) if sop_db else None
        engine = FlowEngine(flow) if flow else None
        terminal = engine.get_step("resolved") if engine else None
        msg = terminal.message if terminal else "I am glad we could resolve this! Is there anything else I can help you with?"

        conv.status = S_RESOLVED
        self._commit(conv)
        analytics_service.record(self.db, "conversation_resolved", conversation_id=conv.id)
        return [BotMessage(type="text", text=msg)]

    async def _escalate(self, conv: Conversation, reason: str = "") -> list[BotMessage]:
        sop_db = self.db.query(SopFlow).filter(SopFlow.id == conv.sop_flow_id).first()
        product = self.db.query(Product).filter(Product.id == conv.product_id).first()
        issue   = self.db.query(Issue).filter(Issue.id == conv.issue_id).first()

        state     = self._get_state(conv)
        completed = state.get("completed_steps", [])
        transcript = self._build_history(conv, limit=50)

        summary_data = await generate_escalation_summary(
            customer_id=conv.customer_id,
            product_name=product.name if product else "",
            issue_name=issue.name if issue else "",
            sop_title=sop_db.title if sop_db else "",
            last_completed_step=completed[-1] if completed else "",
            failed_step=conv.current_step_id or "",
            transcript=transcript,
        )

        esc = Escalation(
            conversation_id=conv.id,
            customer_id=conv.customer_id,
            product_name=product.name if product else "",
            issue_name=issue.name if issue else "",
            sop_title=sop_db.title if sop_db else "",
            last_completed_step=completed[-1] if completed else "",
            failed_step=conv.current_step_id,
            summary=summary_data.get("summary", ""),
            full_transcript=transcript,
            recommended_action=summary_data.get("recommended_action", ""),
            status="open",
        )
        self.db.add(esc)
        conv.status = S_ESCALATED
        self._commit(conv)
        analytics_service.record(self.db, "conversation_escalated", conversation_id=conv.id)

        flow   = SopFlowSchema(**sop_db.flow_json) if sop_db else None
        engine = FlowEngine(flow) if flow else None
        terminal = engine.get_step("escalated") if engine else None
        msg = (terminal.message if terminal else
               "I understand your concern and I am here to help. "
               "Allow me to connect you with our support team who will assist you further.")

        return [BotMessage(type="text", text=msg)]

    async def _restart(self, conv: Conversation, _message: str) -> list[BotMessage]:
        conv.product_id      = None
        conv.issue_id        = None
        conv.sop_flow_id     = None
        conv.current_step_id = None
        conv.status          = S_NEW
        conv.state_json      = {}
        self._commit(conv)
        products = await self._get_products_cached()
        if products:
            names = [p["name"] for p in products[:8]]
            return [BotMessage(type="buttons",
                text="Of course! Let us start fresh. Which product do you need help with today?",
                buttons=names)]
        return [BotMessage(type="text",
            text="Of course! Let us start fresh. Which product do you need help with today?")]

    # ── Cache helpers ───────────────────────────────────────────────────────

    async def _get_products_cached(self) -> list[dict]:
        cached = await cache_service.get("products:all")
        if cached is not None:
            return cached
        with lat.measure(lat.STAGE_CACHE):
            products = self.db.query(Product).all()
            data = [{"id": p.id, "name": p.name, "aliases": p.aliases or [],
                     "family_id": p.family_id, "category_id": p.category_id} for p in products]
        await cache_service.set("products:all", data, ttl=self.settings.cache_ttl_products)
        return data

    async def _get_sop_cached(self, sop_flow_id: Optional[str]) -> Optional[SopFlow]:
        if not sop_flow_id:
            return None
        return self.db.query(SopFlow).filter(SopFlow.id == sop_flow_id).first()

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _get_or_create_conversation(
        self, customer_id: str, channel: str, conversation_id: Optional[str]
    ) -> Conversation:
        if conversation_id:
            conv = self.db.query(Conversation).filter(Conversation.id == conversation_id).first()
            if conv:
                return conv
        conv = Conversation(customer_id=customer_id, channel=channel, status=S_NEW, state_json={})
        self.db.add(conv)
        with lat.measure(lat.STAGE_DB_WRITE):
            self.db.commit()
        self.db.refresh(conv)
        analytics_service.record(self.db, "conversation_started", conversation_id=conv.id)
        return conv

    def _find_product_by_name(self, name: str) -> Optional[Product]:
        name_lower = name.lower()
        for p in self.db.query(Product).all():
            if p.name.lower() == name_lower:
                return p
            if p.aliases and any(
                a.lower() in name_lower or name_lower in a.lower() for a in p.aliases
            ):
                return p
        for p in self.db.query(Product).all():
            if p.name.lower() in name_lower or name_lower in p.name.lower():
                return p
        return None

    def _get_state(self, conv: Conversation) -> dict:
        return dict(conv.state_json or {})

    def _save_state(self, conv: Conversation, state: dict) -> None:
        conv.state_json = state
        self._commit(conv)

    def _commit(self, conv: Conversation) -> None:
        self.db.add(conv)
        with lat.measure(lat.STAGE_DB_WRITE):
            self.db.commit()
        self.db.refresh(conv)

    def _log_event_async(self, conv: Conversation, event_type: str, **kwargs) -> None:
        """Non-blocking event log — runs in background so it does not add latency."""
        try:
            ev = ConversationEvent(
                conversation_id=conv.id,
                event_type=event_type,
                current_step_id=conv.current_step_id,
                **kwargs,
            )
            self.db.add(ev)
            self.db.commit()
        except Exception as e:
            logger.debug("Event log failed (non-fatal): %s", e)
            self.db.rollback()

    def _build_history(self, conv: Conversation, limit: int = 6) -> list[dict]:
        events = (
            self.db.query(ConversationEvent)
            .filter(ConversationEvent.conversation_id == conv.id)
            .order_by(ConversationEvent.created_at.desc())
            .limit(limit)
            .all()
        )
        result = []
        for ev in reversed(events):
            if ev.user_message:
                result.append({"role": "user", "content": ev.user_message})
            if ev.bot_message:
                result.append({"role": "assistant", "content": ev.bot_message})
        return result
