"""개인정보 마스킹.

LLM(외부 API)으로 글을 보내기 전에 전화번호·이메일·주민등록번호 같은 값을 가린다.
- 마스킹은 '보내는 사본'에만 적용하고, 원문은 화면 표시·내보내기에 그대로 쓴다.
- 데모(오프라인) 모드에서는 외부로 나가는 데이터가 없다는 사실을 화면에 함께 표시한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: 순서가 중요하다. 주민번호·카드·사업자번호를 전화/계좌보다 먼저 처리해야
#: 6-7자리 숫자 덩어리가 전화번호로 잘못 잡히지 않는다.
PATTERNS = (
    ("rrn", "주민등록번호", re.compile(r"\b\d{6}\s*[-–]\s*\d{7}\b")),
    ("card", "카드번호", re.compile(r"\b(?:\d{4}[-\s]){3}\d{4}\b")),
    ("bizno", "사업자등록번호", re.compile(r"\b\d{3}-\d{2}-\d{5}\b")),
    ("email", "이메일", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("mobile", "휴대전화", re.compile(r"\b01[016789][-.\s]?\d{3,4}[-.\s]?\d{4}\b")),
    ("tel", "일반전화", re.compile(r"\b0\d{1,2}[-.\s]\d{3,4}[-.\s]\d{4}\b")),
    ("account", "계좌번호", re.compile(r"\b\d{2,6}-\d{2,6}-\d{4,8}\b")),
)

PLACEHOLDER = "[{label}]"


@dataclass
class MaskFinding:
    key: str
    label: str
    count: int
    contexts: list = field(default_factory=list)

    def to_dict(self):
        return {"key": self.key, "label": self.label, "count": self.count,
                "contexts": self.contexts}


@dataclass
class MaskResult:
    text: str
    findings: list
    total: int

    def to_dict(self):
        return {
            "text": self.text,
            "findings": [f.to_dict() for f in self.findings],
            "total": self.total,
            "types": [f.label for f in self.findings],
        }


def _context(text: str, start: int, end: int, width: int = 22) -> str:
    left = text[max(0, start - width):start].replace("\n", " ")
    right = text[end:end + width].replace("\n", " ")
    return f"…{left}{PLACEHOLDER.format(label='가림')}{right}…".strip()


def mask_text(text: str) -> MaskResult:
    findings = []
    masked = text
    for key, label, pattern in PATTERNS:
        count = 0
        contexts = []

        def repl(match, label=label, contexts_ref=contexts):
            nonlocal count
            count += 1
            if len(contexts_ref) < 3:
                contexts_ref.append(_context(mask_source, match.start(), match.end()))
            return PLACEHOLDER.format(label=label)

        mask_source = masked
        masked = pattern.sub(repl, masked)
        if count:
            findings.append(MaskFinding(key=key, label=label, count=count, contexts=contexts))
    return MaskResult(text=masked, findings=findings, total=sum(f.count for f in findings))


def mask_report(result: MaskResult) -> dict:
    """화면에 보여 줄 요약. 원문 값 자체는 담지 않는다."""
    return {
        "total": result.total,
        "findings": [f.to_dict() for f in result.findings],
        "summary": ", ".join(f"{f.label} {f.count}건" for f in result.findings) or "가린 항목 없음",
    }
