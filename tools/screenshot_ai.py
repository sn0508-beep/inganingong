"""AI 연결 모드·그림 감지 화면 캡처 (개발용).

로컬 서버가 떠 있는 상태에서
- 사내 AI를 골랐을 때의 "연동할 수 있는 AI를 찾지 못하였어요" 안내와 대안 버튼
- 주소를 넣어 연결을 확인한 뒤의 그림 감지 배지
- AI 미연결 모드에서 그림 속 내용을 보완하는 카드
를 순서대로 남긴다. 콘솔 오류가 있으면 함께 출력한다.

사용:
    .venv/bin/python run.py &
    .venv/bin/python tools/screenshot_ai.py
결과: screenshots/*.png  (저장소에는 커밋하지 않는다)
"""

from __future__ import annotations

import io
import struct
import sys
import threading
import zipfile
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "screenshots"
URL = "http://127.0.0.1:8000/"
STUB_PORT = 8791

from playwright.sync_api import sync_playwright  # noqa: E402


class _StubAI(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = b'{"data": []}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def _png(rgb: tuple) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    raw = b"\x00" + bytes(rgb)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _docx_with_images(path: Path) -> Path:
    from docx import Document

    document = Document()
    document.add_paragraph("# 인수인계서 — 고객지원팀 계약·요금 업무")
    document.add_paragraph("- 담당 업무: 전기사용계약 변경 접수, 월간 요금 이의신청 1차 회신")
    document.add_paragraph("- 정기 업무: 매월 5일까지 요금 조정 내역 취합, 10일까지 팀 보고")
    document.add_paragraph("- 시스템: 계약관리시스템(권한: 조회·변경), 요금계산기(조회)")
    for color in ((30, 90, 160), (160, 60, 40)):
        document.add_picture(io.BytesIO(_png(color)))
    document.add_paragraph("- 예외: 계량기 오차 의심 민원은 검침팀 재검침 요청 후 회신")
    document.save(path)
    return path


def main() -> int:
    OUT.mkdir(exist_ok=True)
    sample = _docx_with_images(OUT / "sample-with-images.docx")

    stub = ThreadingHTTPServer(("127.0.0.1", STUB_PORT), _StubAI)
    threading.Thread(target=stub.serve_forever, daemon=True).start()

    errors: list = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1320, "height": 940}, device_scale_factor=2)
        page.on("console", lambda msg: errors.append(f"console.{msg.type}: {msg.text}")
                if msg.type == "error" else None)
        page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))

        page.goto(URL, wait_until="networkidle")
        page.wait_for_selector("#draft-input")

        # 1) 사내 AI(텍스트+그림) 선택 → 연결 실패 안내
        page.click('.ai-option[title="사내 AI (텍스트+그림)"]')
        page.wait_for_selector(".ai-notice", timeout=15000)
        page.wait_for_timeout(700)
        page.screenshot(path=str(OUT / "05-ai-fallback-notice.png"))

        # 1b) 대안 버튼 두 가지가 실제로 동작하는지
        page.click('[data-ai-action="external"]')
        page.wait_for_selector(".ai-notice-privacy", timeout=15000)
        page.wait_for_timeout(400)
        if page.query_selector('[data-ai-action="external"]'):
            errors.append("fallback: 외부 AI 모드에서 '외부 AI 연동으로 진행하기'가 다시 보입니다")
        page.click('[data-ai-action="offline"]')
        page.wait_for_selector(".ai-status.is-off", timeout=15000)
        page.wait_for_timeout(400)
        if page.query_selector(".ai-notice"):
            errors.append("fallback: AI 없이 계속하기를 눌렀는데 안내 카드가 남아 있습니다")
        if not page.is_checked('input[value="offline_rules"]'):
            errors.append("fallback: AI 없이 계속하기를 눌렀는데 모드가 바뀌지 않았습니다")
        page.click('.ai-option[title="사내 AI (텍스트+그림)"]')
        page.wait_for_selector(".ai-notice", timeout=15000)
        page.wait_for_timeout(300)

        # 2) 다시 연결하기 → 주소 입력 → 연결 확인
        page.click('[data-ai-action="retry"]')
        page.fill("#ai-endpoint", f"http://127.0.0.1:{STUB_PORT}/v1")
        page.click('[data-ai-action="test"]')
        page.wait_for_selector(".ai-status.is-on", timeout=15000)
        page.wait_for_timeout(500)
        page.screenshot(path=str(OUT / "05b-ai-connected.png"))

        # 3) 그림이 든 docx 업로드 → 2단계: 그림 감지 배지
        page.set_input_files("#file-input", str(sample))
        page.wait_for_selector("#file-status strong", timeout=15000)
        page.wait_for_timeout(900)
        page.click("#btn-next")
        page.wait_for_selector(".image-badge", timeout=15000)
        page.wait_for_timeout(800)
        page.screenshot(path=str(OUT / "06-image-badge.png"))

        # 4) AI 미연결 모드로 바꾸면 같은 문서가 '직접 보완' 카드로 바뀐다
        page.click("#btn-prev")
        page.wait_for_timeout(300)
        page.click('.ai-option[title="AI 미연결 (기본 규칙 점검)"]')
        page.wait_for_timeout(500)
        page.click("#btn-next")
        page.wait_for_selector(".image-card", timeout=15000)
        page.fill("#image-note", "2쪽 조직도 — 계약팀 3명, 요금팀 5명 / 4쪽 화면 캡처 — 신청 메뉴는 [고객지원 > 계약변경]")
        page.wait_for_timeout(700)
        page.screenshot(path=str(OUT / "06-image-supplement.png"))

        # 5) 4단계 문서에 보완 메모가 들어갔는지 확인
        page.click("#btn-next")
        page.wait_for_timeout(1200)
        page.click("#btn-next")
        page.fill("#meta-author", "김하늘 대리")
        page.fill("#meta-successor", "이도윤 주임")
        page.fill("#meta-team", "고객지원팀 계약·요금 업무")
        page.click("#btn-export")
        page.wait_for_selector("#btn-download-md:not([disabled])", timeout=15000)
        page.wait_for_timeout(900)
        preview = page.inner_text("#export-preview")
        if "그림 속 내용 보완" not in preview:
            errors.append("export: 그림 속 내용 보완 항목이 문서에 없습니다")
        page.screenshot(path=str(OUT / "07-export-with-image-note.png"))

        browser.close()
    stub.shutdown()
    stub.server_close()

    for path in sorted(OUT.glob("0[5-7]*.png")):
        print(f"  {path.relative_to(ROOT)}  ({path.stat().st_size:,} bytes)")
    if errors:
        print("\n브라우저 오류:")
        for error in errors:
            print("  -", error)
        return 1
    print("\n브라우저 콘솔 오류 없음")
    return 0


if __name__ == "__main__":
    sys.exit(main())
