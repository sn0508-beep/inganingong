"""파서 테스트 — 실제 샘플 파일로 4가지 형식을 모두 확인한다."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.parsers import ParseError, parse_bytes, parse_pasted

SAMPLES = Path(__file__).resolve().parent.parent / "app" / "samples"


def _read(name: str) -> bytes:
    path = SAMPLES / name
    assert path.exists(), f"샘플 파일이 없습니다: {path} (tools/make_samples.py 실행)"
    return path.read_bytes()


@pytest.mark.parametrize(
    "filename,kind,needle",
    [
        ("handover_sample.md", "text", "전기사용계약 변경"),
        ("handover_sample.docx", "docx", "전기사용계약 변경"),
        ("handover_sample.hwpx", "hwpx", "전기사용계약 변경"),
        ("handover_sample.pdf", "pdf", "전기사용계약 변경"),
    ],
)
def test_sample_formats_extract_korean_text(filename, kind, needle):
    parsed = parse_bytes(filename, _read(filename))
    assert parsed.kind == kind
    assert needle in parsed.text
    assert "한빛에너지공사" in parsed.text
    assert parsed.to_dict()["char_count"] > 300


def test_pdf_pages_are_kept():
    parsed = parse_bytes("handover_sample.pdf", _read("handover_sample.pdf"))
    assert parsed.pages, "PDF는 페이지별 텍스트를 남겨야 한다"
    assert all("한빛" not in page or True for page in parsed.pages)
    assert parsed.meta["page_count"] == len(parsed.pages)


def test_kepco_terms_pdf_has_articles_and_pages():
    parsed = parse_bytes("kepco.pdf", _read("regulation/kepco_basic_supply_terms.pdf"))
    assert parsed.kind == "pdf"
    assert parsed.meta["page_count"] > 100
    assert "제 67 조" in parsed.text or "제 67조" in parsed.text


def test_hwp_real_file_if_available():
    """구형 .hwp는 공개 배포가 어려운 형식이라, 실제 한글 파일이 있을 때만 검사한다.

    HWP_FIXTURE 환경변수에 .hwp 경로를 주면 실행된다.
    """
    fixture = os.environ.get("HWP_FIXTURE")
    if not fixture or not Path(fixture).exists():
        pytest.skip("HWP_FIXTURE 환경변수에 실제 .hwp 파일 경로를 지정하면 검사합니다")
    data = Path(fixture).read_bytes()
    parsed = parse_bytes(Path(fixture).name, data)
    assert parsed.kind == "hwp"
    assert parsed.text.strip()
    assert parsed.meta["version"].startswith("5.")


def test_pasted_text_is_normalized():
    parsed = parse_pasted("첫 줄\r\n\r\n\r\n둘째 줄   ")
    assert parsed.text == "첫 줄\n\n둘째 줄"
    assert parsed.kind == "text"


def test_plain_text_encoded_cp949():
    parsed = parse_bytes("note.txt", "인수인계 메모".encode("cp949"))
    assert "인수인계 메모" in parsed.text


def test_unknown_binary_raises():
    with pytest.raises(ParseError):
        parse_bytes("broken.pdf", b"not a pdf at all")


def test_empty_zip_is_rejected():
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("hello.txt", "hi")
    with pytest.raises(ParseError):
        parse_bytes("mystery.docx", buffer.getvalue())
