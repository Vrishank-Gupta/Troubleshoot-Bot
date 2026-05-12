"""Step-by-step SOP flow execution engine.

Rules:
- Ask only one step at a time.
- Always wait for customer confirmation.
- Never skip, invent, or reorder steps.
- Only follow transitions defined in the SOP JSON.
"""
from __future__ import annotations

import logging
from typing import Optional

from app.models.schemas import (
    BotMessage, InterpretResult, SopFlowSchema, StepSchema, TerminalStateSchema,
)

logger = logging.getLogger(__name__)

TERMINAL_STEP_TYPES = {"terminal", "escalation"}
LABEL_TO_FIELD: dict[str, str] = {
    "done":   "on_done",
    "yes":    "on_yes",
    "no":     "on_no",
    "not_sure": "on_not_sure",
    "failed": "on_failed",
    "other":  "on_other",
    # specials handled explicitly
    "help_needed": None,
    "wants_human": None,
    "unrelated":   None,
}


class FlowEngine:
    def __init__(self, flow: SopFlowSchema):
        self.flow = flow
        self._steps: dict[str, StepSchema] = {s.id: s for s in flow.steps}
        self._terminals: dict[str, TerminalStateSchema] = {t.id: t for t in flow.terminal_states}

    # ── Accessors ──────────────────────────────────────────────────────────

    def get_first_step_id(self) -> Optional[str]:
        return self.flow.steps[0].id if self.flow.steps else None

    def get_step(self, step_id: str) -> Optional[StepSchema | TerminalStateSchema]:
        return self._steps.get(step_id) or self._terminals.get(step_id)

    def is_terminal(self, step_id: str) -> bool:
        return step_id in self._terminals

    def is_escalation(self, step_id: str) -> bool:
        t = self._terminals.get(step_id)
        return t is not None and t.type == "escalation"

    def is_resolved(self, step_id: str) -> bool:
        t = self._terminals.get(step_id)
        return t is not None and t.type == "resolved"

    # ── Rendering ─────────────────────────────────────────────────────────

    def render_step(self, step_id: str) -> list[BotMessage]:
        node = self.get_step(step_id)
        if node is None:
            logger.error("Step %s not found in flow %s", step_id, self.flow.sop_id)
            return [BotMessage(type="text", text="Something went wrong. Let me connect you with support.")]

        if isinstance(node, TerminalStateSchema):
            return [BotMessage(type="text", text=node.message)]

        # It's a StepSchema
        messages: list[BotMessage] = []

        if node.safety_note:
            messages.append(BotMessage(type="info", text=f"⚠️ Safety note: {node.safety_note}"))

        if node.response_buttons:
            messages.append(BotMessage(
                type="buttons",
                text=node.customer_message,
                buttons=node.response_buttons,
            ))
        else:
            messages.append(BotMessage(type="text", text=node.customer_message))

        return messages

    def render_help(self, step_id: str) -> list[BotMessage]:
        """Explain the current step without advancing."""
        node = self._steps.get(step_id)
        if node is None:
            return [BotMessage(type="text", text="I couldn't find help for this step. Let me connect you with support.")]
        text = node.agent_notes or f"Please follow this step carefully: {node.customer_message}"
        return [BotMessage(type="text", text=text)]

    # ── Transitions ────────────────────────────────────────────────────────

    def get_next_step_id(
        self,
        current_step_id: str,
        interpreted: InterpretResult,
        retry_count: int = 0,
    ) -> tuple[str, bool]:  # (next_step_id, is_help_response)
        """
        Returns (next_step_id, is_help_only).
        is_help_only=True means render help but stay on same step.
        """
        label = interpreted.mapped_response

        if label == "wants_human" or interpreted.should_escalate:
            return "escalated", False

        if label == "help_needed":
            return current_step_id, True  # stay, show help

        if label == "unrelated":
            return current_step_id, False  # re-ask same step

        step = self._steps.get(current_step_id)
        if step is None:
            return "escalated", False

        field = LABEL_TO_FIELD.get(label)
        if field:
            next_id = getattr(step, field, None)
            if next_id:
                return next_id, False

        # fallback chain
        for fallback_field in ("on_done", "on_yes", "on_other"):
            fallback = getattr(step, fallback_field, None)
            if fallback:
                return fallback, False

        # retry if within limit
        if retry_count < step.retry_limit:
            return current_step_id, False

        # exceeded retries → escalate
        return step.on_failed or "escalated", False
