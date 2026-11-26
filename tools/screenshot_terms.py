"""3단계 약관 근거 화면 캡처 — 사내 표준약관 AI 연결 / 규정 PDF 폴백 (개발용).

서버를 직접 띄우고(스레드), 사내 표준약관 AI 대신 가짜 HTTP 서버를 붙여 다음을 남긴다.

1. 사내 표준약관 AI 미설정 → 규정 PDF 경로로 바로 동작(내장 샘플 매칭 카드)
2. '사내 표준약관 AI'를 골랐을 때의 "연동할 수 있는 사내 표준약관 AI를 찾지 못하였어요" 안내
   + '다시 연결' · '규정 PDF 업로드로 진행하기' 두 버튼
3. 주소를 넣어 연결한 뒤 사내 AI가 돌려준 조항 카드(이유 포함)
4. '규정 PDF 업로드로 진행하기'로 되돌아왔을 때 기존 PDF 카드가 그대로 나오는지

사용:
    .venv/bin/python tools/screenshot_terms.py
결과: screenshots/08~10*.png  (저장소에는 커밋하지 않는다)
"""

from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "screenshots"
PORT = 8013
STUB_PORT = 8792
URL = f"http://127.0.0.1:{PORT}/"

sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402

from app.server import create_app  # noqa: E402


class _StubTermsAI(BaseHTTPRequestHandler):
    """POST {"sentences": [...]} → 조항 후보. 기관마다 다른 규격 중 하나를 흉내 낸다."""

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        sentences = body.get("sentences") or []
        matches = []
        for sentence in sentences:
            if "이의신청" in sentence or "요금" in sentence:
                matches.append({
                    "sentence": sentence,
                    "article_no": "제74조의2",
                    "article_title": "요금에 대한 이의신청",
                    "page": 59,
                    "chapter": "제8장 요금",
                    "excerpt": "고객은 전기요금에 이의가 있는 경우 이의신청을 할 수 있다.",
                    "confidence": "높음",
                    "reason": "이의신청·회신 표현이 조문과 일치합니다.",
                    "matched_terms": ["이의신청"],
                })
            elif "계량기" in sentence or "검침" in sentence:
                matches.append({
                    "sentence": sentence,
                    "article_no": "제37조",
                    "article_title": "전력량계 등의 설치 및 소유",
                    "page": 22,
                    "chapter": "제4장 설비",
                    "excerpt": "전력량계의 고장 여부는 회사가 확인한다.",
                    "confidence": "중간",
                    "reason": "계량기·검침 표현이 겹칩니다.",
                })
        payload = json.dumps({"matches": matches}, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


def main() -> int:
    OUT.mkdir(exist_ok=True)
    os.environ.pop("INTERNAL_TERMS_API_URL", None)

    stub = ThreadingHTTPServer(("127.0.0.1", STUB_PORT), _StubTermsAI)
    threading.Thread(target=stub.serve_forever, daemon=True).start()

    server = make_server("127.0.0.1", PORT, create_app())
    threading.Thread(target=server.serve_forever, daemon=True).start()

    errors: list = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1320, "height": 940}, device_scale_factor=2)
        page.on("console", lambda msg: errors.append(f"console.{msg.type}: {msg.text}")
                if msg.type == "error" else None)
        page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))

        page.goto(URL, wait_until="networkidle")
        page.click("#btn-sample")
        page.wait_for_selector("#btn-next:not([disabled])", timeout=15000)
        page.click("#btn-next")                     # 2단계
        page.wait_for_selector(".question-card", timeout=20000)
        page.click("#btn-next")                     # 3단계
        page.wait_for_selector(".match-card", timeout=25000)
        page.wait_for_timeout(900)

        # 1) 사내 AI 미설정 → 규정 PDF 경로가 기본으로 바로 돈다
        if not page.is_checked('input[name="terms-source"][value="pdf"]'):
            errors.append("기본값: 사내 표준약관 AI 주소가 없으면 규정 PDF 경로가 기본이어야 합니다")
        if page.query_selector("#terms-internal-panel:not([hidden])"):
            errors.append("기본값: PDF 경로인데 사내 AI 패널이 보입니다")
        page.screenshot(path=str(OUT / "08-step3-pdf-default.png"))
        page.screenshot(path=str(OUT / "08-step3-pdf-default-full.png"), full_page=True)

        # 2) 사내 표준약관 AI 선택 → 연결 실패 안내 + 두 버튼
        page.click('#terms-source .ai-option[title="사내 표준약관 AI 연결"]')
        page.wait_for_selector("#terms-notice .ai-notice", timeout=20000)
        page.wait_for_timeout(700)
        notice = page.inner_text("#terms-notice")
        if "연동할 수 있는 사내 표준약관 AI를 찾지 못하였어요." not in notice:
            errors.append(f"안내 문구가 다릅니다: {notice[:80]}")
        if not page.query_selector('[data-terms-action="retry"]') or not page.query_selector('[data-terms-action="pdf"]'):
            errors.append("안내 카드에 '다시 연결'/'규정 PDF' 버튼이 없습니다")
        if not page.query_selector("#terms-pdf-panel[hidden]"):
            errors.append("사내 AI를 골랐는데 PDF 패널이 그대로 보입니다")
        page.screenshot(path=str(OUT / "09-step3-internal-notice.png"))

        # 3) 주소 입력 → 연결 확인 → 사내 AI 조항 카드
        page.click('[data-terms-action="retry"]')
        page.fill("#terms-endpoint", f"http://127.0.0.1:{STUB_PORT}/search")
        page.click('[data-terms-action="test"]')
        page.wait_for_selector("#terms-status.is-on", timeout=20000)
        page.wait_for_selector(".match-card", timeout=20000)
        page.wait_for_timeout(900)
        if not page.query_selector(".match-reason"):
            errors.append("사내 AI 카드에 '왜 이 조문인가'(reason)가 없습니다")
        summary = page.inner_text("#terms-summary")
        if "사내 표준약관 AI" not in summary:
            errors.append("요약에 '가져온 곳: 사내 표준약관 AI'가 없습니다")
        page.screenshot(path=str(OUT / "09-step3-internal-connected.png"))
        page.screenshot(path=str(OUT / "09-step3-internal-connected-full.png"), full_page=True)

        # 4) '규정 PDF로 진행하기' → 기존 PDF 카드로 복귀
        page.click("#btn-terms-to-pdf")
        page.wait_for_selector(".match-card", timeout=25000)
        page.wait_for_timeout(800)
        if page.query_selector("#terms-notice .ai-notice"):
            errors.append("PDF로 바꿨는데 안내 카드가 남아 있습니다")
        if not page.query_selector("#regulation-select option"):
            errors.append("PDF 경로로 돌아왔는데 규정 목록이 비어 있습니다")
        page.screenshot(path=str(OUT / "10-step3-back-to-pdf.png"))

        browser.close()

    server.shutdown()
    stub.shutdown()
    stub.server_close()

    for path in sorted(OUT.glob("0[89]*.png")) + sorted(OUT.glob("10-*.png")):
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
