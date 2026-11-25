/* 인수인계서 AI 프로토타입 — 화면 로직 (프레임워크 없이 동작) */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const state = {
  step: 1,
  text: "",
  source: null,          // {filename, kind, warnings, image_count, ...}
  answers: {},           // qid -> {text, skipped}
  analysis: null,
  mask: true,
  maskReport: null,
  regulationId: "kepco",
  regulations: [],
  terms: null,
  exportDoc: null,
  focusDimension: null,
  questionFilter: "all",
  aiMode: window.__AI_DEFAULT__ || "offline_rules",
  aiCheck: null,
  aiEndpoint: "",
  aiEndpointOpen: false,
  imageNote: "",
};

const STEP_LABELS = ["시작", "빈틈 점검", "약관·규정 근거", "내보내기"];

/* ------------------------------------------------------------------ */
/* 공통 유틸                                                           */
/* ------------------------------------------------------------------ */

function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function debounce(fn, wait) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), wait);
  };
}

let toastTimer = null;
function toast(message) {
  let el = $(".toast");
  if (!el) {
    el = document.createElement("div");
    el.className = "toast";
    document.body.appendChild(el);
  }
  el.textContent = message;
  el.classList.add("is-on");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("is-on"), 1800);
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `요청 실패 (${response.status})`);
  return data;
}

/* ------------------------------------------------------------------ */
/* AI 연결 환경                                                        */
/* ------------------------------------------------------------------ */

const AI_MODES = window.__AI_MODES__ || [];

function currentMode() {
  return AI_MODES.find((mode) => mode.key === state.aiMode)
    || AI_MODES[AI_MODES.length - 1]
    || { key: "offline_rules", label: "AI 미연결", needs: "none", reads_images: false };
}

function syncModeControls() {
  $$('input[name="ai-mode"]').forEach((input) => { input.checked = input.value === state.aiMode; });
  $$(".ai-option").forEach((label) => {
    label.classList.toggle("is-selected", label.querySelector("input")?.value === state.aiMode);
  });
}

function setAiStatus(kind, text) {
  const badge = $("#ai-mode-status");
  if (!badge) return;
  badge.className = `ai-status is-${kind}`;
  $("#ai-mode-status-text").textContent = text;
}

function renderAiDetail() {
  const box = $("#ai-mode-detail");
  if (!box) return;
  const mode = currentMode();
  const endpoint = state.aiCheck?.ok && state.aiCheck.endpoint ? state.aiCheck.endpoint : "";
  box.innerHTML = `<b>${esc(mode.summary || "")}</b><span>${esc(mode.privacy || "")}</span>`
    + (endpoint ? `<span title="${esc(endpoint)}">· ${esc(endpoint)}</span>` : "");
}

function updateModeBadge() {
  const badge = $("#mode-badge");
  if (!badge) return;
  const mode = currentMode();
  $("#mode-label").textContent = mode.label || "AI 미연결";
  badge.title = `${mode.label || ""} · ${mode.summary || ""}`;
  badge.classList.toggle("is-off", state.aiMode === "offline_rules");
  badge.classList.toggle("is-fail", !!state.aiCheck && !state.aiCheck.ok);
}

function selectAiMode(key, { check = true, endpoint = null } = {}) {
  if (!AI_MODES.some((mode) => mode.key === key)) return;
  state.aiMode = key;
  state.aiCheck = null;
  syncModeControls();
  renderAiDetail();
  updateModeBadge();
  updatePrivacyNote(state.maskReport);
  renderImageNotice();
  if (check) runAiCheck(endpoint);
}

let aiCheckToken = 0;

async function runAiCheck(endpoint) {
  const mode = currentMode();
  if (!mode.key) return;
  const token = ++aiCheckToken;

  if (mode.needs === "none") {
    state.aiCheck = { mode: mode.key, ok: true, status: "ready",
      message: "AI 없이 기본 규칙 점검으로 진행합니다." };
    setAiStatus("off", "AI 미연결 · 규칙 점검");
    renderAiNotice(null);
    renderAiDetail();
    updateModeBadge();
    return;
  }

  setAiStatus("check", "연결 확인 중…");
  try {
    const data = await api("/api/ai/check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: mode.key, endpoint: endpoint || undefined }),
    });
    if (token !== aiCheckToken) return;
    state.aiCheck = data;
    if (data.ok) {
      setAiStatus("on", "연결됨");
      renderAiNotice(null);
      toast(data.message || "AI 연결을 확인했습니다");
    } else {
      setAiStatus("fail", "연결 안 됨");
      renderAiNotice(data);
    }
  } catch (error) {
    if (token !== aiCheckToken) return;
    state.aiCheck = { ok: false, message: "연동할 수 있는 AI를 찾지 못하였어요.", reason: error.message };
    setAiStatus("fail", "연결 안 됨");
    renderAiNotice(state.aiCheck);
  }
  renderAiDetail();
  updateModeBadge();
  updatePrivacyNote(state.maskReport);
  renderImageNotice();
}

function renderAiNotice(data) {
  const box = $("#ai-notice");
  if (!box) return;
  if (!data) {
    box.hidden = true;
    box.innerHTML = "";
    return;
  }
  const mode = currentMode();
  const endpointValue = state.aiEndpoint || "";
  const showEndpoint = mode.needs === "internal" && (state.aiEndpointOpen || !!endpointValue);
  box.hidden = false;
  box.innerHTML = `
    <div class="ai-notice" role="status">
      <div class="ai-notice-head">
        <span class="ai-notice-mark">!</span>
        <div>
          <strong>${esc(data.message || "연동할 수 있는 AI를 찾지 못하였어요.")}</strong>
          ${data.reason ? `<p class="muted small">${esc(data.reason)}</p>` : ""}
        </div>
      </div>
      ${mode.external ? `<p class="ai-notice-privacy">${esc(mode.privacy || "")}</p>` : ""}
      <div class="ai-notice-actions">
        <button type="button" class="btn ghost" data-ai-action="retry">${esc(mode.retry_label || "다시 연결하기")}</button>
        ${mode.key !== "external_masked" ? `<button type="button" class="btn ghost" data-ai-action="external">외부 AI 연동으로 진행하기</button>` : ""}
        <button type="button" class="btn" data-ai-action="offline">AI 없이 기본 점검으로 계속하기</button>
      </div>
      ${mode.needs === "internal" ? `
      <div class="ai-endpoint-row" ${showEndpoint ? "" : "hidden"}>
        <label class="field-label" for="ai-endpoint">사내 AI 주소</label>
        <div class="endpoint-line">
          <input id="ai-endpoint" type="text" inputmode="url" placeholder="http://ai.internal/v1" value="${esc(endpointValue)}" />
          <button type="button" class="btn ghost" data-ai-action="test">연결 확인</button>
        </div>
        <p class="muted small">관리자에게 받은 주소를 넣고 연결을 확인하면 그 주소로 점검을 시도합니다. 주소를 모르면 'AI 없이 기본 점검'으로 진행하세요.</p>
      </div>` : ""}
    </div>`;

  const input = $("#ai-endpoint");
  if (input) {
    input.addEventListener("input", () => { state.aiEndpoint = input.value; });
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        runAiCheck(input.value.trim());
      }
    });
  }
}

$("#ai-notice").addEventListener("click", (event) => {
  const button = event.target.closest("[data-ai-action]");
  if (!button) return;
  const action = button.dataset.aiAction;
  const input = $("#ai-endpoint");

  if (action === "offline") {
    selectAiMode("offline_rules");
    toast("AI 없이 기본 점검으로 진행합니다");
    return;
  }
  if (action === "external") {
    state.aiEndpointOpen = false;
    selectAiMode("external_masked");
    toast("개인정보를 가린 사본만 외부로 전송됩니다");
    return;
  }
  if (action === "retry") {
    // 주소 입력이 닫혀 있으면 먼저 열고 포커스를 준다. 다시 누르면 그 주소로 재시도한다.
    if (input && !state.aiEndpointOpen && !state.aiEndpoint) {
      state.aiEndpointOpen = true;
      renderAiNotice(state.aiCheck || { message: "연동할 수 있는 AI를 찾지 못하였어요.", reason: "" });
      $("#ai-endpoint")?.focus();
      return;
    }
    runAiCheck(input ? input.value.trim() : undefined);
    return;
  }
  if (action === "test") runAiCheck(input ? input.value.trim() : undefined);
});

$$('input[name="ai-mode"]').forEach((input) => {
  input.addEventListener("change", () => {
    state.aiEndpointOpen = false;
    selectAiMode(input.value);
  });
});

/* ------------------------------------------------------------------ */
/* 단계 이동                                                           */
/* ------------------------------------------------------------------ */

function canGoNext() {
  if (state.step === 1) return state.text.trim().length >= 20;
  return state.step < 4;
}

function setStep(step) {
  state.step = step;
  $$(".panel").forEach((panel) => panel.classList.toggle("is-active", panel.id === `panel-${step}`));
  $$(".step").forEach((el) => {
    const index = Number(el.dataset.step);
    el.classList.toggle("is-active", index === step);
    el.classList.toggle("is-done", index < step);
  });
  const prev = $("#btn-prev");
  const next = $("#btn-next");
  prev.disabled = step === 1;
  next.disabled = !canGoNext();
  const labels = ["빈틈 점검 →", "약관 근거 확인 →", "내보내기 →"];
  next.textContent = labels[step - 1] || "다음";
  if (step === 4) next.style.visibility = "hidden";
  else next.style.visibility = "visible";

  if (step === 1) $("#step-hint").textContent = "초안을 올리거나 붙여넣으면 다음 단계로 갈 수 있습니다.";
  if (step === 2) $("#step-hint").textContent = "질문에 답하면 커버리지가 올라갑니다. 답을 모르면 건너뛰어도 됩니다.";
  if (step === 3) $("#step-hint").textContent = "약관 조항 매칭은 선택 사항입니다. 건너뛰고 바로 내보내도 됩니다.";
  if (step === 4) $("#step-hint").textContent = "문서를 생성하고 .md / .txt로 내려받으세요.";
  window.scrollTo({ top: 0, behavior: "smooth" });
}

/* ------------------------------------------------------------------ */
/* 1단계                                                               */
/* ------------------------------------------------------------------ */

const draftInput = $("#draft-input");

function syncDraft() {
  state.text = draftInput.value;
  $("#btn-next").disabled = !canGoNext();
}

draftInput.addEventListener("input", () => {
  syncDraft();
  refreshMaskPreview();
});

const refreshMaskPreview = debounce(async () => {
  const panel = $("#mask-report");
  if (!state.text.trim()) { panel.innerHTML = ""; return; }
  try {
    const data = await api("/api/mask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: state.text, mask: state.mask, ai_mode: state.aiMode }),
    });
    state.maskReport = data;
    renderMaskReport(data);
    updatePrivacyNote(data);
  } catch (error) {
    panel.innerHTML = `<span class="muted small">미리보기를 만들지 못했습니다: ${esc(error.message)}</span>`;
  }
}, 500);

function renderMaskReport(data) {
  const panel = $("#mask-report");
  if (!state.mask) {
    panel.innerHTML = `<span class="muted small">가림을 끄면 전화번호·이메일이 그대로 LLM에 전송됩니다(데모 모드에서는 전송 자체가 없음).</span>`;
    return;
  }
  if (!data.report || !data.report.findings.length) {
    panel.innerHTML = `<span class="muted small">가릴 개인정보가 발견되지 않았습니다.</span>`;
    return;
  }
  const chips = data.report.findings
    .map((f) => `<span class="chip">${esc(f.label)} ${f.count}건</span>`)
    .join("");
  const contexts = data.report.findings.flatMap((f) => f.contexts.map((c) => `<div>· ${esc(c)}</div>`)).join("");
  panel.innerHTML = `
    <div><strong>${esc(data.report.summary)}</strong> 가려집니다.</div>
    <div class="chips">${chips}</div>
    <details><summary>LLM에 보내질 문장 미리보기</summary>
      <pre>${esc(data.preview || "")}</pre>
      <div class="small muted" style="margin-top:6px">${contexts}</div>
    </details>`;
}

function updatePrivacyNote(data) {
  const note = $("#privacy-note");
  if (!note) return;
  const mode = currentMode();
  if (!mode.key || mode.key === "offline_rules") {
    note.textContent = "입력한 내용은 외부로 전송되지 않습니다";
    return;
  }
  if (mode.external) {
    if (!state.mask) {
      note.textContent = "가림을 끈 상태 · 원문이 전송됩니다";
      return;
    }
    const count = data?.masked_count ?? state.maskReport?.masked_count ?? 0;
    note.textContent = count ? `개인정보 ${count}건 가림 후 전송` : "가림 후 전송";
    return;
  }
  note.textContent = "사내망 안에서만 처리";
}

function setText(text, meta = {}) {
  draftInput.value = text;
  state.text = text;
  state.source = meta;
  state.imageNote = "";
  $("#btn-next").disabled = !canGoNext();
  renderImageNotice();
  refreshMaskPreview();
}

/* 파일 업로드 */
const dropzone = $("#dropzone");
const fileInput = $("#file-input");

["dragenter", "dragover"].forEach((type) => {
  dropzone.addEventListener(type, (event) => {
    event.preventDefault();
    dropzone.classList.add("is-over");
  });
});
["dragleave", "drop"].forEach((type) => {
  dropzone.addEventListener(type, (event) => {
    event.preventDefault();
    dropzone.classList.remove("is-over");
  });
});
dropzone.addEventListener("drop", (event) => {
  const file = event.dataTransfer.files?.[0];
  if (file) uploadFile(file);
});
fileInput.addEventListener("change", () => {
  const file = fileInput.files?.[0];
  if (file) uploadFile(file);
});

async function uploadFile(file) {
  const status = $("#file-status");
  const warnings = $("#parse-warnings");
  status.textContent = `${file.name} 읽는 중…`;
  warnings.innerHTML = "";
  const form = new FormData();
  form.append("file", file);
  try {
    const data = await api("/api/parse", { method: "POST", body: form });
    setText(data.text, data);
    const images = data.image_count ? ` · 그림 ${data.image_count}장` : "";
    status.innerHTML = `<strong>${esc(data.filename)}</strong> · ${esc(kindLabel(data.kind))} · ${data.char_count.toLocaleString()}자 · ${data.line_count.toLocaleString()}줄${images}`;
    warnings.innerHTML = (data.warnings || []).map((w) => `<li>${esc(w)}</li>`).join("");
    toast(data.image_count ? `초안을 불러왔습니다 · 그림 ${data.image_count}장 감지` : "초안을 불러왔습니다");
  } catch (error) {
    status.textContent = "";
    warnings.innerHTML = `<li>${esc(error.message)}</li>`;
  }
}

function kindLabel(kind) {
  return { pdf: "PDF", docx: "워드", hwpx: "한글(hwpx)", hwp: "한글(hwp)", text: "텍스트" }[kind] || kind;
}

/* ------------------------------------------------------------------ */
/* 그림 감지 안내 (2단계)                                              */
/* ------------------------------------------------------------------ */

function sourceImageCount() {
  return Number(state.source?.image_count || 0);
}

function renderImageNotice() {
  const box = $("#image-notice");
  if (!box) return;
  const count = sourceImageCount();
  if (!count) {
    box.hidden = true;
    box.innerHTML = "";
    return;
  }
  box.hidden = false;
  const mode = currentMode();

  if (mode.reads_images) {
    box.innerHTML = `<div class="image-badge">
      <span class="image-badge-mark">그림 감지</span>
      <span>그림 ${count}장 감지됨 — AI가 그림 속 표기까지 함께 점검하는 모드예요.</span>
    </div>`;
    return;
  }

  box.innerHTML = `<div class="image-card">
    <div class="image-card-head">
      <span class="image-chip">그림 ${count}장</span>
      <strong>그림 속 내용은 직접 한 줄로 보완해 주세요</strong>
    </div>
    <p class="image-card-text">문서에서 그림 ${count}장이 감지되었어요. 현재 모드에서는 그림 속 표기·글자를 읽을 수 없으니, 그림에 표시된 핵심 내용을 아래에 간단히 적어 주세요.</p>
    <textarea id="image-note" rows="3" placeholder="예) 3쪽 조직도 — 계약팀 3명 · 요금팀 5명 / 5쪽 화면 캡처 — 신청 메뉴는 [고객지원 &gt; 계약변경]">${esc(state.imageNote)}</textarea>
    <div class="image-card-foot">
      <span class="muted small">적은 내용은 4단계 문서에 '그림 속 내용 보완'으로 함께 들어갑니다.</span>
      <span class="saved" id="image-note-saved"></span>
    </div>
  </div>`;

  const note = $("#image-note");
  note.addEventListener("input", () => {
    state.imageNote = note.value;
    const saved = $("#image-note-saved");
    saved.textContent = "저장됨";
    clearTimeout(state.imageSavedTimer);
    state.imageSavedTimer = setTimeout(() => { saved.textContent = ""; }, 1400);
  });
  autosize(note);
}

/* 샘플·템플릿 */
$("#btn-sample").addEventListener("click", async () => {
  try {
    const data = await api("/api/samples/handover-text");
    setText(data.text, { filename: "가상 샘플 인수인계서", kind: "text", warnings: [] });
    $("#file-status").innerHTML = "<strong>가상 샘플</strong> · 실제 기관 자료가 아닙니다";
    $("#parse-warnings").innerHTML = "";
    toast("가상 샘플을 불러왔습니다");
  } catch (error) {
    toast(error.message);
  }
});

$("#btn-template").addEventListener("click", async () => {
  try {
    const data = await api("/api/template");
    setText(data.text, { filename: "표준 템플릿", kind: "text", warnings: [] });
    $("#file-status").innerHTML = "<strong>공기업 표준 템플릿</strong> · 12개 항목 뼈대";
    $("#parse-warnings").innerHTML = "";
    toast("표준 템플릿을 열었습니다");
    $$(".guide-item").forEach((item) => item.removeAttribute("open"));
  } catch (error) {
    toast(error.message);
  }
});

/* 탭 */
$$(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    $$(".tab").forEach((t) => t.classList.toggle("is-active", t === tab));
    $$(".tab-panel").forEach((panel) => panel.classList.toggle("is-active", panel.id === `tab-${tab.dataset.tab}`));
  });
});

$("#mask-toggle").addEventListener("change", (event) => {
  state.mask = event.target.checked;
  refreshMaskPreview();
});

$("#btn-prev").addEventListener("click", () => { if (state.step > 1) setStep(state.step - 1); });
$("#btn-next").addEventListener("click", () => {
  if (!canGoNext()) return;
  const next = state.step + 1;
  setStep(next);
  if (next === 2) runAnalysis();
  if (next === 3) ensureTerms();
  if (next === 4) prepareExportStep();
});

/* ------------------------------------------------------------------ */
/* 2단계 — 분석                                                        */
/* ------------------------------------------------------------------ */

async function runAnalysis({ silent = false } = {}) {
  if (state.text.trim().length < 20) return;
  const list = $("#question-list");
  if (!silent && !state.analysis) list.innerHTML = `<div class="empty-state">초안을 점검하는 중…</div>`;
  try {
    const data = await api("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: state.text, answers: state.answers, mask: state.mask, ai_mode: state.aiMode }),
    });
    state.analysis = data;
    renderSummary(data);
    renderCoverage(data);
    renderQuestions();
    updatePrivacyNote({ masked_count: data.masking?.report?.total || 0 });
  } catch (error) {
    list.innerHTML = `<div class="empty-state">${esc(error.message)}</div>`;
  }
}

function renderSummary(analysis) {
  const summary = analysis.summary || {};
  const stats = analysis.stats || {};
  const draft = Math.round((summary.draft_score || 0) * 100);
  const effective = Math.round((summary.effective_score || 0) * 100);
  const items = [
    { label: "초안 기준 커버리지", value: `${draft}`, unit: "%", note: "12개 항목 평균" },
    { label: "답변 반영 커버리지", value: `${effective}`, unit: "%", note: effective > draft ? `+${effective - draft}%p 올라감` : "답변을 적으면 올라갑니다" },
    { label: "항목 상태", value: `${summary.covered || 0}`, unit: `/ ${summary.dimensions || 12}`, note: `일부 ${summary.partial || 0} · 비어 있음 ${summary.missing || 0}` },
    { label: "질문 진행", value: `${stats.answered || 0}`, unit: `/ ${stats.total || 0}`, note: `미답변 ${stats.unanswered || 0} · 건너뜀 ${stats.skipped || 0}` },
  ];
  $("#analysis-summary").innerHTML = items.map((item) => `
    <div class="summary-item">
      <div class="label">${esc(item.label)}</div>
      <div class="value">${esc(item.value)}<small>${esc(item.unit)}</small></div>
      <div class="note">${esc(item.note)}</div>
    </div>`).join("");
}

function renderCoverage(analysis) {
  const list = $("#coverage-list");
  list.innerHTML = (analysis.coverage || []).map((row) => {
    const draft = Math.round(row.draft_ratio * 100);
    const effective = Math.round(row.effective_ratio * 100);
    const missing = (row.missing || []).map((m) => m.label).join(", ");
    return `
      <div class="coverage-row ${state.focusDimension === row.key ? "is-focused" : ""}" data-dim="${row.key}">
        <div class="coverage-top">
          <span class="status-dot ${row.status}"></span>
          <span class="coverage-label">${esc(row.label)}</span>
          <span class="coverage-ratio">${draft}%${effective > draft ? ` → <b style="color:var(--teal)">${effective}%</b>` : ""}</span>
        </div>
        <div class="bar">
          <span class="fill" style="width:${draft}%"></span>
          <span class="fill-answer" style="width:${Math.max(effective - draft, 0)}%"></span>
        </div>
        ${missing ? `<div class="coverage-missing">빠진 것: <b>${esc(missing)}</b></div>` : ""}
      </div>`;
  }).join("");

  $$(".coverage-row", list).forEach((row) => {
    row.addEventListener("click", () => {
      state.focusDimension = state.focusDimension === row.dataset.dim ? null : row.dataset.dim;
      renderCoverage(state.analysis);
      renderQuestions();
    });
  });
}

function filteredQuestions() {
  const questions = state.analysis?.questions || [];
  return questions.filter((question) => {
    if (state.focusDimension && question.dimension !== state.focusDimension) return false;
    if (state.questionFilter === "all") return true;
    return question.status === state.questionFilter;
  });
}

function renderQuestions() {
  const list = $("#question-list");
  const questions = filteredQuestions();
  const total = state.analysis?.questions?.length || 0;

  $$(".chip-tab", $("#question-filter")).forEach((tab) => {
    const filter = tab.dataset.filter;
    tab.classList.toggle("is-active", filter === state.questionFilter);
    const count = (state.analysis?.questions || []).filter((q) => filter === "all" || q.status === filter).length;
    tab.textContent = `${({ all: "전체", unanswered: "미답변", answered: "답변 완료", skipped: "건너뜀" })[filter]} ${count}`;
  });

  if (!questions.length) {
    list.innerHTML = `<div class="empty-state">${total ? "이 조건에 해당하는 질문이 없습니다." : "질문이 없습니다. 초안이 충분히 채워져 있습니다."}</div>`;
    return;
  }

  list.innerHTML = questions.map((question) => {
    const priority = question.priority === "high" ? "우선" : "보통";
    const statusText = { answered: "답변 완료", skipped: "건너뜀", unanswered: "미답변" }[question.status];
    return `
      <article class="question-card ${question.source === "llm" ? "is-llm" : ""} is-${question.status}" data-id="${esc(question.id)}">
        <div class="q-head">
          <span class="q-dim">${esc(question.dimension_label)}</span>
          <span class="q-priority ${question.priority === "high" ? "" : "normal"}">${priority}</span>
          ${question.source === "llm" ? `<span class="q-source">AI 추가 질문</span>` : ""}
          ${question.signal ? `<span class="chip weak">${esc(question.signal)}</span>` : ""}
          <span class="q-status ${question.status}">${statusText}</span>
        </div>
        <div class="q-text">${esc(question.question)}</div>
        <div class="q-why">${esc(question.why || "")}</div>
        ${question.evidence ? `<div class="q-evidence"><b>초안에서</b>${esc(question.evidence)}</div>` : ""}
        <div class="q-answer">
          <textarea rows="2" placeholder="여기에 답을 적으면 초안에 함께 정리됩니다. (입력하면 자동 저장)">${esc(question.answer || "")}</textarea>
        </div>
        <div class="q-actions">
          <button class="link-btn toggle-skip">${question.status === "skipped" ? "건너뜀 해제" : "건너뜀으로 표시"}</button>
          <span class="saved"></span>
        </div>
        ${question.hint ? `<details><summary class="link-btn" style="margin-top:6px">이렇게 적으면 좋아요</summary><div class="q-hint">${esc(question.hint)}</div></details>` : ""}
      </article>`;
  }).join("");

  $$(".question-card", list).forEach((card) => bindQuestionCard(card));
}

function bindQuestionCard(card) {
  const id = card.dataset.id;
  const textarea = $("textarea", card);
  const saved = $(".saved", card);
  const question = (state.analysis?.questions || []).find((q) => q.id === id);

  const save = debounce(async () => {
    const value = textarea.value.trim();
    const previous = state.answers[id] || {};
    state.answers[id] = { text: value, skipped: value ? false : previous.skipped || false };
    if (!value && !state.answers[id].skipped) delete state.answers[id];
    saved.textContent = "저장됨";
    setTimeout(() => { saved.textContent = ""; }, 1400);
    await refreshCoverageOnly();
  }, 700);

  textarea.addEventListener("input", () => {
    autosize(textarea);
    save();
  });
  autosize(textarea);

  $(".toggle-skip", card).addEventListener("click", async () => {
    const current = state.answers[id] || { text: "", skipped: false };
    const skipped = !current.skipped;
    state.answers[id] = { text: textarea.value.trim(), skipped };
    if (!state.answers[id].text && !skipped) delete state.answers[id];
    card.classList.toggle("is-skipped", skipped);
    card.classList.toggle("is-answered", !skipped && !!textarea.value.trim());
    const status = $(".q-status", card);
    status.textContent = skipped ? "건너뜀" : (textarea.value.trim() ? "답변 완료" : "미답변");
    status.className = `q-status ${skipped ? "skipped" : textarea.value.trim() ? "answered" : "unanswered"}`;
    $(".toggle-skip", card).textContent = skipped ? "건너뜀 해제" : "건너뜀으로 표시";
    await refreshCoverageOnly();
  });
}

function autosize(el) {
  el.style.height = "auto";
  el.style.height = `${Math.min(Math.max(el.scrollHeight, 54), 260)}px`;
}

async function refreshCoverageOnly() {
  try {
    const data = await api("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: state.text, answers: state.answers, mask: state.mask, ai_mode: state.aiMode }),
    });
    const previous = state.analysis;
    state.analysis = data;
    renderSummary(data);
    renderCoverage(data);
    // 질문 카드의 상태 배지만 조용히 갱신 (입력 중 포커스를 잃지 않도록 DOM은 유지)
    $$(".question-card").forEach((card) => {
      const question = data.questions.find((q) => q.id === card.dataset.id);
      if (!question) return;
      const status = $(".q-status", card);
      status.textContent = { answered: "답변 완료", skipped: "건너뜀", unanswered: "미답변" }[question.status];
      status.className = `q-status ${question.status}`;
    });
    const filterCount = $$(".chip-tab", $("#question-filter"));
    filterCount.forEach((tab) => {
      const filter = tab.dataset.filter;
      const count = data.questions.filter((q) => filter === "all" || q.status === filter).length;
      tab.textContent = `${({ all: "전체", unanswered: "미답변", answered: "답변 완료", skipped: "건너뜀" })[filter]} ${count}`;
    });
    if (previous && previous.stats.unanswered !== data.stats.unanswered) {
      $("#step-hint").textContent = `미답변 질문 ${data.stats.unanswered}개 · 답변하면 커버리지가 올라갑니다.`;
    }
  } catch (error) {
    /* 조용히 무시: 입력 자체는 막지 않는다 */
  }
}

$$(".chip-tab", $("#question-filter")).forEach((tab) => {
  tab.addEventListener("click", () => {
    state.questionFilter = tab.dataset.filter;
    renderQuestions();
  });
});

/* ------------------------------------------------------------------ */
/* 3단계 — 약관 매칭                                                    */
/* ------------------------------------------------------------------ */

async function loadRegulations() {
  try {
    const data = await api("/api/regulations");
    state.regulations = data.items;
    const select = $("#regulation-select");
    select.innerHTML = data.items.map((item) => `
      <option value="${esc(item.id)}" ${item.id === state.regulationId ? "selected" : ""}>
        ${esc(item.name)}${item.version_label ? ` (${esc(item.version_label)})` : ""} · 조문 ${item.article_count}개
      </option>`).join("");
    renderRegMeta();
  } catch (error) {
    toast(error.message);
  }
}

function currentRegulation() {
  return state.regulations.find((item) => item.id === state.regulationId) || null;
}

function renderRegMeta() {
  const reg = currentRegulation();
  if (!reg) return;
  $("#reg-meta").innerHTML = `
    <span class="kv">문서 <b>${esc(reg.filename || reg.name)}</b></span>
    <span class="kv">쪽수 <b>${reg.page_count}</b></span>
    <span class="kv">조문 <b>${reg.article_count}</b>개 / 검색단위 <b>${reg.unit_count}</b></span>
    ${reg.version_label ? `<span class="kv">시행 <b>${esc(reg.version_label)}</b></span>` : ""}
    ${reg.id === "kepco" ? `<a class="kv" href="/api/samples/regulation/kepco">원문 PDF 내려받기</a>` : ""}`;
}

$("#regulation-select").addEventListener("change", (event) => {
  state.regulationId = event.target.value;
  state.terms = null;
  renderRegMeta();
  $("#match-list").innerHTML = "";
  $("#terms-summary").innerHTML = "";
});

async function ensureTerms() {
  if (!state.regulations.length) await loadRegulations();
  if (!state.terms) runMatch();
}

$("#btn-match").addEventListener("click", () => runMatch());

async function runMatch() {
  const list = $("#match-list");
  list.innerHTML = `<div class="empty-state">조항을 찾는 중…</div>`;
  try {
    const data = await api("/api/terms", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: state.text, regulation_id: state.regulationId }),
    });
    state.terms = data;
    renderTerms(data);
  } catch (error) {
    list.innerHTML = `<div class="empty-state">${esc(error.message)}</div>`;
  }
}

function renderTerms(data) {
  const stats = data.stats || {};
  const matched = stats.matched || 0;
  const total = stats.sentences || 0;
  $("#terms-summary").innerHTML = `
    <div class="summary-item">
      <div class="label">근거 후보를 찾은 문장</div>
      <div class="value">${matched}<small>/ ${total}</small></div>
      <div class="note">나머지는 약관과 직접 관련 없는 업무 문장입니다</div>
    </div>
    <div class="summary-item">
      <div class="label">걸린 조문</div>
      <div class="value">${stats.articles || 0}<small>개</small></div>
      <div class="note">조문 번호·쪽수는 원문 PDF 기준</div>
    </div>
    <div class="summary-item">
      <div class="label">신뢰도 높음</div>
      <div class="value">${(data.matches || []).filter((m) => m.confidence === "높음").length}<small>건</small></div>
      <div class="note">낮은 후보는 직접 확인이 필요합니다</div>
    </div>`;

  const list = $("#match-list");
  if (!data.matches?.length) {
    list.innerHTML = `<div class="empty-state">초안에서 약관과 연결되는 문장을 찾지 못했습니다. 규정 파일을 바꾸거나 초안에 근거 규정을 함께 적어 보세요.</div>`;
    return;
  }

  list.innerHTML = data.matches.map((match) => {
    const primary = match.primary;
    const alternatives = (match.alternatives || []).map((alt) => `
      <div class="alt-row" data-full="${esc(alt.text)}">
        <span class="article-no" style="font-size:13px">${esc(alt.article_no)}</span>
        <span class="article-title" style="font-size:13px">${esc(alt.title)}</span>
        <span class="loc">${esc(alt.printed_page)}쪽</span>
        <span class="conf ${esc(alt.confidence)}">${esc(alt.confidence)}</span>
        <span class="muted small">점수 ${esc(alt.score)}</span>
      </div>`).join("");

    return `
      <article class="match-card">
        <div class="match-sentence"><span class="mark">초안</span><span>${esc(match.sentence)}</span></div>
        <div class="match-body">
          <div class="match-primary">
            <span class="article-no">${esc(primary.article_no)}</span>
            <span class="article-title">${esc(primary.title)}</span>
            <span class="loc">${esc(primary.paragraph || "")} ${esc(primary.printed_page)}쪽</span>
            ${primary.chapter ? `<span class="loc">${esc(primary.chapter)}</span>` : ""}
            <span class="conf ${esc(primary.confidence)}">신뢰도 ${esc(primary.confidence)}</span>
          </div>
          <div class="excerpt">${highlight(primary.excerpt, primary.matched_terms, primary.matched_words)}</div>
          ${(primary.matched_terms.length || primary.matched_words.length) ? `
            <div class="terms-chips">
              ${primary.matched_terms.map((t) => `<span class="chip">${esc(t)}</span>`).join("")}
              ${primary.matched_words.filter((w) => !primary.matched_terms.includes(w)).slice(0, 4).map((w) => `<span class="chip weak">${esc(w)}</span>`).join("")}
            </div>` : ""}
          ${alternatives ? `<div class="alts"><div class="alts-title">다른 후보 조문</div>${alternatives}</div>` : ""}
          <details><summary class="link-btn" style="margin-top:10px">조문 원문 보기</summary>
            <div class="full-text">${esc(primary.text)}</div>
          </details>
        </div>
      </article>`;
  }).join("");

  $$(".alt-row", list).forEach((row) => {
    row.addEventListener("click", () => {
      const details = row.closest(".match-body").querySelector(".full-text");
      if (details) details.textContent = row.dataset.full || "";
    });
  });
}

function highlight(text, terms = [], words = []) {
  let html = esc(text);
  const needles = [...terms, ...words].filter(Boolean).sort((a, b) => b.length - a.length);
  needles.forEach((needle) => {
    const safe = esc(needle);
    if (!safe) return;
    html = html.split(safe).join(`<mark>${safe}</mark>`);
  });
  return html;
}

/* 규정 업로드 */
$("#btn-upload-reg").addEventListener("click", () => $("#reg-input").click());
$("#reg-input").addEventListener("change", async () => {
  const file = $("#reg-input").files?.[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  toast("규정 파일을 읽는 중…");
  try {
    const data = await api("/api/regulations", { method: "POST", body: form });
    await loadRegulations();
    state.regulationId = data.regulation.id;
    $$("#regulation-select option").forEach((option) => {
      option.selected = option.value === data.regulation.id;
    });
    renderRegMeta();
    toast(`규정을 불러왔습니다 · ${data.regulation.article_count}개 조문`);
    runMatch();
  } catch (error) {
    toast(error.message);
  }
});

/* ------------------------------------------------------------------ */
/* 4단계 — 내보내기                                                    */
/* ------------------------------------------------------------------ */

function prepareExportStep() {
  const pending = (state.analysis?.questions || []).filter((q) => q.status === "unanswered");
  const box = $("#open-questions");
  if (state.terms) $("#include-terms").checked = true;
  if (pending.length) {
    box.innerHTML = `<div class="box"><b>아직 답하지 못한 질문 ${pending.length}개</b><br>
      이 질문들은 문서 마지막에 '아직 답하지 못한 질문 목록'으로 들어갑니다.
      <button class="link-btn" id="back-to-questions">2단계로 돌아가 답하기</button></div>`;
    $("#back-to-questions").addEventListener("click", () => setStep(2));
  } else if (state.analysis) {
    box.innerHTML = `<div class="box" style="background:var(--green-soft);color:#0b5a3d"><b>미답변 질문이 없습니다.</b><br>바로 문서를 생성할 수 있습니다.</div>`;
  } else {
    box.innerHTML = "";
  }

  const imageCount = sourceImageCount();
  if (imageCount > 0) {
    const note = state.imageNote.trim();
    box.innerHTML += `<div class="box" style="margin-top:8px"><b>그림 ${imageCount}장 감지됨</b><br>${
      note
        ? "그림 속 내용 보완이 문서에 함께 들어갑니다."
        : "그림 속 표기·글자는 아직 비어 있습니다. 2단계에서 간단히 적어 두면 문서에 함께 들어갑니다."
    } <button class="link-btn" id="back-to-images">2단계로 돌아가 적기</button></div>`;
    $("#back-to-images").addEventListener("click", () => setStep(2));
  }
}

$("#btn-export").addEventListener("click", async () => {
  const meta = {
    author: $("#meta-author").value,
    successor: $("#meta-successor").value,
    team: $("#meta-team").value,
    period: $("#meta-period").value,
    base: state.source?.filename || "직접 입력",
  };
  const body = {
    meta,
    text: state.text,
    analysis: state.analysis || {},
    terms: ($("#include-terms").checked && state.terms) ? state.terms : null,
    image_note: state.imageNote.trim(),
    image_count: sourceImageCount(),
  };
  try {
    const data = await api("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    state.exportDoc = data;
    $("#export-preview").innerHTML = mdToHtml(data.markdown);
    $("#export-hint").textContent = `${data.filename}.md · ${data.markdown.length.toLocaleString()}자`;
    ["#btn-download-md", "#btn-download-txt", "#btn-copy"].forEach((sel) => { $(sel).disabled = false; });
    toast("문서를 생성했습니다");
  } catch (error) {
    toast(error.message);
  }
});

function download(name, content, type) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

$("#btn-download-md").addEventListener("click", () => {
  if (!state.exportDoc) return;
  download(`${state.exportDoc.filename}.md`, state.exportDoc.markdown, "text/markdown;charset=utf-8");
});
$("#btn-download-txt").addEventListener("click", () => {
  if (!state.exportDoc) return;
  download(`${state.exportDoc.filename}.txt`, state.exportDoc.text, "text/plain;charset=utf-8");
});
$("#btn-copy").addEventListener("click", async () => {
  if (!state.exportDoc) return;
  try {
    await navigator.clipboard.writeText(state.exportDoc.markdown);
    toast("클립보드에 복사했습니다");
  } catch {
    toast("복사가 차단되었습니다. 다운로드를 이용해 주세요.");
  }
});

/* 아주 작은 마크다운 렌더러 (미리보기용) */
function mdToHtml(markdown) {
  const lines = esc(markdown).split("\n");
  const out = [];
  let inCode = false;
  let listOpen = false;
  let tableBuffer = [];

  const flushList = () => { if (listOpen) { out.push("</ul>"); listOpen = false; } };
  const flushTable = () => {
    if (!tableBuffer.length) return;
    const rows = tableBuffer.map((row) => row.split("|").slice(1, -1).map((cell) => cell.trim()));
    const isDivider = rows.length && rows.every((cells) => cells.every((cell) => /^:?-{2,}:?$/.test(cell)));
    if (isDivider) { tableBuffer = []; return; }
    const head = rows[0] || [];
    const body = rows.slice(1).filter((cells) => !cells.every((cell) => /^:?-{2,}:?$/.test(cell)));
    out.push("<table><thead><tr>" + head.map((cell) => `<th>${cell}</th>`).join("") + "</tr></thead><tbody>");
    body.forEach((cells) => out.push("<tr>" + cells.map((cell) => `<td>${cell}</td>`).join("") + "</tr>"));
    out.push("</tbody></table>");
    tableBuffer = [];
  };

  for (const line of lines) {
    if (line.trim().startsWith("```")) {
      flushList(); flushTable();
      out.push(inCode ? "</pre>" : "<pre>");
      inCode = !inCode;
      continue;
    }
    if (inCode) { out.push(line); continue; }
    if (line.startsWith("|")) { flushList(); tableBuffer.push(line); continue; }
    flushTable();
    if (!line.trim()) { flushList(); out.push(""); continue; }
    if (line.startsWith("### ")) { flushList(); out.push(`<h3>${line.slice(4)}</h3>`); continue; }
    if (line.startsWith("## ")) { flushList(); out.push(`<h2>${line.slice(3)}</h2>`); continue; }
    if (line.startsWith("# ")) { flushList(); out.push(`<h1>${line.slice(2)}</h1>`); continue; }
    if (line.startsWith("> ")) { flushList(); out.push(`<blockquote>${line.slice(2)}</blockquote>`); continue; }
    if (line.startsWith("---")) { flushList(); out.push("<hr />"); continue; }
    const bullet = line.match(/^(\s*)[-•]\s+(.*)$/);
    if (bullet) {
      if (!listOpen) { out.push("<ul>"); listOpen = true; }
      out.push(`<li>${bullet[2]}</li>`);
      continue;
    }
    flushList();
    out.push(`<p>${line}</p>`);
  }
  flushList(); flushTable();
  if (inCode) out.push("</pre>");
  return out.join("\n").replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
}

/* ------------------------------------------------------------------ */
/* 초기화                                                              */
/* ------------------------------------------------------------------ */

(async function init() {
  const mode = currentMode();
  if (mode.key) state.aiMode = mode.key;
  syncModeControls();
  renderAiDetail();
  updateModeBadge();
  updatePrivacyNote(null);
  renderImageNotice();
  await loadRegulations();
  setStep(1);
  runAiCheck();
})();
