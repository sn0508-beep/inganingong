"""feature/web-prototype 의 Flask 화면을 GitHub Pages 용 정적 사이트로 빌드한다.

하는 일
1. Flask 테스트 클라이언트로 `/` 를 렌더링해 index.html 을 만든다(템플릿·가이드 12항목 포함).
2. 화면이 서버에 묻던 `/api/...` 응답을 브라우저에서 계산할 수 있도록 필요한 데이터를
   data/*.json 으로 내보낸다(체크리스트 신호·샘플 초안·약관 조문 단위·IDF·용어 가중치).
3. 정적 사이트에서 그대로 쓰는 파일(app.css, app.js, 폰트, 샘플)을 복사한다.
4. 같은 로직을 JS 로 옮긴 demo-core.js 의 결과를 Python 결과와 대조할 수 있도록
   data/expected.json(골든 값)을 만든다.

사용법
    python3 build/build_static.py --repo ../inganingong --site .

`--site` 폴더에 사이트 파일을 쓴다(기존 파일 중 우리가 만드는 것만 덮어쓴다).
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import shutil
import sys
from pathlib import Path

FIXED_NOW = "2026-11-28 14:00"          # 골든 값 비교용 고정 시각
FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<rect width="64" height="64" rx="14" fill="#1d5b86"/>'
    '<text x="32" y="45" font-family="Pretendard,Apple SD Gothic Neo,Malgun Gothic,sans-serif"'
    ' font-size="38" font-weight="700" fill="#fff" text-anchor="middle">\uc778</text>'
    '</svg>\n'
)
DEMO_NOTE = (
    "GitHub Pages 정적 시연 버전 · <code>feature/web-prototype</code> UI 미리보기 — "
    "서버 없이 브라우저에서 4단계가 모두 동작합니다"
)


def load_app_modules(repo: Path):
    sys.path.insert(0, str(repo))
    from app import ai_modes, export, gap, internal_terms, masking, terms  # noqa: F401
    from app.checklist import DIMENSIONS, VAGUE_PATTERNS
    from app.content import SAMPLE_DRAFT, SAMPLE_NOTICE, TEMPLATE_TEXT
    from app.parsers import parse_bytes
    from app.server import create_app

    return {
        "ai_modes": ai_modes,
        "export": export,
        "gap": gap,
        "internal_terms": internal_terms,
        "masking": masking,
        "terms": terms,
        "DIMENSIONS": DIMENSIONS,
        "VAGUE_PATTERNS": VAGUE_PATTERNS,
        "SAMPLE_DRAFT": SAMPLE_DRAFT,
        "SAMPLE_NOTICE": SAMPLE_NOTICE,
        "TEMPLATE_TEXT": TEMPLATE_TEXT,
        "parse_bytes": parse_bytes,
        "create_app": create_app,
    }


# ---------------------------------------------------------------------------
# index.html
# ---------------------------------------------------------------------------

def render_index(mods: dict, repo: Path) -> str:
    app = mods["create_app"]()
    client = app.test_client()
    response = client.get("/")
    if response.status_code != 200:
        raise SystemExit(f"index 렌더링 실패: HTTP {response.status_code}")
    html = response.get_data(as_text=True)

    # 정적 경로 (템플릿은 /static/... 으로 렌더링된다 → 같은 폴더 기준 상대 경로로)
    html = html.replace("/static/app.css", "app.css")
    html = html.replace('src="/static/app.js"', 'src="app.js"')
    html = html.replace(
        '<script src="app.js"></script>',
        '<script src="demo-core.js"></script>\n'
        '<script src="demo-api.js"></script>\n'
        '<script src="app.js"></script>',
    )
    html = html.replace(
        '<link rel="stylesheet" href="app.css" />',
        '<link rel="stylesheet" href="app.css" />\n<link rel="stylesheet" href="demo.css" />',
    )
    html = html.replace(
        '<meta name="viewport" content="width=device-width, initial-scale=1" />',
        '<meta name="viewport" content="width=device-width, initial-scale=1" />\n'
        '<link rel="icon" href="favicon.svg" type="image/svg+xml" />',
    )

    # 샘플 파일 링크: 서버 API 대신 저장소에 함께 올린 샘플 파일을 가리킨다.
    html = html.replace('href="/api/samples/handover/md"', 'href="samples/handover_sample.md" download')
    html = html.replace('href="/api/samples/handover/docx"', 'href="samples/handover_sample.docx" download')
    html = html.replace('href="/api/samples/handover/hwpx"', 'href="samples/handover_sample.hwpx" download')
    html = re.sub(r"\s*<a href=\"/api/samples/handover/pdf\">\.pdf</a>", "", html)

    # 정적 시연 안내 한 줄 (상단 바 아래)
    bar = (
        '\n<div class="demo-bar" role="note">\n'
        '  <div class="demo-bar-inner">\n'
        '    <span class="demo-bar-tag">정적 시연</span>\n'
        f'    <span class="demo-bar-text">{DEMO_NOTE}</span>\n'
        '  </div>\n'
        '</div>\n'
    )
    html = html.replace("</header>", "</header>" + bar, 1)

    # 1단계 파일 안내 문구: 정적 버전에서 실제로 읽는 형식만 남긴다.
    html = html.replace(
        ".hwp · .hwpx · .docx · .pdf · .txt · .md (최대 25MB)",
        ".docx · .hwpx · .md · .txt (브라우저에서 바로 읽음)",
    )
    return html


# ---------------------------------------------------------------------------
# data/*.json
# ---------------------------------------------------------------------------

def checklist_data(mods: dict) -> dict:
    dims = []
    for d in mods["DIMENSIONS"]:
        dims.append({
            "key": d.key,
            "label": d.label,
            "summary": d.summary,
            "guide": d.guide,
            "misses": list(d.misses),
            "example": d.example,
            "signals": [
                {"key": s.key, "label": s.label,
                 "patterns": list(s.patterns), "weight": s.weight}
                for s in d.signals
            ],
            "base_question": d.base_question,
            "signal_questions": dict(d.signal_questions),
            "why": d.why,
        })
    return {
        "dimensions": dims,
        "vague_patterns": [[pattern, reason] for pattern, reason in mods["VAGUE_PATTERNS"]],
    }


def samples_data(mods: dict) -> dict:
    return {
        "sample_text": mods["SAMPLE_DRAFT"],
        "sample_notice": mods["SAMPLE_NOTICE"],
        "template_text": mods["TEMPLATE_TEXT"],
    }


def build_regulation(repo: Path, mods: dict):
    """내장 샘플 약관을 조문 단위로 파싱한다(화면 데이터·골든 값이 같은 객체를 쓴다)."""
    terms = mods["terms"]
    pdf = repo / "app" / "samples" / "regulation" / "kepco_basic_supply_terms.pdf"
    parsed = mods["parse_bytes"](pdf.name, pdf.read_bytes())
    return terms.parse_regulation(
        parsed, reg_id="kepco", name="한국전력공사 기본공급약관",
        source_url="https://www.easylaw.go.kr/CSP/FlDownload.laf?flSeq=1776753697728",
        note="전기사업법 제16조에 따라 한전이 공급조건을 정한 공개 약관. 조항 번호와 쪽수는 PDF 원문 기준.",
        version_label=parsed.meta.get("version_label", ""),
    )


def regulation_data(repo: Path, mods: dict) -> dict:
    terms = mods["terms"]
    reg = build_regulation(repo, mods)
    summary = reg.summary()
    summary["warnings"] = []          # 규정 파일 자체의 그림 안내는 화면에 쓰지 않는다
    units = []
    for u in reg.units:
        units.append({
            "article_no": u.article_no,
            "title": u.article_title,
            "chapter": u.chapter,
            "paragraph": u.paragraph,
            "printed_page": u.printed_page,
            "pdf_page": u.pdf_page,
            "kind": u.kind,
            "location": u.location,
            "text": u.text,
            "tokens": terms._tokens(u.text) + terms._tokens(u.article_title),
        })
    return {
        "summary": summary,
        "units": units,
        "idf": reg.idf,
        "terms": reg.matching_terms(),
        "particles": list(terms.PARTICLES),
        "stopwords": sorted(terms.STOPWORDS),
        "aliases": {key: list(value) for key, value in terms.TERM_ALIASES.items()},
        "disclaimer": terms.DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# 골든 값 (demo-core.js 자체 점검용)
# ---------------------------------------------------------------------------

ANSWER_SAMPLE = {
    "exception::case": {"text": "명의변경 서류가 부족해 반려되는 건이 달에 3~4건 있습니다. 대리인이 오면 위임장 원본을 확인합니다.", "skipped": False},
    "exception::escalation": {"text": "공급정지 처리는 금액과 관계없이 팀장 승인 후 진행합니다.", "skipped": False},
    "pending::items": {"text": "", "skipped": True},
    "documents::path": {"text": "계약 서식 원본은 공유드라이브 고객지원/계약/_양식 폴더에 있습니다.", "skipped": False},
}

EXPORT_META = {
    "author": "김하늘 대리",
    "successor": "이도윤 주임",
    "team": "고객지원팀 계약·요금 업무",
    "period": "2026-12-01 ~ 2026-12-05",
    "base": "가상 샘플 인수인계서",
}


class _FixedNow:
    """골든 값이 매일 달라지지 않도록 문서 생성 시각을 고정한다."""

    @classmethod
    def now(cls, tz=None):
        return datetime.datetime(2026, 11, 28, 14, 0)


def expected_data(repo: Path, mods: dict) -> dict:
    gap = mods["gap"]
    export = mods["export"]
    export.datetime = _FixedNow
    masking = mods["masking"]
    terms = mods["terms"]
    sample = mods["SAMPLE_DRAFT"]

    def slim_analysis(result: dict) -> dict:
        return {
            "coverage": [
                {k: row[k] for k in ("key", "status", "draft_ratio", "effective_ratio")}
                for row in result["coverage"]
            ],
            "questions": [
                {k: q.get(k) for k in ("id", "dimension", "priority", "status", "source", "signal")}
                for q in result["questions"]
            ],
            "stats": result["stats"],
            "summary": result["summary"],
        }

    analyses = {
        "sample": slim_analysis(gap.assess(sample, {})),
        "sample_answered": slim_analysis(gap.assess(sample, ANSWER_SAMPLE)),
        "template": slim_analysis(gap.assess(mods["TEMPLATE_TEXT"], {})),
    }

    mask_cases = [
        "연락처 010-1111-2222, 메일 a@b.com, 주민 900101-1234567",
        "계약 상대 ㈜한빛시설관리 김도현 과장 (031-555-0102) / 사업자 123-45-67890",
    ]
    masked = [{"text": case, "masked_count": masking.mask_text(case).total,
               "types": [f.label for f in masking.mask_text(case).findings]} for case in mask_cases]

    pdf = repo / "app" / "samples" / "regulation" / "kepco_basic_supply_terms.pdf"
    parsed = mods["parse_bytes"](pdf.name, pdf.read_bytes())
    reg = build_regulation(repo, mods)
    match = terms.match_units(reg, sample)
    terms_expected = {
        "stats": match["stats"],
        "matches": [
            {
                "sentence": item["sentence"],
                "primary": {k: item["primary"][k] for k in
                            ("article_no", "title", "printed_page", "score", "confidence", "matched_terms", "matched_words", "paragraph", "location")},
                "alternatives": [
                    {k: alt[k] for k in ("article_no", "score", "confidence")}
                    for alt in item["alternatives"]
                ],
                "confidence": item["confidence"],
            }
            for item in match["matches"]
        ],
    }

    analysis = gap.assess(sample, ANSWER_SAMPLE)
    markdown, plain = export.build(EXPORT_META, sample, analysis, match)
    return {
        "analyses": analyses,
        "masked": masked,
        "terms": terms_expected,
        "export": {"markdown": markdown, "text": plain,
                   "filename": export.filename(EXPORT_META)},
        "answers": ANSWER_SAMPLE,
        "meta": EXPORT_META,
    }


# ---------------------------------------------------------------------------
# 파일 복사
# ---------------------------------------------------------------------------

def copy_static(repo: Path, site: Path, assets: Path) -> None:
    """정적 사이트 파일을 복사한다. 직접 쓴 파일(demo-*.js, demo.css, selftest.html)은
    build/ 에 원본을 함께 두어, 이 브랜치만으로도 다시 빌드할 수 있게 한다."""
    handwritten = ("demo-core.js", "demo-api.js", "demo.css", "selftest.html")
    build_dir = site / "build"
    build_dir.mkdir(exist_ok=True)
    if (assets / "build_static.py").resolve() != (build_dir / "build_static.py").resolve():
        shutil.copy2(assets / "build_static.py", build_dir / "build_static.py")
    for name in handwritten:
        source = assets / name
        in_build = build_dir / name
        at_root = site / name
        if source.resolve() != in_build.resolve():
            shutil.copy2(source, in_build)
        if source.resolve() != at_root.resolve():
            shutil.copy2(source, at_root)
    shutil.copy2(repo / "app" / "static" / "app.js", site / "app.js")
    css = (repo / "app" / "static" / "app.css").read_text(encoding="utf-8")
    css = css.replace('url("/static/fonts/PretendardVariable.woff2")', 'url("fonts/PretendardVariable.woff2")')
    (site / "app.css").write_text(css, encoding="utf-8")
    fonts = site / "fonts"
    fonts.mkdir(exist_ok=True)
    shutil.copy2(repo / "app" / "static" / "fonts" / "PretendardVariable.woff2",
                 fonts / "PretendardVariable.woff2")

    samples = site / "samples"
    (samples / "regulation").mkdir(parents=True, exist_ok=True)
    for name in ("handover_sample.md", "handover_sample.docx", "handover_sample.hwpx"):
        shutil.copy2(repo / "app" / "samples" / name, samples / name)
    shutil.copy2(repo / "app" / "samples" / "regulation" / "kepco_basic_supply_terms.pdf",
                 samples / "regulation" / "kepco_basic_supply_terms.pdf")


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=None, separators=(",", ":")),
                    encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="../inganingong")
    ap.add_argument("--site", default=".")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    site = Path(args.site).resolve()
    site.mkdir(parents=True, exist_ok=True)

    mods = load_app_modules(repo)

    (site / "index.html").write_text(render_index(mods, repo), encoding="utf-8")
    write_json(site / "data" / "checklist.json", checklist_data(mods))
    write_json(site / "data" / "samples.json", samples_data(mods))
    write_json(site / "data" / "regulation.json", regulation_data(repo, mods))
    write_json(site / "data" / "expected.json", expected_data(repo, mods))
    (site / ".nojekyll").write_text("", encoding="utf-8")
    (site / "favicon.svg").write_text(FAVICON_SVG, encoding="utf-8")
    copy_static(repo, site, Path(__file__).resolve().parent)

    sizes = {p.name: p.stat().st_size for p in sorted((site / "data").iterdir())}
    print("index.html", (site / "index.html").stat().st_size, "bytes")
    for name, size in sizes.items():
        print(f"data/{name}", size, "bytes")


if __name__ == "__main__":
    main()
