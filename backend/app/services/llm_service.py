"""LLM abstraction — all OpenAI-compatible calls go through here.

Cost rules:
- Rule-based pre-filter handles yes/no/done/not_sure/skip/wants_human without any LLM call.
- Product detection uses keyword match before falling back to LLM.
- Classify + clarification question are combined into a SINGLE LLM call.
- Prompts are minimal — never send full SOP/PDF at runtime.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI, APITimeoutError, APIConnectionError, APIStatusError

from app.config import get_settings
from app.middleware import latency as lat
from app.models.schemas import ClassifyResult, InterpretResult

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent.parent.parent.parent / "prompts"


def _load_prompt(name: str) -> str:
    path = PROMPTS_DIR / f"{name}.txt"
    return path.read_text(encoding="utf-8")


def _get_client() -> AsyncOpenAI:
    s = get_settings()
    return AsyncOpenAI(
        api_key=s.openai_api_key,
        base_url=s.openai_api_base,
        timeout=s.llm_timeout,
        max_retries=s.llm_max_retries,
    )


async def _call_llm(system_prompt: str, user_content: str, model: str | None = None) -> str:
    client = _get_client()
    s = get_settings()
    m = model or s.llm_model
    with lat.measure(lat.STAGE_LLM):
        try:
            resp = await client.chat.completions.create(
                model=m,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            return resp.choices[0].message.content or "{}"
        except (APITimeoutError, APIConnectionError) as e:
            logger.error("LLM connection error: %s", e)
            raise
        except APIStatusError as e:
            logger.error("LLM API error %s: %s", e.status_code, e.message)
            raise


def _safe_parse(raw: str, fallback: dict | None = None) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("LLM returned invalid JSON: %.200s", raw)
        return fallback or {}


# ── Rule-based short-circuits (avoid LLM for obvious responses) ──────────────

_STEP_RULES: dict[str, set[str]] = {
    "done":        {"done", "ok", "okay", "completed", "finished", "worked", "fixed",
                    "it worked", "success", "all done", "its done", "it's done", "alright done",
                    "great it worked", "yes it worked", "yes done"},
    "yes":         {"yes", "yeah", "yep", "yup", "sure", "correct", "right",
                    "absolutely", "affirmative", "it is", "it does", "i see it"},
    "no":          {"no", "nope", "nah", "not working", "didnt work", "didn't work",
                    "does not work", "doesnt work", "no luck", "negative", "still not working"},
    "not_sure":    {"not sure", "unsure", "idk", "i don't know", "i dont know", "maybe",
                    "not certain", "not sure about that", "dunno"},
    "wants_human": {"human", "agent", "person", "real person", "live agent",
                    "talk to someone", "speak to someone", "representative", "operator",
                    "call center", "support person", "i want a human"},
    "skip":        {"skip", "next", "move on", "pass", "skip this"},
}


def _rule_based_interpret(user_message: str) -> InterpretResult | None:
    """Return a result without any LLM call for simple unambiguous responses."""
    normalised = user_message.strip().lower().rstrip("!.,?")
    for label, phrases in _STEP_RULES.items():
        if normalised in phrases:
            return InterpretResult(
                mapped_response=label,
                confidence=1.0,
                extracted_observation="",
                should_escalate=(label == "wants_human"),
                reason="rule_based",
            )
    return None


def _rule_based_classify(message: str, products_list: str) -> dict | None:
    """Detect product by keyword match before calling LLM."""
    if not products_list:
        return None
    msg_lower = message.lower()
    for line in products_list.splitlines():
        if not line.strip().startswith("-"):
            continue
        parts = line.strip().lstrip("- ").split("(aliases:")
        product_name = parts[0].strip()
        aliases = [a.strip().rstrip(")") for a in parts[1].split(",")] if len(parts) > 1 else []
        candidates = [product_name.lower()] + [a.lower() for a in aliases if a]
        if any(c and c in msg_lower for c in candidates):
            return {
                "detected_product": product_name,
                "detected_issue": "",
                "detected_category": "",
                "detected_family": "",
                "symptoms": [],
                "needs_clarification": True,
                "clarification_question": "",
                "confidence": 0.85,
                "reason": "rule_based_product_match",
            }
    return None


# ── Public API ──────────────────────────────────────────────────────────────

async def parse_sop_to_flow(raw_text: str, source_file: str, metadata_hint: str = "") -> dict:
    """Convert raw SOP text → structured flow JSON (ingestion only, not runtime)."""
    from datetime import datetime, timezone
    template = _load_prompt("sop_parser")
    prompt = template.format(
        source_file=source_file,
        metadata_hint=metadata_hint,
        raw_text=raw_text[:12000],
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    raw = await _call_llm(
        "You are an expert SOP parser. Output ONLY valid JSON.",
        prompt,
    )
    return _safe_parse(raw, {"error": "parse_failed", "raw": raw[:500]})


async def classify_customer_message(
    message: str,
    known_product: str = "",
    known_issue: str = "",
    channel: str = "web",
    products_list: str = "",
    issues_list: str = "",
) -> ClassifyResult:
    """Classify customer message → product + issue + clarification in ONE LLM call.

    Fast path: if the message already names a known product verbatim, skip the LLM.
    """
    with lat.measure(lat.STAGE_RETRIEVE):
        # Fast path
        if not known_product:
            rule_match = _rule_based_classify(message, products_list)
            if rule_match:
                try:
                    return ClassifyResult(**rule_match)
                except Exception:
                    pass

    template = _load_prompt("classifier")
    prompt = template.format(
        known_product=known_product or "unknown",
        known_issue=known_issue or "unknown",
        channel=channel,
        customer_message=message,
        products_list=products_list or "not available",
        issues_list=issues_list or "not available",
    )
    raw = await _call_llm(
        "You are a customer support classifier. Output ONLY valid JSON.",
        prompt,
    )
    data = _safe_parse(raw, {"confidence": 0.0, "needs_clarification": True})
    try:
        return ClassifyResult(**data)
    except Exception:
        return ClassifyResult(confidence=0.0, needs_clarification=True, reason="parse_error")


async def interpret_step_response(
    user_message: str,
    step: dict,
    history: list[dict] | None = None,
) -> InterpretResult:
    """Map customer reply to a controlled label.

    Rule-based pre-filter handles simple responses (yes/no/done/not_sure/skip/wants_human)
    with zero LLM cost. Falls through to LLM only for ambiguous free-text.
    """
    rule_result = _rule_based_interpret(user_message)
    if rule_result:
        logger.debug("Rule-based interpret: '%s' → %s", user_message, rule_result.mapped_response)
        return rule_result

    template = _load_prompt("step_interpreter")
    history_text = "\n".join(
        f"{h['role'].upper()}: {h['content']}" for h in (history or [])[-3:]
    )
    prompt = template.format(
        step_json=json.dumps(step, ensure_ascii=False),
        customer_message=user_message,
        history=history_text or "none",
    )
    raw = await _call_llm("You are a step response interpreter. Output ONLY valid JSON.", prompt)
    data = _safe_parse(raw, {"mapped_response": "other", "confidence": 0.0})
    try:
        return InterpretResult(**data)
    except Exception:
        return InterpretResult(mapped_response="other", confidence=0.0, reason="parse_error")


async def generate_clarifying_question(
    candidates: list[dict],
    customer_message: str,
    known_product: str = "",
) -> str:
    """Only called when classify did not return a clarification_question."""
    template = _load_prompt("clarification")
    candidates_text = "\n".join(
        f"- {c.get('title','')} (issue: {c.get('issue','')})" for c in candidates[:4]
    )
    prompt = template.format(
        customer_message=customer_message,
        known_product=known_product or "unknown",
        candidates=candidates_text,
    )
    raw = await _call_llm("You generate clarifying questions. Output ONLY valid JSON.", prompt)
    data = _safe_parse(raw, {"clarification_question": "Could you describe your issue in a bit more detail?"})
    return data.get("clarification_question", "Could you tell me a bit more about the issue you are facing?")


async def generate_escalation_summary(
    customer_id: str,
    product_name: str,
    issue_name: str,
    sop_title: str,
    last_completed_step: str,
    failed_step: str,
    transcript: list[dict],
) -> dict:
    template = _load_prompt("escalation_summary")
    transcript_text = "\n".join(
        f"{t.get('role','?').upper()}: {t.get('content','')}" for t in transcript[-20:]
    )
    prompt = template.format(
        customer_id=customer_id,
        product_name=product_name or "unknown",
        issue_name=issue_name or "unknown",
        sop_title=sop_title or "unknown",
        last_completed_step=last_completed_step or "none",
        failed_step=failed_step or "none",
        transcript=transcript_text,
    )
    raw = await _call_llm("You generate escalation summaries. Output ONLY valid JSON.", prompt)
    return _safe_parse(raw, {
        "summary": "The customer was unable to resolve the issue and has been escalated to the support team.",
        "recommended_action": "Please review the conversation and contact the customer at your earliest convenience.",
        "key_observations": [],
        "urgency": "medium",
    })
