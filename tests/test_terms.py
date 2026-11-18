"""3단계(약관 조문 파싱·매칭) 테스트 — 내장 기본공급약관 PDF를 실제로 읽는다."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.content import SAMPLE_DRAFT
from app.parsers import parse_bytes
from app.terms import match_units, parse_regulation

SAMPLE_PDF = Path(__file__).resolve().parent.parent / "app" / "samples" / "regulation" / "kepco_basic_supply_terms.pdf"


@pytest.fixture(scope="module")
def regulation():
    doc = parse_bytes(SAMPLE_PDF.name, SAMPLE_PDF.read_bytes())
    return parse_regulation(
        doc, reg_id="kepco", name="한국전력공사 기본공급약관", version_label="2026. 4. 1"
    )


def test_articles_are_parsed_with_location(regulation):
    assert regulation.structure == "article"
    assert regulation.article_count > 90
    first = next(u for u in regulation.units if u.article_no == "제1조")
    assert first.article_title == "목적"
    assert first.printed_page == 1
    assert first.chapter.startswith("제1장")
    assert "전기사업법 제16조" in first.text


def test_article_number_with_sub_number(regulation):
    unit = next(u for u in regulation.units if u.article_no == "제67조의3")
    assert "초과사용부가금" in unit.article_title
    assert unit.printed_page > 40


def test_paragraph_level_units(regulation):
    units = [u for u in regulation.units if u.article_no == "제12조"]
    assert len(units) >= 2
    assert any(u.paragraph == "①" for u in units)


def test_match_finds_official_article_for_handover_sentence(regulation):
    result = match_units(regulation, "월간 전기요금 이의신청 접수 및 1차 회신")
    assert result["matches"], "이의신청 문장은 근거 조문을 찾아야 한다"
    primary = result["matches"][0]["primary"]
    assert primary["article_no"] == "제74조의2"
    assert primary["printed_page"] == 59
    assert primary["confidence"] in ("높음", "중간")
    assert "이의신청" in primary["matched_terms"]


def test_match_covers_sample_draft(regulation):
    result = match_units(regulation, SAMPLE_DRAFT)
    assert result["stats"]["matched"] >= 5
    articles = {m["primary"]["article_no"] for m in result["matches"]}
    assert any(a.startswith("제74조") for a in articles)
    assert result["stats"]["sentences"] >= result["stats"]["matched"]


def test_match_ignores_metadata_lines(regulation):
    result = match_units(regulation, "- 인수인계 기간: 2026-12-01 ~ 2026-12-05\n- 작성일: 2026-11-18")
    assert result["matches"] == []


def test_unrelated_text_has_no_matches(regulation):
    result = match_units(regulation, "오늘 점심은 김치찌개를 먹었고 오후에는 회의가 두 개 있습니다.")
    assert result["matches"] == []


def test_block_fallback_for_pdf_without_articles():
    """조문 구조가 없는 PDF는 페이지 단위 블록으로 대체된다."""
    pdf = Path(__file__).resolve().parent.parent / "app" / "samples" / "handover_sample.pdf"
    doc = parse_bytes(pdf.name, pdf.read_bytes())
    reg = parse_regulation(doc, reg_id="sample", name="인수인계 샘플 PDF")
    assert reg.structure == "block"
    assert reg.units
    assert any("조문 구조를 찾지 못해" in w for w in reg.warnings)
