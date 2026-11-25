"""AI 연결 모드와 연결 확인 API 테스트.

- 네 모드가 그대로 노출되는지
- 설정이 없거나 응답이 없을 때 "연동할 수 있는 AI를 찾지 못하였어요"와 이유를 주는지
- 화면에서 넣은 주소로 실제 연결을 확인하고, 성공한 주소를 기억하는지
- AI 미연결 모드가 외부 LLM 설정을 무시하는지
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app import ai_modes
from app.content import TEMPLATE_TEXT
from app.server import create_app


@pytest.fixture(autouse=True)
def clean_runtime_endpoints():
    ai_modes.RUNTIME_ENDPOINTS.clear()
    yield
    ai_modes.RUNTIME_ENDPOINTS.clear()


@pytest.fixture
def client():
    app = create_app()
    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        yield test_client


class _StubHandler(BaseHTTPRequestHandler):
    """OpenAI 호환 /models 에 200으로 답하는 최소 서버."""

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler 규약
        body = b'{"data": []}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def stub_ai():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def test_modes_endpoint_lists_four_choices(client):
    data = client.get("/api/ai/modes").get_json()
    keys = [mode["key"] for mode in data["modes"]]
    assert keys == ["internal_multimodal", "internal_text", "external_masked", "offline_rules"]
    assert data["notice"] == "연동할 수 있는 AI를 찾지 못하였어요."
    labels = {mode["key"]: mode["label"] for mode in data["modes"]}
    assert labels["internal_multimodal"] == "사내 AI (텍스트+그림)"
    assert labels["internal_text"] == "사내 AI (텍스트만)"
    assert labels["external_masked"] == "외부 AI 연동 (민감정보 가림)"
    assert labels["offline_rules"] == "AI 미연결 (기본 규칙 점검)"


def test_image_capability_matches_mode(client):
    modes = {mode["key"]: mode for mode in client.get("/api/ai/modes").get_json()["modes"]}
    assert modes["internal_multimodal"]["reads_images"] is True
    assert modes["external_masked"]["reads_images"] is True
    assert modes["internal_text"]["reads_images"] is False
    assert modes["offline_rules"]["reads_images"] is False


def test_offline_mode_is_always_ready(client):
    data = client.post("/api/ai/check", json={"mode": "offline_rules"}).get_json()
    assert data["ok"] is True
    assert data["status"] == "ready"
    assert data["reads_images"] is False


def test_internal_mode_without_endpoint_reports_unavailable(client, monkeypatch):
    monkeypatch.delenv("INTERNAL_AI_BASE_URL", raising=False)
    data = client.post("/api/ai/check", json={"mode": "internal_multimodal"}).get_json()
    assert data["ok"] is False
    assert data["status"] == "not_configured"
    assert data["message"] == "연동할 수 있는 AI를 찾지 못하였어요."
    assert "주소" in data["reason"]
    assert data["retry_label"] == "사내 AI 다시 연결하기"


def test_internal_endpoint_given_in_ui_connects_and_is_remembered(client, stub_ai):
    response = client.post("/api/ai/check", json={
        "mode": "internal_text", "endpoint": f"{stub_ai}/v1",
    })
    data = response.get_json()
    assert data["ok"] is True
    assert data["status"] == "connected"
    assert data["endpoint"] == f"{stub_ai}/v1"
    assert ai_modes.RUNTIME_ENDPOINTS["internal_text"] == f"{stub_ai}/v1"

    # 주소를 다시 넣지 않아도 기억한 주소로 확인된다.
    again = client.post("/api/ai/check", json={"mode": "internal_text"}).get_json()
    assert again["ok"] is True


def test_internal_endpoint_unreachable_reports_reason(client):
    data = client.post("/api/ai/check", json={
        "mode": "internal_multimodal", "endpoint": "http://127.0.0.1:9",
    }).get_json()
    assert data["ok"] is False
    assert data["status"] == "unreachable"
    assert data["message"] == "연동할 수 있는 AI를 찾지 못하였어요."
    assert data["reason"]


def test_invalid_endpoint_is_rejected(client):
    data = client.post("/api/ai/check", json={
        "mode": "internal_text", "endpoint": "ftp://ai.internal",
    }).get_json()
    assert data["ok"] is False
    assert data["status"] == "invalid_endpoint"
    assert "http" in data["reason"]


def test_external_mode_in_demo_reports_not_configured(client, monkeypatch):
    for name in ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    data = client.post("/api/ai/check", json={"mode": "external_masked"}).get_json()
    assert data["ok"] is False
    assert data["status"] == "not_configured"
    assert data["message"] == "연동할 수 있는 AI를 찾지 못하였어요."


def test_unknown_mode_falls_back_to_notice(client):
    data = client.post("/api/ai/check", json={"mode": "no-such-mode"}).get_json()
    assert data["ok"] is False
    assert data["message"] == "연동할 수 있는 AI를 찾지 못하였어요."


def test_offline_mode_never_uses_configured_external_llm(client, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    payload = client.post("/api/analyze", json={
        "text": TEMPLATE_TEXT, "answers": {}, "mask": True, "ai_mode": "offline_rules",
    }).get_json()
    assert payload["llm"]["provider"] == "demo"
    assert payload["ai"]["mode"] == "offline_rules"
    assert payload["ai"]["configured"] is False


def test_mask_endpoint_reports_llm_activity_by_mode(client, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    offline = client.post("/api/mask", json={"text": "연락처 010-1111-2222", "ai_mode": "offline_rules"}).get_json()
    external = client.post("/api/mask", json={"text": "연락처 010-1111-2222", "ai_mode": "external_masked"}).get_json()
    assert offline["llm_active"] is False
    assert external["llm_active"] is True
