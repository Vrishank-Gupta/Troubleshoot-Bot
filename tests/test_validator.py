"""Test SOP validator / review report."""
import json
import pytest
from pathlib import Path

from app.models.schemas import SopFlowSchema
from app.ingestion.sop_validator import validate_and_report

SEEDS_DIR = Path(__file__).parent.parent / "data" / "seeds"


@pytest.fixture
def wifi_sop():
    data = json.loads((SEEDS_DIR / "wifi_router_no_internet.json").read_text(encoding="utf-8"))
    return SopFlowSchema(**data)


def test_valid_sop_has_no_issues(wifi_sop):
    report = validate_and_report(wifi_sop)
    assert report["ready_for_review"] is True
    assert len(report["issues"]) == 0


def test_missing_product_name_flagged():
    data = json.loads((SEEDS_DIR / "wifi_router_no_internet.json").read_text(encoding="utf-8"))
    data["product"]["name"] = ""
    sop = SopFlowSchema(**data)
    report = validate_and_report(sop)
    assert any("product.name" in i for i in report["issues"])


def test_missing_issue_name_flagged():
    data = json.loads((SEEDS_DIR / "wifi_router_no_internet.json").read_text(encoding="utf-8"))
    data["issue"]["name"] = ""
    sop = SopFlowSchema(**data)
    report = validate_and_report(sop)
    assert any("issue.name" in i for i in report["issues"])


def test_broken_link_flagged():
    data = json.loads((SEEDS_DIR / "wifi_router_no_internet.json").read_text(encoding="utf-8"))
    data["steps"][0]["on_done"] = "nonexistent_step_xyz"
    sop = SopFlowSchema(**data)
    report = validate_and_report(sop)
    assert any("BROKEN_LINK" in i for i in report["issues"])


def test_empty_steps_flagged():
    data = json.loads((SEEDS_DIR / "wifi_router_no_internet.json").read_text(encoding="utf-8"))
    data["steps"] = []
    sop = SopFlowSchema(**data)
    report = validate_and_report(sop)
    assert any("steps" in i.lower() for i in report["issues"])


def test_report_includes_step_count(wifi_sop):
    report = validate_and_report(wifi_sop)
    assert report["step_count"] == len(wifi_sop.steps)


def test_inferred_structure_flags_warning():
    data = json.loads((SEEDS_DIR / "wifi_router_no_internet.json").read_text(encoding="utf-8"))
    data["inferred_structure"] = True
    sop = SopFlowSchema(**data)
    report = validate_and_report(sop)
    assert any("inferred" in w.lower() for w in report["warnings"])
