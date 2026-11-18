"""LLM 어댑터.

세 가지 모드를 같은 인터페이스로 쓴다.
- demo   : 외부 호출 없이 규칙 기반으로만 동작 (API 키 없이 바로 시연 가능)
- openai : OpenAI 호환 /chat/completions 엔드포인트 (OpenAI, Azure 게이트웨이, vLLM 등)
- ollama : 로컬 Ollama /api/chat (사내망·온프레미스 시연용)

설계 원칙
- 이 앱의 핵심 판단(빈틈 탐지, 약관 조항 매칭)은 LLM 없이도 동작해야 한다.
  LLM은 '질문을 더 자연스럽게 늘리는' 보조로만 쓰고, 실패하면 조용히 규칙 결과만 낸다.
- 외부로 나가는 본문은 항상 마스킹된 사본이다(호출부에서 보장).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

DEFAULT_TIMEOUT = 30


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def config_from_env() -> dict:
    provider = (_env("LLM_PROVIDER", "demo") or "demo").lower()
    if provider in ("", "none", "offline"):
        provider = "demo"
    if provider in ("openai_compatible", "openai-compatible", "api"):
        provider = "openai"
    return {
        "provider": provider,
        "base_url": _env("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        "model": _env("LLM_MODEL", "gpt-4o-mini"),
        "api_key": _env("LLM_API_KEY", ""),
        "timeout": int(_env("LLM_TIMEOUT", str(DEFAULT_TIMEOUT)) or DEFAULT_TIMEOUT),
    }


class LLMClient:
    def __init__(self, config: dict | None = None):
        self.config = config or config_from_env()

    # -- 상태 -------------------------------------------------------------
    @property
    def provider(self) -> str:
        return self.config.get("provider", "demo")

    @property
    def is_demo(self) -> bool:
        return self.provider == "demo"

    @property
    def available(self) -> bool:
        if self.is_demo:
            return False
        if self.provider == "openai":
            return bool(self.config.get("api_key"))
        return True  # ollama: 로컬 서버가 떠 있는지는 호출해 봐야 안다

    def describe(self) -> dict:
        if self.is_demo:
            return {"provider": "demo", "label": "데모(오프라인) 모드",
                    "detail": "외부 전송 없음 · 규칙 기반 질문 생성",
                    "available": True}
        label = "OpenAI 호환 API" if self.provider == "openai" else "Ollama(로컬)"
        detail = f"{self.config.get('model')} @ {self.config.get('base_url')}"
        return {"provider": self.provider, "label": label, "detail": detail,
                "available": self.available}

    # -- 호출 -------------------------------------------------------------
    def _chat(self, system: str, user: str) -> str:
        if self.provider == "openai":
            url = f"{self.config['base_url']}/chat/completions"
            body = {
                "model": self.config["model"],
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            }
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.get('api_key', '')}",
            }
        elif self.provider == "ollama":
            url = f"{self.config['base_url']}/api/chat"
            body = {
                "model": self.config["model"],
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.2},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            }
            headers = {"Content-Type": "application/json"}
        else:
            raise RuntimeError("데모 모드에서는 LLM을 호출하지 않습니다.")

        request = urllib.request.Request(
            url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST"
        )
        with urllib.request.urlopen(request, timeout=self.config.get("timeout", DEFAULT_TIMEOUT)) as resp:
            payload = json.loads(resp.read().decode("utf-8"))

        if self.provider == "openai":
            return payload["choices"][0]["message"]["content"]
        return payload["message"]["content"]

    def extra_questions(self, masked_draft: str, covered: list, existing: list) -> tuple:
        """후임자 관점 질문을 더 만들어 (질문목록, 경고)로 돌려준다."""
        if not self.available:
            return [], None

        system = (
            "너는 공기업 인수인계서를 검토하는 후임자다. 주어진 초안에서 '후임자가 실제로 업무를 "
            "수행할 때 막힐 지점'을 찾아 날카로운 꼬리질문을 만든다. "
            "이미 만들어진 질문과 겹치지 않게, 초안 문장을 직접 인용하며 질문한다. "
            "반드시 JSON만 출력한다: {\"questions\": [{\"dimension\": \"항목키\", "
            "\"question\": \"질문\", \"why\": \"왜 필요한지 한 문장\", \"evidence\": \"초안 인용\"}]}. "
            "질문은 최대 5개, 한국어 존댓말, 각 질문은 한 문장."
        )
        user = json.dumps(
            {
                "항목키": ["scope", "routine", "exception", "contacts", "systems", "rules",
                         "pending", "documents", "budget", "reporting", "verify", "support"],
                "이미_다룬_항목": covered,
                "이미_만든_질문": [q["question"] for q in existing],
                "초안": masked_draft[:6000],
            },
            ensure_ascii=False,
        )
        try:
            raw = self._chat(system, user)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, KeyError, ValueError) as exc:
            return [], f"LLM 호출에 실패해 규칙 기반 질문만 표시합니다 ({type(exc).__name__}: {exc})"

        questions = []
        try:
            data = json.loads(raw)
            for item in (data.get("questions") or [])[:5]:
                text = str(item.get("question", "")).strip()
                if not text:
                    continue
                questions.append({
                    "dimension": str(item.get("dimension", "")).strip() or "exception",
                    "question": text,
                    "why": str(item.get("why", "")).strip() or "후임자가 같은 지점에서 막힐 수 있습니다.",
                    "evidence": str(item.get("evidence", "")).strip(),
                    "source": "llm",
                })
        except (json.JSONDecodeError, AttributeError, TypeError):
            return [], "LLM 응답을 해석하지 못해 규칙 기반 질문만 표시합니다."
        return questions, None
