"""화면 캡처 + 흐름 점검 도구 (개발용).

로컬 서버가 떠 있는 상태에서 4단계를 순서대로 눌러 가며 스크린샷을 남기고,
브라우저 콘솔 오류가 있으면 함께 출력한다.

사용:
    python run.py &            # 서버 실행
    .venv/bin/python tools/screenshot.py
결과: screenshots/*.png  (저장소에는 커밋하지 않는다)
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "screenshots"
URL = "http://127.0.0.1:8000/"

from playwright.sync_api import sync_playwright  # noqa: E402


def main() -> int:
    OUT.mkdir(exist_ok=True)
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1320, "height": 940}, device_scale_factor=2)
        page.on("console", lambda msg: errors.append(f"console.{msg.type}: {msg.text}") if msg.type == "error" else None)
        page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))

        page.goto(URL, wait_until="networkidle")
        page.wait_for_selector("#draft-input")

        # 1단계: 가상 샘플을 불러온 상태
        page.click("#btn-sample")
        page.wait_for_timeout(2400)
        page.screenshot(path=str(OUT / "01-step1-start.png"))

        # 2단계: 빈틈 점검
        page.click("#btn-next")
        page.wait_for_selector(".question-card", timeout=15000)
        page.wait_for_timeout(1200)
        page.screenshot(path=str(OUT / "02-step2-gap-check.png"))
        page.screenshot(path=str(OUT / "02-step2-full.png"), full_page=True)

        # 답변 하나를 채워 커버리지가 오르는 모습 확인
        card = page.query_selector(".question-card")
        if card:
            card.query_selector("textarea").fill(
                "과오납 환불이 50만원을 넘으면 팀장 승인 후 처리하고, 계량기 오차 의심 시 검침팀에 재검침을 요청합니다."
            )
            page.wait_for_timeout(1600)
            page.screenshot(path=str(OUT / "02-step2-answered.png"))
        stats = page.inner_text("#analysis-summary")

        # 3단계: 약관 매칭
        page.click("#btn-next")
        page.wait_for_selector(".match-card", timeout=20000)
        page.wait_for_timeout(1200)
        page.screenshot(path=str(OUT / "03-step3-terms.png"))

        # 4단계: 문서 생성
        page.click("#btn-next")
        page.fill("#meta-author", "김하늘 대리")
        page.fill("#meta-successor", "이도윤 주임")
        page.fill("#meta-team", "고객지원팀 계약·요금 업무")
        page.fill("#meta-period", "2026-12-01 ~ 2026-12-05")
        page.click("#btn-export")
        page.wait_for_selector("#btn-download-md:not([disabled])", timeout=15000)
        page.wait_for_timeout(2400)
        page.screenshot(path=str(OUT / "04-step4-export.png"))

        browser.close()

    print("요약 카드:", " | ".join(stats.split("\n")))
    for path in sorted(OUT.glob("*.png")):
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
