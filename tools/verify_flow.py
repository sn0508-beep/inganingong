"""전체 동작 점검 스크립트 (개발용).

서버를 띄우지 않고 Flask 테스트 클라이언트로 4단계 API를 실제 파일로 한 번씩 호출하고,
보고용 요약을 출력한다. 마지막에 화면 캡처(tools/screenshot.py)를 따로 실행하면 된다.

사용: .venv/bin/python tools/verify_flow.py [hwp 파일 경로]
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.content import SAMPLE_DRAFT  # noqa: E402
from app.server import create_app  # noqa: E402

SAMPLES = ROOT / "app" / "samples"


def main() -> int:
    client = create_app().test_client()
    print("== 1) 상태 확인")
    health = client.get("/api/health").get_json()
    print(f"   상태: {health['status']} / LLM: {health['llm']['label']}")
    reg = health["samples"]["regulations"][0]
    print(f"   내장 규정: {reg['name']} {reg['version_label']} · {reg['page_count']}쪽 · 조문 {reg['article_count']}개")

    print("== 2) 파일 형식별 업로드")
    for name in ("handover_sample.md", "handover_sample.docx", "handover_sample.hwpx", "handover_sample.pdf"):
        data = (SAMPLES / name).read_bytes()
        response = client.post("/api/parse", data={"file": (io.BytesIO(data), name)},
                               content_type="multipart/form-data")
        payload = response.get_json()
        text = payload.get("text", "")
        print(f"   {name:26s} {response.status_code} {payload.get('kind'):5s} {payload.get('char_count'):5d}자 "
              f"'전기사용계약 변경'={'전기사용계약 변경' in text}")

    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
        response = client.post("/api/parse", data={"file": (io.BytesIO(path.read_bytes()), path.name)},
                               content_type="multipart/form-data")
        payload = response.get_json()
        print(f"   {path.name:26s} {response.status_code} {payload.get('kind')} "
              f"{payload.get('char_count')}자 version={payload.get('meta', {}).get('version')}")
        print(f"   경고: {payload.get('warnings')}")

    print("== 3) 2단계 빈틈 점검 (가상 샘플)")
    analysis = client.post("/api/analyze", json={"text": SAMPLE_DRAFT, "answers": {}, "mask": True}).get_json()
    summary, stats = analysis["summary"], analysis["stats"]
    print(f"   커버리지 {int(summary['draft_score'] * 100)}% · 충실 {summary['covered']} / 일부 {summary['partial']} / 비어 있음 {summary['missing']}")
    print(f"   질문 {stats['total']}개 (미답변 {stats['unanswered']})")
    for question in analysis["questions"][:4]:
        print(f"   - [{question['dimension_label']}] {question['question'][:60]}")
    print(f"   가림: {analysis['masking']['report']['summary']}")

    first = analysis["questions"][0]
    answered = client.post("/api/analyze", json={
        "text": SAMPLE_DRAFT,
        "answers": {first["id"]: {"text": "민원 반복 시 팀장 승인 후 처리하고, 과오납 환불은 50만원 초과 시 승인받습니다."}},
        "mask": True,
    }).get_json()
    print(f"   답변 1건 반영 후 커버리지 {int(answered['summary']['effective_score'] * 100)}% "
          f"(미답변 {answered['stats']['unanswered']})")

    print("== 4) 3단계 약관 조항 매칭")
    terms = client.post("/api/terms", json={"text": SAMPLE_DRAFT, "regulation_id": "kepco"}).get_json()
    print(f"   문장 {terms['stats']['sentences']}개 중 {terms['stats']['matched']}개에서 근거 후보, 조문 {terms['stats']['articles']}개")
    for match in terms["matches"][:5]:
        primary = match["primary"]
        print(f"   - {match['sentence'][:38]:40s} → {primary['article_no']} {primary['title']} "
              f"{primary['printed_page']}쪽 ({primary['confidence']})")

    print("== 5) 4단계 내보내기")
    exported = client.post("/api/export", json={
        "meta": {"author": "김하늘 대리", "successor": "이도윤 주임", "team": "고객지원팀 계약·요금 업무",
                 "period": "2026-12-01 ~ 2026-12-05"},
        "text": SAMPLE_DRAFT, "analysis": answered, "terms": terms,
    }).get_json()
    markdown = exported["markdown"]
    print(f"   {exported['filename']}.md · {len(markdown)}자")
    print(f"   미답변 질문 목록 포함: {'아직 답하지 못한 질문 목록' in markdown}")
    print(f"   근거 규정 섹션 포함: {'검토한 근거 규정' in markdown}")
    print(f"   원문 보존(부록 B): {'부록 B' in markdown}")

    print("== 6) 규정 PDF 업로드(동적 색인)")
    data = (SAMPLES / "regulation" / "kepco_basic_supply_terms.pdf").read_bytes()
    uploaded = client.post("/api/regulations", data={"file": (io.BytesIO(data), "my_terms.pdf"), "name": "사내 규정 테스트"},
                           content_type="multipart/form-data")
    summary2 = uploaded.get_json()["regulation"]
    print(f"   {uploaded.status_code} 조문 {summary2['article_count']}개 색인 (id={summary2['id']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
