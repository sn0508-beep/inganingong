"""2단계(빈틈 점검)·가림·내보내기 테스트."""

from __future__ import annotations

from app import export, gap, masking
from app.content import SAMPLE_DRAFT, TEMPLATE_TEXT


def test_masking_finds_korean_pii():
    text = (
        "팀장 박서준 010-1234-5678, 메일 haneul.kim@example.com, "
        "주민번호 900101-1234567, 사업자 123-45-67890, 계좌 110-123-456789"
    )
    result = masking.mask_text(text)
    labels = {finding.label for finding in result.findings}
    assert {"휴대전화", "이메일", "주민등록번호", "사업자등록번호", "계좌번호"} <= labels
    assert "010-1234-5678" not in result.text
    assert "[휴대전화]" in result.text
    assert "haneul.kim@example.com" not in result.text
    # 원문은 건드리지 않는다
    assert "010-1234-5678" in text


def test_masking_report_has_no_raw_values():
    result = masking.mask_text("연락처 010-9876-5432")
    report = masking.mask_report(result)
    assert "010-9876-5432" not in str(report)
    assert report["total"] == 1


def test_sample_draft_has_gaps():
    analysis = gap.assess(SAMPLE_DRAFT)
    summary = analysis["summary"]
    assert summary["dimensions"] == 12
    assert summary["missing"] >= 1, "샘플은 일부러 빈틈을 남긴 문서다"
    assert summary["draft_score"] < 0.75
    assert analysis["stats"]["total"] >= 10


def test_questions_name_the_missing_signal():
    analysis = gap.assess(SAMPLE_DRAFT)
    questions = [q["question"] for q in analysis["questions"]]
    joined = " ".join(questions)
    assert "마감일" in joined or "마감" in joined
    assert any(q["dimension"] == "exception" for q in analysis["questions"])


def test_vague_expression_is_questioned():
    analysis = gap.assess("## 연락처\n- 자세한 연락처는 팀 공유 폴더 참고\n")
    questions = " ".join(q["question"] for q in analysis["questions"])
    assert "공유 폴더" in questions or "문서 안에" in questions


def test_vague_only_line_does_not_count_as_covered():
    vague = "## 진행 중 현안\n- 진행 중인 건은 담당자에게 문의\n"
    analysis = gap.assess(vague)
    pending = next(c for c in analysis["coverage"] if c["key"] == "pending")
    assert pending["status"] != "covered"


def test_answers_raise_effective_coverage():
    base = gap.assess(SAMPLE_DRAFT)
    question = next(q for q in base["questions"] if q["dimension"] == "verify")
    answers = {question["id"]: {"text": "CIS 처리내역과 접수대장을 대조하고, 오류는 당일 정정 요청합니다."}}
    after = gap.assess(SAMPLE_DRAFT, answers=answers)
    assert after["summary"]["effective_score"] > base["summary"]["effective_score"]
    answered = [q for q in after["questions"] if q["id"] == question["id"]][0]
    assert answered["status"] == "answered"


def test_base_question_answer_raises_dimension_coverage():
    base = gap.assess(SAMPLE_DRAFT)
    question = next(q for q in base["questions"] if q["id"].endswith("::base"))
    after = gap.assess(SAMPLE_DRAFT, {
        question["id"]: {"text": "계약 변경 접수와 요금 이의신청 1차 회신을 담당하고, 설비 민원은 설비운영팀으로 넘깁니다."}
    })
    before_row = next(c for c in base["coverage"] if c["key"] == question["dimension"])
    after_row = next(c for c in after["coverage"] if c["key"] == question["dimension"])
    assert after_row["effective_ratio"] > before_row["effective_ratio"]
    assert after["summary"]["effective_score"] > base["summary"]["effective_score"]


def test_skipped_question_counts_as_skipped():
    base = gap.assess(SAMPLE_DRAFT)
    question = base["questions"][0]
    after = gap.assess(SAMPLE_DRAFT, answers={question["id"]: {"text": "", "skipped": True}})
    skipped = [q for q in after["questions"] if q["id"] == question["id"]][0]
    assert skipped["status"] == "skipped"
    assert after["stats"]["skipped"] == 1


def test_template_has_no_content_so_everything_is_missing():
    analysis = gap.assess(TEMPLATE_TEXT)
    assert analysis["summary"]["missing"] >= 8
    assert analysis["summary"]["draft_score"] < 0.2


def test_demo_mode_adds_no_llm_questions():
    result = gap.analyze(SAMPLE_DRAFT)
    assert result["llm"]["provider"] == "demo"
    assert result["llm"]["added"] == 0
    assert all(q["source"] != "llm" for q in result["questions"])


def test_export_contains_answers_and_pending_questions():
    analysis = gap.assess(SAMPLE_DRAFT)
    answered = next(q for q in analysis["questions"] if q["dimension"] == "exception")
    analysis = gap.assess(SAMPLE_DRAFT, answers={answered["id"]: {"text": "과오납 50만원 초과 시 팀장 승인."}})
    markdown, plain = export.build(
        {"author": "김하늘 대리", "successor": "이도윤 주임", "team": "고객지원팀", "period": "12/1~12/5"},
        SAMPLE_DRAFT, analysis,
    )
    assert "인수인계서 — 고객지원팀" in markdown
    assert "과오납 50만원 초과 시 팀장 승인." in markdown
    assert "아직 답하지 못한 질문 목록" in markdown
    assert "부록 B" in markdown
    # 미답변 질문이 표로 들어간다
    pending = [q for q in analysis["questions"] if q["status"] == "unanswered"]
    if pending:
        assert pending[0]["question"][:20] in markdown.replace("|", "")
    assert "인수인계서" in plain and "#" not in plain.split("\n")[0]


def test_export_includes_terms_section():
    analysis = gap.assess(SAMPLE_DRAFT)
    fake_terms = {
        "regulation": {"name": "한국전력공사 기본공급약관", "version_label": "2026. 4. 1", "source_url": ""},
        "matches": [{
            "sentence": "월간 전기요금 이의신청 접수 및 1차 회신",
            "primary": {"article_no": "제74조의2", "title": "요금에 대한 이의신청",
                        "printed_page": 59, "confidence": "높음"},
        }],
    }
    markdown, _ = export.build({}, SAMPLE_DRAFT, analysis, fake_terms)
    assert "## 검토한 근거 규정" in markdown
    assert "제74조의2" in markdown
    assert "법적 판단이 아니라" in markdown
