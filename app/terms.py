"""3단계: 약관·규정 조항 찾기.

하는 일
1. 규정 PDF(기본은 내장 한국전력공사 기본공급약관)를 조문 단위로 나눈다.
   조문 번호·제목·장·쪽수를 함께 들고 있어서 "제67조 (요금의 계산) · 54쪽 · 제3항"처럼
   원문 위치를 그대로 보여 줄 수 있다.
2. 인수인계 초안을 문장 단위로 끊고, 각 문장과 가장 가까운 조문을 찾는다.
   점수는 (가) 업무 용어 일치 가중치 (나) 조문 제목 일치 (다) 일반 단어 겹침(IDF)으로 계산한다.
3. 점수가 낮으면 억지로 붙이지 않고 "근거를 찾지 못함"으로 남긴다.

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
DOMAIN_TERMS = {
    "전기사용계약": 1.6, "계약전력": 3.0, "전기요금": 2.6, "요금적용전력": 3.0,
    "공급정지": 3.0, "공급의 중지": 3.0, "위약금": 3.0, "시설부담금": 3.0,
    "역률": 3.0, "검침": 3.0, "전력량계": 3.0, "계량기": 2.6, "이의신청": 3.0,
    "연체료": 3.0, "명의변경": 3.4, "전기사용계약자": 3.0, "계약종별": 3.0,
    "증설": 2.2, "감소": 2.0, "해지": 2.4, "휴지": 2.4, "재사용": 2.2,
    "납기일": 3.0, "납부": 2.0, "보증금": 2.6, "보증": 1.8, "수급지점": 2.6,
    "수급개시일": 2.6, "전기사용장소": 2.6, "안전관리": 2.2, "점검": 1.8,
    "과오납": 2.6, "환불": 2.2, "정산": 1.8, "계절": 1.6, "시간대": 1.8,
    "최대수요전력": 3.0, "초과사용": 2.8, "부가금": 2.4, "감액": 2.4,
    "전기설비": 2.0, "고객": 0.4, "한전": 1.2, "요금": 1.6, "정전": 2.4,
}

#: 같은 뜻으로 쓰이는 표현. 문서에는 '명의변경'이라 썼는데 약관은 '계약자의 변경'이라고 쓰는 식의
#: 간극을 메운다(비교할 때는 띄어쓰기를 지운 형태로 본다).
TERM_ALIASES = {
    "명의변경": ("전기사용계약자의변경", "계약자의변경", "계약자변경"),
    "계량기": ("전력량계",),
    "공급정지": ("공급의중지", "공급중지", "사용의제한"),
    "검침": ("검침일",),
    "연체료": ("연체",),
    "과오납": ("재계산", "환불"),
    "전기요금": ("요금",),
    "초과사용": ("초과사용부가금",),
    "시설부담금": ("시설부담",),
    "이의신청": ("이의신청",),
    "계약종별": ("계약종별",),
    "전기사용계약": ("전기사용계약", "전기사용계약자"),
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


# ---------------------------------------------------------------------------
# 파싱
# ---------------------------------------------------------------------------

ARTICLE_RE = re.compile(
    r"^제\s+(\d+)\s+조(?:\s*의\s*(\d+))?\s*(\(\s*[^\)\n]{0,40}\)|\[\s*[^\]\n]{0,40}\]|<삭\s*제>)",
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
        chapter = toc_info.get("chapter", "")

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


def _domain_hits(sentence: str, unit_text: str) -> list:
    """문장에 나온 업무 용어가 조문 본문·제목에 있는지(동의어 포함)."""
    compact_unit = re.sub(r"\s+", "", unit_text)
    hits = []
    for term, weight in DOMAIN_TERMS.items():
        if term not in sentence:
            continue
        candidates = (term,) + TERM_ALIASES.get(term, ())
        if any(candidate in compact_unit for candidate in candidates):
            hits.append((term, weight))
    return hits


def match_units(reg: Regulation, handover_text: str, *, top_k: int = 3,
                threshold: float = 2.4) -> dict:
    """인수인계 문장마다 근거 후보 조문을 찾는다(BM25 + 업무용어 가중)."""
    idf = reg.idf
    sentences = _sentences(handover_text)
    unit_tokens = []
    for unit in reg.units:
        tokens = _tokens(unit.text) + _tokens(unit.article_title)
        unit_tokens.append((tokens, set(tokens), len(tokens)))
    average_length = (sum(length for _, _, length in unit_tokens) / len(unit_tokens)) if unit_tokens else 1
    k1, b = 1.4, 0.7
    results = []

    for sentence in sentences:
        sentence_tokens = set(_tokens(sentence))
        if not sentence_tokens:
            continue
        scored = []
        for index, unit in enumerate(reg.units):
            tokens, token_set, length = unit_tokens[index]
            shared = sentence_tokens & token_set
            domain_hits = _domain_hits(sentence, unit.text + " " + unit.article_title)
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
            score += 1.6 * min(len(domain_hits), 2)
            if score > 0:
                strong_words = sorted(
                    (t for t in shared if idf.get(t, 0) >= 1.1), key=lambda t: -idf.get(t, 0)
                )[:6]
                scored.append((score, unit, sorted(domain_hits, key=lambda h: -h[1]), strong_words, title_hits))

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
