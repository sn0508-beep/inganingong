"""Flask 서버 — 화면 4단계에 대응하는 API.

상태는 서버에 저장하지 않는다(프로토타입). 브라우저가 초안·답변·선택을 들고 다니고,
서버는 요청마다 계산만 한다. 덕분에 서버를 껐다 켜도 사용자가 쓰던 화면이 유지된다.
예외는 '업로드한 규정 PDF'뿐이며, 메모리에만 두고 재시작하면 사라진다.
"""

from __future__ import annotations

import io
import time
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file

from . import export, gap, masking, terms
from .checklist import DIMENSIONS
from .content import SAMPLE_DRAFT, SAMPLE_NOTICE, TEMPLATE_TEXT
from .llm import LLMClient
from .parsers import ParseError, parse_bytes, parse_pasted

BASE_DIR = Path(__file__).resolve().parent
SAMPLE_DIR = BASE_DIR / "samples"
KEPCO_PDF = SAMPLE_DIR / "regulation" / "kepco_basic_supply_terms.pdf"
KEPCO_SOURCE = (
    "https://www.easylaw.go.kr/CSP/FlDownload.laf?flSeq=1776753697728"
    "(법제처 찾기쉬운 생활법령정보 게시본, 한국전력공사 기본공급약관 2026. 4. 1 시행본)"
)
MAX_UPLOAD = 25 * 1024 * 1024

HANDOVER_SAMPLES = [
    ("md", "handover_sample.md", "마크다운(.md)"),
    ("docx", "handover_sample.docx", "워드(.docx)"),
    ("hwpx", "handover_sample.hwpx", "한글(.hwpx)"),
    ("pdf", "handover_sample.pdf", "PDF(.pdf)"),
]

UPLOADED: dict = {}


def create_app() -> Flask:
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD
    app.json.ensure_ascii = False

    cache: dict = {}

    def builtin_regulation() -> terms.Regulation:
        if "kepco" not in cache:
            data = KEPCO_PDF.read_bytes()
            parsed = parse_bytes(KEPCO_PDF.name, data)
            cache["kepco"] = terms.parse_regulation(
                parsed, reg_id="kepco", name="한국전력공사 기본공급약관",
                source_url=KEPCO_SOURCE,
                note="전기사업법 제16조에 따라 한전이 공급조건을 정한 공개 약관. 조항 번호와 쪽수는 PDF 원문 기준.",
                version_label=parsed.meta.get("version_label", ""),
            )
        return cache["kepco"]

    def regulation_list() -> list:
        items = [builtin_regulation().summary()]
        items.extend(reg.summary() for reg in UPLOADED.values())
        return items

    # ------------------------------------------------------------------
    # 화면
    # ------------------------------------------------------------------
    @app.get("/")
    def index():
        return render_template(
            "index.html",
            llm=LLMClient().describe(),
            checklist=[
                {
                    "key": d.key, "label": d.label, "summary": d.summary,
                    "guide": d.guide, "misses": list(d.misses), "example": d.example,
                }
                for d in DIMENSIONS
            ],
            sample_notice=SAMPLE_NOTICE,
        )

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------
    @app.get("/api/health")
    def health():
        return jsonify({
            "status": "ok",
            "llm": LLMClient().describe(),
            "samples": {
                "handover": [{"format": f, "filename": n, "label": l,
                              "url": f"/api/samples/handover/{f}"} for f, n, l in HANDOVER_SAMPLES],
                "regulations": regulation_list(),
            },
            "template_available": True,
        })

    @app.get("/api/template")
    def template():
        return jsonify({
            "text": TEMPLATE_TEXT,
            "checklist": [
                {"key": d.key, "label": d.label, "summary": d.summary, "guide": d.guide,
                 "misses": list(d.misses), "example": d.example}
                for d in DIMENSIONS
            ],
        })

    @app.get("/api/samples/handover/<fmt>")
    def handover_sample(fmt: str):
        for key, filename, _label in HANDOVER_SAMPLES:
            if key == fmt:
                path = SAMPLE_DIR / filename
                if not path.exists():
                    return jsonify({"error": "샘플 파일이 없습니다."}), 404
                return send_file(path, as_attachment=True, download_name=filename)
        return jsonify({"error": "지원하지 않는 형식입니다."}), 404

    @app.get("/api/samples/handover-text")
    def handover_sample_text():
        return jsonify({"text": SAMPLE_DRAFT, "notice": SAMPLE_NOTICE})

    @app.get("/api/samples/regulation/<reg_id>")
    def regulation_file(reg_id: str):
        path = KEPCO_PDF if reg_id == "kepco" else None
        if path and path.exists():
            return send_file(path, as_attachment=True, download_name="한국전력공사_기본공급약관.pdf")
        return jsonify({"error": "파일을 찾을 수 없습니다."}), 404

    @app.post("/api/parse")
    def parse_upload():
        upload = request.files.get("file")
        if not upload or not upload.filename:
            return jsonify({"error": "파일이 없습니다."}), 400
        data = upload.read()
        if len(data) > MAX_UPLOAD:
            return jsonify({"error": "파일이 너무 큽니다(최대 25MB)."}), 413
        try:
            parsed = parse_bytes(upload.filename, data)
        except ParseError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify(parsed.to_dict())

    @app.post("/api/paste")
    def parse_paste():
        payload = request.get_json(silent=True) or {}
        text = (payload.get("text") or "").strip()
        if not text:
            return jsonify({"error": "붙여넣은 내용이 비어 있습니다."}), 400
        return jsonify(parse_pasted(text).to_dict())

    @app.post("/api/mask")
    def mask_preview():
        payload = request.get_json(silent=True) or {}
        text = payload.get("text") or ""
        masked = masking.mask_text(text)
        enabled = bool(payload.get("mask", True))
        return jsonify({
            "report": masking.mask_report(masked),
            "preview": (masked.text if enabled else text)[:600],
            "masked_count": masked.total,
            "llm_active": not LLMClient().is_demo,
        })

    @app.post("/api/analyze")
    def analyze():
        payload = request.get_json(silent=True) or {}
        text = (payload.get("text") or "").strip()
        if len(text) < 20:
            return jsonify({"error": "분석할 내용이 너무 짧습니다. 초안을 20자 이상 입력해 주세요."}), 400
        answers = payload.get("answers") or {}
        mask_enabled = bool(payload.get("mask", True))

        masked = masking.mask_text(text)
        result = gap.analyze(
            text,
            answers=answers,
            llm=LLMClient(),
            masked_text=masked.text if mask_enabled else text,
        )
        result["masking"] = {
            "enabled": mask_enabled,
            "report": masking.mask_report(masked),
            "preview": (masked.text if mask_enabled else text)[:600],
        }
        return jsonify(result)

    @app.get("/api/regulations")
    def regulations():
        return jsonify({"items": regulation_list()})

    @app.post("/api/regulations")
    def upload_regulation():
        upload = request.files.get("file")
        if not upload or not upload.filename:
            return jsonify({"error": "파일이 없습니다."}), 400
        data = upload.read()
        try:
            parsed = parse_bytes(upload.filename, data)
        except ParseError as exc:
            return jsonify({"error": str(exc)}), 400
        reg_id = f"up-{int(time.time() * 1000)}"
        name = (request.form.get("name") or Path(upload.filename).stem).strip()
        reg = terms.parse_regulation(parsed, reg_id=reg_id, name=name, uploaded=True,
                                     note="사용자가 올린 규정 파일", version_label=parsed.meta.get("version_label", ""))
        if not reg.units:
            return jsonify({"error": "규정 파일에서 조문을 찾지 못했습니다."}), 400
        UPLOADED[reg_id] = reg
        return jsonify({"regulation": reg.summary()})

    @app.post("/api/terms")
    def match_terms():
        payload = request.get_json(silent=True) or {}
        text = (payload.get("text") or "").strip()
        reg_id = payload.get("regulation_id") or "kepco"
        if not text:
            return jsonify({"error": "인수인계 초안이 비어 있습니다."}), 400
        if reg_id == "kepco":
            reg = builtin_regulation()
        elif reg_id in UPLOADED:
            reg = UPLOADED[reg_id]
        else:
            return jsonify({"error": "규정을 찾을 수 없습니다. 다시 선택해 주세요."}), 404
        result = terms.match_units(reg, text)
        result["regulation"] = reg.summary()
        return jsonify(result)

    @app.post("/api/export")
    def export_document():
        payload = request.get_json(silent=True) or {}
        text = (payload.get("text") or "").strip()
        analysis = payload.get("analysis") or {}
        meta = payload.get("meta") or {}
        terms_result = payload.get("terms") or None
        if not text:
            return jsonify({"error": "내보낼 초안이 없습니다."}), 400
        markdown, plain = export.build(meta, text, analysis, terms_result)
        return jsonify({
            "markdown": markdown,
            "text": plain,
            "filename": export.filename(meta),
        })

    @app.errorhandler(413)
    def too_large(_error):
        return jsonify({"error": "파일이 너무 큽니다(최대 25MB)."}), 413

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=False)
