/* 정적 시연용 API 어댑터
 *
 * 화면(app.js)은 Flask 의 `/api/...` 를 그대로 부른다. GitHub Pages 에는 서버가 없으므로,
 * 이 파일이 fetch 를 가로채 같은 모양의 응답을 브라우저 안에서 만든다(계산은 demo-core.js).
 * 그래서 화면 코드는 서버 버전과 똑같은 것을 쓴다 — 화면을 고칠 때 양쪽이 갈라지지 않는다.
 *
 * 정직하게 남긴 한계
 * - 사내 AI · 외부 AI · 사내 표준약관 AI 주소로는 실제 연결하지 않는다(연결 실패 안내 카드 노출).
 * - PDF · 한글 5.0(.hwp) 파일은 브라우저에서 글자를 뽑지 못한다(안내 문구 반환).
 * - 업로드한 규정은 서버가 없어 저장되지 않는다(내장 샘플 1건으로 동작).
 */
(function (global) {
  'use strict';

  const CORE = global.DEMO_CORE;
  const realFetch = global.fetch.bind(global);
  const ROOT = new URL('.', global.location.href);

  const UNAVAILABLE_AI = '연동할 수 있는 AI를 찾지 못하였어요.';
  const UNAVAILABLE_TERMS = '연동할 수 있는 사내 표준약관 AI를 찾지 못하였어요.';
  const DEMO_REASON = '정적 시연 버전이라 실제 AI 서버로 연결하지 않습니다. 실제 배포에서는 관리자에게 받은 주소로 연결을 확인합니다.';
  const PDF_REASON = '정적 시연 버전이라 브라우저에서 사내 주소로 연결을 확인할 수 없습니다. 실제 배포에서는 이 주소로 연결을 확인합니다.';
  const REGULATION_UPLOAD_ERROR = '정적 시연 버전에서는 규정 PDF를 직접 해석할 수 없습니다. 내장 샘플(한국전력공사 기본공급약관)로 진행해 주세요.';

  const cache = Object.create(null);

  function loadData(name) {
    if (!cache[name]) {
      cache[name] = realFetch(new URL('data/' + name, ROOT).toString())
        .then((response) => {
          if (!response.ok) throw new Error('데모 데이터를 불러오지 못했습니다(' + name + ')');
          return response.json();
        });
    }
    return cache[name];
  }

  function jsonResponse(payload, status) {
    return new Response(JSON.stringify(payload), {
      status: status || 200,
      headers: { 'Content-Type': 'application/json; charset=utf-8' },
    });
  }

  function errorResponse(message, status) {
    return jsonResponse({ error: message }, status || 400);
  }

  function modeList() {
    return global.__AI_MODES__ || [];
  }

  function modeOf(key) {
    return modeList().find((mode) => mode.key === key) || null;
  }

  function llmDescribe() {
    return {
      provider: 'demo',
      label: '데모(오프라인) 모드',
      detail: '외부 전송 없음 · 규칙 기반 질문 생성',
      available: true,
    };
  }

  /** ai_modes.describe(mode) 와 같은 모양 */
  function describeAi(key) {
    const mode = modeOf(key) || modeOf('offline_rules');
    return {
      mode: mode.key,
      label: mode.label,
      reads_images: !!mode.reads_images,
      external: !!mode.external,
      privacy: mode.privacy,
      configured: false,
      endpoint: mode.needs === 'none' ? '' : '',
    };
  }

  function internalTermsDescribe() {
    return {
      source: 'internal_terms',
      label: '사내 표준약관 AI',
      configured: false,
      endpoint: '',
      from_env: false,
      from_runtime: false,
      key_set: false,
      timeout: 2,
      notice: UNAVAILABLE_TERMS,
    };
  }

  function basicChecklist(checklist) {
    return checklist.dimensions.map((dim) => ({
      key: dim.key, label: dim.label, summary: dim.summary,
      guide: dim.guide, misses: dim.misses, example: dim.example,
    }));
  }

  async function readJsonBody(init) {
    const body = init && init.body;
    if (!body) return {};
    if (typeof body === 'string') {
      try { return JSON.parse(body); } catch (error) { return {}; }
    }
    return {};
  }

  /* ------------------------------------------------------------------ */
  /* 라우트                                                             */
  /* ------------------------------------------------------------------ */

  const handlers = {
    'GET /api/health': async () => {
      const [samples, reg] = await Promise.all([loadData('samples.json'), loadData('regulation.json')]);
      return {
        status: 'ok',
        llm: llmDescribe(),
        samples: {
          handover: [
            { format: 'md', filename: 'handover_sample.md', label: '마크다운(.md)', url: 'samples/handover_sample.md' },
            { format: 'docx', filename: 'handover_sample.docx', label: '워드(.docx)', url: 'samples/handover_sample.docx' },
            { format: 'hwpx', filename: 'handover_sample.hwpx', label: '한글(.hwpx)', url: 'samples/handover_sample.hwpx' },
          ],
          regulations: [reg.summary],
        },
        template_available: true,
        ai: { modes: modeList(), default: global.__AI_DEFAULT__ || 'offline_rules', notice: UNAVAILABLE_AI },
        terms: { internal: internalTermsDescribe(), notice: UNAVAILABLE_TERMS, sources: ['internal', 'pdf'] },
        demo: { static: true, sample_notice: samples.sample_notice },
      };
    },

    'GET /api/ai/modes': async () => ({
      modes: modeList(),
      default: global.__AI_DEFAULT__ || 'offline_rules',
      notice: UNAVAILABLE_AI,
    }),

    'POST /api/ai/check': async (body) => {
      const key = String(body.mode || global.__AI_DEFAULT__ || 'offline_rules').trim();
      const mode = modeOf(key) || modeOf('offline_rules');
      const base = {
        mode: mode.key,
        ok: false,
        status: 'not_configured',
        notice: UNAVAILABLE_AI,
        message: UNAVAILABLE_AI,
        reason: '',
        reads_images: !!mode.reads_images,
        retry_label: mode.retry_label || '',
        endpoint: '',
        label: mode.label,
      };
      if (mode.needs === 'none') {
        return { ...base, ok: true, status: 'ready', notice: '', message: 'AI 없이 기본 규칙 점검으로 진행합니다.', reason: '' };
      }
      if (mode.needs === 'external') {
        return {
          ...base,
          status: 'not_configured',
          reason: '이 환경에는 외부 AI 주소나 키가 설정되어 있지 않습니다. 계속하려면 \'AI 없이 기본 점검\'을 눌러 주세요. ' + DEMO_REASON,
        };
      }
      const typed = String(body.endpoint || '').trim();
      if (typed) {
        return { ...base, status: 'unreachable', endpoint: typed, reason: PDF_REASON };
      }
      return {
        ...base,
        reason: '사내 AI 주소가 설정되어 있지 않습니다. 관리자에게 받은 주소를 넣고 연결을 확인해 보세요. ' + DEMO_REASON,
      };
    },

    'GET /api/template': async () => {
      const [samples, checklist] = await Promise.all([loadData('samples.json'), loadData('checklist.json')]);
      return { text: samples.template_text, checklist: basicChecklist(checklist) };
    },

    'GET /api/samples/handover-text': async () => {
      const samples = await loadData('samples.json');
      return { text: samples.sample_text, notice: samples.sample_notice };
    },

    'POST /api/parse': async (body, init) => {
      const form = init && init.body;
      const file = form && typeof form.get === 'function' ? form.get('file') : null;
      if (!file || !file.name) throw httpError('파일이 없습니다.', 400);
      if (file.size > 25 * 1024 * 1024) throw httpError('파일이 너무 큽니다(최대 25MB).', 413);
      try {
        return await CORE.parseFile(file);
      } catch (error) {
        throw httpError(error.message || '파일을 읽지 못했습니다.', 400);
      }
    },

    'POST /api/paste': async (body) => {
      const text = String(body.text || '').trim();
      if (!text) throw httpError('붙여넣은 내용이 비어 있습니다.', 400);
      return {
        filename: '붙여넣은 텍스트', kind: 'text', text, pages: [], page_count: 0,
        warnings: [], meta: { source: 'paste' }, image_count: 0,
        char_count: text.length, line_count: text.split('\n').length,
      };
    },

    'POST /api/mask': async (body) => {
      const text = body.text || '';
      const masked = CORE.maskText(text);
      const enabled = body.mask === undefined ? true : !!body.mask;
      return {
        report: CORE.maskReport(masked),
        preview: (enabled ? masked.text : text).slice(0, 600),
        masked_count: masked.total,
        llm_active: false,
      };
    },

    'POST /api/analyze': async (body) => {
      const text = String(body.text || '').trim();
      if (text.length < 20) {
        throw httpError('분석할 내용이 너무 짧습니다. 초안을 20자 이상 입력해 주세요.', 400);
      }
      const checklist = await loadData('checklist.json');
      const answers = body.answers || {};
      const maskEnabled = body.mask === undefined ? true : !!body.mask;
      const mode = modeOf(String(body.ai_mode || '')) ? String(body.ai_mode) : 'offline_rules';

      const masked = CORE.maskText(text);
      const result = CORE.assess(text, answers, checklist);
      result.ai = describeAi(mode);
      result.masking = {
        enabled: maskEnabled,
        report: CORE.maskReport(masked),
        preview: (maskEnabled ? masked.text : text).slice(0, 600),
      };
      result.llm = { ...llmDescribe(), added: 0, note: null };
      return result;
    },

    'GET /api/regulations': async () => {
      const reg = await loadData('regulation.json');
      return { items: [reg.summary] };
    },

    'POST /api/regulations': async () => errorResponse(REGULATION_UPLOAD_ERROR, 400),

    'GET /api/terms/status': async () => {
      const reg = await loadData('regulation.json');
      return {
        internal: internalTermsDescribe(),
        pdf: { items: [reg.summary], default_id: reg.summary.id, label: '규정 PDF 업로드 / 내장 샘플' },
        sources: ['internal', 'pdf'],
        notice: UNAVAILABLE_TERMS,
        disclaimer: reg.disclaimer,
      };
    },

    'POST /api/terms/check': async (body) => {
      const typed = String(body.endpoint || '').trim();
      return {
        source: 'internal_terms',
        label: '사내 표준약관 AI',
        ok: false,
        status: typed ? 'unreachable' : 'not_configured',
        notice: UNAVAILABLE_TERMS,
        message: UNAVAILABLE_TERMS,
        reason: typed
          ? PDF_REASON
          : '사내 표준약관 AI 주소가 설정되어 있지 않습니다. 관리자에게 받은 주소를 넣거나, 아래에서 규정 PDF로 진행하세요. ' + DEMO_REASON,
        endpoint: typed,
        retry_label: '사내 표준약관 AI 다시 연결하기',
        fallback_label: '규정 PDF 업로드로 진행하기',
      };
    },

    'POST /api/terms': async (body) => {
      const text = String(body.text || '').trim();
      if (!text) throw httpError('인수인계 초안이 비어 있습니다.', 400);
      const source = String(body.source || 'pdf').trim();
      if (source === 'internal') {
        return {
          ok: false,
          source: 'internal',
          status: 'not_configured',
          notice: UNAVAILABLE_TERMS,
          message: UNAVAILABLE_TERMS,
          reason: '사내 표준약관 AI 주소가 설정되어 있지 않습니다. 관리자에게 받은 주소를 넣거나 규정 PDF 업로드로 진행하세요. ' + DEMO_REASON,
          endpoint: '',
          retry_label: '사내 표준약관 AI 다시 연결하기',
          fallback_label: '규정 PDF 업로드로 진행하기',
        };
      }
      if (source !== 'pdf') throw httpError('알 수 없는 근거 경로입니다.', 400);
      const reg = await loadData('regulation.json');
      const regId = body.regulation_id || reg.summary.id;
      if (regId !== reg.summary.id) {
        throw httpError('규정을 찾을 수 없습니다. 다시 선택해 주세요.', 404);
      }
      const result = CORE.matchRegulation(reg, text);
      result.regulation = reg.summary;
      result.source = 'pdf';
      result.ok = true;
      return result;
    },

    'POST /api/export': async (body) => {
      const text = String(body.text || '').trim();
      if (!text) throw httpError('내보낼 초안이 없습니다.', 400);
      const checklist = await loadData('checklist.json');
      return CORE.buildExport(body.meta || {}, text, body.analysis || {}, body.terms || null, {
        checklist,
        image_note: body.image_note || '',
        image_count: body.image_count || 0,
      });
    },
  };

  function httpError(message, status) {
    const error = new Error(message);
    error.status = status || 400;
    return error;
  }

  /* ------------------------------------------------------------------ */
  /* fetch 가로채기                                                      */
  /* ------------------------------------------------------------------ */

  function requestPath(input) {
    const raw = typeof input === 'string' ? input : (input && input.url) || String(input);
    try {
      const url = new URL(raw, global.location.href);
      return url.pathname + url.search;
    } catch (error) {
      return raw;
    }
  }

  global.fetch = async function demoFetch(input, init) {
    const path = requestPath(input);
    const index = path.indexOf('/api/');
    if (index === -1) return realFetch(input, init);

    const apiPath = path.slice(index).split('?')[0].replace(/\/$/, '') || path.slice(index);
    const method = String((init && init.method) || (input && input.method) || 'GET').toUpperCase();
    const key = method + ' ' + apiPath;
    const handler = handlers[key];

    if (!handler) {
      return jsonResponse({ error: '정적 시연 버전에서 지원하지 않는 기능입니다(' + key + ').' }, 404);
    }
    try {
      const body = method === 'GET' || method === 'HEAD' ? {} : await readJsonBody(init);
      const payload = await handler(body, init);
      return jsonResponse(payload);
    } catch (error) {
      const status = error && error.status ? error.status : 500;
      return jsonResponse({ error: (error && error.message) || '요청을 처리하지 못했습니다.' }, status);
    }
  };

  /* ------------------------------------------------------------------ */
  /* 정적 사이트에서만 필요한 잔손질                                      */
  /* ------------------------------------------------------------------ */

  // 화면이 만드는 '원문 PDF 내려받기' 링크는 서버 주소를 가리킨다 → 함께 올린 파일로 보낸다.
  document.addEventListener('click', (event) => {
    const link = event.target.closest && event.target.closest('a[href*="/api/samples/regulation/"]');
    if (!link) return;
    event.preventDefault();
    global.location.href = new URL('samples/regulation/kepco_basic_supply_terms.pdf', ROOT).toString();
  });

  // 그림 포함 문서를 시험해 볼 수 있도록 안내 (샘플 파일에는 그림이 없다)
  document.addEventListener('DOMContentLoaded', () => {
    const bar = document.querySelector('.demo-bar-text');
    if (!bar) return;
    const note = document.createElement('span');
    note.className = 'demo-bar-sub';
    note.textContent = ' 그림이 든 .docx를 올리면 2단계에서 보완 입력 칸이 나타납니다.';
    bar.appendChild(note);
  });
})(window);
