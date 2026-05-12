"""Integration tests for the conversation flow (with mocked LLM + embed)."""
import json
import uuid
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.models.db_models import Product, Issue, SopFlow
from app.models.schemas import SopFlowSchema

SEEDS_DIR = Path(__file__).parent.parent / "data" / "seeds"


def _load_wifi_sop():
    return json.loads((SEEDS_DIR / "wifi_router_no_internet.json").read_text(encoding="utf-8"))


def _seed_db(db):
    """Insert a published Wi-Fi Router SOP into the test DB with a unique slug per call."""
    data = _load_wifi_sop()
    sop = SopFlowSchema(**data)

    # Use unique IDs per test run to avoid UNIQUE constraint violations
    unique_suffix = uuid.uuid4().hex[:8]

    product = Product(name=f"Wi-Fi Router {unique_suffix}", category="Networking",
                      aliases=["router", "WiFi router"])
    db.add(product)
    db.flush()

    issue = Issue(product_id=product.id, name="No Internet Connection",
                  symptom_phrases=["no internet", "wifi not working"])
    db.add(issue)
    db.flush()

    flow = SopFlow(
        product_id=product.id,
        issue_id=issue.id,
        sop_slug=f"{sop.sop_id}-{unique_suffix}",   # unique slug
        title=sop.title,
        status="published",
        flow_json=sop.model_dump(),                  # pydantic v2: model_dump not dict
        source_file="test",
    )
    db.add(flow)
    db.commit()
    db.refresh(product)
    db.refresh(issue)
    db.refresh(flow)
    return product, issue, flow


def _mock_classify(product="Wi-Fi Router", issue="No Internet Connection", confidence=0.9):
    return json.dumps({
        "detected_product": product,
        "detected_issue": issue,
        "symptoms": ["no internet"],
        "needs_clarification": False,
        "confidence": confidence,
        "reason": "test",
    })


def _mock_interpret(mapped="done"):
    return json.dumps({
        "mapped_response": mapped,
        "confidence": 0.95,
        "extracted_observation": "",
        "should_escalate": False,
        "reason": "test",
    })


@pytest.mark.parametrize("first_message", ["hello", "__init__"])
def test_new_conversation_asks_product(client, db, first_message):
    with patch("app.services.llm_service._call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("app.services.embedding_service.embed_text", new_callable=AsyncMock) as mock_embed:
        mock_embed.return_value = [0.1] * 1536
        mock_llm.return_value = json.dumps({
            "detected_product": "", "detected_issue": "",
            "symptoms": [], "needs_clarification": True, "confidence": 0.0, "reason": ""
        })
        r = client.post("/chat/message", json={
            "customer_id": "test_001",
            "channel": "web",
            "message": first_message,
        })
        assert r.status_code == 200
        data = r.json()
        assert data["conversation_id"]
        assert len(data["messages"]) > 0
        combined_text = " ".join(m["text"] for m in data["messages"]).lower()
        assert any(w in combined_text for w in ["product", "help", "which"])


def test_conversation_selects_sop_and_runs_step_1(client, db):
    product, issue, flow_db = _seed_db(db)

    with patch("app.services.llm_service._call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("app.services.embedding_service.embed_text", new_callable=AsyncMock) as mock_embed, \
         patch("app.services.search_service._pg_vector_search") as mock_vec:
        mock_embed.return_value = [0.1] * 1536
        mock_vec.return_value = []
        # Classify returns the product name that matches what we seeded
        mock_llm.return_value = json.dumps({
            "detected_product": product.name,
            "detected_issue": "No Internet Connection",
            "symptoms": ["no internet"],
            "needs_clarification": False,
            "confidence": 0.9,
            "reason": "test",
        })

        r = client.post("/chat/message", json={
            "customer_id": "test_002",
            "channel": "web",
            "message": f"My {product.name} has no internet",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["conversation_id"]
        assert data["state"] != "NEW"


def test_done_advances_to_next_step(client, db):
    product, issue, flow_db = _seed_db(db)

    from app.models.db_models import Conversation
    conv = Conversation(
        customer_id="test_003",
        channel="web",
        product_id=product.id,
        issue_id=issue.id,
        sop_flow_id=flow_db.id,
        current_step_id="step_1",
        status="RUNNING_STEP",
        state_json={"retry_counts": {}, "completed_steps": []},
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)

    with patch("app.services.llm_service._call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = _mock_interpret("done")
        r = client.post("/chat/message", json={
            "customer_id": "test_003",
            "conversation_id": conv.id,
            "channel": "web",
            "message": "Done",
        })
        assert r.status_code == 200
        data = r.json()
        db.refresh(conv)
        # step_1 → on_done → step_2
        assert conv.current_step_id != "step_1" or conv.status == "RESOLVED"


def test_wants_human_triggers_escalation(client, db):
    product, issue, flow_db = _seed_db(db)

    from app.models.db_models import Conversation, Escalation
    conv = Conversation(
        customer_id="test_004",
        channel="web",
        product_id=product.id,
        issue_id=issue.id,
        sop_flow_id=flow_db.id,
        current_step_id="step_1",
        status="RUNNING_STEP",
        state_json={"retry_counts": {}, "completed_steps": []},
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)

    with patch("app.services.llm_service._call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.side_effect = [
            _mock_interpret("wants_human"),
            json.dumps({
                "summary": "Customer wants human.",
                "recommended_action": "Contact customer.",
                "key_observations": [],
                "urgency": "medium",
            }),
        ]
        r = client.post("/chat/message", json={
            "customer_id": "test_004",
            "conversation_id": conv.id,
            "channel": "web",
            "message": "I want to talk to a human",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["state"] == "ESCALATED"

        esc = db.query(Escalation).filter(Escalation.conversation_id == conv.id).first()
        assert esc is not None


def test_restart_resets_conversation(client, db):
    product, issue, flow_db = _seed_db(db)

    from app.models.db_models import Conversation
    conv = Conversation(
        customer_id="test_005",
        channel="web",
        product_id=product.id,
        issue_id=issue.id,
        sop_flow_id=flow_db.id,
        current_step_id="step_3",
        status="RUNNING_STEP",
        state_json={},
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)

    r = client.post("/chat/message", json={
        "customer_id": "test_005",
        "conversation_id": conv.id,
        "channel": "web",
        "message": "restart",
    })
    assert r.status_code == 200
    db.refresh(conv)
    assert conv.status == "NEW"
    assert conv.sop_flow_id is None
