"""3단계 사내 표준약관 AI 연결 테스트 — 실제 사내 AI는 없으므로 HTTP 경계를 바꿔 끼운다.

- `app.internal_terms._post`를 가짜 함수로 바꿔 "연결됨 / 응답 없음 / 인증 실패 / 형식 오류"를 만든다.
- 응답 규격이 기관마다 달라도 우리 모양(조문 번호·쪽수·신뢰도·이유)으로 맞춰지는지 확인한다.
- 사내 AI가 없을 때 기존 규정 PDF 경로가 그대로 도는지(폴백)도 함께 확인한다.
"""

from __future__ import annotations

import urllib.error

import pytest

from app import internal_terms
from app.content import SAMPLE_DRAFT
from app.internal_terms import (
    UNAVAILABLE_NOTICE,
    TermsAIError,
    check,
    match,
    normalize_response,
)
from app.server import create_app

SENTENCES = [
    "월간 전기요금 이의신청 접수 및 1차 회신",
    "계량기 고장 접수 시 검침팀에 재검침을 요청합니다",
]


def _payload():
    """사내 표준약관 AI가 돌려줄 법한 응답(계약서에 적은 규약 그대로)."""
    return {
        "matches": [
            {
                "sentence": SENTENCES[0],
                "article_no": "제74조의2",
                "article_title": "요금에 대한 이의신청",
                "page": 59,
                "chapter": "제8장 요금",
                "excerpt": "고객은 전기요금에 이의가 있는 경우 이의신청을 할 수 있다.",
                "confidence": "높음",
                "reason": "이의신청·회신 표현이 조문과 일치합니다.",
                "matched_terms": ["이의신청"],
            },
            {
                "sentence": SENTENCES[1],
                "article_no": "제37조",
                "article_title": "전력량계 등의 설치 및 소유",
                "page": 22,
                "chapter": "제4장 설비",
                "excerpt": "전력량계의 고장 여부는 회사가 확인한다.",
                "confidence": "medium",
                "reason": "계량기·검침 표현이 겹칩니다.",
                "alternatives": [
                    {"article_no": "제38조", "article_title": "계량기의 검정", "page": 23, "confidence": 0.42}
                ],
            },
        ]
    }


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("INTERNAL_TERMS_API_URL", raising=False)
    monkeypatch.delenv("INTERNAL_TERMS_API_KEY", raising=False)
    monkeypatch.delenv("INTERNAL_TERMS_TIMEOUT", raising=False)
    internal_terms.RUNTIME.clear()
    yield
    internal_terms.RUNTIME.clear()


@pytest.fixture()
def client():
    app = create_app()
    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        yield test_client


@pytest.fixture()
def reachable(monkeypatch):
    """연결·조회가 모두 되는 사내 AI. 보낸 payload를 captured에 남긴다."""
    captured = {}

    def fake_post(url, payload, key="", timeout_s=None):
        captured["url"] = url
        captured["payload"] = payload
        captured["key"] = key
        return _payload()

    monkeypatch.setattr(internal_terms, "_post", fake_post)
    return captured


# ---------------------------------------------------------------------------
# 연결 확인
# ---------------------------------------------------------------------------

def test_check_without_any_endpoint_is_not_configured():
    result = check()
    assert result["ok"] is False
    assert result["status"] == "not_configured"
    assert result["notice"] == UNAVAILABLE_NOTICE
    assert UNAVAILABLE_NOTICE == "연동할 수 있는 사내 표준약관 AI를 찾지 못하였어요."
    assert result["fallback_label"] == "규정 PDF 업로드로 진행하기"


def test_check_rejects_bad_scheme():
    result = check("ftp://terms.internal/search")
    assert result["status"] == "invalid_endpoint"
    assert "http://" in result["reason"]


def test_check_reads_env_endpoint(monkeypatch, reachable):
    monkeypatch.setenv("INTERNAL_TERMS_API_URL", "https://terms.internal/api/search")
    monkeypatch.setenv("INTERNAL_TERMS_API_KEY", "secret-key")
    result = check()
    assert result["ok"] is True
    assert result["status"] == "connected"
    assert result["endpoint"] == "https://terms.internal/api/search"
    assert result["notice"] == ""
    assert reachable["url"] == "https://terms.internal/api/search"
    assert reachable["payload"] == {"sentences": [internal_terms.PROBE_SENTENCE]}
    assert reachable["key"] == "secret-key"


def test_check_typed_endpoint_is_remembered(reachable):
    result = check("terms.internal/api/search")
    assert result["ok"] is True
    assert result["endpoint"] == "http://terms.internal/api/search"
    assert internal_terms.endpoint() == "http://terms.internal/api/search"


def test_check_reports_unreachable(monkeypatch):
    def fake_post(*args, **kwargs):
        raise TermsAIError("unreachable", "terms.internal에서 응답이 없습니다.")

    monkeypatch.setattr(internal_terms, "_post", fake_post)
    result = check("https://terms.internal/api/search")
    assert result["ok"] is False
    assert result["status"] == "unreachable"
    assert result["notice"] == UNAVAILABLE_NOTICE
    assert "응답이 없습니다" in result["reason"]


def test_check_reports_auth_failure(monkeypatch):
    def fake_post(*args, **kwargs):
        raise TermsAIError("unauthorized", "인증에 실패했습니다.")

    monkeypatch.setattr(internal_terms, "_post", fake_post)
    result = check("https://terms.internal/api/search")
    assert result["status"] == "unauthorized"
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# HTTP 오류 → 상태 코드 매핑
# ---------------------------------------------------------------------------

def _http_error(code):
    return urllib.error.HTTPError("https://terms.internal", code, "err", {}, None)


@pytest.mark.parametrize("code,status", [(401, "unauthorized"), (403, "unauthorized"),
                                         (404, "not_endpoint"), (500, "server_error")])
def test_post_maps_http_errors(monkeypatch, code, status):
    def fake_urlopen(*args, **kwargs):
        raise _http_error(code)

    monkeypatch.setattr(internal_terms.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(TermsAIError) as raised:
        internal_terms._post("https://terms.internal", {"sentences": ["x"]})
    assert raised.value.status == status


def test_post_maps_connection_error(monkeypatch):
    def fake_urlopen(*args, **kwargs):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(internal_terms.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(TermsAIError) as raised:
        internal_terms._post("https://terms.internal", {"sentences": ["x"]})
    assert raised.value.status == "unreachable"
    assert "terms.internal" in raised.value.reason


# ---------------------------------------------------------------------------
# 응답 정규화
# ---------------------------------------------------------------------------

def test_normalize_response_keeps_article_location_and_reason():
    result = normalize_response(_payload(), SENTENCES, endpoint="https://terms.internal")
    assert result["ok"] is True
    assert result["source"] == "internal"
    assert result["stats"] == {"sentences": 2, "matched": 2, "articles": 3}
    first, second = result["matches"]

    primary = first["primary"]
    assert primary["article_no"] == "제74조의2"
    assert primary["title"] == "요금에 대한 이의신청"
    assert primary["printed_page"] == 59
    assert primary["chapter"] == "제8장 요금"
    assert primary["confidence"] == "높음"
    assert "이의신청" in primary["reason"]
    assert primary["location"].startswith("제74조의2 (요금에 대한 이의신청)")
    assert "59쪽" in primary["location"]
    assert first["sentence"] == SENTENCES[0]

    assert second["primary"]["confidence"] == "중간"        # medium → 중간
    assert second["alternatives"][0]["article_no"] == "제38조"
    assert second["alternatives"][0]["confidence"] == "중간"  # 0.42 → 중간
    assert result["regulation"]["name"] == "사내 표준약관 AI"
    assert result["regulation"]["source_url"] == "https://terms.internal"
    assert result["disclaimer"].startswith("이 결과는 법적 판단이 아니라")


def test_normalize_response_accepts_alternative_shapes():
    payload = {"data": {"results": [
        {"text": "명의변경 접수", "article": "제19조", "title": "전기사용계약자의 변경",
         "printed_page": 12, "confidence": "high", "snippet": "계약자의 변경은 회사에 신청한다."}
    ]}}
    result = normalize_response(payload, ["명의변경 접수"], endpoint="https://terms.internal")
    primary = result["matches"][0]["primary"]
    assert primary["article_no"] == "제19조"
    assert primary["title"] == "전기사용계약자의 변경"
    assert primary["printed_page"] == 12
    assert primary["confidence"] == "높음"
    assert result["matches"][0]["sentence"] == "명의변경 접수"


def test_normalize_response_without_matches_explains_itself():
    result = normalize_response({"matches": []}, SENTENCES, endpoint="https://terms.internal")
    assert result["ok"] is True
    assert result["matches"] == []
    assert result["stats"]["matched"] == 0
    assert result["notices"]


# ---------------------------------------------------------------------------
# 조항 찾기
# ---------------------------------------------------------------------------

def test_match_requires_endpoint():
    with pytest.raises(TermsAIError) as raised:
        match(SAMPLE_DRAFT)
    assert raised.value.status == "not_configured"


def test_match_sends_sentences_and_normalizes(reachable):
    result = match(SAMPLE_DRAFT, endpoint_value="https://terms.internal/api/search")
    assert result["ok"] is True
    assert reachable["url"] == "https://terms.internal/api/search"
    assert len(reachable["payload"]["sentences"]) >= 5
    assert "월간 전기요금 이의신청 접수 및 1차 회신" in reachable["payload"]["sentences"]
    assert result["matches"][0]["primary"]["article_no"] == "제74조의2"
    assert result["ai"]["masked"] is False


def test_match_can_send_masked_copy(reachable):
    text = SAMPLE_DRAFT + "\n연락처 010-1234-5678 로 회신 요청"
    result = match(text, endpoint_value="https://terms.internal/api/search", mask=True)
    sent = " ".join(reachable["payload"]["sentences"])
    assert "010-1234-5678" not in sent
    assert result["ai"]["masked"] is True
    assert result["ai"]["masked_count"] >= 1


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def test_status_endpoint_lists_both_paths(client):
    data = client.get("/api/terms/status").get_json()
    assert data["sources"] == ["internal", "pdf"]
    assert data["internal"]["configured"] is False
    assert data["internal"]["notice"] == UNAVAILABLE_NOTICE
    ids = [item["id"] for item in data["pdf"]["items"]]
    assert "kepco" in ids


def test_health_reports_terms_connection(client):
    data = client.get("/api/health").get_json()
    assert data["terms"]["internal"]["configured"] is False
    assert data["terms"]["notice"] == UNAVAILABLE_NOTICE


def test_api_check_unconfigured(client):
    data = client.post("/api/terms/check", json={}).get_json()
    assert data["ok"] is False
    assert data["status"] == "not_configured"
    assert data["message"] == UNAVAILABLE_NOTICE


def test_api_check_mocked_reachable(client, reachable):
    data = client.post("/api/terms/check", json={"endpoint": "https://terms.internal/api/search"}).get_json()
    assert data["ok"] is True
    assert data["status"] == "connected"


def test_api_match_internal_unconfigured(client):
    data = client.post("/api/terms", json={"text": SAMPLE_DRAFT, "source": "internal"}).get_json()
    assert data["ok"] is False
    assert data["status"] == "not_configured"
    assert data["notice"] == UNAVAILABLE_NOTICE
    assert data["fallback_label"] == "규정 PDF 업로드로 진행하기"


def test_api_match_internal_after_check(client, reachable):
    client.post("/api/terms/check", json={"endpoint": "https://terms.internal/api/search"})
    data = client.post("/api/terms", json={"text": SAMPLE_DRAFT, "source": "internal"}).get_json()
    assert data["ok"] is True
    assert data["source"] == "internal"
    assert data["matches"][0]["primary"]["article_no"] == "제74조의2"
    assert data["stats"]["matched"] == 2
    assert data["regulation"]["name"] == "사내 표준약관 AI"


def test_api_match_internal_unreachable_returns_notice(client, monkeypatch):
    def fake_post(*args, **kwargs):
        raise TermsAIError("unreachable", "terms.internal에서 응답이 없습니다.")

    monkeypatch.setattr(internal_terms, "_post", fake_post)
    data = client.post(
        "/api/terms",
        json={"text": SAMPLE_DRAFT, "source": "internal", "endpoint": "https://terms.internal/api/search"},
    ).get_json()
    assert data["ok"] is False
    assert data["status"] == "unreachable"
    assert data["notice"] == UNAVAILABLE_NOTICE


def test_api_match_pdf_fallback_still_works(client):
    """사내 표준약관 AI가 없는 기관은 기존 PDF 경로 그대로(내장 샘플)."""
    data = client.post("/api/terms", json={"text": SAMPLE_DRAFT, "source": "pdf",
                                           "regulation_id": "kepco"}).get_json()
    assert data["ok"] is True
    assert data["source"] == "pdf"
    assert data["stats"]["matched"] >= 5
    assert data["regulation"]["id"] == "kepco"
    assert data["matches"][0]["primary"]["article_no"].startswith("제")


def test_api_match_rejects_unknown_source(client):
    response = client.post("/api/terms", json={"text": SAMPLE_DRAFT, "source": "magic"})
    assert response.status_code == 400
