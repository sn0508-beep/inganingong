"""4단계: 내보내기 문서 만들기.

결과물은 두 가지다.
1. 정리된 인수인계서 — 표준 12개 항목 순서로 초안 내용 + 질문에 대한 답변을 모아 놓은 문서
2. 아직 답하지 못한 질문 목록 — 후임자가 첫 주에 직접 확인해야 할 목록

초안 원문은 지워지지 않는다. 항목을 옮겨 담지 못한 문장은 '부록: 초안 원문'에 그대로 남겨,
자동 정리가 내용을 잃어버리는 사고를 막는다.
"""

from __future__ import annotations

import re
from datetime import datetime

from .checklist import DIMENSIONS
from .terms import DISCLAIMER as TERMS_DISCLAIMER


META_LINE_RE = re.compile(
    r"^-?\s*(인계자|인수자|소속|부서\s*/\s*직무|직무|작성일|인수인계\s*기간|파일명)\s*[:：]"
)


#: 초안의 제목(섹션)을 표준 항목으로 옮기는 힌트. 제목이 있으면 그 아래 문장은
#: 제목의 항목으로 보내는 것이 신호 추정보다 정확하다.
HEADING_HINTS = (
    ("인수인계 후", "support"), ("지원", "support"),
    ("검증", "verify"), ("확인 방법", "verify"), ("점검", "verify"),
    ("보고", "reporting"), ("승인", "reporting"), ("결재", "reporting"),
    ("예산", "budget"), ("정산", "budget"), ("계약", "budget"),
    ("문서", "documents"), ("자료", "documents"), ("파일", "documents"),
    ("현안", "pending"), ("미결", "pending"), ("진행", "pending"),
    ("규정", "rules"), ("약관", "rules"), ("법규", "rules"),
    ("시스템", "systems"), ("계정", "systems"), ("권한", "systems"),
    ("연락처", "contacts"), ("협력", "contacts"), ("유관", "contacts"),
    ("예외", "exception"), ("돌발", "exception"), ("민원", "exception"),
    ("정기", "routine"), ("일상", "routine"), ("반복", "routine"),
    ("업무 개요", "scope"), ("담당 업무", "scope"), ("개요", "scope"),
)


def _heading_dimension(line: str):
    heading = line.lstrip("#").strip()
    for needle, key in HEADING_HINTS:
        if needle in heading:
            return key
    return None


def _is_heading(line: str) -> bool:
    return bool(line.startswith("#")
                or re.match(r"^\d+[).]\s+\S", line)
                or re.match(r"^[□■○●▸▶]\s*\S", line))


def _dimension_of(line: str) -> tuple:
    """초안 한 줄이 어느 표준 항목에 속하는지 추정한다.

    (1) 항목별 신호 일치 개수, (2) 항목 이름에 쓰인 낱말이 줄에 있으면 가산 —
    '예산'이 든 줄은 예산 항목으로, '시스템'이 든 줄은 시스템 항목으로 보내기 위해서다.
    """
    best, best_score = "", 0
    for dim in DIMENSIONS:
        score = 0
        for signal in dim.signals:
            for pattern in signal.patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    score += 1
                    break
        for part in dim.label.split("·"):
            part = part.strip()
            if len(part) >= 2 and part in line:
                score += 2
        if score > best_score:
            best, best_score = dim.key, score
    if best_score:
        return best, best_score
    # 항목을 못 정했지만 업무 서술로 보이면 업무 개요로 보낸다.
    if re.search(r"(접수|처리|담당|관리|등록|회신|안내|작성|보고|검토)", line):
        return "scope", 1
    return "", 0


def build(meta: dict, draft: str, analysis: dict, terms: dict | None = None,
          image_note: str = "", image_count: int = 0) -> tuple:
    """(마크다운, 일반텍스트)를 돌려준다."""
    meta = meta or {}
    questions = analysis.get("questions", [])
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    assigned = {dim.key: [] for dim in DIMENSIONS}
    unassigned = []
    current = None
    for raw in (draft or "").split("\n"):
        line = raw.strip()
        if not line:
            continue
        if _is_heading(line):
            current = _heading_dimension(line)
            continue
        if line.upper().startswith("TODO") or META_LINE_RE.match(line):
            continue
        text = re.sub(r"^[-•·]\s*", "", line)
        if current:
            assigned[current].append(text)
            continue
        key, score = _dimension_of(text)
        if key and score > 0:
            assigned[key].append(text)
        else:
            unassigned.append(text)

    md = []
    md.append(f"# 인수인계서 — {meta.get('team') or '업무 인수인계'}")
    md.append("")
    md.append("| 항목 | 내용 |")
    md.append("| --- | --- |")
    for label, key in (("인계자", "author"), ("인수자", "successor"), ("부서·직무", "team"),
                       ("인수인계 기간", "period"), ("작성 기준", "base"), ("문서 생성", "generated")):
        value = meta.get(key) or ("(미정)" if key == "successor" else "")
        if key == "generated":
            value = f"{now} · 인수인계서 AI 프로토타입(가상 데모)"
        md.append(f"| {label} | {value} |")
    md.append("")

    summary = analysis.get("summary", {})
    md.append("## 문서 완성도 요약")
    md.append("")
    md.append(f"- 초안 기준 커버리지: **{int(summary.get('draft_score', 0) * 100)}%**")
    md.append(f"- 답변 반영 커버리지: **{int(summary.get('effective_score', 0) * 100)}%**")
    md.append(f"- 항목 점검(초안의 표현을 기준으로): 충실 {summary.get('covered', 0)}개 · 일부 {summary.get('partial', 0)}개 · 비어 있음 {summary.get('missing', 0)}개 (총 {summary.get('dimensions', 12)}개)")
    stats = analysis.get("stats", {})
    md.append(f"- 질문 {stats.get('total', 0)}개 중 답변 {stats.get('answered', 0)}개, 건너뜀 {stats.get('skipped', 0)}개, 미답변 {stats.get('unanswered', 0)}개")
    md.append("")

    image_note = (image_note or "").strip()
    if image_count or image_note:
        md.append("## 그림 속 내용 보완")
        md.append("")
        if image_count:
            md.append(f"- 문서에서 그림 {image_count}장이 감지되었습니다.")
        if image_note:
            md.append("- 그림 속 표기·글자는 자동으로 읽지 않았고, 인계자가 확인해 아래와 같이 적었습니다.")
            md.append("")
            md.append(image_note)
        else:
            md.append("- 그림 속 내용은 아직 보완되지 않았습니다. 후임자가 직접 확인해야 합니다.")
        md.append("")

    for index, dim in enumerate(DIMENSIONS, start=1):
        md.append(f"## {index}. {dim.label}")
        md.append("")
        if assigned.get(dim.key):
            for line in assigned[dim.key]:
                md.append(f"- {line}")
        else:
            md.append("- (초안에 해당 항목이 없습니다)")
        md.append("")

        answers = [q for q in questions if q.get("dimension") == dim.key and q.get("status") == "answered"]
        if answers:
            md.append("**추가 확인한 내용**")
            md.append("")
            for q in answers:
                md.append(f"- {q['question']}")
                md.append(f"  → {q['answer']}")
            md.append("")

        open_questions = [q for q in questions if q.get("dimension") == dim.key and q.get("status") == "unanswered"]
        if open_questions:
            md.append("**확인 필요**")
            md.append("")
            for q in open_questions:
                md.append(f"- {q['question']}")
            md.append("")

    pending = [q for q in questions if q.get("status") == "unanswered"]
    md.append("## 아직 답하지 못한 질문 목록")
    md.append("")
    if pending:
        md.append("후임자가 첫 주에 직접 확인해야 할 항목입니다.")
        md.append("")
        md.append("| # | 항목 | 질문 | 왜 필요한가 |")
        md.append("| --- | --- | --- | --- |")
        for number, q in enumerate(pending, start=1):
            why = (q.get("why") or "").replace("|", "/")
            question = (q.get("question") or "").replace("|", "/")
            md.append(f"| {number} | {q.get('dimension_label', '')} | {question} | {why} |")
    else:
        md.append("없습니다. 모든 질문에 답변이 등록되었습니다.")
    md.append("")

    if terms and terms.get("matches"):
        md.append("## 검토한 근거 규정")
        md.append("")
        reg = terms.get("regulation", {})
        md.append(f"- 규정: {reg.get('name', '')} {('(' + reg.get('version_label', '') + ')') if reg.get('version_label') else ''}")
        if reg.get("source_url"):
            md.append(f"- 출처: {reg.get('source_url')}")
        md.append("")
        md.append("| 인수인계 문장 | 근거 후보 조문 | 위치 | 신뢰도 |")
        md.append("| --- | --- | --- | --- |")
        for item in terms["matches"]:
            primary = item["primary"]
            md.append(
                f"| {item['sentence'].replace('|', '/')} | {primary['article_no']} {primary['title']} "
                f"| {primary['printed_page']}쪽 | {primary['confidence']} |"
            )
        md.append("")
        md.append(f"> {TERMS_DISCLAIMER}")
        md.append("")

    if unassigned:
        md.append("## 부록 A. 초안 원문 중 항목을 정하지 못한 문장")
        md.append("")
        for line in unassigned:
            md.append(f"- {line}")
        md.append("")

    md.append("## 부록 B. 초안 원문 (가공 없이 보존)")
    md.append("")
    md.append("```")
    md.append(draft.strip())
    md.append("```")
    md.append("")
    md.append("---")
    md.append(f"생성: {now} · 인수인계서 AI 프로토타입 (공개 자료·가상 데이터로만 작성)")

    markdown = "\n".join(md)
    return markdown, to_plain(markdown)


def to_plain(markdown: str) -> str:
    out = []
    for line in markdown.split("\n"):
        if line.startswith("```"):
            continue
        if line.startswith("#"):
            text = line.lstrip("#").strip()
            out.append(text)
            out.append("-" * min(len(text), 40))
            continue
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if set("".join(cells)) <= set("-"):
                continue
            out.append("  ".join(cells))
            continue
        out.append(line.replace("**", "").replace("> ", ""))
    return "\n".join(out).strip() + "\n"


def filename(meta: dict) -> str:
    team = (meta or {}).get("team") or "인수인계서"
    safe = re.sub(r"[^0-9A-Za-z가-힣]+", "_", team).strip("_") or "인수인계서"
    return f"{safe}_인수인계서_{datetime.now().strftime('%Y%m%d')}"
