"""AI 연결 모드와 연결 확인.

화면 1단계에서 "이 환경에서 AI를 어디까지 쓸지"를 네 가지 중 하나로 고른다.
모드는 (1) 무엇을 읽을 수 있는지(그림 포함 여부), (2) 어디로 나가는지(사내망/외부/없음),
(3) 어떤 주소가 설정되어 있어야 하는지를 함께 들고 있다.

연결 확인
- `offline_rules`는 확인할 대상이 없다(항상 준비됨). 핵심 점검은 규칙 기반으로 돌아간다.
- `internal_*`는 `INTERNAL_AI_BASE_URL`(또는 화면에서 입력한 주소)로 상태를 확인한다.
- `external_masked`는 `LLM_PROVIDER`(openai|ollama) 설정을 그대로 쓴다.
설정이 없거나 응답이 없으면 `연동할 수 있는 AI를 찾지 못하였어요`와 이유를 돌려주고,
화면은 그 자리에서 세 가지 대안(다시 연결 · 외부 AI · AI 없이 계속)을 보여 준다.

화면에서 확인에 성공한 주소는 메모리에만 기억한다(업로드한 규정과 같은 방식, 재시작하면 사라짐).
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request
from urllib.parse import urlparse

from .llm import config_from_env

UNAVAILABLE_NOTICE = "연동할 수 있는 AI를 찾지 못하였어요."
DEFAULT_TIMEOUT = 1.5

#: 연결 확인에 성공한 주소(모드키 -> 주소). 프로토타입이라 메모리에만 둔다.
RUNTIME_ENDPOINTS: dict = {}

MODES = (
    {
        "key": "internal_multimodal",
        "name": "사내 AI",
        "capability": "텍스트+그림",
        "label": "사내 AI (텍스트+그림)",
        "summary": "사내 AI가 글자와 그림을 함께 읽고 질문을 더합니다.",
        "privacy": "입력한 내용은 사내망 안에서만 처리됩니다.",
        "reads_images": True,
        "external": False,
        "needs": "internal",
        "retry_label": "사내 AI 다시 연결하기",
    },
    {
        "key": "internal_text",
        "name": "사내 AI",
        "capability": "텍스트만",
        "label": "사내 AI (텍스트만)",
        "summary": "사내 AI에 글자만 보냅니다. 그림은 직접 보완합니다.",
        "privacy": "입력한 내용은 사내망 안에서만 처리됩니다.",
        "reads_images": False,
        "external": False,
        "needs": "internal",
        "retry_label": "사내 AI 다시 연결하기",
    },
    {
        "key": "external_masked",
        "name": "외부 AI 연동",
        "capability": "민감정보 가림",
        "label": "외부 AI 연동 (민감정보 가림)",
        "summary": "개인정보를 가린 사본만 외부 AI로 보냅니다.",
        "privacy": "개인정보를 가린 사본만 외부로 전송됩니다. 원문은 화면과 내보내기에 그대로 남습니다.",
        "reads_images": True,
        "external": True,
        "needs": "external",
        "retry_label": "외부 AI 다시 연결하기",
    },
    {
        "key": "offline_rules",
        "name": "AI 미연결",
        "capability": "기본 규칙 점검",
        "label": "AI 미연결 (기본 규칙 점검)",
        "summary": "AI 없이 규칙 기반 점검만 합니다.",
        "privacy": "입력한 내용은 외부로 전송되지 않습니다.",
        "reads_images": False,
        "external": False,
        "needs": "none",
        "retry_label": "",
    },
)

MODE_MAP = {mode["key"]: mode for mode in MODES}
INTERNAL_KEYS = ("internal_multimodal", "internal_text")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def mode_list() -> list:
    """화면이 그대로 그릴 수 있는 모드 목록."""
    return [dict(mode) for mode in MODES]


def get(key: str) -> dict | None:
    return MODE_MAP.get(key)


def default_key() -> str:
    """설정된 환경에 맞는 기본 모드. 설정이 없으면 AI 미연결(규칙 점검)로 시작한다."""
    if _env("INTERNAL_AI_BASE_URL"):
        return "internal_text"
    if config_from_env()["provider"] != "demo":
        return "external_masked"
    return "offline_rules"


def endpoint_for(key: str) -> str:
    if key in RUNTIME_ENDPOINTS:
        return RUNTIME_ENDPOINTS[key]
    if key in INTERNAL_KEYS:
        return _env("INTERNAL_AI_BASE_URL").rstrip("/")
    return config_from_env()["base_url"].rstrip("/")


def config_for(key: str) -> dict:
    """모드에 맞는 LLM 클라이언트 설정. 연결이 없으면 demo(규칙 기반)로 떨어진다."""
    mode = MODE_MAP.get(key)
    if mode is None or mode["needs"] == "none":
        return {"provider": "demo", "base_url": "", "model": "", "api_key": "", "timeout": 30}

    if key in INTERNAL_KEYS:
        base_url = endpoint_for(key)
        config = {
            "provider": "openai",            # 사내 AI도 OpenAI 호환 /chat/completions 규격을 가정
            "base_url": base_url,
            "model": _env("INTERNAL_AI_MODEL", "internal-llm"),
            "api_key": _env("INTERNAL_AI_API_KEY"),
            "allow_no_key": True,
            "timeout": int(_env("INTERNAL_AI_TIMEOUT", "30") or 30),
        }
        if not base_url:
            config["provider"] = "demo"      # 주소가 없으면 호출하지 않는다
        return config

    config = config_from_env()
    if key in RUNTIME_ENDPOINTS:
        config["base_url"] = RUNTIME_ENDPOINTS[key]
    return config


def describe(key: str) -> dict:
    mode = MODE_MAP.get(key) or MODE_MAP["offline_rules"]
    config = config_for(mode["key"])
    return {
        "mode": mode["key"],
        "label": mode["label"],
        "reads_images": mode["reads_images"],
        "external": mode["external"],
        "privacy": mode["privacy"],
        "configured": config.get("provider") != "demo",
        "endpoint": endpoint_for(mode["key"]) if mode["needs"] != "none" else "",
    }


def _normalize_endpoint(value: str) -> tuple:
    text = (value or "").strip()
    if not text:
        return "", ""
    if "://" not in text:
        text = "http://" + text
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return "", "주소는 http:// 또는 https://로 시작하는 형식이어야 합니다."
    return text.rstrip("/"), ""


def _probe(base_url: str, api_key: str = "", provider: str = "openai",
           timeout: float = DEFAULT_TIMEOUT) -> tuple:
    """(연결됨, 이유) — 상태 확인용 GET 한 번. 404는 서버가 응답한 것으로 본다."""
    path = "/api/tags" if provider == "ollama" else "/models"
    url = base_url.rstrip("/") + path
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read(256)
        return True, ""
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return False, "주소는 응답하지만 인증에 실패했습니다(키를 확인해 주세요)."
        if exc.code == 404:
            return True, ""
        return False, f"AI 서버가 오류를 돌려주었습니다(HTTP {exc.code})."
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        detail = getattr(exc, "reason", exc)
        return False, f"{urlparse(base_url).netloc or base_url}에서 응답이 없습니다. 주소와 방화벽을 확인해 주세요. ({detail})"


def check(key: str, endpoint: str | None = None, timeout: float | None = None) -> dict:
    """모드의 연결 상태를 확인한다. 어떤 경우에도 예외를 던지지 않는다."""
    mode = MODE_MAP.get(key)
    base = {
        "mode": key,
        "ok": False,
        "status": "unknown",
        "notice": UNAVAILABLE_NOTICE,
        "message": UNAVAILABLE_NOTICE,
        "reason": "",
        "reads_images": False,
        "retry_label": "",
        "endpoint": "",
    }
    if mode is None:
        return {**base, "reason": "알 수 없는 연결 모드입니다."}

    base.update({
        "label": mode["label"],
        "reads_images": mode["reads_images"],
        "retry_label": mode["retry_label"],
    })

    if mode["needs"] == "none":
        return {**base, "ok": True, "status": "ready",
                "message": "AI 없이 기본 규칙 점검으로 진행합니다."}

    typed, error = _normalize_endpoint(endpoint or "")
    if error:
        return {**base, "status": "invalid_endpoint", "reason": error}

    config = config_for(key)

    if mode["needs"] == "internal":
        target = typed or config.get("base_url", "")
        if not target:
            return {**base, "status": "not_configured",
                    "reason": "사내 AI 주소가 설정되어 있지 않습니다. 관리자에게 받은 주소를 넣고 연결을 확인해 보세요."}
    else:
        provider = config.get("provider", "demo")
        if provider == "demo":
            return {**base, "status": "not_configured",
                    "reason": "이 환경에는 외부 AI 주소나 키가 설정되어 있지 않습니다. 계속하려면 'AI 없이 기본 점검'을 눌러 주세요."}
        if provider == "openai" and not config.get("api_key"):
            return {**base, "status": "not_configured",
                    "reason": "외부 AI 키가 설정되어 있지 않습니다. 키를 넣은 뒤 다시 연결해 주세요."}
        target = typed or config.get("base_url", "")

    ok, detail = _probe(target, api_key=config.get("api_key", ""),
                        provider=config.get("provider", "openai"),
                        timeout=timeout or DEFAULT_TIMEOUT)
    if ok:
        if typed:
            RUNTIME_ENDPOINTS[key] = typed
        return {**base, "ok": True, "status": "connected", "endpoint": target,
                "message": f"{mode['label']} 연결을 확인했습니다."}

    return {**base, "status": "unreachable", "endpoint": target, "reason": detail}
