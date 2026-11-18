"""샘플 인수인계서 파일 생성기 (앱 실행과 무관한 1회성 도구).

만드는 파일
- app/samples/handover_sample.md    : 원문 텍스트
- app/samples/handover_sample.docx  : python-docx
- app/samples/handover_sample.pdf   : reportlab (한글 CID 폰트)
- app/samples/handover_sample.hwpx  : OWPML 최소 구조를 직접 조립

내용은 모두 가상 데이터(app/content.py의 SAMPLE_DRAFT)이며, 실제 기관 자료가 아니다.

사용:  pip install reportlab && .venv/bin/python tools/make_samples.py
      (reportlab은 샘플 PDF를 만들 때만 쓰고, 앱 실행에는 필요 없습니다.)
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.content import SAMPLE_DRAFT, SAMPLE_NOTICE  # noqa: E402

SAMPLE_DIR = ROOT / "app" / "samples"

# 초안을 (종류, 내용) 목록으로 구조화한다. 각 형식 생성기가 같은 구조를 쓴다.
BLOCKS = [
    ("h1", "인수인계서 — 고객지원팀 계약·요금 업무"),
    ("p", "가상 샘플 · 회사명·인물·연락처는 모두 지어낸 값입니다."),
    ("p", "인계자: 김하늘 대리 (고객지원팀) / 인수자: (미정)"),
    ("p", "소속: 한빛에너지공사 고객지원팀 (가상의 회사)"),
    ("p", "인수인계 기간: 2026-12-01 ~ 2026-12-05 / 작성일: 2026-11-18"),
    ("h2", "1. 업무 개요"),
    ("li", "산업용·일반용 고객의 전기사용계약 변경(명의변경, 계약전력 증설·감소) 접수와 처리"),
    ("li", "월간 전기요금 이의신청 접수 및 1차 회신"),
    ("li", "정기 검침 결과 이상치 확인 후 고객 안내"),
    ("h2", "2. 정기 업무"),
    ("li", "매월 초 전월 이의신청 처리 결과를 취합해서 팀장님께 보고"),
    ("li", "분기마다 협력업체와 검침 결과 검토 회의"),
    ("h2", "3. 연락처"),
    ("li", "팀장: 박서준 차장 (010-1234-5678)"),
    ("li", "계량기 협력업체: 한빛계량기서비스 김도현 과장 (031-555-0102)"),
    ("li", "자세한 연락처는 팀 공유 폴더 참고"),
    ("h2", "4. 시스템"),
    ("li", "고객정보 시스템(CIS)에서 계약 변경 등록"),
    ("li", "권한 신청은 정보보호팀에 요청"),
    ("h2", "5. 요금·민원 처리"),
    ("li", "요금 관련 문의는 대부분 규정대로 처리하면 됨"),
    ("li", "연체 고객은 상황에 따라 공급정지까지 진행하는 경우가 있음"),
    ("li", "명의변경 서류가 부족하면 반려"),
    ("h2", "6. 기타"),
    ("li", "진행 중인 건은 담당자에게 문의"),
    ("li", "예산은 팀에서 관리"),
]


# ---------------------------------------------------------------------------
# 마크다운
# ---------------------------------------------------------------------------

def write_markdown() -> Path:
    path = SAMPLE_DIR / "handover_sample.md"
    path.write_text(SAMPLE_DRAFT.strip() + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# 워드 (.docx)
# ---------------------------------------------------------------------------

def write_docx() -> Path:
    from docx import Document
    from docx.shared import Pt

    document = Document()
    style = document.styles["Normal"]
    style.font.name = "맑은 고딕"
    style.font.size = Pt(10.5)

    document.add_heading("인수인계서 — 고객지원팀 계약·요금 업무", level=1)
    note = document.add_paragraph(SAMPLE_NOTICE)
    note.runs[0].italic = True

    table = document.add_table(rows=4, cols=2)
    table.style = "Table Grid"
    rows = [
        ("인계자", "김하늘 대리 (고객지원팀)"),
        ("인수자", "(미정)"),
        ("소속", "한빛에너지공사 고객지원팀 (가상의 회사)"),
        ("인수인계 기간", "2026-12-01 ~ 2026-12-05"),
    ]
    for row, (key, value) in zip(table.rows, rows):
        row.cells[0].text = key
        row.cells[1].text = value

    for kind, text in BLOCKS[5:]:
        if kind == "h2":
            document.add_heading(text, level=2)
        elif kind == "li":
            document.add_paragraph(text, style="List Bullet")
        else:
            document.add_paragraph(text)

    path = SAMPLE_DIR / "handover_sample.docx"
    document.save(path)
    return path


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def _wrap(text: str, width: int) -> list:
    lines, current = [], ""
    for chunk in text.split(" "):
        while len(chunk) > width:
            if current:
                lines.append(current)
                current = ""
            lines.append(chunk[:width])
            chunk = chunk[width:]
        candidate = f"{current} {chunk}".strip()
        if len(candidate) <= width:
            current = candidate
        else:
            lines.append(current)
            current = chunk
    if current:
        lines.append(current)
    return lines


def write_pdf() -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas

    font = "HYSMyeongJo-Medium"
    pdfmetrics.registerFont(UnicodeCIDFont(font))
    path = SAMPLE_DIR / "handover_sample.pdf"
    page_width, page_height = A4
    pdf = canvas.Canvas(str(path), pagesize=A4)
    left, top = 56, page_height - 64
    y = top

    def line(text, size=10.5, gap=17, bold=False):
        nonlocal y
        if y < 70:
            pdf.showPage()
            pdf.setFont(font, size)
            y = top
        pdf.setFont(font, size)
        pdf.drawString(left, y, text)
        y -= gap

    line("인수인계서 — 고객지원팀 계약·요금 업무", size=17, gap=26)
    line("가상 샘플 · 회사명·인물·연락처는 모두 지어낸 값입니다.", size=9, gap=22)
    for kind, text in BLOCKS[2:]:
        if kind == "h2":
            y -= 6
            line(text, size=12.5, gap=19)
        elif kind == "li":
            for index, part in enumerate(_wrap(text, 46)):
                line(("• " if index == 0 else "   ") + part, gap=16)
        else:
            for part in _wrap(text, 48):
                line(part, gap=16)
    line("", gap=6)
    line("※ 이 문서는 인수인계서 AI 프로토타입의 형식 확인용 가상 자료입니다.", size=8.5, gap=14)
    pdf.save()
    return path


# ---------------------------------------------------------------------------
# 한글 (.hwpx) — OWPML 최소 패키지
# ---------------------------------------------------------------------------

MIMETYPE = "application/hwp+zip"

VERSION_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<hv:version xmlns:hv="http://www.hancom.co.kr/hwpml/2011/version" appVersion="11.0.0.0" buildNumber="0" os="10" application="Hancom Office Hangul" tagetApplication="WORDPROCESSOR"/>"""

CONTAINER_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<ocf:container xmlns:ocf="urn:oasis:names:tc:opendocument:xmlns:container">
  <ocf:rootfiles>
    <ocf:rootfile full-path="Contents/content.hpf" media-type="application/hwpml-package+xml"/>
  </ocf:rootfiles>
</ocf:container>"""

CONTENT_HPF = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<opf:package xmlns:opf="http://www.idpf.org/2007/opf/" version="1.0" unique-identifier="hwpml">
  <opf:metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>인수인계서 — 고객지원팀 계약·요금 업무</dc:title>
    <dc:creator>인수인계서 AI 프로토타입 (가상 샘플)</dc:creator>
    <dc:language>ko</dc:language>
  </opf:metadata>
  <opf:manifest>
    <opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>
    <opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>
  </opf:manifest>
  <opf:spine>
    <opf:itemref idref="header" linear="yes"/>
    <opf:itemref idref="section0" linear="yes"/>
  </opf:spine>
</opf:package>"""

MANIFEST_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<odf:manifest xmlns:odf="urn:oasis:names:tc:opendocument:xmlns:manifest/1.0">
  <odf:file-entry odf:full-path="/" odf:media-type="application/hwp+zip"/>
  <odf:file-entry odf:full-path="version.xml" odf:media-type="application/xml"/>
  <odf:file-entry odf:full-path="Contents/content.hpf" odf:media-type="application/hwpml-package+xml"/>
  <odf:file-entry odf:full-path="Contents/header.xml" odf:media-type="application/xml"/>
  <odf:file-entry odf:full-path="Contents/section0.xml" odf:media-type="application/xml"/>
</odf:manifest>"""

HEADER_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<hh:head xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core" version="1.3">
  <hh:beginNum page="1" footnote="1" endnote="1" pic="1" tbl="1" equation="1"/>
  <hh:refList>
    <hh:fontfaces itemCnt="1">
      <hh:fontface lang="HANGUL" fontCnt="1">
        <hh:font id="0" face="함초롬돋움" type="TTF" isEmbedded="0"/>
      </hh:fontface>
    </hh:fontfaces>
    <hh:borderFills itemCnt="1">
      <hh:borderFill id="1" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0">
        <hh:slash type="NONE" Crooked="0" isCounter="0"/>
        <hh:backSlash type="NONE" Crooked="0" isCounter="0"/>
        <hh:leftBorder type="NONE" width="0.1mm" color="#000000"/>
        <hh:rightBorder type="NONE" width="0.1mm" color="#000000"/>
        <hh:topBorder type="NONE" width="0.1mm" color="#000000"/>
        <hh:bottomBorder type="NONE" width="0.1mm" color="#000000"/>
        <hh:diagonal type="SOLID" width="0.1mm" color="#000000"/>
      </hh:borderFill>
    </hh:borderFills>
    <hh:charProperties itemCnt="1">
      <hh:charPr id="0" height="1000" textColor="#000000" shadeColor="none" useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="1">
        <hh:fontRef hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>
        <hh:ratio hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/>
        <hh:spacing hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>
        <hh:relSz hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/>
        <hh:offset hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>
        <hh:italic/>
      </hh:charPr>
    </hh:charProperties>
    <hh:paraProperties itemCnt="1">
      <hh:paraPr id="0" tabPrIDRef="0" condense="0" fontLineHeight="0" snapToGrid="1" suppressLineNumbers="0" checked="0">
        <hh:align horizontal="JUSTIFY" vertical="BASELINE"/>
        <hh:heading type="NONE" idRef="0" level="0"/>
        <hh:breakSetting breakLatinWord="KEEP_WORD" breakNonLatinWord="BREAK_WORD" widowOrphan="0" keepWithNext="0" keepLines="0" pageBreakBefore="0" lineWrap="BREAK"/>
        <hh:autoSpacing eAsianEng="0" eAsianNum="0"/>
        <hh:margin>
          <hc:intent value="0"/>
          <hc:left value="0"/>
          <hc:right value="0"/>
          <hc:prev value="0"/>
          <hc:next value="0"/>
        </hh:margin>
        <hh:lineSpacing type="PERCENT" value="160" unit="HWPUNIT"/>
        <hh:border borderFillIDRef="1" offsetLeft="0" offsetRight="0" offsetTop="0" offsetBottom="0" connect="0" ignoreMargin="0"/>
      </hh:paraPr>
    </hh:paraProperties>
    <hh:styles itemCnt="1">
      <hh:style id="0" type="PARA" name="바탕글" engName="Normal" paraPrIDRef="0" charPrIDRef="0" nextStyleIDRef="0" langID="0" lockForm="0"/>
    </hh:styles>
  </hh:refList>
</hh:head>"""


def _section_xml() -> str:
    paragraphs = []
    for kind, text in BLOCKS:
        size = 1000
        if kind == "h1":
            size = 1800
        elif kind == "h2":
            size = 1300
        prefix = "• " if kind == "li" else ""
        body = (prefix + text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        paragraphs.append(
            f"""    <hp:p paraPrIDRef="0" styleIDRef="0">
      <hp:run charPrIDRef="0"><hp:t>{body}</hp:t></hp:run>
    </hp:p>"""
        )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
        'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
        'xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core">\n'
        + "\n".join(paragraphs)
        + "\n</hs:sec>"
    )


def write_hwpx() -> Path:
    path = SAMPLE_DIR / "handover_sample.hwpx"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", MIMETYPE)
        archive.writestr("version.xml", VERSION_XML)
        archive.writestr("META-INF/container.xml", CONTAINER_XML)
        archive.writestr("META-INF/manifest.xml", MANIFEST_XML)
        archive.writestr("Contents/content.hpf", CONTENT_HPF)
        archive.writestr("Contents/header.xml", HEADER_XML)
        archive.writestr("Contents/section0.xml", _section_xml())
    return path


# ---------------------------------------------------------------------------

def main() -> None:
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    made = [write_markdown(), write_docx(), write_pdf(), write_hwpx()]
    for path in made:
        print(f"  {path.relative_to(ROOT)}  ({path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
