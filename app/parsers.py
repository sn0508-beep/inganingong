"""파일 형식별 텍스트 추출기.

지원 형식: .pdf / .docx / .hwpx / .hwp(한글 5.0 바이너리) / .txt / .md

각 파서는 원문 텍스트를 최대한 보존하고, 형식 특성상 잃어버리는 정보가 있으면
`warnings`에 남긴다. 화면과 리포트에서 "이 파일은 이런 한계가 있다"를 그대로
보여 주기 위한 것으로, 조용히 실패하지 않게 하려는 장치다.
"""

from __future__ import annotations

import io
import re
import struct
import zipfile
import zlib
from dataclasses import dataclass, field

SUPPORTED_EXTENSIONS = (".pdf", ".docx", ".hwpx", ".hwp", ".txt", ".md")

HWP_SIGNATURE = b"HWP Document File"


class ParseError(Exception):
    """파일을 읽을 수 없을 때."""


@dataclass
class ParsedDocument:
    filename: str
    kind: str                      # pdf | docx | hwpx | hwp | text
    text: str
    pages: list = field(default_factory=list)      # PDF만: 페이지별 텍스트
    warnings: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def to_dict(self):
        return {
            "filename": self.filename,
            "kind": self.kind,
            "text": self.text,
            "pages": self.pages,
            "page_count": len(self.pages),
            "warnings": self.warnings,
            "meta": self.meta,
            "char_count": len(self.text),
            "line_count": self.text.count("\n") + 1 if self.text else 0,
        }


# ---------------------------------------------------------------------------
# 공통 진입점
# ---------------------------------------------------------------------------

def parse_bytes(filename: str, data: bytes) -> ParsedDocument:
    """파일명 확장자를 우선 쓰되, 내용(매직 바이트)이 다르면 내용을 믿는다."""
    name = filename or "붙여넣은 텍스트"
    ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""

    if data[:4] == b"%PDF":
        return _parse_pdf(name, data)
    if data[:4] == b"PK\x03\x04":
        return _parse_zip_based(name, data)
    if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return _parse_hwp(name, data)
    if ext in (".pdf", ".docx", ".hwpx", ".hwp"):
        raise ParseError(
            f"{ext} 형식으로 열리지 않습니다(파일 내용이 확장자와 다릅니다). "
            "한글/워드에서 다시 저장한 뒤 올려 주세요."
        )
    return _parse_text(name, data)


def parse_pasted(text: str, filename: str = "붙여넣은 텍스트") -> ParsedDocument:
    cleaned = _normalize(text)
    return ParsedDocument(filename=filename, kind="text", text=cleaned,
                          meta={"source": "paste"})


def _normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00a0", " ").replace("\u200b", "")
    lines = [line.rstrip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# 텍스트 / 마크다운
# ---------------------------------------------------------------------------

def _decode_text(data: bytes) -> tuple:
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace"), "utf-8(일부 글자 손상)"


def _parse_text(filename: str, data: bytes) -> ParsedDocument:
    text, enc = _decode_text(data)
    warnings = []
    if enc not in ("utf-8", "utf-8-sig"):
        warnings.append(f"텍스트 인코딩을 {enc}로 추정해 읽었습니다. 글자가 깨지면 UTF-8로 저장해 다시 올려 주세요.")
    return ParsedDocument(filename=filename, kind="text", text=_normalize(text),
                          warnings=warnings, meta={"encoding": enc})


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def _parse_pdf(filename: str, data: bytes) -> ParsedDocument:
    pages, warnings, engine = [], [], None

    try:  # PyMuPDF가 있으면 한글 추출 품질이 좋아 우선 사용
        import pymupdf  # type: ignore

        doc = pymupdf.open(stream=data, filetype="pdf")
        pages = [page.get_text() for page in doc]
        meta = {k: v for k, v in (doc.metadata or {}).items() if v}
        doc.close()
        engine = "pymupdf"
    except Exception:  # pragma: no cover - 폴백 경로
        try:
            import pypdf  # type: ignore

            reader = pypdf.PdfReader(io.BytesIO(data))
            pages = [(p.extract_text() or "") for p in reader.pages]
            meta = {}
            engine = "pypdf"
        except Exception as exc:
            raise ParseError(f"PDF를 읽지 못했습니다: {exc}") from exc

    text = "\n".join(pages)
    if not text.strip():
        raise ParseError(
            "PDF에서 글자를 찾지 못했습니다. 스캔 이미지로만 된 PDF는 지원하지 않습니다(OCR 필요)."
        )
    if len(text.strip()) < 20:
        warnings.append("PDF에서 추출된 글자가 적습니다. 스캔본이면 OCR이 필요합니다.")

    return ParsedDocument(
        filename=filename, kind="pdf", text=_normalize(text), pages=[_normalize(p) for p in pages],
        warnings=warnings, meta={"engine": engine, "page_count": len(pages), **meta},
    )


# ---------------------------------------------------------------------------
# ZIP 계열: .docx / .hwpx
# ---------------------------------------------------------------------------

def _parse_zip_based(filename: str, data: bytes) -> ParsedDocument:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        names = set(zf.namelist())
    except zipfile.BadZipFile as exc:
        raise ParseError(f"압축 파일을 열지 못했습니다: {exc}") from exc

    if "word/document.xml" in names:
        return _parse_docx(filename, data)
    if any(n.startswith("Contents/section") for n in names):
        return _parse_hwpx(filename, data)
    raise ParseError("docx도 hwpx도 아닌 압축 파일입니다. 지원 형식(.pdf/.docx/.hwpx/.hwp/.txt)인지 확인해 주세요.")


def _parse_docx(filename: str, data: bytes) -> ParsedDocument:
    try:
        from docx import Document
    except ImportError as exc:  # pragma: no cover
        raise ParseError("python-docx가 설치되어 있지 않습니다. requirements.txt를 설치해 주세요.") from exc

    try:
        doc = Document(io.BytesIO(data))
    except Exception as exc:
        raise ParseError(f"docx를 읽지 못했습니다: {exc}") from exc

    blocks = []
    warnings = []
    body = doc.element.body
    for child in body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            from docx.text.paragraph import Paragraph

            text = Paragraph(child, doc).text.strip()
            if text:
                style = (Paragraph(child, doc).style.name or "")
                blocks.append(_headingize(text, style))
        elif tag == "tbl":
            from docx.table import Table

            for row in Table(child, doc).rows:
                cells = [c.text.strip().replace("\n", " ") for c in row.cells]
                if any(cells):
                    blocks.append("| " + " | ".join(cells) + " |")
    text = "\n".join(blocks)
    meta = {"paragraphs": len(doc.paragraphs), "tables": len(doc.tables)}
    if doc.inline_shapes:
        warnings.append(f"이미지 {len(doc.inline_shapes)}개는 텍스트로 읽지 않았습니다.")
    if not text.strip():
        raise ParseError("docx에서 텍스트를 찾지 못했습니다. 내용이 이미지로만 들어 있지 않은지 확인해 주세요.")
    return ParsedDocument(filename=filename, kind="docx", text=_normalize(text),
                          warnings=warnings, meta=meta)


def _headingize(text: str, style: str) -> str:
    """워드 제목 스타일이면 마크다운 제목으로 바꿔 섹션 구조를 살린다."""
    if style and style.lower().startswith(("heading", "제목", "title")):
        level = 2
        digits = re.findall(r"\d", style)
        if digits:
            level = min(3, max(1, int(digits[0])))
        return "#" * level + " " + text
    return text


HWPX_TEXT = "{http://www.hancom.co.kr/hwpml/2011/paragraph}t"
HWPX_PARA = "{http://www.hancom.co.kr/hwpml/2011/paragraph}p"
HWPX_TABLE = "{http://www.hancom.co.kr/hwpml/2011/paragraph}tbl"


def _localname(el) -> str:
    tag = el.tag
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _parse_hwpx(filename: str, data: bytes) -> ParsedDocument:
    try:
        from lxml import etree
    except ImportError as exc:  # pragma: no cover
        raise ParseError("lxml이 설치되어 있지 않습니다. requirements.txt를 설치해 주세요.") from exc

    zf = zipfile.ZipFile(io.BytesIO(data))
    sections = sorted(n for n in zf.namelist()
                      if re.fullmatch(r"Contents/section\d+\.xml", n))
    if not sections:
        raise ParseError("hwpx 안에서 본문(section*.xml)을 찾지 못했습니다.")

    lines, warnings = [], []
    for section in sections:
        try:
            root = etree.fromstring(zf.read(section))
        except etree.XMLSyntaxError as exc:
            warnings.append(f"{section}을 읽지 못했습니다: {exc}")
            continue
        lines.extend(_hwpx_walk(root))

    text = "\n".join(line for line in lines if line.strip())
    meta = {"sections": len(sections)}
    names = zf.namelist()
    if any(n.startswith("BinData/") for n in names):
        warnings.append("hwpx에 포함된 이미지·개체는 텍스트로 읽지 않았습니다.")
    if not text.strip():
        raise ParseError("hwpx에서 텍스트를 찾지 못했습니다. 내용이 표·이미지로만 되어 있는지 확인해 주세요.")
    return ParsedDocument(filename=filename, kind="hwpx", text=_normalize(text),
                          warnings=warnings, meta=meta)


def _hwpx_walk(root) -> list:
    """문단은 줄 단위로, 표는 행 단위(' | ' 구분)로 펼친다."""
    lines = []

    def para_text(para, skip_tables=True):
        parts = []

        def rec(el):
            for child in el:
                name = _localname(child)
                if name == "t":
                    parts.append("".join(child.itertext()))
                elif name == "tbl" and skip_tables:
                    continue          # 표는 행 단위로 따로 펼친다
                elif name == "p":
                    continue          # 중첩 문단은 자기 차례에 처리
                else:
                    rec(child)

        rec(para)
        return "".join(parts).strip()

    def emit_table(tbl):
        for tr in tbl:
            if _localname(tr) != "tr":
                for deeper in tr.iterchildren() if hasattr(tr, "iterchildren") else []:
                    if _localname(deeper) == "tr":
                        emit_row(deeper)
                continue
            emit_row(tr)

    def emit_row(tr):
        cells, nested = [], []
        for tc in tr:
            if _localname(tc) != "tc":
                continue
            cell_paras = [p for p in tc.iter() if _localname(p) == "p"]
            cells.append(" ".join(" ".join(para_text(p).split()) for p in cell_paras))
            nested.extend(c for c in tc.iter() if _localname(c) == "tbl")
        if any(cells):
            lines.append("| " + " | ".join(cells) + " |")
        for sub in nested:
            emit_table(sub)

    def walk(el):
        for child in el:
            name = _localname(child)
            if name == "tbl":
                emit_table(child)
            elif name == "p":
                text = para_text(child)
                if text:
                    lines.append(text)
                for sub in child:
                    walk(sub)          # 문단 안에 들어 있는 표·개체
            else:
                walk(child)

    walk(root)
    return lines


# ---------------------------------------------------------------------------
# HWP 5.0 (바이너리, CFB 컨테이너)
# ---------------------------------------------------------------------------

HWPTAG_PARA_TEXT = 67
#: 문단 텍스트 안의 제어 문자 중 뒤에 8바이트(4 WCHAR) 확장 데이터가 붙는 코드
_HWP_EXTENDED_CONTROLS = {1, 2, 3, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23}


def _parse_hwp(filename: str, data: bytes) -> ParsedDocument:
    try:
        import olefile
    except ImportError as exc:  # pragma: no cover
        raise ParseError("olefile이 설치되어 있지 않습니다. requirements.txt를 설치해 주세요.") from exc

    try:
        ole = olefile.OleFileIO(io.BytesIO(data))
    except Exception as exc:
        raise ParseError(f"한글 파일 컨테이너를 열지 못했습니다: {exc}") from exc

    if not ole.exists("FileHeader"):
        raise ParseError("한글 5.0 문서가 아닙니다(FileHeader 없음).")

    header = ole.openstream("FileHeader").read()
    if not header.startswith(HWP_SIGNATURE):
        raise ParseError("한글 5.0 문서가 아닙니다(서명 불일치).")

    version = struct.unpack_from("<I", header, 32)[0]
    props = struct.unpack_from("<I", header, 36)[0]
    compressed = bool(props & 0x01)
    encrypted = bool(props & 0x02)
    if encrypted:
        raise ParseError("암호가 설정된 한글 문서는 읽을 수 없습니다. 암호를 해제하고 다시 올려 주세요.")

    warnings = []
    lines = []
    sections = sorted(p for p in ole.listdir()
                      if len(p) == 2 and p[0] == "BodyText")
    for section in sections:
        raw = ole.openstream(section).read()
        if compressed:
            try:
                raw = zlib.decompress(raw, -15)
            except zlib.error:
                warnings.append(f"{'/'.join(section)} 압축을 풀지 못해 일부 내용이 빠질 수 있습니다.")
                continue
        for tag, _level, payload in _iter_hwp_records(raw):
            if tag != HWPTAG_PARA_TEXT:
                continue
            line = _decode_para_text(payload)
            if line.strip():
                lines.append(line)

    if not lines and ole.exists("PrvText"):
        preview = ole.openstream("PrvText").read().decode("utf-16-le", errors="replace")
        warnings.append("본문 스트림을 읽지 못해 미리보기 텍스트로 대체했습니다(서식·표 구조 손실).")
        lines = [line for line in preview.split("\n") if line.strip()]

    ole.close()
    text = "\n".join(lines)
    if not text.strip():
        raise ParseError("한글 문서에서 텍스트를 찾지 못했습니다.")

    warnings.append("구형 .hwp는 글자만 추출하며 표는 행 순서의 텍스트로 펴집니다(서식 손실).")
    return ParsedDocument(
        filename=filename, kind="hwp", text=_normalize(text), warnings=warnings,
        meta={
            "version": f"{version >> 24}.{(version >> 16) & 0xFF}.{(version >> 8) & 0xFF}.{version & 0xFF}",
            "compressed": compressed,
            "sections": len(sections),
        },
    )


def _iter_hwp_records(raw: bytes):
    i, n = 0, len(raw)
    while i + 4 <= n:
        header = struct.unpack_from("<I", raw, i)[0]
        i += 4
        tag = header & 0x3FF
        level = (header >> 10) & 0x3FF
        size = (header >> 20) & 0xFFF
        if size == 0xFFF:
            if i + 4 > n:
                break
            size = struct.unpack_from("<I", raw, i)[0]
            i += 4
        payload = raw[i:i + size]
        i += size
        yield tag, level, payload


def _decode_para_text(payload: bytes) -> str:
    """HWPTAG_PARA_TEXT: UTF-16LE + 인라인 제어 문자."""
    out = []
    i, n = 0, len(payload)
    while i + 1 < n:
        code = struct.unpack_from("<H", payload, i)[0]
        i += 2
        if code == 0:
            continue
        if code in (10, 13):            # 줄/문단 나눔
            out.append("\n")
        elif code == 9:                 # 탭
            out.append("\t")
        elif code < 32:                 # 인라인 제어 문자
            if code in _HWP_EXTENDED_CONTROLS:
                i += 8
        else:
            out.append(chr(code))
    return "".join(out).strip()
