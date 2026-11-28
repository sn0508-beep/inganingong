"""3단계(약관 조문 파싱·매칭) 테스트 — 내장 기본공급약관 PDF를 실제로 읽는다.

업종이 다른 규정(가상의 교통공사 운송약관·사기업 인사·구매·보안 규정)도 같은 방식으로
조문을 찾는지 함께 확인한다. 아래 가상 문서는 테스트용으로 지어낸 글이며 실제 기관 규정이 아니다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.content import SAMPLE_DRAFT
from app.parsers import parse_bytes, parse_pasted
from app.terms import DOMAIN_TERMS, match_units, parse_regulation

SAMPLE_PDF = Path(__file__).resolve().parent.parent / "app" / "samples" / "regulation" / "kepco_basic_supply_terms.pdf"

#: 가상의 교통공사 운송약관(전력 용어가 하나도 없다).
TRANSIT_TERMS = """한빛교통공사 도시철도 운송약관

제1장 총칙

제1조 (목적) 이 약관은 한빛교통공사(이하 "공사"라 한다)가 운영하는 도시철도의 여객 운송에 관하여 공사와 여객 간의 권리와 의무를 정함을 목적으로 한다.

제2조 (정의) 이 약관에서 사용하는 용어의 뜻은 다음과 같다.
1. "승차권"이라 함은 여객이 열차에 승차하기 위하여 결제한 운임의 증표를 말한다.
2. "역무원"이라 함은 역에서 여객 안내와 시설 관리 업무를 담당하는 직원을 말한다.

제3장 운임

제10조 (운임의 반환) ① 여객이 승차권을 사용하지 아니하고 반환을 요청하는 경우에는 운임 전액을 반환한다.
② 열차의 운행 지연으로 목적지에 도착하지 못한 여객이 운임 반환을 요청하는 경우에는 승차한 구간의 운임을 반환한다.

제11조 (부가운임) ① 정당한 승차권 없이 승차한 여객에게는 승차 구간 운임에 부가운임을 더하여 징수한다.
② 승차권을 다른 사람에게 양도한 경우에도 부가운임을 징수할 수 있다.

제12조 (승차권의 효력) 승차권은 발매한 날부터 사용할 때까지 효력이 있으며, 역무원의 요청이 있으면 제시하여야 한다.

제4장 운송

제16조 (분실물의 처리) ① 여객이 열차 안이나 역 구내에서 분실물을 습득한 경우에는 가까운 역무실에 제출한다.
② 역무실에서 보관하는 분실물은 7일간 공고하고, 그 기간이 지나면 공사의 규정에 따라 처리한다.

제5장 개인정보

제25조 (개인정보의 보호) 공사는 여객의 개인정보를 수집·이용하는 경우 목적을 밝히고 동의를 받아야 하며, 목적을 달성하면 파기한다.
"""

#: 가상의 사기업 인사·구매·보안 규정.
PRIVATE_TERMS = """한빛제조 주식회사 인사·구매·보안 규정

제1장 총칙

제1조 (목적) 이 규정은 한빛제조 주식회사의 인사, 구매, 정보보안 업무 처리 기준을 정함을 목적으로 한다.

제2조 (적용범위) 이 규정은 본사와 전 사업장의 임직원에게 적용한다.

제2장 인사

제3조 (채용 및 수습기간) ① 신규 채용자의 수습기간은 채용일부터 3개월로 한다.
② 수습기간 중 업무평가 결과가 기준에 미달하는 경우 정규 임용을 거부할 수 있다.

제5조 (근태 및 휴가) ① 임직원은 근무시간을 준수하여야 하며, 지각이나 조퇴가 반복되면 인사팀에 통보한다.
② 연차휴가는 사전에 부서장의 승인을 받아 신청한다.

제7조 (징계의 종류) 징계는 견책, 감봉, 정직, 해고로 구분하며, 징계위원회의 의결을 거쳐 결정한다.

제3장 구매

제12조 (구매요청 및 발주) ① 물품이나 용역을 구매하려는 부서는 구매요청서를 작성하여 구매팀에 제출한다.
② 500만원 이상 구매는 견적서 3건 이상을 비교한 후 발주하여야 한다.

제13조 (협력업체의 평가) 구매팀은 협력업체를 등록하고 반기마다 납기와 품질을 평가하여 우수업체를 우대한다.

제4장 정보보안

제18조 (접근권한의 부여와 회수) ① 시스템 접근권한은 업무상 필요한 범위에서 부여한다.
② 퇴직이나 전보가 확정되면 지체 없이 접근권한을 회수한다.

제19조 (개인정보의 처리) 임직원은 업무상 알게 된 고객의 개인정보를 목적 외로 이용하거나 외부에 유출하여서는 안 된다.
"""


@pytest.fixture(scope="module")
def regulation():
    doc = parse_bytes(SAMPLE_PDF.name, SAMPLE_PDF.read_bytes())
    return parse_regulation(
        doc, reg_id="kepco", name="한국전력공사 기본공급약관", version_label="2026. 4. 1"
    )


@pytest.fixture(scope="module")
def transit():
    doc = parse_pasted(TRANSIT_TERMS, "transit_terms.txt")
    return parse_regulation(doc, reg_id="transit", name="한빛교통공사 도시철도 운송약관")


@pytest.fixture(scope="module")
def private_company():
    doc = parse_pasted(PRIVATE_TERMS, "private_terms.txt")
    return parse_regulation(doc, reg_id="private", name="한빛제조 인사·구매·보안 규정")


def _primary(reg, sentence):
    result = match_units(reg, sentence)
    assert result["matches"], f"근거 조문을 찾아야 한다: {sentence}"
    return result["matches"][0]["primary"]


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


# ---------------------------------------------------------------------------
# 업종 중립성 — 고정 사전과 문서별 동적 용어
# ---------------------------------------------------------------------------

UTILITY_ONLY_TERMS = (
    "한전", "한국전력", "전기사용계약", "계약전력", "요금적용전력", "역률",
    "전력량계", "수급지점", "전기설비", "계약종별", "최대수요전력",
)


def test_fixed_term_table_has_no_utility_only_terms():
    """고정 사전에는 특정 업종·기관 전용 용어가 남아 있으면 안 된다."""
    for term in UTILITY_ONLY_TERMS:
        assert term not in DOMAIN_TERMS, f"고정 사전에 업종 전용 용어가 남아 있음: {term}"


def test_fixed_term_table_covers_common_admin_words():
    """공기업·사기업 모두에 쓰는 행정·계약·재무·인사·보안 용어는 남아 있어야 한다."""
    for term in ("명의변경", "과오납", "해지", "이의신청", "예산", "채용", "개인정보", "징계"):
        assert term in DOMAIN_TERMS


def test_dynamic_terms_are_extracted_from_article_titles(transit):
    terms = transit.domain_terms()
    assert terms, "조문 제목에서 동적 업무 용어를 뽑아야 한다"
    for word in ("운임", "분실물", "승차권", "개인정보"):
        assert word in terms
    assert all(1.8 <= weight <= 3.2 for weight in terms.values())


def test_dynamic_terms_stay_inside_their_own_document(transit, private_company):
    assert "운임" not in private_company.domain_terms()
    assert "수습기간" not in transit.domain_terms()
    assert "수습기간" in private_company.domain_terms()


def test_dynamic_terms_are_cached(transit):
    assert transit.domain_terms() is transit.domain_terms()


# ---------------------------------------------------------------------------
# 전력 용어가 없는 규정에서도 조문 맞히기
# ---------------------------------------------------------------------------

def test_transit_regulation_is_parsed_by_article(transit):
    assert transit.structure == "article"
    assert transit.article_count == 7
    first = next(u for u in transit.units if u.article_no == "제1조")
    assert first.article_title == "목적"
    assert first.chapter == "제1장 총칙"


@pytest.mark.parametrize("sentence,article_no", [
    ("열차 지연으로 목적지에 도착하지 못한 여객이 운임 반환을 요청하면 승차 구간 운임을 반환합니다", "제10조"),
    ("정당한 승차권 없이 승차한 여객에게는 부가운임을 징수합니다", "제11조"),
    ("전동차 안에서 습득한 분실물은 역무실에서 보관하고 7일간 공고합니다", "제16조"),
    ("여객의 개인정보는 수집 목적을 달성하면 파기합니다", "제25조"),
])
def test_transit_draft_sentences_find_their_article(transit, sentence, article_no):
    primary = _primary(transit, sentence)
    assert primary["article_no"] == article_no
    assert primary["confidence"] in ("높음", "중간")


@pytest.mark.parametrize("sentence,article_no", [
    ("신규 채용자의 수습기간은 3개월이며 평가 결과에 따라 정규 임용을 거부할 수 있습니다", "제3조"),
    ("500만원 이상 물품을 구매할 때는 견적서 3건을 비교한 후 발주합니다", "제12조"),
    ("퇴직자의 시스템 접근권한은 지체 없이 회수합니다", "제18조"),
    ("고객의 개인정보를 외부에 유출하면 안 됩니다", "제19조"),
])
def test_private_company_draft_sentences_find_their_article(private_company, sentence, article_no):
    primary = _primary(private_company, sentence)
    assert primary["article_no"] == article_no
    assert primary["confidence"] in ("높음", "중간")


def test_alias_connects_draft_word_to_regulation_wording():
    """초안의 '명의변경'과 규정의 '계약자의 변경'을 같은 뜻으로 본다."""
    text = (
        "제1조 (목적) 이 약관은 고객에게 서비스를 제공하는 조건을 정한다.\n"
        "제7조 (계약자의 변경) ① 고객이 바뀌면 새로운 고객은 계약자의 변경 신청을 하여야 한다.\n"
        "제9조 (요금의 감면) 요금을 감면받으려면 신청서를 제출한다.\n"
    )
    reg = parse_regulation(parse_pasted(text, "alias.txt"), reg_id="alias", name="가상 약관")
    primary = _primary(reg, "명의변경 서류를 접수하면 처리합니다")
    assert primary["article_no"] == "제7조"
    assert "명의변경" in primary["matched_terms"]


def test_builtin_sample_still_matches_its_own_articles(regulation):
    """내장 기본공급약관도 동적 용어 덕분에 기존처럼 정확히 걸린다."""
    assert "계약전력" in regulation.domain_terms()
    primary = _primary(regulation, "계약전력 산정 기준을 확인해 안내합니다")
    assert primary["article_no"] == "제19조"
    assert primary["confidence"] in ("높음", "중간")
