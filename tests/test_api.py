"""API 테스트 — 실제 HTTP 라우트를 Flask 테스트 클라이언트로 확인한다."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from app.content import TEMPLATE_TEXT
from app.server import create_app

SAMPLES = Path(__file__).resolve().parent.parent / "app" / "samples"


@pytest.fixture(scope="module")
def client():
    app = create_app()
    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        yield test_client


def test_index_renders(client):
    response = client.get("/")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "인수인계서 AI" in body
    assert "작성 가이드" in body


def test_health_lists_samples_and_regulation(client):
    data = client.get("/api/health").get_json()
    assert data["status"] == "ok"
    assert data["llm"]["provider"] == "demo"
    formats = {item["format"] for item in data["samples"]["handover"]}
    assert {"md", "docx", "hwpx", "pdf"} <= formats
    kepco = data["samples"]["regulations"][0]
    assert kepco["id"] == "kepco"
    assert kepco["article_count"] > 90


def test_template_endpoint(client):
    data = client.get("/api/template").get_json()
    assert "## 1. 업무 개요" in data["text"]
    assert len(data["checklist"]) == 12


@pytest.mark.parametrize("fmt,filename", [
    ("md", "handover_sample.md"),
    ("docx", "handover_sample.docx"),
    ("hwpx", "handover_sample.hwpx"),
    ("pdf", "handover_sample.pdf"),
])
def test_parse_upload_each_format(client, fmt, filename):
    data = (SAMPLES / filename).read_bytes()
    response = client.post(
        "/api/parse",
        data={"file": (io.BytesIO(data), filename)},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    payload = response.get_json()
    assert "전기사용계약 변경" in payload["text"]
    assert payload["char_count"] > 300


def test_parse_upload_rejects_broken_pdf(client):
    response = client.post(
        "/api/parse",
        data={"file": (io.BytesIO(b"%broken"), "broken.pdf")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    assert "error" in response.get_json()


def test_mask_endpoint(client):
    response = client.post("/api/mask", json={"text": "연락처 010-1111-2222, 메일 a@b.com", "mask": True})
    payload = response.get_json()
    assert payload["masked_count"] == 2
    assert "010-1111-2222" not in payload["preview"]


def test_analyze_endpoint(client):
    response = client.post("/api/analyze", json={"text": TEMPLATE_TEXT, "answers": {}, "mask": True})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["summary"]["dimensions"] == 12
    assert payload["questions"]
    assert payload["llm"]["provider"] == "demo"
    assert payload["masking"]["report"]["total"] == 0


def test_analyze_rejects_short_text(client):
    response = client.post("/api/analyze", json={"text": "짧음"})
    assert response.status_code == 400


def test_terms_endpoint_with_builtin_regulation(client):
    response = client.post("/api/terms", json={
        "text": "월간 전기요금 이의신청 접수 및 1차 회신",
        "regulation_id": "kepco",
    })
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["matches"]
    assert payload["regulation"]["article_count"] > 90
    assert "법적 판단이 아니라" in payload["disclaimer"]


def test_regulation_upload_registers_new_document(client):
    data = (SAMPLES / "regulation" / "kepco_basic_supply_terms.pdf").read_bytes()
    response = client.post(
        "/api/regulations",
        data={"file": (io.BytesIO(data), "kepco_copy.pdf"), "name": "테스트 약관"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    summary = response.get_json()["regulation"]
    assert summary["uploaded"] is True
    assert summary["article_count"] > 90

    listed = client.get("/api/regulations").get_json()["items"]
    assert any(item["id"] == summary["id"] for item in listed)


def test_export_endpoint(client):
    analysis = client.post("/api/analyze", json={"text": TEMPLATE_TEXT}).get_json()
    response = client.post("/api/export", json={
        "meta": {"author": "테스트", "successor": "후임"},
        "text": TEMPLATE_TEXT,
        "analysis": analysis,
    })
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["markdown"].startswith("# 인수인계서")
    assert "아직 답하지 못한 질문 목록" in payload["markdown"]
    assert payload["text"].strip()
    assert payload["filename"].endswith(".md") is False  # 확장자는 화면에서 붙인다
