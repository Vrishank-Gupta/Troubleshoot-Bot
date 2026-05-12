"""Test SOP JSON schema validation."""
import json
import pytest
from pathlib import Path
from pydantic import ValidationError

from app.models.schemas import SopFlowSchema


SEEDS_DIR = Path(__file__).parent.parent / "data" / "seeds"


def _load_seed(name: str) -> dict:
    return json.loads((SEEDS_DIR / name).read_text(encoding="utf-8"))


def test_wifi_sop_validates():
    data = _load_seed("wifi_router_no_internet.json")
    sop = SopFlowSchema(**data)
    assert sop.sop_id == "wifi-router-no-internet"
    assert sop.product.name == "Wi-Fi Router"
    assert sop.issue.name == "No Internet Connection"
    assert len(sop.steps) >= 5
    assert sop.status == "published"


def test_tv_sop_validates():
    data = _load_seed("smart_tv_no_power.json")
    sop = SopFlowSchema(**data)
    assert sop.product.name == "Smart TV"
    assert len(sop.steps) > 0


def test_ac_sop_validates():
    data = _load_seed("air_conditioner_not_cooling.json")
    sop = SopFlowSchema(**data)
    assert "AC" in sop.product.model_aliases or "Air Conditioner" == sop.product.name


def test_terminal_states_auto_added():
    """resolved and escalated terminals must always exist."""
    data = _load_seed("wifi_router_no_internet.json")
    data["terminal_states"] = []  # remove them
    sop = SopFlowSchema(**data)
    ids = {t.id for t in sop.terminal_states}
    assert "resolved" in ids
    assert "escalated" in ids


def test_step_types_valid():
    data = _load_seed("wifi_router_no_internet.json")
    sop = SopFlowSchema(**data)
    valid_types = {"instruction", "question", "check", "decision", "terminal", "escalation"}
    for step in sop.steps:
        assert step.type in valid_types, f"Invalid type {step.type} for step {step.id}"


def test_missing_product_name_still_parses():
    data = _load_seed("wifi_router_no_internet.json")
    data["product"]["name"] = ""
    sop = SopFlowSchema(**data)
    assert sop.product.name == ""


def test_invalid_step_type_raises():
    data = _load_seed("wifi_router_no_internet.json")
    data["steps"][0]["type"] = "invalid_type"
    with pytest.raises(ValidationError):
        SopFlowSchema(**data)
