"""그림 감지(image_count)와 보완 메모 테스트.

샘플 문서에는 그림이 없으므로, 그림이 든 docx/hwpx/pdf를 테스트 안에서 직접 만든다.
"""

from __future__ import annotations

import io
import struct
import zipfile
import zlib
from pathlib import Path

import pytest

from app.content import TEMPLATE_TEXT
from app.parsers import parse_bytes
from app.server import create_app

SAMPLES = Path(__file__).resolve().parent.parent / "app" / "samples"


def _png(rgb: tuple) -> bytes:
    """의존성 없이 1x1 PNG를 만든다(색이 다르면 서로 다른 그림 파일이 된다)."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    raw = b"\x00" + bytes(rgb)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _docx_with_images(count: int = 2) -> bytes:
    from docx import Document

    document = Document()
    document.add_paragraph("전기사용계약 변경 인수인계 초안")
    document.add_paragraph("- 담당 업무: 계약 변경 접수, 요금 이의신청 1차 회신")
    for index in range(count):
        document.add_picture(io.BytesIO(_png((10 * index, 120, 200))))
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _hwpx_with_image() -> bytes:
    source = SAMPLES / "handover_sample.hwpx"
    buffer = io.BytesIO()
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as copy:
        for item in original.infolist():
            copy.writestr(item, original.read(item.filename))
        copy.writestr("BinData/BIN0001.png", _png((0, 100, 180)))
    return buffer.getvalue()


def _pdf_with_image() -> bytes:
    pytest.importorskip("reportlab")
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.setFont("Helvetica", 11)
    pdf.drawString(72, 760, "handover note sample text for image counting")
    pdf.drawImage(ImageReader(io.BytesIO(_png((200, 40, 40)))), 72, 640, width=40, height=40)
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


@pytest.fixture(scope="module")
def client():
    app = create_app()
    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        yield test_client


def test_docx_image_count():
    parsed = parse_bytes("with_images.docx", _docx_with_images(2))
    assert parsed.kind == "docx"
    assert parsed.image_count == 2
    assert "전기사용계약 변경" in parsed.text
    assert any("그림 2장" in warning for warning in parsed.warnings)
    assert parsed.to_dict()["image_count"] == 2


def test_hwpx_image_count():
    parsed = parse_bytes("with_image.hwpx", _hwpx_with_image())
    assert parsed.kind == "hwpx"
    assert parsed.image_count == 1
    assert "전기사용계약 변경" in parsed.text
    assert any("그림 1장" in warning for warning in parsed.warnings)


def test_pdf_image_count():
    parsed = parse_bytes("with_image.pdf", _pdf_with_image())
    assert parsed.kind == "pdf"
    assert parsed.image_count >= 1


@pytest.mark.parametrize("filename", [
    "handover_sample.md", "handover_sample.docx", "handover_sample.hwpx", "handover_sample.pdf",
])
def test_text_only_samples_have_no_images(filename):
    parsed = parse_bytes(filename, (SAMPLES / filename).read_bytes())
    assert parsed.image_count == 0


def test_parse_api_returns_image_count(client):
    response = client.post(
        "/api/parse",
        data={"file": (io.BytesIO(_docx_with_images(1)), "handover_with_image.docx")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["image_count"] == 1
    assert payload["text"]


def test_export_includes_image_note(client):
    analysis = client.post("/api/analyze", json={"text": TEMPLATE_TEXT}).get_json()
    response = client.post("/api/export", json={
        "meta": {"author": "테스트", "successor": "후임"},
        "text": TEMPLATE_TEXT,
        "analysis": analysis,
        "image_count": 2,
        "image_note": "3쪽 조직도 — 계약팀 3명, 요금팀 5명",
    })
    assert response.status_code == 200
    payload = response.get_json()
    assert "## 그림 속 내용 보완" in payload["markdown"]
    assert "그림 2장" in payload["markdown"]
    assert "계약팀 3명" in payload["markdown"]
    assert "계약팀 3명" in payload["text"]


def test_export_marks_missing_image_note(client):
    analysis = client.post("/api/analyze", json={"text": TEMPLATE_TEXT}).get_json()
    payload = client.post("/api/export", json={
        "meta": {}, "text": TEMPLATE_TEXT, "analysis": analysis, "image_count": 1,
    }).get_json()
    assert "## 그림 속 내용 보완" in payload["markdown"]
    assert "아직 보완되지 않았습니다" in payload["markdown"]


def test_export_without_images_has_no_image_section(client):
    analysis = client.post("/api/analyze", json={"text": TEMPLATE_TEXT}).get_json()
    payload = client.post("/api/export", json={
        "meta": {}, "text": TEMPLATE_TEXT, "analysis": analysis,
    }).get_json()
    assert "그림 속 내용 보완" not in payload["markdown"]
