# 인수인계서 AI — 정적 시연 (GitHub Pages)

`feature/web-prototype` 브랜치의 웹 화면을 **서버 없이 그대로 열어 볼 수 있게** 만든 시연 사이트입니다.

- 주소: <https://sn0508-beep.github.io/inganingong/>
- 원본 코드·문서: [`feature/web-prototype`](https://github.com/sn0508-beep/inganingong/tree/feature/web-prototype)
- 자체 점검 페이지: <https://sn0508-beep.github.io/inganingong/selftest.html>

## 이 브랜치는 자동 생성물입니다

`gh-pages` 브랜치의 파일은 대부분 빌드 결과입니다. 손으로 고치면 다음 빌드에서 덮어써집니다.
고칠 곳은 `feature/web-prototype` 브랜치의 원본(`app/templates/index.html`, `app/static/app.js`,
`app/static/app.css`, `app/*.py`)과 이 브랜치의 `build/` 안에 있는 `demo-*.js` · `demo.css` ·
`selftest.html`(서버 계산을 브라우저로 옮긴 부분)입니다. 고친 뒤 다시 빌드해서 이 브랜치에 올립니다.

```bash
# 원본 저장소 클론 안에서
python3 build/build_static.py --repo ../inganingong --site .
git add -A && git commit -m "chore: 정적 시연 재빌드" && git push origin gh-pages
```

## 구성

| 경로 | 설명 |
| --- | --- |
| `index.html` | Flask 템플릿(`app/templates/index.html`)을 렌더링한 결과 |
| `app.js`, `app.css` | 원본 `app/static/` 파일. 화면 로직은 서버 버전과 **같은 파일**을 씁니다 |
| `demo-api.js` | 화면이 부르는 `/api/...` 호출을 가로채 브라우저 안에서 응답을 만드는 어댑터 (원본: `build/demo-api.js`) |
| `demo-core.js` | 서버 계산(`app/gap.py` · `app/terms.py` · `app/export.py` · `app/masking.py`)을 옮긴 모듈 (원본: `build/demo-core.js`) |
| `demo.css` | 정적 시연 안내 줄 스타일(기존 디자인은 그대로) (원본: `build/demo.css`) |
| `data/` | 빌드가 내보낸 데이터 — 12항목 신호·질문 은행, 샘플 초안, 약관 조문 단위·IDF·용어 가중치, 자체 점검 기대값 |
| `samples/` | 1단계에서 내려받아 업로드해 볼 샘플 파일 |
| `build/` | 빌드 스크립트(`build_static.py`)와 손으로 쓴 원본(`demo-core.js` · `demo-api.js` · `demo.css` · `selftest.html`). 루트의 같은 이름 파일은 여기서 복사된 것입니다 |
| `selftest.html` | `demo-core.js` 계산 결과를 서버(Python) 결과와 문항별로 대조하는 페이지 (원본: `build/selftest.html`) |

## 정적 시연이라 안 되는 것 (화면에서 안내문으로 알려 줍니다)

- **AI 연결**: 사내 AI · 외부 AI · 사내 표준약관 AI 주소로 실제 연결하지 않습니다.
  연결할 수 없을 때의 안내 카드와 대체 경로(규정 PDF로 진행 등)는 그대로 보입니다.
- **파일 읽기**: `.docx` · `.hwpx` · `.md` · `.txt` 는 브라우저에서 직접 읽습니다.
  `.pdf` · 한글 5.0(`.hwp`)은 글자를 뽑지 못해 안내 문구를 돌려줍니다.
- **규정 업로드**: 서버가 없어 올린 규정을 보관하지 않습니다. 내장 샘플(한국전력공사 기본공급약관,
  법제처 게시본) 1건으로 조항 매칭이 동작합니다.

## 데이터에 대해

화면에 나오는 회사·인물·연락처·금액은 모두 지어낸 값입니다. 내장 약관만 공개 자료
(법제처 찾기쉬운 생활법령정보 게시본, 한국전력공사 기본공급약관 2026. 4. 1 시행)입니다.
