"""Basic API health and endpoint smoke tests."""
import pytest


def test_root_returns_ok(client):
    r = client.get("/")
    assert r.status_code == 200
    data = r.json()
    assert "message" in data


def test_health_endpoint(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_admin_health(client):
    r = client.get("/admin/health")
    assert r.status_code == 200


def test_sops_list_empty(client):
    r = client.get("/sops/")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_sop_not_found(client):
    r = client.get("/sops/nonexistent-slug")
    assert r.status_code == 404


def test_escalations_list_empty(client):
    r = client.get("/escalations/")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_analytics_summary(client):
    r = client.get("/analytics/summary")
    assert r.status_code == 200
    data = r.json()
    assert "total_conversations" in data


def test_conversations_list(client):
    r = client.get("/admin/conversations")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_chat_requires_customer_id(client):
    r = client.post("/chat/message", json={"message": "hello"})
    assert r.status_code == 422  # validation error
