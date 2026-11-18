"""2단계: 빈틈 점검과 후임자 관점 꼬리질문 생성.

동작 방식(규칙 기반, LLM 없이도 완전 동작)
1. 초안에서 제목·TODO 같은 뼈대 줄을 걷어내고 실제 내용만 남긴다.
2. 항목별 '신호'를 찾아 그 항목이 어디까지 채워졌는지 비율로 계산한다(0이면 비어 있음).
3. 비어 있거나 덜 채워진 신호마다 그 신호를 정확히 겨냥한 질문을 만든다.
   '예외 상황이 없습니다'가 아니라 '민원이 반복될 때 어디서 판단이 갈리는지'를 묻는다.
4. '상황에 따라', '담당자에게 문의' 같은 모호 표현은 그 문장을 인용해 되묻는다.
5. 답변한 질문은 그 신호를 채운 것으로 다시 계산해 '초안 대비 → 답변 반영' 커버리지를 보여 준다.
"""

from __future__ import annotations

import re

from .checklist import DIMENSIONS, DIMENSION_MAP, VAGUE_PATTERNS
from .llm import LLMClient

MAX_RULE_QUESTIONS = 16


#: 머리말/서식 줄 (인계자·인수자·작성일 등) — 내용 점검 대상이 아니다.
META_LINE_RE = re.compile(
    r"^-?\s*(인계자|인수자|소속|부서\s*/\s*직무|직무|작성일|인수인계\s*기간|파일명)\s*[:：]"
)


def _content_lines(text: str) -> list:
    """제목(#)·TODO·(작성…) 같은 뼈대 줄과 머리말을 제외한 실제 내용 줄."""
    lines = []
    for raw in (text or "").split("\n"):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.upper().startswith("TODO") or re.match(r"^\(작성", line):
            continue
        if META_LINE_RE.match(line):
            continue
        lines.append(line)
    return lines


def _sentences(lines: list) -> list:
    out = []
    for line in lines:
        for piece in re.split(r"(?<=[.다요음])\s+", line):
            piece = piece.strip(" -•·\t")
            if len(piece) >= 6:
                out.append(piece)
    return out


def _find_signal(text: str, patterns) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(0)
    return ""


def _signal_evidence(lines: list, patterns) -> str:
    for line in lines:
        if _find_signal(line, patterns):
            return line[:160]
    return ""


def _normalize_answers(answers: dict | None) -> dict:
    result = {}
    for key, value in (answers or {}).items():
        if isinstance(value, dict):
            text = (value.get("text") or "").strip()
            skipped = bool(value.get("skipped"))
        else:
            text = str(value or "").strip()
            skipped = False
        if text or skipped:
            result[key] = {"text": text, "skipped": skipped}
    return result


def assess(draft: str, answers: dict | None = None) -> dict:
    lines = _content_lines(draft)
    body = "\n".join(lines)
    answered = _normalize_answers(answers)

    coverage = []
    questions = []

    for dim in DIMENSIONS:
        hits, missing = [], []
        for signal in dim.signals:
            matched = [line for line in lines if _find_signal(line, signal.patterns)]
            strong = [line for line in matched if not _is_vague(line)]
            if strong:
                hits.append(signal)
            else:
                # '담당자에게 문의'처럼 모호한 문장만 있는 경우는 채워진 것으로 치지 않는다.
                missing.append(signal)

        total_weight = sum(s.weight for s in dim.signals) or 1
        hit_weight = sum(s.weight for s in hits)
        draft_ratio = round(hit_weight / total_weight, 2)

        # 답변으로 채워진 신호
        effective_hits = list(hits)
        for signal in missing:
            qid = f"{dim.key}::{signal.key}"
            answer = answered.get(qid)
            if answer and answer["text"]:
                effective_hits.append(signal)

        # 항목 전체를 묻는 질문(base)에 답했다면, 그 항목의 대표 신호 2개가 채워진 것으로 본다.
        # (한 문단으로 답한 내용을 신호 단위로 쪼개 확인할 수 없기 때문)
        base_answer = answered.get(f"{dim.key}::base")
        if base_answer and base_answer["text"]:
            for signal in missing[:2]:
                if signal not in effective_hits:
                    effective_hits.append(signal)
        effective_ratio = round(sum(s.weight for s in effective_hits) / total_weight, 2)

        status = "missing" if not hits else ("covered" if draft_ratio >= 0.6 else "partial")
        coverage.append({
            "key": dim.key,
            "label": dim.label,
            "summary": dim.summary,
            "status": status,
            "draft_ratio": draft_ratio,
            "effective_ratio": effective_ratio,
            "hits": [{"key": s.key, "label": s.label} for s in hits],
            "missing": [{"key": s.key, "label": s.label} for s in missing],
            "guide": dim.guide,
            "misses": list(dim.misses),
            "example": dim.example,
        })

        # 질문 생성: 항목이 통째로 비면 1개, 일부만 차 있으면 빈 신호를 최대 2개까지
        if not hits:
            questions.append({
                "id": f"{dim.key}::base",
                "dimension": dim.key,
                "dimension_label": dim.label,
                "question": dim.base_question,
                "why": dim.why,
                "priority": "high",
                "evidence": "",
                "hint": dim.example,
                "source": "rule",
            })
        else:
            for signal in missing[:2]:
                questions.append({
                    "id": f"{dim.key}::{signal.key}",
                    "dimension": dim.key,
                    "dimension_label": dim.label,
                    "question": dim.signal_questions.get(signal.key, dim.base_question),
                    "why": dim.why,
                    "priority": "high" if draft_ratio < 0.5 else "normal",
                    "evidence": _signal_evidence(lines, signal.patterns) or "",
                    "hint": dim.example,
                    "source": "rule",
                    "signal": signal.label,
                })

    # 모호 표현 되묻기
    vague = []
    for idx, (pattern, reason) in enumerate(VAGUE_PATTERNS):
        for occ, match in enumerate(re.finditer(pattern, body, re.IGNORECASE)):
            if occ >= 2:
                break
            sentence = _sentence_around(body, match.start())
            if not sentence:
                continue
            dim_key = _guess_dimension(sentence)
            vague.append({
                "id": f"vague::{idx}::{occ}",
                "dimension": dim_key,
                "dimension_label": DIMENSION_MAP[dim_key].label,
                "question": _vague_question(match.group(0), sentence),
                "why": f"'{match.group(0)}'라고만 적혀 있어 후임자가 판단할 수 없습니다({reason}).",
                "priority": "high" if "문의" in match.group(0) or "참고" in match.group(0) else "normal",
                "evidence": sentence[:160],
                "hint": "",
                "source": "vague",
                "signal": "모호 표현",
            })
    # 같은 항목에 모호 표현 질문이 여러 개 붙지 않도록 항목별 1개만 남긴다.
    seen_dims, picked = set(), []
    for item in vague:
        if item["dimension"] in seen_dims:
            continue
        seen_dims.add(item["dimension"])
        picked.append(item)
    questions.extend(picked[:4])

    # 정렬: 우선순위 → 항목 순서
    order = {d.key: i for i, d in enumerate(DIMENSIONS)}
    questions.sort(key=lambda q: (0 if q["priority"] == "high" else 1, order.get(q["dimension"], 99)))
    questions = questions[:MAX_RULE_QUESTIONS]

    for question in questions:
        answer = answered.get(question["id"])
        question["answer"] = answer["text"] if answer else ""
        question["skipped"] = bool(answer and answer["skipped"])
        question["status"] = ("answered" if answer and answer["text"]
                              else "skipped" if question["skipped"] else "unanswered")

    stats = {
        "total": len(questions),
        "answered": sum(1 for q in questions if q["status"] == "answered"),
        "skipped": sum(1 for q in questions if q["status"] == "skipped"),
        "unanswered": sum(1 for q in questions if q["status"] == "unanswered"),
    }

    draft_score = round(sum(c["draft_ratio"] for c in coverage) / len(coverage), 2)
    effective_score = round(sum(c["effective_ratio"] for c in coverage) / len(coverage), 2)

    return {
        "coverage": coverage,
        "questions": questions,
        "vague": vague,
        "stats": stats,
        "summary": {
            "dimensions": len(coverage),
            "covered": sum(1 for c in coverage if c["status"] == "covered"),
            "partial": sum(1 for c in coverage if c["status"] == "partial"),
            "missing": sum(1 for c in coverage if c["status"] == "missing"),
            "draft_score": draft_score,
            "effective_score": effective_score,
        },
    }


def _is_vague(line: str) -> bool:
    return any(re.search(pattern, line, re.IGNORECASE) for pattern, _reason in VAGUE_PATTERNS)


def _sentence_around(text: str, index: int) -> str:
    start = max(text.rfind("\n", 0, index) + 1, 0)
    end = text.find("\n", index)
    if end == -1:
        end = len(text)
    return text[start:end].strip()[:200]


#: 모호한 문장을 어느 항목으로 되물을지 정할 때 쓰는 힌트
GUESS_HINTS = (
    (r"진행|현안|미결|계류", "pending"),
    (r"폴더|드라이브|경로|최신|버전", "documents"),
    (r"권한|시스템|계정|비밀번호", "systems"),
    (r"예산|계약|정산|지급", "budget"),
    (r"연락처|전화|메일|문의", "contacts"),
    (r"규정|약관|조항|법령", "rules"),
)


def _guess_dimension(sentence: str) -> str:
    best, best_score = "exception", 0
    for dim in DIMENSIONS:
        score = sum(1 for signal in dim.signals if _find_signal(sentence, signal.patterns))
        if score > best_score:
            best, best_score = dim.key, score
    for pattern, key in GUESS_HINTS:
        if re.search(pattern, sentence) and DIMENSION_MAP.get(key):
            return key
    return best


def _vague_question(phrase: str, sentence: str) -> str:
    short = sentence if len(sentence) <= 60 else sentence[:57] + "…"
    if "문의" in phrase or "참고" in phrase:
        return f"“{short}”라고 적혀 있는데, 그 정보를 문서 안에 옮겨 적을 수 있을까요? 후임자가 바로 쓸 수 있어야 합니다."
    if "상황" in phrase or "경우" in phrase or "따라" in phrase:
        return f"“{short}”에서 '상황'이 구체적으로 무엇을 말하는지, 어떤 조건일 때 그렇게 하는지 알려 주세요."
    if "추후" in phrase or "미정" in phrase or "확인" in phrase:
        return f"“{short}” — 아직 정해지지 않은 부분은 언제, 누가 정하는지와 그때까지 어떻게 처리하는지 알려 주세요."
    if "대부분" in phrase or "보통" in phrase:
        return f"“{short}”에서 '예외'에 해당하는 경우는 어떤 경우인지 알려 주세요."
    return f"“{short}” 부분을 조금 더 구체적으로 알려 주세요. 후임자가 같은 판단을 할 수 있을 만큼요."


def analyze(draft: str, answers: dict | None = None, llm: LLMClient | None = None,
            masked_text: str | None = None) -> dict:
    """규칙 기반 결과 + (가능하면) LLM이 더한 질문을 합쳐 돌려준다."""
    result = assess(draft, answers)
    llm_client = llm or LLMClient()
    llm_note, added = None, []

    if not llm_client.is_demo and llm_client.available:
        existing = [{"question": q["question"]} for q in result["questions"]]
        covered = [c["label"] for c in result["coverage"] if c["status"] == "covered"]
        added, llm_note = llm_client.extra_questions(masked_text or draft, covered, existing)
        seen = {q["question"].strip() for q in result["questions"]}
        for item in added:
            if item["question"] in seen:
                continue
            dim_key = item["dimension"] if item["dimension"] in DIMENSION_MAP else _guess_dimension(item["question"])
            result["questions"].append({
                "id": f"llm::{len(result['questions'])}",
                "dimension": dim_key,
                "dimension_label": DIMENSION_MAP[dim_key].label,
                "question": item["question"],
                "why": item["why"],
                "priority": "normal",
                "evidence": item["evidence"],
                "hint": "",
                "source": "llm",
                "answer": "",
                "skipped": False,
                "status": "unanswered",
            })
            seen.add(item["question"])

    result["llm"] = {
        **llm_client.describe(),
        "added": len(added),
        "note": llm_note,
    }
    return result


def unanswered(result: dict) -> list:
    return [q for q in result.get("questions", []) if q.get("status") == "unanswered"]
