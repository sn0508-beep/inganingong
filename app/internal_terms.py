"""3단계: 사내 표준약관 AI 연결 (선택).

하는 일
- 사내에 표준약관·규정 검색 AI(또는 검색 API)가 있는 기관은 그 주소를 연결해 3단계 근거 찾기를
  그 AI에 맡긴다. 주소는 환경변수 `INTERNAL_TERMS_API_URL`로 두거나 화면 3단계에서 직접 넣는다.
- 그런 AI가 없는 기관은 이 모듈을 쓰지 않고 기존 **규정 PDF 업로드/내장 샘플** 경로로 그대로 간다.
  (두 경로 모두 같은 결과 모양으로 돌려주므로 화면·내보내기 코드는 하나만 알면 된다.)

연결 규약(사내 AI에 요구하는 것)
    POST <INTERNAL_TERMS_API_URL>
    Content-Type: application/json
    Authorization: Bearer <INTERNAL_TERMS_API_KEY>   (키를 설정한 경우에만)
    {"sentences": ["초안 문장", ...]}

    → 200 {"matches": [
            {"sentence": "초안 문장",
             "article_no": "제12조", "article_title": "계약 변경의 처리",
             "page": 15, "chapter": "제2장 계약", "excerpt": "…", 
             "confidence": "높음", "reason": "계약·변경 표현이 조문과 일치"}
          ]}

- `matches`는 `{"results": [...]}`·`{"data": {...}}`·배열 그대로도 받아 준다(기관마다 규격이 달라서).
- `confidence`는 `높음/중간/낮음`, `high/medium/low`, 0~1 또는 0~100 숫자를 모두 받아 우리 표기로 바꾼다.
- 응답에 없는 필드는 빈 값으로 채우고, 화면에는 '사내 표준약관 AI가 돌려준 후보'라고 표시한다.

중요: 여기서도 '법적 판단'이 아니라 '확인이 필요한 지점과 근거 후보'다. 면책 문구는 PDF 경로와 같다.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from urllib.parse import urlparse

from . import masking
from .terms import DISCLAIMER, split_sentences

UNAVAILABLE_NOTICE = "연동할 수 있는 사내 표준약관 AI를 찾지 못하였어요."
LABEL = "사내 표준약관 AI"
DEFAULT_TIMEOUT = 2.0          # 연결 확인은 짧게
DEFAULT_MATCH_TIMEOUT = 20.0   # 조항 찾기는 문장이 많아 조금 길게
PROBE_SENTENCE = "연결 확인"

#: 화면에서 연결에 성공한 주소. 업로드한 규정과 같이 메모리에만 둔다(재시작하면 사라짐).
RUNTIME: dict = {}

VALID_CONFIDENCE = ("높음", "중간", "낮음")


class TermsAIError(Exception):
    """사내 표준약관 AI 호출 실패. `status`는 화면이 그대로 쓸 수 있는 짧은 코드."""

    def __init__(self, status: str, reason: str):
        super().__init__(reason)
        self.status = status
        self.reason = reason


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def env_endpoint() -> str:
    return _env("INTERNAL_TERMS_API_URL").rstrip("/")


def api_key() -> str:
    return _env("INTERNAL_TERMS_API_KEY")


def timeout(seconds: float | None = None) -> float:
    if seconds:
        return float(seconds)
    raw = _env("INTERNAL_TERMS_TIMEOUT")
    try:
        return float(raw) if raw else DEFAULT_MATCH_TIMEOUT
    except ValueError:
        return DEFAULT_MATCH_TIMEOUT


def endpoint() -> str:
    return (RUNTIME.get("endpoint") or env_endpoint()).rstrip("/")


def normalize_endpoint(value: str) -> tuple:
    text = (value or "").strip()
    if not text:
        return "", ""
    if "://" not in text:
        text = "http://" + text
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return "", "주소는 http:// 또는 https://로 시작하는 형식이어야 합니다."
    return text.rstrip("/"), ""


def describe() -> dict:
    """화면이 연결 카드에 그대로 쓸 수 있는 현재 상태(호출 없이)."""
    current = endpoint()
    return {
        "source": "internal_terms",
        "label": LABEL,
        "configured": bool(current),
        "endpoint": current,
        "from_env": bool(env_endpoint()),
        "from_runtime": bool(RUNTIME.get("endpoint")),
        "key_set": bool(api_key()),
        "timeout": timeout(DEFAULT_TIMEOUT),
        "notice": UNAVAILABLE_NOTICE,
    }


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _post(url: str, payload: dict, key: str = "", timeout_s: float | None = None) -> dict:
    """POST JSON 한 번. 실패는 모두 TermsAIError로 바꿔 던진다."""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    host = urlparse(url).netloc or url
    try:
        with urllib.request.urlopen(request, timeout=timeout_s or timeout()) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise TermsAIError("unauthorized", "주소는 응답하지만 인증에 실패했습니다(키를 확인해 주세요).") from exc
        if exc.code in (404, 405):
            raise TermsAIError(
                "not_endpoint",
                "주소는 응답하지만 조항을 찾는 API가 아닙니다(HTTP %d). 관리자에게 받은 검색 주소를 확인해 주세요." % exc.code,
            ) from exc
        raise TermsAIError("server_error", f"사내 표준약관 AI가 오류를 돌려주었습니다(HTTP {exc.code}).") from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        detail = getattr(exc, "reason", exc)
        raise TermsAIError(
            "unreachable",
            f"{host}에서 응답이 없습니다. 주소와 방화벽을 확인해 주세요. ({detail})",
        ) from exc

    if not raw.strip():
        return {}
    try:
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise TermsAIError("bad_response", "사내 표준약관 AI 응답을 JSON으로 읽지 못했습니다.") from exc
    if not isinstance(data, (dict, list)):
        raise TermsAIError("bad_response", "사내 표준약관 AI 응답 형식이 예상과 다릅니다.")
    return data


# ---------------------------------------------------------------------------
# 연결 확인
# ---------------------------------------------------------------------------

def check(endpoint_value: str | None = None, timeout_s: float | None = None) -> dict:
    """사내 표준약관 AI 연결 상태. 어떤 경우에도 예외를 던지지 않는다."""
    base = {
        "source": "internal_terms",
        "label": LABEL,
        "ok": False,
        "status": "unknown",
        "notice": UNAVAILABLE_NOTICE,
        "message": UNAVAILABLE_NOTICE,
        "reason": "",
        "endpoint": "",
        "retry_label": "사내 표준약관 AI 다시 연결하기",
        "fallback_label": "규정 PDF 업로드로 진행하기",
    }

    typed, error = normalize_endpoint(endpoint_value or "")
    if error:
        return {**base, "status": "invalid_endpoint", "reason": error}

    target = typed or endpoint()
    if not target:
        return {
            **base,
            "status": "not_configured",
            "reason": "사내 표준약관 AI 주소가 설정되어 있지 않습니다. 관리자에게 받은 주소를 넣거나, 아래에서 규정 PDF로 진행하세요.",
        }

    try:
        _post(target, {"sentences": [PROBE_SENTENCE]}, key=api_key(),
              timeout_s=timeout_s or timeout(DEFAULT_TIMEOUT))
    except TermsAIError as exc:
        return {**base, "status": exc.status, "reason": exc.reason, "endpoint": target}

    if typed:
        RUNTIME["endpoint"] = typed
    return {
        **base,
        "ok": True,
        "status": "connected",
        "message": f"{LABEL} 연결을 확인했습니다.",
        "notice": "",
        "endpoint": target,
    }


# ---------------------------------------------------------------------------
# 조항 찾기
# ---------------------------------------------------------------------------

def match(text: str, *, endpoint_value: str | None = None, mask: bool = False,
          timeout_s: float | None = None) -> dict:
    """초안 문장을 사내 표준약관 AI로 보내 근거 후보를 받는다.

    실패는 TermsAIError(연결 없음/응답 없음/형식 오류)로 던진다 —
    화면은 그 자리에서 '다시 연결' 또는 '규정 PDF로 진행' 카드를 보여 준다.
    """
    typed, error = normalize_endpoint(endpoint_value or "")
    if error:
        raise TermsAIError("invalid_endpoint", error)
    target = typed or endpoint()
    if not target:
        raise TermsAIError(
            "not_configured",
            "사내 표준약관 AI 주소가 설정되어 있지 않습니다. 관리자에게 받은 주소를 넣거나, 규정 PDF 업로드로 진행하세요.",
        )

    masked_count = 0
    outgoing_text = text
    if mask:
        masked = masking.mask_text(text)
        outgoing_text = masked.text
        masked_count = masked.total

    sentences = split_sentences(outgoing_text)
    if not sentences:
        return _empty_result(target, masked=mask, masked_count=masked_count,
                             notice="초안에서 조항과 비교할 문장을 찾지 못했습니다.")

    payload = _post(target, {"sentences": sentences}, key=api_key(),
                    timeout_s=timeout_s or timeout())
    if typed:
        RUNTIME["endpoint"] = typed
    return normalize_response(payload, sentences, endpoint=target, masked=mask,
                              masked_count=masked_count)


def _empty_result(target: str, *, masked: bool, masked_count: int, notice: str = "") -> dict:
    result = {
        "ok": True,
        "source": "internal",
        "matches": [],
        "stats": {"sentences": 0, "matched": 0, "articles": 0},
        "articles": [],
        "disclaimer": DISCLAIMER,
        "regulation": _regulation_summary(target, 0),
        "ai": _ai_meta(target, masked, masked_count),
    }
    if notice:
        result["notices"] = [notice]
    return result


def _ai_meta(target: str, masked: bool, masked_count: int) -> dict:
    return {
        "source": "internal",
        "label": LABEL,
        "endpoint": target,
        "masked": masked,
        "masked_count": masked_count,
        "privacy": "사내망 안에서만 처리됩니다." if not masked else "개인정보를 가린 사본만 전송했습니다.",
    }


def _regulation_summary(target: str, article_count: int) -> dict:
    return {
        "id": "internal-terms",
        "name": LABEL,
        "filename": target,
        "source_url": target,
        "note": "사내 표준약관 AI가 돌려준 조항 후보입니다. 조문 번호·쪽수는 그 AI가 색인한 원문 기준입니다.",
        "version_label": "",
        "page_count": 0,
        "article_count": article_count,
        "unit_count": article_count,
        "structure": "internal",
        "uploaded": False,
        "warnings": [],
    }


def normalize_response(payload, sentences: list, *, endpoint: str = "",
                       masked: bool = False, masked_count: int = 0) -> dict:
    """사내 AI 응답(제각각)을 PDF 경로와 같은 모양으로 맞춘다."""
    raw_items = _unwrap(payload)
    matches = []
    for index, item in enumerate(raw_items):
        if not isinstance(item, dict):
            continue
        fallback = sentences[index] if index < len(sentences) else ""
        packed = _pack(item, fallback)
        if packed:
            matches.append(packed)

    articles = {}
    for item in matches:
        for candidate in [item["primary"]] + item["alternatives"]:
            key = candidate["article_no"] or candidate["location"] or ""
            if not key:
                continue
            entry = articles.setdefault(key, {
                "article_no": candidate["article_no"],
                "title": candidate["title"],
                "chapter": candidate["chapter"],
                "printed_page": candidate["printed_page"],
                "sentences": 0,
                "location": candidate["location"],
            })
            entry["sentences"] += 1

    result = {
        "ok": True,
        "source": "internal",
        "matches": matches,
        "stats": {"sentences": len(sentences), "matched": len(matches), "articles": len(articles)},
        "articles": sorted(articles.values(), key=lambda a: -a["sentences"]),
        "disclaimer": DISCLAIMER,
        "regulation": _regulation_summary(endpoint, len(articles)),
        "ai": _ai_meta(endpoint, masked, masked_count),
    }
    if not matches:
        result["notices"] = [
            "사내 표준약관 AI가 근거 후보를 돌려주지 않았습니다. 질문 범위를 좁히거나 규정 PDF 경로를 함께 써 보세요."
        ]
    return result


def _unwrap(payload):
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("matches", "results", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    data = payload.get("data")
    if isinstance(data, (dict, list)):
        return _unwrap(data)
    if payload.get("article_no") or payload.get("article") or payload.get("title"):
        return [payload]          # 문장 하나짜리 응답
    return []


def _first(item: dict, *keys, default=None):
    for key in keys:
        if key in item and item[key] not in (None, ""):
            return item[key]
    return default


def _pack(item: dict, fallback_sentence: str) -> dict | None:
    sentence = str(_first(item, "sentence", "text", "draft", "source_text", default=fallback_sentence) or "").strip()
    candidate = item.get("primary") if isinstance(item.get("primary"), dict) else item
    primary = _candidate(candidate)
    if not any([primary["article_no"], primary["title"], primary["excerpt"]]):
        return None
    alternatives = []
    for extra in _first(candidate, "alternatives", "others", "candidates", default=[]) or []:
        if isinstance(extra, dict):
            packed = _candidate(extra)
            if any([packed["article_no"], packed["title"], packed["excerpt"]]):
                alternatives.append(packed)
    return {
        "sentence": sentence,
        "primary": primary,
        "alternatives": alternatives,
        "confidence": primary["confidence"],
    }


def _candidate(item: dict) -> dict:
    article_no = str(_first(item, "article_no", "article-no", "article", "조문", "number", default="") or "").strip()
    title = str(_first(item, "article_title", "article-title", "title", "조문제목", default="") or "").strip()
    chapter = str(_first(item, "chapter", "장", default="") or "").strip()
    paragraph = str(_first(item, "paragraph", "항", default="") or "").strip()
    page = _first(item, "page", "printed_page", "printed-page", "page_no", "쪽", default="")
    text = str(_first(item, "text", "full_text", "body", default="") or "").strip()
    excerpt = str(_first(item, "excerpt", "snippet", "quote", "summary", default="") or text).strip()
    reason = str(_first(item, "reason", "why", "rationale", "note", default="") or "").strip()
    confidence = _confidence(_first(item, "confidence", "score", "reliability", default=""))
    terms = _first(item, "matched_terms", "terms", "keywords", default=[]) or []
    if isinstance(terms, str):
        terms = [term.strip() for term in terms.replace(",", " ").split() if term.strip()]
    location = str(_first(item, "location", "position", default="") or "").strip()
    if not location:
        head = f"{article_no} ({title})" if article_no and title else (article_no or title)
        parts = [part for part in (head, paragraph,
                                   f"{page}쪽" if page not in ("", None) else "", chapter) if part]
        location = " · ".join(parts)
    return {
        "article_no": article_no,
        "title": title,
        "chapter": chapter,
        "paragraph": paragraph,
        "printed_page": page,
        "location": location,
        "text": text,
        "excerpt": excerpt,
        "score": "",
        "confidence": confidence,
        "reason": reason,
        "matched_terms": [str(term) for term in terms],
        "matched_words": [],
        "kind": "internal",
    }


def _confidence(value) -> str:
    if value in (None, ""):
        return "낮음"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if number > 1:                 # 0~100 표기
            number = number / 100
        if number >= 0.75:
            return "높음"
        if number >= 0.4:
            return "중간"
        return "낮음"
    text = str(value).strip().lower()
    if text in VALID_CONFIDENCE:
        return text
    if text in ("high", "h", "strong", "확실"):
        return "높음"
    if text in ("medium", "mid", "moderate", "보통"):
        return "중간"
    return "낮음"
