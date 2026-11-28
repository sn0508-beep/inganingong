"""3단계: 약관·규정 조항 찾기.

하는 일
1. 규정 PDF(내장 샘플은 한국전력공사 기본공급약관)를 조문 단위로 나눈다.
   조문 번호·제목·장·쪽수를 함께 들고 있어서 "제67조 (요금의 계산) · 54쪽 · 제3항"처럼
   원문 위치를 그대로 보여 줄 수 있다.
2. 인수인계 초안을 문장 단위로 끊고, 각 문장과 가장 가까운 조문을 찾는다.
   점수는 (가) 업무 용어 일치 가중치 (나) 조문 제목 일치 (다) 일반 단어 겹침(IDF)으로 계산한다.
3. 점수가 낮으면 억지로 붙이지 않고 "근거를 찾지 못함"으로 남긴다.

특정 회사·업종에 매이지 않도록:
- 고정 사전(`DOMAIN_TERMS`)에는 어느 기관의 규정에도 나오는 계약·요금·재무·인사·안전·보안
  표현만 둔다. 전력·철도 같은 업종 전용 용어는 넣지 않는다.
- 업종·기관 고유 용어는 올린 규정의 **조문 제목과 장 이름에서 그때그때 뽑아** 가중치로 쓴다
  (`Regulation.domain_terms()`). 그래서 어떤 규정을 올려도 그 문서의 말이 먼저 걸린다.

중요: 이 기능은 '법적 판단'이 아니라 '확인이 필요한 지점과 근거 후보'를 짚는 검토 보조다.
화면과 내보내기 문서 모두에 그 문구를 함께 넣는다.
"""

from __future__ import annotations

import bisect
import math
import re
from dataclasses import dataclass, field

from .parsers import ParsedDocument

DISCLAIMER = (
    "이 결과는 법적 판단이 아니라 확인이 필요한 지점과 근거 후보를 짚어 주는 검토 보조입니다. "
    "실제 적용 여부는 원문 조항과 사내 규정을 직접 확인하세요."
)

#: 업무 용어 → 가중치. 인수인계서에서 이 표현이 나오면 해당 조문을 우선 본다.
#: 3.0을 '뚜렷한 업무 용어'의 기준으로 두고, 넓게 쓰이는 말은 낮춘다.
#: 여기에는 기관·업종을 가리지 않는 말만 넣는다. 문서마다 다른 용어는
#: `Regulation.domain_terms()`가 조문 제목·장에서 뽑아 이 사전 위에 덧씌운다.
DOMAIN_TERMS = {
    # 계약·거래
    "계약": 1.2, "계약변경": 2.8, "계약기간": 2.2, "계약해지": 3.0, "해지": 2.4,
    "해약": 2.4, "갱신": 2.0, "승계": 2.4, "양도": 2.2, "명의변경": 3.2,
    "위약금": 2.8, "보증금": 2.4, "손해배상": 2.8, "면책": 2.2, "손해": 1.8,
    "이의신청": 3.0, "이의제기": 3.0, "재심": 2.2, "통지": 1.8, "공고": 1.8,
    "동의": 1.4, "취소": 2.0, "철회": 2.0, "반려": 2.4, "해제": 2.0,
    "정지": 2.0, "중지": 2.0, "제한": 1.8, "반환": 2.0, "이관": 1.8,
    # 요금·재무·구매
    "요금": 1.6, "청구": 1.8, "납부": 2.0, "납기": 2.2, "연체": 2.4,
    "환불": 2.4, "과오납": 2.6, "정산": 2.0, "감액": 2.2, "부가금": 2.2,
    "세금계산서": 2.4, "예산": 1.8, "집행": 1.8, "품의": 2.0, "검수": 2.2,
    "지급": 1.8, "원가": 1.8, "회계": 1.8, "결산": 2.0, "단가": 2.0,
    "물품": 1.8, "용역": 1.8, "발주": 2.0, "입찰": 2.2, "견적": 2.2,
    # 공급·설비(수도·가스·전기·통신 등 어느 공급계약에도 쓰는 말)
    "공급정지": 2.8, "공급중지": 2.8, "검침": 2.8, "계량기": 2.6,
    # 인사·노무
    "채용": 2.2, "인사": 1.8, "발령": 2.2, "전보": 2.2, "징계": 2.4,
    "평가": 1.6, "교육": 1.6, "근태": 2.0, "휴가": 1.8, "급여": 2.2,
    "수당": 2.0, "퇴직": 2.2, "복무": 2.2, "수습": 2.0,
    # 안전·보안
    "안전": 1.6, "재해": 2.2, "점검": 1.8, "사고": 1.8, "위험": 1.8,
    "보안": 1.8, "개인정보": 2.6, "비밀": 2.0, "정보보호": 2.4,
    "접근권한": 2.4, "인증": 2.0, "유출": 2.4, "침해": 2.4, "파기": 2.2,
    # 규정 운영·일반
    "적용범위": 2.0, "개정": 2.0, "폐지": 2.2, "시행": 1.6, "위임": 2.2,
    "준용": 2.2, "예외": 1.6, "기한": 1.8, "지연": 1.8, "배상": 2.0,
    "책임": 1.2, "권한": 1.8, "승인": 1.4, "결재": 1.8, "협의": 1.2,
    "민원": 2.0, "고객": 0.6, "이용자": 0.8, "회원": 0.8, "신청": 0.8,
    "변경": 0.8, "보관": 1.6,
}

#: 같은 뜻으로 쓰이는 표현. 초안에는 '명의변경'이라 썼는데 규정은 '계약자의 변경'이라고 쓰는 식의
#: 간극을 메운다(비교할 때는 띄어쓰기를 지운 형태로 본다). 업종과 상관없는 행정·계약 표현만 둔다.
TERM_ALIASES = {
    "명의변경": ("계약자의변경", "계약자변경"),
    "계약자변경": ("계약자의변경", "명의변경"),
    "계약해지": ("해지", "해약"),
    "해지": ("계약해지", "해약"),
    "이의신청": ("이의제기",),
    "이의제기": ("이의신청",),
    "과오납": ("재계산", "환불", "과다납부"),
    "환불": ("재계산", "과오납"),
    "공급정지": ("공급의중지", "공급중지", "사용의제한"),
    "검침": ("검침일",),
    "계량기": ("전력량계", "미터기"),
    "연체료": ("연체",),
    "반려": ("반송", "거부"),
}

PARTICLES = (
    "으로서", "으로써", "에서는", "에게는", "이라고", "라고는", "부터", "까지",
    "에서", "에게", "으로", "로는", "에는", "하고", "한다", "하여", "되는",
    "입니다", "합니다", "이다", "있다", "없다", "보다", "처럼", "만큼", "및",
    "은", "는", "이", "가", "을", "를", "의", "에", "로", "와", "과", "도", "만", "한",
)

STOPWORDS = {
    "그리고", "또는", "그러나", "따라서", "위하여", "대하여", "관하여", "경우", "때문",
    "다음", "이하", "해당", "관련", "부분", "내용", "업무", "처리", "확인", "경우에는",
    "있습니다", "없습니다", "합니다", "됩니다", "것입니다", "그것", "이것", "저것",
    "요청", "신청", "대부분", "보통", "결과", "검토", "진행", "담당", "문의", "안내",
    "접수", "등록", "사용", "관리", "정도", "때문에", "어떤", "무엇", "누구", "언제",
}

#: 조문 제목·장 이름에서 용어를 뽑을 때 빼는 말. 어느 규정에나 붙어 있어 변별력이 없다.
TITLE_STOPWORDS = {
    "목적", "정의", "적용", "적용범위", "기준", "방법", "절차", "내용", "사항", "경우",
    "관련", "일반", "원칙", "특례", "예외", "조치", "기타", "그밖", "기타의", "및",
    "해당", "기본", "개요", "총칙", "부칙", "별표", "서식", "양식",
}

#: 동적 용어의 최대·최소 가중치. 3.0은 `DOMAIN_TERMS`의 '뚜렷한 업무 용어' 기준과 맞춘다.
DYNAMIC_TERM_MAX = 3.2
DYNAMIC_TERM_MIN = 1.8

#: 업무 용어 하나가 맞았을 때 더하는 점수와, 그 기준이 되는 가중치(3.0 → 1.6점).
DOMAIN_BOOST = 1.6
DOMAIN_REFERENCE = 3.0

#: 문장·조문을 비교할 때 띄어쓰기를 지운 형태를 쓰므로, 띄어쓰기만 다른 표현도 걸린다.
_SPACE_RE = re.compile(r"\s+")


@dataclass
class Unit:
    """조문 1개(또는 항 1개) — 검색·표시의 최소 단위."""
    article_no: str          # '제67조', '제67조의3', '별표 1'
    article_title: str
    chapter: str
    paragraph: str           # '①', '②' … 또는 ''
    printed_page: int
    pdf_page: int
    text: str
    kind: str = "article"    # article | annex | addendum | block

    @property
    def location(self) -> str:
        parts = [self.article_no]
        if self.article_title:
            parts.append(f"({self.article_title})")
        if self.paragraph:
            parts.append(self.paragraph)
        parts.append(f"{self.printed_page}쪽")
        if self.chapter:
            parts.append(self.chapter)
        return " · ".join(parts)


@dataclass
class Regulation:
    id: str
    name: str
    filename: str
    source_url: str
    note: str
    version_label: str
    page_count: int
    units: list = field(default_factory=list)
    structure: str = "article"       # article | block
    uploaded: bool = False
    warnings: list = field(default_factory=list)
    _idf: dict = field(default_factory=dict, repr=False)
    _domain_terms: dict = field(default_factory=dict, repr=False)

    @property
    def article_count(self) -> int:
        return len({u.article_no for u in self.units})

    def summary(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "filename": self.filename,
            "source_url": self.source_url,
            "note": self.note,
            "version_label": self.version_label,
            "page_count": self.page_count,
            "article_count": self.article_count,
            "unit_count": len(self.units),
            "structure": self.structure,
            "uploaded": self.uploaded,
            "warnings": self.warnings,
        }

    def build_idf(self):
        documents = [_tokens(u.text) for u in self.units]
        df = {}
        for tokens in documents:
            for token in set(tokens):
                df[token] = df.get(token, 0) + 1
        total = max(len(documents), 1)
        self._idf = {t: math.log(1 + total / (1 + d)) for t, d in df.items()}

    @property
    def idf(self) -> dict:
        if not self._idf:
            self.build_idf()
        return self._idf

    def domain_terms(self) -> dict:
        """이 규정의 조문 제목·장 이름에서 뽑은 용어 → 가중치(캐시)."""
        if not self._domain_terms:
            self._domain_terms = build_domain_terms(self)
        return self._domain_terms

    def matching_terms(self) -> dict:
        """고정 범용 사전 위에 이 문서의 동적 용어를 얹은 최종 사전."""
        terms = dict(DOMAIN_TERMS)
        for term, weight in self.domain_terms().items():
            terms[term] = max(weight, terms.get(term, 0.0))
        return terms


# ---------------------------------------------------------------------------
# 파싱
# ---------------------------------------------------------------------------

ARTICLE_RE = re.compile(
    r"^제\s*(\d+)\s*조(?:\s*의\s*(\d+))?\s*(\(\s*[^\)\n]{0,40}\)|\[\s*[^\]\n]{0,40}\]|<삭\s*제>)",
    re.MULTILINE,
)
CHAPTER_RE = re.compile(r"^제\s*(\d+)\s*장\s+(\S[^\n]{1,40})$", re.MULTILINE)
ANNEX_RE = re.compile(r"^별표\s*(\d+)\s*[.．]\s*([^\n]{2,40})$", re.MULTILINE)
PARA_RE = re.compile(r"(?=(?:[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑳])\s?)")
TOC_PAGE_RE = re.compile(r"·{3,}")


def _toc_entries(pages: list) -> tuple:
    """목차에서 (조문, 장, 인쇄쪽수)를 얻는다. 본문 쪽수 표기의 기준이 된다."""
    entries, chapter = {}, ""
    for page in pages[:15]:
        if not (TOC_PAGE_RE.search(page) or "CONTENTS" in page):
            continue
        for line in page.split("\n"):
            line = line.strip()
            if not line:
                continue
            if TOC_PAGE_RE.search(line):
                match = re.match(r"^제\s*(\d+)\s*조(?:\s*의\s*(\d+))?", line)
                page_no = re.search(r"(\d+)\s*$", line)
                if match and page_no:
                    key = (match.group(1), match.group(2) or "")
                    entries[key] = {"chapter": chapter, "page": int(page_no.group(1))}
                continue
            match = CHAPTER_RE.match(line)
            if match:
                chapter = f"제{match.group(1)}장 {match.group(2).strip()}"
    return entries, chapter


def parse_regulation(doc: ParsedDocument, *, reg_id: str, name: str,
                     source_url: str = "", note: str = "", version_label: str = "",
                     uploaded: bool = False) -> Regulation:
    pages = doc.pages or [doc.text]
    toc, _ = _toc_entries(pages)
    toc_pages = {i for i, page in enumerate(pages[:15])
                 if TOC_PAGE_RE.search(page) or "CONTENTS" in page}
    body_pages = [i for i in range(len(pages)) if i not in toc_pages]

    offsets, chunks, pos = [], [], 0
    for index in body_pages:
        chunks.append(pages[index])
        offsets.append((pos, index))
        pos += len(pages[index]) + 1
    flat = "\n".join(chunks)
    starts = [o for o, _ in offsets]

    def page_at(offset: int) -> int:
        if not starts:
            return 1
        idx = bisect.bisect_right(starts, offset) - 1
        return offsets[max(idx, 0)][1] + 1

    heads = []
    for match in ARTICLE_RE.finditer(flat):
        heads.append((match.start(), match.end(), "article", match))
    for match in ANNEX_RE.finditer(flat):
        heads.append((match.start(), match.end(), "annex", match))
    heads.sort()

    # 목차가 없는 문서(붙여넣은 텍스트 등)도 장 이름을 붙일 수 있도록 본문의 장 제목을 찾아 둔다.
    chapter_marks = [(m.start(), f"제{m.group(1)}장 {m.group(2).strip()}")
                     for m in CHAPTER_RE.finditer(flat)]
    chapter_starts = [pos for pos, _ in chapter_marks]

    def chapter_at(offset: int) -> str:
        index = bisect.bisect_right(chapter_starts, offset) - 1
        return chapter_marks[index][1] if index >= 0 else ""

    units = []
    for index, (start, end, kind, match) in enumerate(heads):
        stop = heads[index + 1][0] if index + 1 < len(heads) else len(flat)
        body = flat[end:stop].strip()
        if kind == "article":
            number, sub = match.group(1), match.group(2)
            article_no = f"제{number}조" + (f"의{sub}" if sub else "")
            title = match.group(3).strip()
            title = re.sub(r"^[\(\[]\s*|\s*[\)\]]$", "", title)
            if title.startswith("삭"):
                title = "삭제"
            toc_info = toc.get((number, sub or ""), {})
        else:
            article_no = f"별표 {match.group(1)}"
            title = match.group(2).strip()
            toc_info = {}

        pdf_page = page_at(start)
        printed = toc_info.get("page") or max(1, pdf_page - _page_offset(pages, toc_pages))
        chapter = toc_info.get("chapter", "") or chapter_at(start)

        pieces = [piece.strip() for piece in PARA_RE.split(body) if piece.strip()]
        if not pieces:
            pieces = [body] if body else []
        if len(pieces) <= 1:
            units.append(Unit(article_no, title, chapter, "", printed, pdf_page,
                              _clean(body), kind=kind))
        else:
            for piece in pieces:
                marker = piece[0] if piece and piece[0] in "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑳" else ""
                units.append(Unit(article_no, title, chapter, marker, printed, pdf_page,
                                  _clean(piece), kind=kind))

    structure = "article" if units else "block"
    warnings = list(doc.warnings)
    if not units:
        units = _block_units(pages, body_pages)
        warnings.append("조문 구조를 찾지 못해 페이지·문단 단위로 나눴습니다. 위치 표시가 조문 번호 대신 쪽수가 됩니다.")

    reg = Regulation(
        id=reg_id, name=name, filename=doc.filename, source_url=source_url, note=note,
        version_label=version_label or _guess_version(pages), page_count=len(pages),
        units=units, structure=structure, uploaded=uploaded, warnings=warnings,
    )
    reg.build_idf()
    return reg


def _page_offset(pages: list, toc_pages: set) -> int:
    """PDF 쪽번호와 인쇄 쪽번호의 차이(표지·목차 분량)."""
    first_body = min((i for i in range(len(pages)) if i not in toc_pages), default=0)
    return max(0, first_body)


def _guess_version(pages: list) -> str:
    if pages:
        match = re.search(r"(\d{4})\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})", pages[0])
        if match:
            return f"{match.group(1)}. {int(match.group(2))}. {int(match.group(3))}"
    return ""


def _clean(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def _block_units(pages: list, body_pages: list, size: int = 700) -> list:
    units = []
    for index in body_pages:
        text = pages[index].strip()
        while text:
            chunk, text = text[:size], text[size:]
            if chunk.strip():
                units.append(Unit("", "", "", "", index + 1, index + 1, _clean(chunk), kind="block"))
    return units


# ---------------------------------------------------------------------------
# 매칭
# ---------------------------------------------------------------------------

def _tokens(text: str) -> list:
    raw = re.findall(r"[가-힣]{2,}|[A-Za-z]{3,}", text or "")
    tokens = []
    for token in raw:
        token = token.lower()
        for particle in PARTICLES:
            if len(token) > len(particle) + 1 and token.endswith(particle):
                token = token[: -len(particle)]
                break
        if len(token) >= 2 and token not in STOPWORDS:
            tokens.append(token)
    return tokens


#: 서식·머리말 줄은 검색 대상에서 뺀다(날짜만으로 조문이 걸리는 것을 막는다).
META_LINE_RE = re.compile(
    r"^\s*-?\s*(인수인계\s*기간|작성일|인계자|인수자|소속|부서\s*/\s*직무|직무|파일명)\s*[:：]"
)


# ---------------------------------------------------------------------------
# 문서에서 뽑는 동적 용어
# ---------------------------------------------------------------------------

def _title_words(text: str) -> list:
    """조문 제목·장 이름을 핵심 명사 단위로 나눈다(괄호 안 한자 병기 등은 버린다)."""
    cleaned = re.sub(r"[\(\[][^\)\]]{0,30}[\)\]]", " ", text or "")
    words = []
    for raw in re.split(r"[^가-힣A-Za-z0-9]+", cleaned):
        if not raw:
            continue
        token = raw.lower()
        for particle in PARTICLES:
            if len(token) > len(particle) + 1 and token.endswith(particle):
                token = token[: -len(particle)]
                break
        if len(token) < 2 or token in TITLE_STOPWORDS or token in STOPWORDS:
            continue
        words.append(token)
    return words


def _title_terms(text: str) -> dict:
    """제목 하나에서 용어 후보를 뽑는다. 이웃한 말을 붙인 복합어도 함께 담는다.

    예: '운임의 반환' → 운임 · 반환 · 운임반환
    """
    words = _title_words(text)
    terms = {word: (word,) for word in words}
    for left, right in zip(words, words[1:]):
        compound = left + right
        if 3 <= len(compound) <= 14:
            terms.setdefault(compound, (left, right))
    return terms


def _dynamic_weight(parts: tuple, title_df: int, total_titles: int, idf: dict) -> float:
    """제목에 드물게 쓰인 용어일수록, 본문에서도 드문 용어일수록 높은 가중치.

    본문 빈도(IDF)를 더 크게 본다. '변경'·'신청'처럼 어느 조문에나 나오는 말은
    제목에 한 번 보였다는 이유로 높은 점수를 받으면 안 되기 때문이다.
    """
    rarity = 1.0 - (title_df - 1) / max(total_titles - 1, 1)
    body = idf.get(parts[0]) if len(parts) == 1 else None
    if body is None:
        known = [idf[part] for part in parts if part in idf]
        body = max(known) if known else 1.2
    weight = 1.2 + 0.9 * min(body, 4.0) / 4.0 + 0.7 * rarity
    return round(min(DYNAMIC_TERM_MAX, weight), 2)


def build_domain_terms(reg: "Regulation") -> dict:
    """규정의 조문 제목·장 이름에서 그 문서의 업종·기관 용어를 뽑아 가중치를 준다.

    고정 사전에 없는 말도, 그 규정에서 여러 조문을 가로질러 쓰인 말이라면
    초안 문장과 조문을 이어 주는 단서가 된다. 어느 문서를 올려도 같은 방식이 적용된다.
    """
    idf = reg.idf
    titles, chapters = [], []
    seen_title, seen_chapter = set(), set()
    for unit in reg.units:
        title = (unit.article_title or "").strip()
        if title and title not in seen_title:
            seen_title.add(title)
            titles.append(title)
        chapter = (unit.chapter or "").strip()
        if chapter and chapter not in seen_chapter:
            seen_chapter.add(chapter)
            chapters.append(chapter)

    parts_of, df = {}, {}
    for title in titles:
        for term, parts in _title_terms(title).items():
            parts_of.setdefault(term, parts)
            df[term] = df.get(term, 0) + 1

    total_titles = max(len(titles), 1)
    terms = {}
    for term, count in df.items():
        weight = _dynamic_weight(parts_of.get(term, (term,)), count, total_titles, idf)
        if weight >= DYNAMIC_TERM_MIN:
            terms[term] = weight

    # 장 이름에만 있는 말(예: '요금의 계산 및 납부')은 조문 제목보다 조금 낮게 보탠다.
    for chapter in chapters:
        for term, parts in _title_terms(chapter).items():
            if term in terms:
                continue
            weight = _dynamic_weight(parts, 1, total_titles, idf) - 0.4
            if weight >= DYNAMIC_TERM_MIN:
                terms[term] = round(weight, 2)
    return terms


def _sentences(text: str) -> list:
    lines = [line.strip(" -•·\t") for line in (text or "").split("\n")]
    sentences = []
    for line in lines:
        if not line or line.startswith("#") or line.upper().startswith("TODO"):
            continue
        if META_LINE_RE.match(line):
            continue
        for piece in re.split(r"(?<=[.다요음])\s+|(?<=[\)\]])\s+", line):
            piece = piece.strip(" -•·\t")
            if len(piece) < 8:
                continue
            if not re.search(r"[가-힣]{2,}", piece):   # 숫자·코드만 있는 줄 제외
                continue
            sentences.append(piece)
    return sentences


def split_sentences(text: str) -> list:
    """초안을 문장 단위로 나눈다(3단계 사내 표준약관 AI 연결에서도 같은 기준을 쓴다)."""
    return _sentences(text)


def _sentence_terms(compact_sentence: str, terms: dict) -> list:
    """문장에 실제로 들어 있는 업무 용어만 골라 (용어, 가중치, 표기들)로 돌려준다.

    조문 수백 개를 돌 때 같은 문장을 용어 사전 전체와 매번 대조하지 않도록,
    문장 쪽은 한 번만 본다.
    """
    found = []
    for term, weight in terms.items():
        if len(term) >= 2 and term in compact_sentence:
            found.append((term, weight, _term_variants(term)))
    found.sort(key=lambda item: -item[1])
    return found


def _domain_hits(compact_unit: str, candidates: list) -> list:
    """문장에 나온 업무 용어가 조문 본문·제목에 있는지(동의어 포함)."""
    return [(term, weight) for term, weight, variants in candidates
            if any(variant in compact_unit for variant in variants)]


def _term_variants(term: str) -> tuple:
    """한 용어를 약관 쪽에서 다르게 쓸 수 있는 표기들(동의어·조사 생략형)."""
    base = _SPACE_RE.sub("", term)
    variants = [base]
    if "의" in base and len(base) >= 4:
        variants.append(base.replace("의", ""))
    variants.extend(TERM_ALIASES.get(base, ()))
    return tuple(dict.fromkeys(variants))


def match_units(reg: Regulation, handover_text: str, *, top_k: int = 3,
                threshold: float = 2.4) -> dict:
    """인수인계 문장마다 근거 후보 조문을 찾는다(BM25 + 업무용어 가중).

    업무 용어 사전은 (가) 업종을 가리지 않는 고정 사전 + (나) 이 규정의 조문 제목에서
    뽑은 동적 용어로 만들어진다. 그래서 올린 문서가 무엇이든 그 문서의 말이 먼저 걸린다.
    """
    idf = reg.idf
    terms = reg.matching_terms()
    sentences = _sentences(handover_text)
    unit_tokens = []
    for unit in reg.units:
        tokens = _tokens(unit.text) + _tokens(unit.article_title)
        compact = _SPACE_RE.sub("", unit.text + " " + unit.article_title)
        compact_title = _SPACE_RE.sub("", unit.article_title)
        unit_tokens.append((tokens, set(tokens), len(tokens), compact, compact_title))
    average_length = (sum(length for _, _, length, _, _ in unit_tokens) / len(unit_tokens)) if unit_tokens else 1
    k1, b = 1.4, 0.7
    results = []

    for sentence in sentences:
        sentence_tokens = set(_tokens(sentence))
        if not sentence_tokens:
            continue
        compact_sentence = _SPACE_RE.sub("", sentence)
        candidates = _sentence_terms(compact_sentence, terms)
        scored = []
        for index, unit in enumerate(reg.units):
            tokens, token_set, length, compact_unit, compact_title = unit_tokens[index]
            shared = sentence_tokens & token_set
            domain_hits = _domain_hits(compact_unit, candidates)
            if not shared and not domain_hits:
                continue
            strong_shared = [t for t in shared if idf.get(t, 0) >= 1.1]
            if not domain_hits and len(strong_shared) < 2:
                continue          # 업무 용어도 없고 뚜렷한 단어도 하나뿐이면 버린다

            score = 0.0
            for token in shared:
                tf = tokens.count(token)
                denominator = tf + k1 * (1 - b + b * length / max(average_length, 1))
                score += idf.get(token, 0.5) * (tf * (k1 + 1)) / max(denominator, 0.001)

            title_tokens = set(_tokens(unit.article_title))
            title_hits = len(shared & title_tokens)
            score += 1.2 * title_hits
            # 업무 용어 가중치 합(상위 2개)을 3.0 기준으로 환산해 더한다.
            weight_sum = sum(weight for _, weight in domain_hits[:2])
            score += DOMAIN_BOOST * min(weight_sum / DOMAIN_REFERENCE, 2.0)
            # 그 용어가 조문 제목에까지 있으면 이 조문의 주제라는 뜻이라 조금 더 준다.
            title_term_hits = sum(
                1 for term, _ in domain_hits
                if any(variant in compact_title for variant in _term_variants(term))
            )
            score += 0.6 * min(title_term_hits, 2)
            if score > 0:
                strong_words = sorted(
                    (t for t in shared if idf.get(t, 0) >= 1.1), key=lambda t: -idf.get(t, 0)
                )[:6]
                scored.append((score, unit, domain_hits, strong_words, title_hits))

        scored.sort(key=lambda item: -item[0])
        best = []
        for rank, (score, unit, hits, words, title_hits) in enumerate(scored[:top_k]):
            if score < threshold:
                break
            if rank > 0 and score < (scored[0][0] if scored else 0) * 0.55:
                break
            confidence = _confidence(score)
            if title_hits == 0 and confidence == "높음":
                # 조문 제목과 직접 맞는 단어가 없으면 '높음'이라고 말하지 않는다.
                confidence = "중간"
            best.append({
                "unit": unit,
                "score": round(score, 2),
                "confidence": confidence,
                "matched_terms": [h[0] for h in hits],
                "matched_words": words,
                "excerpt": _excerpt(unit.text, [h[0] for h in hits], words),
            })
        if best:
            results.append({
                "sentence": sentence,
                "primary": best[0],
                "alternatives": best[1:],
                "confidence": best[0]["confidence"],
            })

    matched_articles = {}
    for item in results:
        for candidate in [item["primary"]] + item["alternatives"]:
            unit = candidate["unit"]
            key = unit.article_no or f"p.{unit.printed_page}"
            entry = matched_articles.setdefault(key, {
                "article_no": unit.article_no,
                "title": unit.article_title,
                "chapter": unit.chapter,
                "printed_page": unit.printed_page,
                "sentences": 0,
                "location": unit.location,
            })
            entry["sentences"] += 1

    return {
        "matches": [_serialize(item) for item in results],
        "stats": {
            "sentences": len(sentences),
            "matched": len(results),
            "articles": len(matched_articles),
        },
        "articles": sorted(matched_articles.values(), key=lambda a: -a["sentences"]),
        "disclaimer": DISCLAIMER,
        "regulation": reg.summary(),
    }


def _confidence(score: float) -> str:
    if score >= 9.0:
        return "높음"
    if score >= 5.0:
        return "중간"
    return "낮음"


def _excerpt(text: str, terms: list, words, limit: int = 320) -> str:
    text = _clean(text)
    if len(text) <= limit:
        return text
    position = -1
    for term in list(terms) + list(words):
        found = text.find(term)
        if found != -1 and (position == -1 or found < position):
            position = found
    if position == -1:
        return text[:limit] + "…"
    start = max(0, position - 80)
    return ("…" if start else "") + text[start:start + limit] + "…"


def _serialize(item: dict) -> dict:
    def pack(candidate):
        unit = candidate["unit"]
        return {
            "article_no": unit.article_no,
            "title": unit.article_title,
            "chapter": unit.chapter,
            "paragraph": unit.paragraph,
            "printed_page": unit.printed_page,
            "location": unit.location,
            "text": unit.text,
            "excerpt": candidate["excerpt"],
            "score": candidate["score"],
            "confidence": candidate["confidence"],
            "matched_terms": candidate["matched_terms"],
            "matched_words": candidate["matched_words"],
            "kind": unit.kind,
        }

    return {
        "sentence": item["sentence"],
        "primary": pack(item["primary"]),
        "alternatives": [pack(alt) for alt in item["alternatives"]],
        "confidence": item["confidence"],
    }
