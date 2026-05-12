"""Validate a parsed SOP JSON and produce a human-readable review report."""
from __future__ import annotations

from typing import Any

from app.models.schemas import SopFlowSchema, StepSchema


def validate_and_report(sop: SopFlowSchema) -> dict[str, Any]:
    issues: list[str] = []
    warnings: list[str] = []
    suggestions: list[str] = []

    # Product checks
    if not sop.product.name:
        issues.append("MISSING: product.name is empty")
    if not sop.product.category:
        warnings.append("WARN: product.category is empty")

    # Issue checks
    if not sop.issue.name:
        issues.append("MISSING: issue.name is empty")
    if not sop.issue.symptom_phrases:
        warnings.append("WARN: No symptom_phrases — search quality will be reduced")

    # Step checks
    if not sop.steps:
        issues.append("MISSING: steps list is empty")

    for step in sop.steps:
        if not step.customer_message:
            issues.append(f"MISSING: step {step.id} has no customer_message")
        if not step.expected_responses:
            warnings.append(f"WARN: step {step.id} has no expected_responses")
        if step.type == "instruction" and not (step.on_done or step.on_yes):
            warnings.append(f"WARN: step {step.id} (instruction) has no on_done/on_yes transition")
        if not step.response_buttons and step.type != "terminal":
            suggestions.append(f"SUGGEST: step {step.id} has no response_buttons — add buttons for better UX")
        if any(kw in step.customer_message.lower() for kw in ["warranty", "damage", "electric", "shock", "danger"]):
            if not step.safety_note:
                warnings.append(f"WARN: step {step.id} may need a safety_note (contains sensitive keywords)")

    # Dead-end detection
    step_ids = {s.id for s in sop.steps}
    terminal_ids = {t.id for t in sop.terminal_states}
    all_ids = step_ids | terminal_ids
    for step in sop.steps:
        for field in ("on_done", "on_yes", "on_no", "on_not_sure", "on_failed", "on_other"):
            ref = getattr(step, field, None)
            if ref and ref not in all_ids:
                issues.append(f"BROKEN_LINK: step {step.id}.{field} → '{ref}' does not exist")

    # Inferred structure note
    if sop.inferred_structure:
        warnings.append("NOTE: Structure was inferred — manual review recommended for branching logic")

    return {
        "sop_id": sop.sop_id,
        "title": sop.title,
        "step_count": len(sop.steps),
        "issues": issues,
        "warnings": warnings,
        "suggestions": suggestions,
        "ready_for_review": len(issues) == 0,
        "requires_manual_review": len(issues) > 0 or sop.inferred_structure,
    }
