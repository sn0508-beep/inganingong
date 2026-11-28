/* 인수인계서 AI — 정적 시연용 핵심 로직
 *
 * Flask 서버(app/gap.py · app/terms.py · app/export.py · app/masking.py)가 하던 계산을
 * 브라우저에서 같은 결과로 돌리기 위해 옮긴 모듈이다. 화면(app.js)은 서버 API 를 그대로
 * 부르고, demo-api.js 가 그 호출을 이 모듈로 연결한다. 그래서 화면 코드는 손대지 않는다.
 *
 * 옮길 때 지킨 것
 * - 규칙·가중치·문턱값을 원본 그대로 둔다(값을 바꾸면 서버 버전과 결과가 갈라진다).
 * - 숨은 판단을 새로 넣지 않는다. 정적 데모에서 안 되는 것(PDF·한글 5.0 파일 읽기,
 *   사내 AI 연결)만 "안 된다"고 정직하게 돌려준다.
 */
(function (global) {
  'use strict';

  const CORE = {};

  /* ================================================================== */
  /* 공통 유틸                                                          */
  /* ================================================================== */

  const reCache = new Map();

  function compile(pattern, flags) {
    const key = (flags || '') + '\u0000' + pattern;
    if (reCache.has(key)) return reCache.get(key);
    let rx = null;
    try {
      rx = new RegExp(pattern, flags || '');
    } catch (error) {
      rx = null;                       // 지원하지 않는 정규식(아주 오래된 브라우저)은 건너뛴다
    }
    reCache.set(key, rx);
    return rx;
  }

  function test(pattern, text, flags) {
    const rx = compile(pattern, flags);
    return rx ? rx.test(text) : false;
  }

  function firstMatch(pattern, text, flags) {
    const rx = compile(pattern, flags);
    if (!rx) return '';
    const found = rx.exec(text);
    return found ? found[0] : '';
  }

  /** Python round() 와 같게(짝수 반올림) 맞춘다. 비율·점수 표기가 서버와 어긋나지 않도록. */
  function pyRound(value, digits) {
    const d = digits || 0;
    const factor = Math.pow(10, d);
    const scaled = value * factor;
    const floor = Math.floor(scaled);
    const diff = scaled - floor;
    let rounded;
    if (diff > 0.5) rounded = floor + 1;
    else if (diff < 0.5) rounded = floor;
    else rounded = floor % 2 === 0 ? floor : floor + 1;
    return rounded / factor;
  }

  function stripChars(text, chars) {
    const set = chars.replace(/[\\\]^-]/g, '\\$&');
    return String(text).replace(new RegExp('^[' + set + ']+|[' + set + ']+$', 'g'), '');
  }

  function escapeHtml(value) {
    return String(value == null ? '' : value).replace(/&/g, '&amp;')
      .replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  CORE.pyRound = pyRound;
  CORE.escapeHtml = escapeHtml;

  /* ================================================================== */
  /* 1) 개인정보 가림 (app/masking.py)                                  */
  /* ================================================================== */

  //: 순서가 중요하다. 주민번호·카드·사업자번호를 전화/계좌보다 먼저 처리한다.
  const MASK_PATTERNS = [
    ['rrn', '주민등록번호', '\\b\\d{6}\\s*[-–]\\s*\\d{7}\\b'],
    ['card', '카드번호', '\\b(?:\\d{4}[-\\s]){3}\\d{4}\\b'],
    ['bizno', '사업자등록번호', '\\b\\d{3}-\\d{2}-\\d{5}\\b'],
    ['email', '이메일', '[\\w.+-]+@[\\w-]+\\.[\\w.-]+'],
    ['mobile', '휴대전화', '\\b01[016789][-.\\s]?\\d{3,4}[-.\\s]?\\d{4}\\b'],
    ['tel', '일반전화', '\\b0\\d{1,2}[-.\\s]\\d{3,4}[-.\\s]\\d{4}\\b'],
    ['account', '계좌번호', '\\b\\d{2,6}-\\d{2,6}-\\d{4,8}\\b'],
  ];

  function placeholder(label) {
    return '[가림:' + label + ']';
  }

  function contextAround(text, start, end, label, width) {
    const w = width || 22;
    const left = text.slice(Math.max(0, start - w), start).replace(/\n/g, ' ');
    const right = text.slice(end, end + w).replace(/\n/g, ' ');
    return ('…' + left + placeholder(label) + right + '…').trim();
  }

  CORE.maskText = function maskText(input) {
    const source = input == null ? '' : String(input);
    let masked = source;
    const findings = [];
    MASK_PATTERNS.forEach(([key, label, pattern]) => {
      const rx = compile(pattern, 'g');
      if (!rx) return;
      let count = 0;
      const contexts = [];
      const before = masked;
      masked = before.replace(rx, (match, offset) => {
        count += 1;
        if (contexts.length < 3) {
          contexts.push(contextAround(before, offset, offset + match.length, label));
        }
        return placeholder(label);
      });
      if (count) findings.push({ key, label, count, contexts });
    });
    const total = findings.reduce((sum, finding) => sum + finding.count, 0);
    return {
      text: masked,
      findings,
      total,
      types: findings.map((finding) => finding.label),
    };
  };

  CORE.maskReport = function maskReport(result) {
    return {
      total: result.total,
      findings: result.findings,
      summary: result.findings.map((f) => f.label + ' ' + f.count + '건').join(', ') || '가린 항목 없음',
    };
  };

  /* ================================================================== */
  /* 2) 빈틈 점검 (app/gap.py + app/checklist.py)                       */
  /* ================================================================== */

  const META_LINE_RE = '^-?\\s*(인계자|인수자|소속|부서\\s*/\\s*직무|직무|작성일|인수인계\\s*기간|파일명)\\s*[:：]';
  const MAX_RULE_QUESTIONS = 16;

  //: 모호한 문장을 어느 항목으로 되물을지 정할 때 쓰는 힌트 (gap.GUESS_HINTS)
  const GUESS_HINTS = [
    ['진행|현안|미결|계류', 'pending'],
    ['폴더|드라이브|경로|최신|버전', 'documents'],
    ['권한|시스템|계정|비밀번호', 'systems'],
    ['예산|계약|정산|지급', 'budget'],
    ['연락처|전화|메일|문의', 'contacts'],
    ['규정|약관|조항|법령', 'rules'],
  ];

  function contentLines(text) {
    const lines = [];
    String(text || '').split('\n').forEach((raw) => {
      const line = raw.trim();
      if (!line) return;
      if (line.startsWith('#')) return;
      if (line.toUpperCase().startsWith('TODO')) return;
      if (test('^\\(작성', line)) return;
      if (test(META_LINE_RE, line)) return;
      lines.push(line);
    });
    return lines;
  }

  function isVague(line, vaguePatterns) {
    return vaguePatterns.some(([pattern]) => test(pattern, line, 'i'));
  }

  function signalEvidence(lines, patterns) {
    for (const line of lines) {
      if (patterns.some((pattern) => firstMatch(pattern, line, 'i'))) return line.slice(0, 160);
    }
    return '';
  }

  function normalizeAnswers(answers) {
    const result = {};
    Object.keys(answers || {}).forEach((key) => {
      const value = answers[key];
      let text = '';
      let skipped = false;
      if (value && typeof value === 'object') {
        text = String(value.text || '').trim();
        skipped = !!value.skipped;
      } else {
        text = String(value == null ? '' : value).trim();
      }
      if (text || skipped) result[key] = { text, skipped };
    });
    return result;
  }

  function sentenceAround(text, index) {
    const start = Math.max(text.lastIndexOf('\n', index - 1) + 1, 0);
    let end = text.indexOf('\n', index);
    if (end === -1) end = text.length;
    return text.slice(start, end).trim().slice(0, 200);
  }

  function guessDimension(sentence, dims) {
    let best = 'exception';
    let bestScore = 0;
    dims.forEach((dim) => {
      const score = dim.signals.filter((signal) =>
        signal.patterns.some((pattern) => firstMatch(pattern, sentence, 'i'))).length;
      if (score > bestScore) { best = dim.key; bestScore = score; }
    });
    for (const [pattern, key] of GUESS_HINTS) {
      if (test(pattern, sentence) && dims.some((dim) => dim.key === key)) return key;
    }
    return best;
  }

  function vagueQuestion(phrase, sentence) {
    const short = sentence.length <= 60 ? sentence : sentence.slice(0, 57) + '…';
    if (phrase.indexOf('문의') !== -1 || phrase.indexOf('참고') !== -1) {
      return '“' + short + '”라고 적혀 있는데, 그 정보를 문서 안에 옮겨 적을 수 있을까요? 후임자가 바로 쓸 수 있어야 합니다.';
    }
    if (phrase.indexOf('상황') !== -1 || phrase.indexOf('경우') !== -1 || phrase.indexOf('따라') !== -1) {
      return '“' + short + '”에서 \'상황\'이 구체적으로 무엇을 말하는지, 어떤 조건일 때 그렇게 하는지 알려 주세요.';
    }
    if (phrase.indexOf('추후') !== -1 || phrase.indexOf('미정') !== -1 || phrase.indexOf('확인') !== -1) {
      return '“' + short + '” — 아직 정해지지 않은 부분은 언제, 누가 정하는지와 그때까지 어떻게 처리하는지 알려 주세요.';
    }
    if (phrase.indexOf('대부분') !== -1 || phrase.indexOf('보통') !== -1) {
      return '“' + short + '”에서 \'예외\'에 해당하는 경우는 어떤 경우인지 알려 주세요.';
    }
    return '“' + short + '” 부분을 조금 더 구체적으로 알려 주세요. 후임자가 같은 판단을 할 수 있을 만큼요.';
  }

  /** 2단계 결과. chk 는 data/checklist.json (12항목 신호·질문 은행). */
  CORE.assess = function assess(draft, answers, chk) {
    const dims = chk.dimensions;
    const vaguePatterns = chk.vague_patterns;
    const lines = contentLines(draft);
    const body = lines.join('\n');
    const answered = normalizeAnswers(answers);

    const coverage = [];
    const questions = [];

    dims.forEach((dim) => {
      const hits = [];
      const missing = [];
      dim.signals.forEach((signal) => {
        const matched = lines.filter((line) =>
          signal.patterns.some((pattern) => firstMatch(pattern, line, 'i')));
        const strong = matched.filter((line) => !isVague(line, vaguePatterns));
        if (strong.length) hits.push(signal);
        else missing.push(signal);
      });

      const totalWeight = dim.signals.reduce((sum, signal) => sum + signal.weight, 0) || 1;
      const hitWeight = hits.reduce((sum, signal) => sum + signal.weight, 0);
      const draftRatio = pyRound(hitWeight / totalWeight, 2);

      const effectiveHits = hits.slice();
      missing.forEach((signal) => {
        const qid = dim.key + '::' + signal.key;
        const answer = answered[qid];
        if (answer && answer.text) effectiveHits.push(signal);
      });

      const baseAnswer = answered[dim.key + '::base'];
      if (baseAnswer && baseAnswer.text) {
        missing.slice(0, 2).forEach((signal) => {
          if (!effectiveHits.includes(signal)) effectiveHits.push(signal);
        });
      }
      const effectiveWeight = effectiveHits.reduce((sum, signal) => sum + signal.weight, 0);
      const effectiveRatio = pyRound(effectiveWeight / totalWeight, 2);

      const status = !hits.length ? 'missing' : (draftRatio >= 0.6 ? 'covered' : 'partial');
      coverage.push({
        key: dim.key,
        label: dim.label,
        summary: dim.summary,
        status,
        draft_ratio: draftRatio,
        effective_ratio: effectiveRatio,
        hits: hits.map((signal) => ({ key: signal.key, label: signal.label })),
        missing: missing.map((signal) => ({ key: signal.key, label: signal.label })),
        guide: dim.guide,
        misses: dim.misses.slice(),
        example: dim.example,
      });

      if (!hits.length) {
        questions.push({
          id: dim.key + '::base',
          dimension: dim.key,
          dimension_label: dim.label,
          question: dim.base_question,
          why: dim.why,
          priority: 'high',
          evidence: '',
          hint: dim.example,
          source: 'rule',
        });
      } else {
        missing.slice(0, 2).forEach((signal) => {
          questions.push({
            id: dim.key + '::' + signal.key,
            dimension: dim.key,
            dimension_label: dim.label,
            question: (dim.signal_questions || {})[signal.key] || dim.base_question,
            why: dim.why,
            priority: draftRatio < 0.5 ? 'high' : 'normal',
            evidence: signalEvidence(lines, signal.patterns) || '',
            hint: dim.example,
            source: 'rule',
            signal: signal.label,
          });
        });
      }
    });

    // 모호 표현 되묻기
    const vague = [];
    vaguePatterns.forEach(([pattern, reason], idx) => {
      const rx = compile(pattern, 'gi');
      if (!rx) return;
      let occ = 0;
      let found;
      while ((found = rx.exec(body)) !== null) {
        if (occ >= 2) break;
        const sentence = sentenceAround(body, found.index);
        if (sentence) {
          const dimKey = guessDimension(sentence, dims);
          const dim = dims.find((item) => item.key === dimKey) || dims[0];
          const phrase = found[0];
          vague.push({
            id: 'vague::' + idx + '::' + occ,
            dimension: dimKey,
            dimension_label: dim.label,
            question: vagueQuestion(phrase, sentence),
            why: "'" + phrase + "'라고만 적혀 있어 후임자가 판단할 수 없습니다(" + reason + ').',
            priority: (phrase.indexOf('문의') !== -1 || phrase.indexOf('참고') !== -1) ? 'high' : 'normal',
            evidence: sentence.slice(0, 160),
            hint: '',
            source: 'vague',
            signal: '모호 표현',
          });
        }
        occ += 1;
        if (found.index === rx.lastIndex) rx.lastIndex += 1;   // 빈 매치 무한 반복 방지
      }
    });

    const seenDims = new Set();
    const picked = [];
    vague.forEach((item) => {
      if (seenDims.has(item.dimension)) return;
      seenDims.add(item.dimension);
      picked.push(item);
    });
    questions.push(...picked.slice(0, 4));

    const order = {};
    dims.forEach((dim, index) => { order[dim.key] = index; });
    questions.sort((a, b) => {
      const pa = a.priority === 'high' ? 0 : 1;
      const pb = b.priority === 'high' ? 0 : 1;
      if (pa !== pb) return pa - pb;
      const oa = order[a.dimension] == null ? 99 : order[a.dimension];
      const ob = order[b.dimension] == null ? 99 : order[b.dimension];
      return oa - ob;
    });
    const limited = questions.slice(0, MAX_RULE_QUESTIONS);

    limited.forEach((question) => {
      const answer = answered[question.id];
      question.answer = answer ? answer.text : '';
      question.skipped = !!(answer && answer.skipped);
      question.status = (answer && answer.text) ? 'answered' : (question.skipped ? 'skipped' : 'unanswered');
    });

    const stats = {
      total: limited.length,
      answered: limited.filter((q) => q.status === 'answered').length,
      skipped: limited.filter((q) => q.status === 'skipped').length,
      unanswered: limited.filter((q) => q.status === 'unanswered').length,
    };

    const draftScore = pyRound(coverage.reduce((sum, row) => sum + row.draft_ratio, 0) / coverage.length, 2);
    const effectiveScore = pyRound(coverage.reduce((sum, row) => sum + row.effective_ratio, 0) / coverage.length, 2);

    return {
      coverage,
      questions: limited,
      vague,
      stats,
      summary: {
        dimensions: coverage.length,
        covered: coverage.filter((row) => row.status === 'covered').length,
        partial: coverage.filter((row) => row.status === 'partial').length,
        missing: coverage.filter((row) => row.status === 'missing').length,
        draft_score: draftScore,
        effective_score: effectiveScore,
      },
    };
  };

  /* ================================================================== */
  /* 3) 약관·규정 조항 찾기 (app/terms.py)                              */
  /* ================================================================== */

  const SPACE_RE = /\s+/g;

  function tokenize(text) {
    const words = String(text || '').match(/[가-힣]{2,}|[A-Za-z]{3,}/g) || [];
    const tokens = [];
    words.forEach((word) => {
      let token = word.toLowerCase();
      const particles = CORE._particles || [];
      for (const particle of particles) {
        if (token.length > particle.length + 1 && token.endsWith(particle)) {
          token = token.slice(0, -particle.length);
          break;
        }
      }
      if (token.length >= 2 && !(CORE._stopwords && CORE._stopwords.has(token))) tokens.push(token);
    });
    return tokens;
  }

  function splitSentences(text) {
    const sentences = [];
    String(text || '').split('\n').forEach((raw) => {
      const line = stripChars(raw, ' -•·\t');
      if (!line) return;
      if (line.startsWith('#')) return;
      if (line.toUpperCase().startsWith('TODO')) return;
      if (test(META_LINE_RE, line)) return;
      const pieces = splitByLookbehind(line);
      pieces.forEach((piece) => {
        const trimmed = stripChars(piece, ' -•·\t');
        if (trimmed.length < 8) return;
        if (!test('[가-힣]{2,}', trimmed)) return;
        sentences.push(trimmed);
      });
    });
    return sentences;
  }

  function splitByLookbehind(line) {
    const rx = compile('(?<=[.다요음])\\s+|(?<=[\\)\\]])\\s+', 'g');
    if (!rx) return [line];       // lookbehind 미지원 브라우저: 줄 단위로만 나눈다
    return line.split(rx);
  }

  function termVariants(term) {
    const base = String(term).replace(SPACE_RE, '');
    const variants = [base];
    if (base.indexOf('의') !== -1 && base.length >= 4) variants.push(base.split('의').join(''));
    ((CORE._aliases || {})[base] || []).forEach((alias) => variants.push(alias));
    return variants.filter((value, index) => variants.indexOf(value) === index);
  }

  function sentenceTerms(compactSentence, termsDict) {
    const found = [];
    Object.keys(termsDict).forEach((term) => {
      if (term.length >= 2 && compactSentence.indexOf(term) !== -1) {
        found.push({ term, weight: termsDict[term], variants: termVariants(term) });
      }
    });
    found.sort((a, b) => b.weight - a.weight);
    return found;
  }

  function confidence(score) {
    if (score >= 9.0) return '높음';
    if (score >= 5.0) return '중간';
    return '낮음';
  }

  function cleanText(text) {
    return String(text || '').replace(/[ \t]+/g, ' ').replace(/\n{2,}/g, '\n').trim();
  }

  function excerpt(text, terms, words, limit) {
    const max = limit || 320;
    const body = cleanText(text);
    if (body.length <= max) return body;
    let position = -1;
    [...(terms || []), ...(words || [])].forEach((needle) => {
      if (!needle) return;
      const found = body.indexOf(needle);
      if (found !== -1 && (position === -1 || found < position)) position = found;
    });
    if (position === -1) return body.slice(0, max) + '…';
    const start = Math.max(0, position - 80);
    return (start ? '…' : '') + body.slice(start, start + max) + '…';
  }

  function unitLocation(unit) {
    const parts = [unit.article_no];
    if (unit.title) parts.push('(' + unit.title + ')');
    if (unit.paragraph) parts.push(unit.paragraph);
    parts.push(unit.printed_page + '쪽');
    if (unit.chapter) parts.push(unit.chapter);
    return parts.join(' · ');
  }

  function packCandidate(candidate) {
    const unit = candidate.unit;
    return {
      article_no: unit.article_no,
      title: unit.title,
      chapter: unit.chapter,
      paragraph: unit.paragraph,
      printed_page: unit.printed_page,
      location: unit.location,
      text: unit.text,
      excerpt: candidate.excerpt,
      score: candidate.score,
      confidence: candidate.confidence,
      matched_terms: candidate.matched_terms,
      matched_words: candidate.matched_words,
      kind: unit.kind,
    };
  }

  /**
   * 규정 1건(내장 샘플)에 대해 초안 문장마다 근거 후보 조문을 찾는다.
   * reg 는 data/regulation.json — 조문 단위·IDF·용어 가중치가 미리 들어 있다.
   */
  CORE.matchRegulation = function matchRegulation(reg, handoverText, options) {
    const opts = options || {};
    const topK = opts.top_k || 3;
    const threshold = opts.threshold == null ? 2.4 : opts.threshold;

    CORE._particles = reg.particles;
    CORE._stopwords = new Set(reg.stopwords);
    CORE._aliases = reg.aliases;

    const idf = reg.idf;
    const termsDict = reg.terms;
    const sentences = splitSentences(handoverText);

    const prepared = reg.units.map((unit) => {
      const tokens = unit.tokens;
      const compact = (unit.text + ' ' + unit.title).replace(SPACE_RE, '');
      const compactTitle = unit.title.replace(SPACE_RE, '');
      return { unit, tokens, tokenSet: new Set(tokens), length: tokens.length, compact, compactTitle };
    });
    const averageLength = prepared.length
      ? prepared.reduce((sum, item) => sum + item.length, 0) / prepared.length
      : 1;
    const k1 = 1.4;
    const b = 0.7;

    const results = [];

    sentences.forEach((sentence) => {
      const sentenceTokens = new Set(tokenize(sentence));
      if (!sentenceTokens.size) return;
      const compactSentence = sentence.replace(SPACE_RE, '');
      const candidates = sentenceTerms(compactSentence, termsDict);
      const scored = [];

      prepared.forEach((item) => {
        const shared = [];
        sentenceTokens.forEach((token) => { if (item.tokenSet.has(token)) shared.push(token); });
        const domainHits = candidates
          .filter((candidate) => candidate.variants.some((variant) => item.compact.indexOf(variant) !== -1))
          .map((candidate) => ({ term: candidate.term, weight: candidate.weight }));
        if (!shared.length && !domainHits.length) return;
        const strongShared = shared.filter((token) => (idf[token] || 0) >= 1.1);
        if (!domainHits.length && strongShared.length < 2) return;

        let score = 0;
        shared.forEach((token) => {
          let tf = 0;
          item.tokens.forEach((value) => { if (value === token) tf += 1; });
          const denominator = tf + k1 * (1 - b + b * item.length / Math.max(averageLength, 1));
          score += (idf[token] == null ? 0.5 : idf[token]) * (tf * (k1 + 1)) / Math.max(denominator, 0.001);
        });

        const titleTokens = new Set(tokenize(item.unit.title));
        let titleHits = 0;
        shared.forEach((token) => { if (titleTokens.has(token)) titleHits += 1; });
        score += 1.2 * titleHits;

        const weightSum = domainHits.slice(0, 2).reduce((sum, hit) => sum + hit.weight, 0);
        score += 1.6 * Math.min(weightSum / 3.0, 2.0);

        const titleTermHits = domainHits.filter((hit) =>
          termVariants(hit.term).some((variant) => item.compactTitle.indexOf(variant) !== -1)).length;
        score += 0.6 * Math.min(titleTermHits, 2);

        if (score > 0) {
          const strongWords = shared
            .filter((token) => (idf[token] || 0) >= 1.1)
            .sort((left, right) => (idf[right] || 0) - (idf[left] || 0))
            .slice(0, 6);
          scored.push({ score, unit: item.unit, hits: domainHits, words: strongWords, titleHits });
        }
      });

      scored.sort((left, right) => right.score - left.score);
      const best = [];
      scored.slice(0, topK).forEach((row, rank) => {
        if (row.score < threshold) return;
        if (rank > 0 && scored.length && row.score < scored[0].score * 0.55) return;
        let conf = confidence(row.score);
        if (row.titleHits === 0 && conf === '높음') conf = '중간';
        best.push({
          unit: row.unit,
          score: pyRound(row.score, 2),
          confidence: conf,
          matched_terms: row.hits.map((hit) => hit.term),
          matched_words: row.words,
          excerpt: excerpt(row.unit.text, row.hits.map((hit) => hit.term), row.words),
        });
      });

      if (best.length) {
        results.push({
          sentence,
          primary: best[0],
          alternatives: best.slice(1),
          confidence: best[0].confidence,
        });
      }
    });

    const matchedArticles = new Map();
    results.forEach((item) => {
      [item.primary, ...item.alternatives].forEach((candidate) => {
        const unit = candidate.unit;
        const key = unit.article_no || ('p.' + unit.printed_page);
        if (!matchedArticles.has(key)) {
          matchedArticles.set(key, {
            article_no: unit.article_no,
            title: unit.title,
            chapter: unit.chapter,
            printed_page: unit.printed_page,
            sentences: 0,
            location: unit.location,
          });
        }
        matchedArticles.get(key).sentences += 1;
      });
    });

    return {
      matches: results.map((item) => ({
        sentence: item.sentence,
        primary: packCandidate(item.primary),
        alternatives: item.alternatives.map(packCandidate),
        confidence: item.confidence,
      })),
      stats: {
        sentences: sentences.length,
        matched: results.length,
        articles: matchedArticles.size,
      },
      articles: Array.from(matchedArticles.values()).sort((left, right) => right.sentences - left.sentences),
      disclaimer: reg.disclaimer,
      regulation: reg.summary,
    };
  };

  CORE.splitSentences = splitSentences;
  CORE.tokenize = tokenize;

  /* ================================================================== */
  /* 4) 내보내기 (app/export.py)                                        */
  /* ================================================================== */

  const EXPORT_META_LINE_RE = '^-?\\s*(인계자|인수자|소속|부서\\s*/\\s*직무|직무|작성일|인수인계\\s*기간|파일명)\\s*[:：]';

  const HEADING_HINTS = [
    ['인수인계 후', 'support'], ['지원', 'support'],
    ['검증', 'verify'], ['확인 방법', 'verify'], ['점검', 'verify'],
    ['보고', 'reporting'], ['승인', 'reporting'], ['결재', 'reporting'],
    ['예산', 'budget'], ['정산', 'budget'], ['계약', 'budget'],
    ['문서', 'documents'], ['자료', 'documents'], ['파일', 'documents'],
    ['현안', 'pending'], ['미결', 'pending'], ['진행', 'pending'],
    ['규정', 'rules'], ['약관', 'rules'], ['법규', 'rules'],
    ['시스템', 'systems'], ['계정', 'systems'], ['권한', 'systems'],
    ['연락처', 'contacts'], ['협력', 'contacts'], ['유관', 'contacts'],
    ['예외', 'exception'], ['돌발', 'exception'], ['민원', 'exception'],
    ['정기', 'routine'], ['일상', 'routine'], ['반복', 'routine'],
    ['업무 개요', 'scope'], ['담당 업무', 'scope'], ['개요', 'scope'],
  ];

  function headingDimension(line) {
    const heading = line.replace(/^#+/, '').trim();
    for (const [needle, key] of HEADING_HINTS) {
      if (heading.indexOf(needle) !== -1) return key;
    }
    return null;
  }

  function isHeading(line) {
    return line.startsWith('#')
      || test('^\\d+[).]\\s+\\S', line)
      || test('^[□■○●▸▶]\\s*\\S', line);
  }

  function dimensionOf(line, dims) {
    let best = '';
    let bestScore = 0;
    dims.forEach((dim) => {
      let score = 0;
      dim.signals.forEach((signal) => {
        if (signal.patterns.some((pattern) => firstMatch(pattern, line, 'i'))) score += 1;
      });
      dim.label.split('·').forEach((part) => {
        const trimmed = part.trim();
        if (trimmed.length >= 2 && line.indexOf(trimmed) !== -1) score += 2;
      });
      if (score > bestScore) { best = dim.key; bestScore = score; }
    });
    if (bestScore) return [best, bestScore];
    if (test('(접수|처리|담당|관리|등록|회신|안내|작성|보고|검토)', line)) return ['scope', 1];
    return ['', 0];
  }

  function nowStamp(now) {
    if (now) return now;
    const d = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate())
      + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
  }

  /**
   * 정리된 인수인계서(마크다운)와 일반 텍스트를 만든다.
   * chk 는 data/checklist.json (표준 12항목 정의), termsResult 는 3단계 결과 또는 null.
   */
  CORE.buildExport = function buildExport(meta, draft, analysis, termsResult, options) {
    const opts = options || {};
    const chk = opts.checklist;
    const dims = chk.dimensions;
    const questions = (analysis && analysis.questions) || [];
    const now = nowStamp(opts.now);
    const imageNote = String(opts.image_note || '').trim();
    const imageCount = Number(opts.image_count || 0) || 0;

    const assigned = {};
    dims.forEach((dim) => { assigned[dim.key] = []; });
    const unassigned = [];
    let current = null;

    String(draft || '').split('\n').forEach((raw) => {
      const line = raw.trim();
      if (!line) return;
      if (isHeading(line)) { current = headingDimension(line); return; }
      if (line.toUpperCase().startsWith('TODO') || test(EXPORT_META_LINE_RE, line)) return;
      const text = line.replace(/^[-•·]\s*/, '');
      if (current) { assigned[current].push(text); return; }
      const [key, score] = dimensionOf(text, dims);
      if (key && score > 0) assigned[key].push(text);
      else unassigned.push(text);
    });

    const m = meta || {};
    const md = [];
    md.push('# 인수인계서 — ' + (m.team || '업무 인수인계'));
    md.push('');
    md.push('| 항목 | 내용 |');
    md.push('| --- | --- |');
    [['인계자', 'author'], ['인수자', 'successor'], ['부서·직무', 'team'],
      ['인수인계 기간', 'period'], ['작성 기준', 'base'], ['문서 생성', 'generated']]
      .forEach(([label, key]) => {
        let value = m[key] || (key === 'successor' ? '(미정)' : '');
        if (key === 'generated') value = now + ' · 인수인계서 AI 프로토타입(가상 데모)';
        md.push('| ' + label + ' | ' + value + ' |');
      });
    md.push('');

    const summary = (analysis && analysis.summary) || {};
    md.push('## 문서 완성도 요약');
    md.push('');
    md.push('- 초안 기준 커버리지: **' + Math.trunc((summary.draft_score || 0) * 100) + '%**');
    md.push('- 답변 반영 커버리지: **' + Math.trunc((summary.effective_score || 0) * 100) + '%**');
    md.push('- 항목 점검(초안의 표현을 기준으로): 충실 ' + (summary.covered || 0) + '개 · 일부 '
      + (summary.partial || 0) + '개 · 비어 있음 ' + (summary.missing || 0) + '개 (총 '
      + (summary.dimensions || 12) + '개)');
    const stats = (analysis && analysis.stats) || {};
    md.push('- 질문 ' + (stats.total || 0) + '개 중 답변 ' + (stats.answered || 0) + '개, 건너뜀 '
      + (stats.skipped || 0) + '개, 미답변 ' + (stats.unanswered || 0) + '개');
    md.push('');

    if (imageCount || imageNote) {
      md.push('## 그림 속 내용 보완');
      md.push('');
      if (imageCount) md.push('- 문서에서 그림 ' + imageCount + '장이 감지되었습니다.');
      if (imageNote) {
        md.push('- 그림 속 표기·글자는 자동으로 읽지 않았고, 인계자가 확인해 아래와 같이 적었습니다.');
        md.push('');
        md.push(imageNote);
      } else {
        md.push('- 그림 속 내용은 아직 보완되지 않았습니다. 후임자가 직접 확인해야 합니다.');
      }
      md.push('');
    }

    dims.forEach((dim, index) => {
      md.push('## ' + (index + 1) + '. ' + dim.label);
      md.push('');
      if (assigned[dim.key] && assigned[dim.key].length) {
        assigned[dim.key].forEach((line) => md.push('- ' + line));
      } else {
        md.push('- (초안에 해당 항목이 없습니다)');
      }
      md.push('');

      const answers = questions.filter((q) => q.dimension === dim.key && q.status === 'answered');
      if (answers.length) {
        md.push('**추가 확인한 내용**');
        md.push('');
        answers.forEach((q) => {
          md.push('- ' + q.question);
          md.push('  → ' + q.answer);
        });
        md.push('');
      }

      const openQuestions = questions.filter((q) => q.dimension === dim.key && q.status === 'unanswered');
      if (openQuestions.length) {
        md.push('**확인 필요**');
        md.push('');
        openQuestions.forEach((q) => md.push('- ' + q.question));
        md.push('');
      }
    });

    const pending = questions.filter((q) => q.status === 'unanswered');
    md.push('## 아직 답하지 못한 질문 목록');
    md.push('');
    if (pending.length) {
      md.push('후임자가 첫 주에 직접 확인해야 할 항목입니다.');
      md.push('');
      md.push('| # | 항목 | 질문 | 왜 필요한가 |');
      md.push('| --- | --- | --- | --- |');
      pending.forEach((q, index) => {
        const why = String(q.why || '').replace(/\|/g, '/');
        const question = String(q.question || '').replace(/\|/g, '/');
        md.push('| ' + (index + 1) + ' | ' + (q.dimension_label || '') + ' | ' + question + ' | ' + why + ' |');
      });
    } else {
      md.push('없습니다. 모든 질문에 답변이 등록되었습니다.');
    }
    md.push('');

    if (termsResult && termsResult.matches && termsResult.matches.length) {
      md.push('## 검토한 근거 규정');
      md.push('');
      const reg = termsResult.regulation || {};
      md.push('- 규정: ' + (reg.name || '') + (reg.version_label ? ' (' + reg.version_label + ')' : ''));
      if (reg.source_url) md.push('- 출처: ' + reg.source_url);
      md.push('');
      md.push('| 인수인계 문장 | 근거 후보 조문 | 위치 | 신뢰도 |');
      md.push('| --- | --- | --- | --- |');
      termsResult.matches.forEach((item) => {
        const primary = item.primary;
        md.push('| ' + String(item.sentence).replace(/\|/g, '/') + ' | ' + primary.article_no + ' '
          + primary.title + ' | ' + primary.printed_page + '쪽 | ' + primary.confidence + ' |');
      });
      md.push('');
      md.push('> ' + (reg.disclaimer || termsResult.disclaimer || ''));
      md.push('');
    }

    if (unassigned.length) {
      md.push('## 부록 A. 초안 원문 중 항목을 정하지 못한 문장');
      md.push('');
      unassigned.forEach((line) => md.push('- ' + line));
      md.push('');
    }

    md.push('## 부록 B. 초안 원문 (가공 없이 보존)');
    md.push('');
    md.push('```');
    md.push(String(draft || '').trim());
    md.push('```');
    md.push('');
    md.push('---');
    md.push('생성: ' + now + ' · 인수인계서 AI 프로토타입 (공개 자료·가상 데이터로만 작성)');

    const markdown = md.join('\n');
    return {
      markdown,
      text: toPlain(markdown),
      filename: exportFilename(m),
    };
  };

  function toPlain(markdown) {
    const out = [];
    String(markdown).split('\n').forEach((line) => {
      if (line.startsWith('```')) return;
      if (line.startsWith('#')) {
        const text = line.replace(/^#+/, '').trim();
        out.push(text);
        out.push('-'.repeat(Math.min(text.length, 40)));
        return;
      }
      if (line.startsWith('|')) {
        const cells = line.replace(/^\||\|$/g, '').split('|').map((cell) => cell.trim());
        if (cells.join('').split('').every((ch) => ch === '-')) return;
        out.push(cells.join('  '));
        return;
      }
      out.push(line.replace(/\*\*/g, '').replace(/> /g, ''));
    });
    return out.join('\n').trim() + '\n';
  }

  function exportFilename(meta) {
    const team = (meta || {}).team || '인수인계서';
    const safe = team.replace(/[^0-9A-Za-z가-힣]+/g, '_').replace(/^_+|_+$/g, '') || '인수인계서';
    const d = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    return safe + '_인수인계서_' + d.getFullYear() + pad(d.getMonth() + 1) + pad(d.getDate());
  }

  /* ================================================================== */
  /* 5) 파일 읽기 (.docx · .hwpx · .md · .txt)                          */
  /* ================================================================== */

  const IMAGE_EXTENSIONS = ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tif', '.tiff',
    '.webp', '.svg', '.emf', '.wmf'];

  function decodeEntities(text) {
    return String(text)
      .replace(/&lt;/g, '<').replace(/&gt;/g, '>')
      .replace(/&quot;/g, '"').replace(/&apos;/g, "'")
      .replace(/&#x([0-9a-fA-F]+);/g, (m, hex) => String.fromCodePoint(parseInt(hex, 16)))
      .replace(/&#(\d+);/g, (m, dec) => String.fromCodePoint(parseInt(dec, 10)))
      .replace(/&amp;/g, '&');
  }

  function normalizeText(text) {
    return String(text)
      .replace(/\r\n/g, '\n').replace(/\r/g, '\n')
      .replace(/\u00a0/g, ' ').replace(/\u200b/g, '')
      .split('\n').map((line) => line.replace(/[ \t]+$/, '')).join('\n')
      .replace(/\n{3,}/g, '\n\n')
      .trim();
  }

  async function unzip(buffer) {
    const view = new DataView(buffer);
    const bytes = new Uint8Array(buffer);
    let eocd = -1;
    const floor = Math.max(0, bytes.length - 66000);
    for (let i = bytes.length - 22; i >= floor; i -= 1) {
      if (view.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
    }
    if (eocd < 0) throw new Error('압축 구조를 찾지 못했습니다(문서가 손상되었을 수 있습니다).');
    const count = view.getUint16(eocd + 10, true);
    const start = view.getUint32(eocd + 16, true);
    const entries = new Map();
    let p = start;
    for (let i = 0; i < count; i += 1) {
      if (p + 46 > bytes.length || view.getUint32(p, true) !== 0x02014b50) break;
      const method = view.getUint16(p + 10, true);
      const compSize = view.getUint32(p + 20, true);
      const nameLen = view.getUint16(p + 28, true);
      const extraLen = view.getUint16(p + 30, true);
      const commentLen = view.getUint16(p + 32, true);
      const localOffset = view.getUint32(p + 42, true);
      const name = new TextDecoder('utf-8').decode(bytes.subarray(p + 46, p + 46 + nameLen));
      entries.set(name, { method, compSize, localOffset });
      p += 46 + nameLen + extraLen + commentLen;
    }
    return {
      names: Array.from(entries.keys()),
      has: (name) => entries.has(name),
      async read(name) {
        const entry = entries.get(name);
        if (!entry) throw new Error('문서 안에서 ' + name + ' 을(를) 찾지 못했습니다.');
        const local = entry.localOffset;
        const nameLen = view.getUint16(local + 26, true);
        const extraLen = view.getUint16(local + 28, true);
        const dataStart = local + 30 + nameLen + extraLen;
        const data = bytes.subarray(dataStart, dataStart + entry.compSize);
        if (entry.method === 0) return new TextDecoder('utf-8').decode(data);
        if (entry.method !== 8) throw new Error('지원하지 않는 압축 방식입니다.');
        if (typeof DecompressionStream === 'undefined') {
          throw new Error('이 브라우저는 압축 해제를 지원하지 않습니다. 최신 브라우저로 열어 주세요.');
        }
        const stream = new Blob([data]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
        return new TextDecoder('utf-8').decode(await new Response(stream).arrayBuffer());
      },
    };
  }

  /** 정규식의 첫 번째 캡처 그룹들을 모두 모아 이어 붙인다(태그는 버린다). */
  function collectText(block, pattern) {
    const rx = new RegExp(pattern.source, pattern.flags.indexOf('g') === -1 ? pattern.flags + 'g' : pattern.flags);
    const parts = [];
    let found;
    while ((found = rx.exec(block)) !== null) {
      parts.push(found[1] == null ? '' : found[1]);
      if (found.index === rx.lastIndex) rx.lastIndex += 1;
    }
    return parts.join('');
  }

  /** 워드 제목 스타일이면 마크다운 제목으로 바꿔 섹션 구조를 살린다(서버 파서와 같은 규칙). */
  function headingPrefix(styleName) {
    const style = String(styleName || '').trim();
    if (!style) return '';
    const lower = style.toLowerCase();
    if (lower.indexOf('title') !== -1) return '# ';
    if (lower.indexOf('heading') === -1) return '';
    const digit = lower.match(/(\d)/);
    const level = digit ? Math.min(3, Math.max(1, parseInt(digit[1], 10))) : 2;
    return '#'.repeat(level) + ' ';
  }

  /**
   * XML(워드·한글 문서)에서 문단은 줄로, 표는 '| 셀 | 셀 |' 행으로 펼친다.
   * 태그만 걷어내고 값은 그대로 둔다(서버 파서와 같은 방침: 읽지 못한 것은 경고로 알린다).
   */
  function documentLines(xml, spec) {
    const tables = [];
    const withoutTables = xml.replace(spec.table, (block) => {
      const rows = [];
      const rowPattern = new RegExp(spec.row.source, 'g');
      let row;
      while ((row = rowPattern.exec(block)) !== null) {
        const cells = [];
        const cellPattern = new RegExp(spec.cell.source, 'g');
        let cell;
        while ((cell = cellPattern.exec(row[0])) !== null) {
          const parts = [];
          const paraPattern = new RegExp(spec.para.source, 'g');
          let para;
          while ((para = paraPattern.exec(cell[0])) !== null) {
            parts.push(collectText(para[0], spec.text));
          }
          cells.push(decodeEntities(parts.join(' ')).replace(/\s+/g, ' ').trim());
        }
        if (cells.some((value) => value)) rows.push('| ' + cells.join(' | ') + ' |');
      }
      tables.push(rows);
      return '\u0000';
    });

    const lines = [];
    const chunks = withoutTables.split('\u0000');
    chunks.forEach((chunk, index) => {
      const paraPattern = new RegExp(spec.para.source, 'g');
      let para;
      while ((para = paraPattern.exec(chunk)) !== null) {
        const text = decodeEntities(collectText(para[0], spec.text)).trim();
        if (!text) continue;
        const style = (para[0].match(spec.style) || [])[1];
        lines.push(style ? headingPrefix(style) + text : text);
      }
      if (index < chunks.length - 1 && tables[index]) lines.push(...tables[index]);
    });
    return lines;
  }

  const DOCX_SPEC = {
    table: /<w:tbl[ >][\s\S]*?<\/w:tbl>/g,
    row: /<w:tr[ >][\s\S]*?<\/w:tr>/g,
    cell: /<w:tc[ >][\s\S]*?<\/w:tc>/g,
    para: /<w:p[ >][\s\S]*?<\/w:p>/g,
    text: /<w:t(?:\s[^>]*)?>([\s\S]*?)<\/w:t>/g,
    style: /<w:pStyle w:val="([^"]+)"\s*\/>/,
  };

  const HWPX_SPEC = {
    table: /<hp:tbl[ >][\s\S]*?<\/hp:tbl>/g,
    row: /<hp:tr[ >][\s\S]*?<\/hp:tr>/g,
    cell: /<hp:tc[ >][\s\S]*?<\/hp:tc>/g,
    para: /<hp:p[ >][\s\S]*?<\/hp:p>/g,
    text: /<hp:t(?:\s[^>]*)?>([\s\S]*?)<\/hp:t>/g,
    style: /$^/,
  };

  function paragraphsFromXml(xml, spec) {
    return documentLines(xml, spec || DOCX_SPEC);
  }

  /** 파일을 읽어 화면 1단계가 쓰는 모양(kind·text·image_count·warnings)으로 돌려준다. */
  CORE.parseFile = async function parseFile(file) {
    const name = file.name || '붙여넣은 텍스트';
    const ext = name.indexOf('.') !== -1 ? '.' + name.split('.').pop().toLowerCase() : '';
    const buffer = await file.arrayBuffer();
    const head = new Uint8Array(buffer.slice(0, 8));

    if (head[0] === 0x25 && head[1] === 0x50 && head[2] === 0x44 && head[3] === 0x46) {
      throw new Error('정적 시연 버전에서는 PDF의 글자를 읽지 못합니다. .docx · .hwpx · .md · .txt 파일로 올려 주세요.');
    }
    if (head[0] === 0x50 && head[1] === 0x4b) {
      const zip = await unzip(buffer);
      const names = zip.names;
      if (names.indexOf('word/document.xml') !== -1) {
        const xml = await zip.read('word/document.xml');
        const text = normalizeText(paragraphsFromXml(xml, DOCX_SPEC).join('\n'));
        const imageCount = names.filter((entry) =>
          entry.startsWith('word/media/') && IMAGE_EXTENSIONS.some((imageExt) => entry.toLowerCase().endsWith(imageExt))).length;
        const warnings = [];
        if (imageCount) {
          warnings.push('그림 ' + imageCount + '장은 글자로 읽지 않았습니다. 그림 속 표기는 2단계에서 직접 보완할 수 있습니다.');
        }
        if (!text) throw new Error('docx에서 텍스트를 찾지 못했습니다. 내용이 이미지로만 들어 있지 않은지 확인해 주세요.');
        return makeParsed(name, 'docx', text, warnings, imageCount, {});
      }
      const sections = names.filter((entry) => /^Contents\/section\d+\.xml$/.test(entry)).sort();
      if (sections.length) {
        const lines = [];
        for (const section of sections) {
          const xml = await zip.read(section);
          lines.push(...paragraphsFromXml(xml, HWPX_SPEC));
        }
        const text = normalizeText(lines.join('\n'));
        const imageCount = names.filter((entry) =>
          entry.startsWith('BinData/') && IMAGE_EXTENSIONS.some((imageExt) => entry.toLowerCase().endsWith(imageExt))).length;
        const warnings = [];
        if (imageCount) {
          warnings.push('그림 ' + imageCount + '장은 글자로 읽지 않았습니다. 그림 속 표기는 2단계에서 직접 보완할 수 있습니다.');
        } else if (names.some((entry) => entry.startsWith('BinData/'))) {
          warnings.push('hwpx에 포함된 개체는 텍스트로 읽지 않았습니다.');
        }
        if (!text) throw new Error('hwpx에서 텍스트를 찾지 못했습니다. 내용이 표·이미지로만 되어 있는지 확인해 주세요.');
        return makeParsed(name, 'hwpx', text, warnings, imageCount, { sections: sections.length });
      }
      throw new Error('docx도 hwpx도 아닌 압축 파일입니다. 지원 형식(.docx/.hwpx/.md/.txt)인지 확인해 주세요.');
    }
    if (ext === '.hwp' || (head[0] === 0x48 && head[1] === 0x57 && head[2] === 0x50)) {
      throw new Error('한글 5.0(.hwp) 파일은 정적 시연 버전에서 읽지 못합니다. .hwpx로 저장해 올려 주세요.');
    }
    const text = normalizeText(new TextDecoder('utf-8').decode(buffer));
    return makeParsed(name, 'text', text, [], 0, {});
  };

  function makeParsed(filename, kind, text, warnings, imageCount, meta) {
    return {
      filename,
      kind,
      text,
      pages: [],
      page_count: 0,
      warnings,
      meta: meta || {},
      image_count: imageCount,
      char_count: text.length,
      line_count: text ? text.split('\n').length : 0,
    };
  }

  global.DEMO_CORE = CORE;
})(window);
