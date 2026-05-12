"""Test the SOP flow execution engine."""
import json
import pytest
from pathlib import Path

from app.models.schemas import InterpretResult, SopFlowSchema
from app.services.flow_engine import FlowEngine

SEEDS_DIR = Path(__file__).parent.parent / "data" / "seeds"


@pytest.fixture
def wifi_sop():
    data = json.loads((SEEDS_DIR / "wifi_router_no_internet.json").read_text(encoding="utf-8"))
    return SopFlowSchema(**data)


@pytest.fixture
def engine(wifi_sop):
    return FlowEngine(wifi_sop)


def _interp(label: str, escalate: bool = False) -> InterpretResult:
    return InterpretResult(mapped_response=label, confidence=0.9, should_escalate=escalate)


def test_first_step_is_step_1(engine):
    assert engine.get_first_step_id() == "step_1"


def test_render_step_1_returns_messages(engine):
    msgs = engine.render_step("step_1")
    assert len(msgs) > 0
    assert any(m.type in ("text", "buttons") for m in msgs)


def test_render_step_with_buttons(engine):
    msgs = engine.render_step("step_1")
    button_msg = next((m for m in msgs if m.type == "buttons"), None)
    assert button_msg is not None
    assert len(button_msg.buttons) > 0


def test_done_advances_to_step_2(engine):
    next_id, is_help = engine.get_next_step_id("step_1", _interp("done"))
    assert next_id == "step_2"
    assert is_help is False


def test_not_sure_goes_to_help_step(engine):
    next_id, is_help = engine.get_next_step_id("step_1", _interp("not_sure"))
    assert next_id == "step_1_help"
    assert is_help is False


def test_help_needed_stays_on_same_step(engine):
    next_id, is_help = engine.get_next_step_id("step_1", _interp("help_needed"))
    assert next_id == "step_1"
    assert is_help is True


def test_render_help_returns_text(engine):
    msgs = engine.render_help("step_1")
    assert len(msgs) > 0


def test_wants_human_escalates(engine):
    next_id, is_help = engine.get_next_step_id("step_1", _interp("wants_human"))
    assert next_id == "escalated"
    assert is_help is False


def test_should_escalate_flag(engine):
    result = _interp("done", escalate=True)
    next_id, _ = engine.get_next_step_id("step_1", result)
    assert next_id == "escalated"


def test_terminal_resolved_detected(engine):
    assert engine.is_resolved("resolved") is True
    assert engine.is_escalation("resolved") is False


def test_terminal_escalated_detected(engine):
    assert engine.is_escalation("escalated") is True
    assert engine.is_resolved("escalated") is False


def test_render_terminal_resolved(engine):
    msgs = engine.render_step("resolved")
    assert len(msgs) > 0
    assert "resolved" in msgs[0].text.lower() or "glad" in msgs[0].text.lower() or "great" in msgs[0].text.lower()


def test_nonexistent_step_renders_error_message(engine):
    msgs = engine.render_step("nonexistent_step_xyz")
    assert len(msgs) > 0


def test_full_linear_flow(engine):
    """Simulate Done → Done → Done through steps."""
    step = engine.get_first_step_id()
    visited = []
    for _ in range(20):
        if engine.is_terminal(step):
            break
        visited.append(step)
        next_step, _ = engine.get_next_step_id(step, _interp("done"))
        assert next_step != step or engine.is_terminal(next_step), f"Stuck at {step}"
        step = next_step
    assert len(visited) >= 1
