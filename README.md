# open_site_clipper

**흩어진 조직의 공지를 한 편의 보고서로.**
정부·공공기관의 RSS/OpenAPI 는 물론, 한국외국어대학교처럼 본부·처·팀이
홈페이지를 따로 쓰는 조직도 **한 기관으로 묶어** 수집합니다. 필요한 목적
(고용·장학·정부투자…)만 골라 브리프로 만들고, 모든 출력에 출처와
**공공누리(KOGL) 등급**을 남깁니다. Markdown · HTML · JSON, 브라우저에서
클릭으로 쓰는 로컬 웹 UI(`--serve`), 그리고 **휴대폰에서 주소 하나로 쓰는 웹 버전**
(정부 65곳 + 한국장학재단 + 전국 대학·전문대 356곳, Vercel 무료 배포)까지 — 런타임 의존성 0.

> 📱 **휴대폰으로 바로 쓰려면** → [휴대폰에서 쓰기 — 웹 버전](#휴대폰에서-쓰기--웹-버전)

[![CI](https://github.com/corey1-cmd/open_site_clipper/actions/workflows/ci.yml/badge.svg)](https://github.com/corey1-cmd/open_site_clipper/actions/workflows/ci.yml)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![deps](https://img.shields.io/badge/runtime%20deps-0-brightgreen)
![license](https://img.shields.io/badge/license-MIT-green)

---

## 왜 만들었나

정부·지자체 공지는 부처마다 흩어진 RSS·공공데이터포털에 조각나 있고, 각
자료의 **재이용 조건(공공누리 유형)** 은 화면 어딘가에 작게 표기돼 실무에서
놓치기 쉽습니다. `open_site_clipper`는 이 둘을 한 번에 해결합니다.

- **한곳에 모아** — 여러 기관의 공지를 한 번의 명령으로 수집·중복 제거·정렬
- **하나의 보고서로** — 기관별로 묶어 읽기 좋은 문서(HTML/MD/JSON)로 출력
- **라이선스를 명시** — 공지마다 공공누리 등급 배지 + 보고서 하단에 재이용
  조건 범례. "무단 전재"가 아니라 **조건부 개방 자료**임을 문서가 스스로 증명

## 특징

- 📱 **휴대폰 웹 버전** — 기관·학교를 골라 [모으기], 진행 상황·남은 시간·날짜별 목록·공유 링크·보고서 저장. Vercel(서울 리전)에 Import 한 번으로 배포
- 🏫 **전국 학교 356곳** — 4년제·교대·과기원·사관학교·사이버대·전문대(2026-10 통합·폐교 반영). 게시판을 전부 모으고, '공지사항'에 올라온 글도 제목(장학·학자금·수강·졸업·채용…)으로 학사·장학·입학 갈래에 다시 나눔
- 🔌 **런타임 의존성 0** — 파이썬 표준 라이브러리만. `pip install` 후 바로 실행
- 📴 **오프라인 동작** — 모델·외부 API 없음. 저장한 피드로 재현 가능(`--input`)
- 🧾 **공공누리(KOGL) 인식** — 제7조·1~4유형 등급을 배지·범례로 표기
- 🛡 **견고한 파싱** — RSS 2.0 / Atom / data.go.kr(표준·odcloud) + XML 폭탄 차단
- 🔔 **변경 감지** — `--state`로 이전 실행에 없던 공지만 🆕 표기, `--only-new` 필터
- 📊 **기간 요약** — LLM 없이 규칙(빈도)만으로 기관·분류·키워드 다이제스트
- 📐 **사용자 템플릿** — `$title` `$body_md` 마커 치환으로 조직 서식 그대로 출력
- 🎯 **정체성 기반 선별** — 출처의 주제 태그와 테마 정의로 *관련 있는 자료만* 골라냄(근거 키워드 표기)
- 🗂 **테마 브리프** — 관련 자료를 섹션·사안 단위로 묶은 브리핑 (`--theme`)
- 📈 **해석** — 발행 추이·기관 활동·주요 사안·타임라인을 표와 SVG 그래프로 (LLM 없이 계산)
- 📎 **관련 자료 링크** — 본문 속 첨부(PDF·HWP)만 캐옴, 본문 복제 없음 (`--deep-links`)
- 🔎 **목적 검색** — `--query 고용` 한 줄로 관련 공지만(동의어 자동 확장, 파일 불필요)
- 🖱 **로컬 웹 UI** — `--serve` 한 번이면 브라우저에서 조직을 골라 클릭으로 수집·검색 (127.0.0.1 전용)
- 🔎 **출처 자동 탐지** — 홈페이지 주소 하나로 RSS·K2Web 좌표 초안 생성, 근거·검증 표시 (`--discover`)
- 🏛 **기관 단위 통합** — 본부·처·팀·대학원이 사이트를 따로 써도 한 기관으로 묶어 부서까지 표시 (`--group-by org`)
- ⚡ **병렬 수집** — 기관은 동시에, 한 서버에는 천천히(robots 의 Crawl-delay 우선) (`--jobs` `--delay`)
- 🔬 **구조 테스트** — 메뉴 이름이 아니라 '날짜 붙은 목록인가'로 수집 대상을 판정
- 🏢 **정부 65곳 프리셋** — 홈 주소만으로 공지·인사·보도자료·채용·입찰 경로를 실행 시 자동 발견
- 🧾 **항목별 출처 표시** — 각 공지 아래에 어느 경로로 가져왔는지 작은 상자로 표기
- 🩺 **접근 진단** — 수집 전에 어디가 전면 차단이고 어디가 경로별 차단인지 표로 확인 (`--check-access`)
- 🔀 **정부 캐스케이드** — 메뉴 종류마다 5개 경로를 돌려가며 시도, 막히면 다음으로 (`kind: "govorg"`)
- 🏛 **정부 부처 통합** — 공지·인사·보도자료는 RSS 로, RSS 가 없는 채용·입찰은 게시판 목록으로 (`kind: "govweb"`)
- 🪜 **단계적 폴백** — RSS → 목록 → JSON API → 메뉴 순으로 시도, 앞이 막혀도 멈추지 않고 시도 이력을 남김
- 🤖 **robots.txt 준수** — 표준 robotparser로 우리 UA 기준 판정(무시 옵션 없음)
- 🩹 **fail-open** — 한 출처가 죽어도(해외 IP 차단·URL 변경) 나머지로 보고서 완성,
  실패 출처는 표지에 투명 표기
- 🎨 **자체 완결형 HTML** — 인라인 CSS·다크모드 대응, 그대로 열람·인쇄·공유

## 설치

**필요한 것**: Python 3.10 이상 (없으면 [python.org](https://www.python.org/downloads/)에서 설치 —
Windows 는 설치 중 **"Add Python to PATH"** 를 반드시 체크).

### 1) 내려받기

- **git 있으면**:
  ```bash
  git clone https://github.com/corey1-cmd/open_site_clipper.git
  cd open_site_clipper
  ```
- **git 없으면**: GitHub 저장소에서 초록색 **Code → Download ZIP** → 압축 해제 →
  그 폴더로 이동. `dir`(Windows) / `ls`(Mac) 했을 때 **`pyproject.toml`·`src`·`examples`**
  가 보이는 위치가 맞습니다. 한 겹 더 안쪽 폴더에 있으면 `cd` 로 더 들어가세요.

### 2) 설치 (세 줄, 한 줄씩)

**Windows (명령 프롬프트)**
```bat
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

**Mac / Linux (터미널)**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

가운데 줄이 성공하면 프롬프트 앞에 `(.venv)` 가 붙습니다. 이후 새 터미널을 열 때마다
그 activate 줄만 다시 실행하면 됩니다.

### 3) 확인

```bash
open_site_clipper --version      # open_site_clipper 0.26.0
python -m pytest -q              # 326 passed (인터넷 불필요)
```

### 4) 바로 써보기

```bash
open_site_clipper --serve        # 브라우저가 http://127.0.0.1:8765 로 자동으로 열립니다
```
명령줄이 편하면 아래 [빠른 시작](#빠른-시작)의 예시를 쓰세요. `--serve` 사용법은
[로컬 웹 UI](#로컬-웹-ui---serve) 참고.

## 휴대폰에서 쓰기 — 웹 버전

같은 수집기를 휴대폰 브라우저에서 씁니다. Vercel(무료)에 한 번 올리면 **주소 하나**를
나눠 주는 것으로 끝납니다 — 받는 사람은 아무것도 설치하지 않습니다.

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https%3A%2F%2Fgithub.com%2Fcorey1-cmd%2Fopen_site_clipper&project-name=open-site-clipper&repository-name=open-site-clipper)

화면에서 하는 일:

- **고르기** — 정부 기관 65곳 + 공공기관(한국장학재단) · 학교 356곳(유형·지역 거르기, 이름 검색). 실측에서 글을 읽어 온 곳엔 '확인됨' 표시. 고른 목록은 기기에 기억됩니다
- **모으기** — 서버(서울 리전)가 기관을 한 곳씩 수집하고, 화면은 동시에 4곳씩 묻습니다.
  끝낸 곳 / 지금 묻는 곳 / 남은 시간이 실시간으로 보입니다
- **읽기** — 날짜별 목록. 갈래(학사·장학·입학·채용·공지·보도자료…)·새 글·기관으로 거르고
  제목으로 찾습니다. 못 가져온 곳은 사유를 사람 말로(robots.txt 차단·접속 거부·시간 초과 …)
- **나누기** — [링크 공유]는 고른 기관이 주소에 담겨, 받은 사람이 같은 목록을 바로 모읍니다.
  [보고서 저장]은 HTML 한 장. [홈 화면에 추가]하면 앱처럼 열립니다

### 배포 (처음 한 번, 5분)

1. 이 저장소가 본인 GitHub 에 있어야 합니다(위 **Deploy** 단추는 복제까지 해 줍니다).
2. [vercel.com/new](https://vercel.com/new) → 저장소 **Import** → **Deploy**. 설정은 고칠 것이
   없습니다 — `vercel.json` 이 서울 리전(icn1)·함수 300초·정적 화면 폴더를 정합니다.
3. 나온 주소(`https://<프로젝트>.vercel.app`)를 휴대폰에서 열고 공유 메뉴 → **홈 화면에 추가**.

이후에는 GitHub 에 올릴 때마다 자동으로 다시 배포됩니다.

### 실측 점검과 경로 캐시 (선택 — 수집이 수 초로 빨라짐)

처음에는 기관마다 홈에서 게시판을 찾느라 수십 초가 걸립니다. 배포한 서버로 전 기관을
한 번 점검해 **공지가 실제로 나온 게시판 주소**를 저장해 두면, 다음부터는 그 주소만 엽니다.

```bash
python scripts/bake_routes.py https://<프로젝트>.vercel.app   # 국내망 불필요(점검은 서버가 함)
git add src/open_site_clipper/data/route-cache.json docs/ && git commit -m "경로 캐시" && git push
```

`docs/실측-점검-날짜.md` 에 묶음별 성공 수와 못 모은 곳의 사유가 남습니다. 게시판 주소가
바뀌어 캐시가 0건을 내면 서버가 그 자리에서 다시 찾습니다(느려질 뿐 틀리지 않음).

**현재 저장된 캐시(2026-10-10 실측, 서울 리전·기관당 60초·최근 30일)** —
[docs/실측-점검-2026-10-10.md](docs/실측-점검-2026-10-10.md)

| 묶음 | 점검 | 글 있음 | 연결(기간 내 새 글 없음) | 못 모음 | 30일 글 |
|---|---:|---:|---:|---:|---:|
| 정부·공공 | 66 | 49 | 2 | 15 | 1,549 |
| 학교 | 356 | 149 | 16 | 191 | 3,677 |

갈래별로는 장학 426건(73곳 — 학교 72 + 한국장학재단) · 학사 321건 · 입학 226건 · 채용 828건 …
(보고서의 '갈래별' 표). 한국외대는 확인된 게시판 번호를 프리셋으로 넣어 두었다
(공지·학사·장학·채용·학술 + 학생지원팀 장학·학생활동 — `examples/sources-schools.json`).

글의 갈래는 **게시판 이름이 먼저, 그다음 글 제목**으로 정합니다. '장학공지' 게시판의 글은
전부 장학이고, '공지사항'에 올라온 '○○재단 장학생 모집'도 제목으로 장학이 됩니다. 게시판
이름을 모를 때('READ'·'더보기')만 글 제목들을 보고 게시판 이름을 짓습니다(60% 이상이 한
갈래일 때) — 이름 있는 게시판까지 내용으로 바꿨더니 일반 공지가 '입학안내'·'장학'이 되는
오분류가 생겨서 그렇게 정했습니다.

못 모은 곳의 대부분은 홈·게시판이 자바스크립트로만 그려지거나(목록 HTML 없음),
robots.txt 로 수집을 막았거나(설계상 따름), 인증서가 잘못된 곳(검증을 끄지 않음)입니다.
점검은 기관당 60초였고 실제 화면은 기관당 240초까지 찾으므로, '시간 안에 다 보지 못함'
으로 남은 곳은 휴대폰에서 직접 모을 때 잡히기도 합니다.

### 배포 없이 내 컴퓨터에서

```bash
open_site_clipper --web          # http://127.0.0.1:8765 — 배포본과 같은 화면
open_site_clipper --web --lan    # 같은 와이파이의 휴대폰에서 http://<PC 주소>:8765
```

### 구조와 예절

```
public/                 화면(HTML·CSS·JS, 의존성 없음) + 홈 화면 아이콘
api/catalog.py          기관 목록          ┐ 전부 src/open_site_clipper/webapp.py 를 부른다
api/collect.py          기관 하나 수집     │ (로컬 --web 도 같은 함수)
api/verify.py           여러 기관 일괄 점검 ┘
examples/sources-gov.json · sources-schools.json   기관·학교 목록(홈 주소만)
```

- 같은 기관 결과는 **30분 동안 CDN 이 대신 답합니다** — 여러 사람이 써도 사이트에 가는 요청은 늘지 않습니다
- 서버는 CLI 와 똑같이 robots.txt·Crawl-delay 를 따르고, 제목·날짜·링크만 담습니다
- 학교·기관을 더하려면 `examples/sources-*.json` 에 이름과 홈 주소 한 줄이면 됩니다

## 빠른 시작

```bash
# 네트워크 없이 번들 샘플로 동작 확인 (HTML 보고서)
open_site_clipper --demo -o demo.html

# 실시간 수집 → 마크다운 파일
open_site_clipper --format markdown -o report.md

# 최근 7일 · 특정 기관만
open_site_clipper --since 7 --agency 행정안전부 -o mois.html

# 설정된 출처 확인
open_site_clipper --list-sources

# 이전 실행 대비 신규 공지만 (첫 실행은 기준선 저장)
open_site_clipper --state state.json --only-new -o new.html

# 사내 회람 서식으로 출력
open_site_clipper --template examples/circular-template.tmpl -o circular.md

# 테마 브리프 — 관련 자료만 골라 섹션·해석까지
open_site_clipper --theme examples/theme-data-digital.json -o brief.html

# 한국외대 전 사이트를 한 기관으로 — 기관→사이트→부서 보고서
open_site_clipper --sources examples/sources-hufs.json --group-by org -o hufs.html

# 목적으로 검색 — '고용' 한 마디가 채용·모집·공채·인턴으로 확장
open_site_clipper --sources examples/sources-hufs.json --query 고용 -o 고용.html
```

### 예시 출력 (`--demo --format markdown`)

```markdown
# 정부·공공기관 공지 보고서

- 생성 시각: 2025-07-07T09:00:00+09:00
- 공지 5건 · 기관 2곳

## 기간 요약

- 기관: 행정안전부 3건 · 과학기술정보통신부 2건
- 분류: 보도자료 5건

## 행정안전부 (3건)

| 발행일 | 제목 | 등급 |
|---|---|---|
| 2025-07-07 | [재난안전데이터 공유 플랫폼 정식 개통](https://www.mois.go.kr/notice/1001) | KOGL-1 |
| 2025-07-04 | [여름철 집중호우 대비 국민행동요령 안내](https://www.mois.go.kr/notice/1002) | KOGL-1 |
...

### 출처 및 재이용 조건
- **KOGL-1** — 공공누리 제1유형 — 출처표시(상업적 이용·변형 허용)
```

실제 렌더링 결과는 [`examples/`](examples/) 폴더를 참고하세요 — 공지 보고서 `demo-report.html` · `.md` · `.json`, 테마 브리프 `demo-brief.html` · `.md`.

## 실전 검증

단위 테스트 265개(전부 오프라인, 페처 주입)에 더해 **실제 사이트에서 끝까지**
확인했습니다.

- **한국외국어대학교 실수집** — K2Web 사이트 프리셋으로 한 번에 **공지 88건**,
  기관→사이트→부서 3단 보고서. 목록의 작성자 칸에서 행정지원처·전략기획팀·
  장학팀 같은 실제 부서명이 그대로 추출됩니다.
- **폴백 실동작** — hufs.ac.kr 의 robots.txt 는 `/bbs/*` 를 차단합니다. RSS·목록이
  막히자 캐스케이드가 다음 수단으로 넘어가 수집했고, 그 이력이 보고서에 그대로
  남습니다(조용한 실패 금지):

  ```
  rss: robots.txt 차단 → list: robots.txt 차단 → page: 60건
  ```

- **타 대학 호환** — 한국방송통신대학교 게시판이 같은 CMS(K2Web Wizard)·같은 칸
  구조임을 확인. 좌표만 바꾸면 코드 수정 없이 동작하며, 고려대·전북대 등도 같은
  CMS 를 씁니다.
- **정부기관 65곳 실수집** — 부·청·위원회를 한 번에 돌려 **공지 3,600여 건 ·
  기관 37곳**을 모았습니다. 분류는 보도자료·공지·채용·입찰·소식·인사·업무추진비
  등으로 갈립니다. 실패한 기관은 사유가 남습니다:

  ```
  ⚠ 외교부 보도자료 (korea: 주소 없음(404))
  ⚠ 해양수산부: 진단: 응답 0KB · <a> 0개 · 내부 0 · 후보 0개
  ```

  수집을 거듭하며 드러난 실제 문제들 — 한글 날짜 표기(`2026년 7월 20일`)를
  못 읽던 것, 첨부 칸이 제목 자리를 빼앗던 것, 후보 40개 상한에 소개 메뉴만
  차던 것 — 을 하나씩 고쳐 왔습니다. 지금도 홈이 빈 응답인 기관 19곳은 원인을
  좁히는 중이며, 진단 숫자가 보고서에 그대로 남습니다.

## 사용법

```
open_site_clipper [옵션]

  -f, --format {md,markdown,html,json}   보고서 형식 (기본: html)
  -o, --output FILE                      출력 파일 (기본: 표준 출력)
      --since DAYS                       최근 N일 이내 공지만
      --agency NAME                      기관명 부분일치 필터
      --sources FILE                     사용자 정의 출처 JSON
      --input DIR                        오프라인 모드(저장한 피드 디렉터리)
      --demo                             번들 샘플로 오프라인 보고서
      --state FILE                       실행 간 상태(JSON) — 신규 공지 🆕 표기·저장
      --only-new                         신규 공지만(--state 필수)
      --digest / --no-digest             기간 요약(기관·분류·키워드) 포함 여부 (기본: 포함)
      --template FILE                    사용자 템플릿 출력(지정 시 --format 무시)
      --query TERMS                      목적·키워드 즉석 검색(동의어 확장, --theme 배타)
      --theme FILE                       테마 브리프 — 관련 자료만 선별·섹션화·해석
      --min-score N                      테마 관련성 채택 하한 (기본 3)
      --group-by agency|topic|org        섹션 축 — org 는 기관→사이트→부서 (기본 agency)
      --quote-mode conservative|full     발췌 정책 — full 은 등급 미상(대학 공지)도 발췌 유지
      --deep-links                       본문에서 첨부·관련 자료 링크 수집
      --deep-links-limit N               본문을 열어볼 공지 수 상한 (기본 20)
      --list-sources                     설정된 출처 출력
      --title TEXT                       보고서 제목 재정의
      --discover URL                     홈페이지 주소로 출처 초안 자동 탐지
      --discover-org URL                 조직 산하 여러 사이트까지 훑어 초안 생성
      --max-sites N                      --discover-org 가 훑을 사이트 수 (기본 6)
      --check-access FILE                수집 전 접근 진단(robots 판정만, 수집 안 함)
      --jobs N                           동시에 처리할 기관 수 (기본 16)
      --delay SEC                        같은 서버 요청 간격 (기본 1.0, robots 우선)
      --serve                            로컬 웹 UI 시작(브라우저 자동 오픈)
      --port N                           --serve 포트 (기본 8765)
```

### data.go.kr 인증키

공공데이터포털(`kind: "datago"`) 출처는 [data.go.kr](https://www.data.go.kr)에서
발급받은 인증키가 필요합니다. 키는 저장소·출처 파일에 적지 말고 환경변수로만
넘기세요.

```bash
export OSC_DATAGO_KEY="발급받은-serviceKey"      # 인코딩/디코딩 키 모두 가능
open_site_clipper --sources my.json -o report.html
```

URL에 `serviceKey`를 직접 쓴 경우 그 값을 존중하며, 형식 파라미터(`type` 등)가
없으면 `type=json`을 붙입니다(파서는 JSON만 읽음). 키가 없으면 해당 출처는
네트워크를 두드리지 않고 보고서 표지에 **"인증키 미설정"** 으로 구분 표기됩니다.

### 실행 간 변경 감지 (`--state`)

`--state FILE`을 주면 이전 실행에서 본 공지 목록(JSON)을 기억해, 이번에 처음
등장한 공지를 🆕(MD)·NEW 배지(HTML)·`"new": true`(JSON)로 표기하고 실행 후
상태를 갱신합니다. 파일이 없으면 **첫 실행(기준선)** 으로 간주해 아무것도 신규
표기하지 않습니다 — 첫 보고서 전체가 🆕로 도배되는 오탐을 막습니다.
`--only-new`는 신규 공지만으로 보고서를 만듭니다(크론 알림용).

### 기간 요약 (`--digest`)

보고서 상단에 기관별 건수·분류 분포·제목 키워드 상위를 붙입니다. 모델·외부
API 없이 순수 빈도 집계라 같은 입력이면 항상 같은 요약이 나옵니다(재현 가능).
상투어(안내·공고 등)·숫자·회차·기관명은 키워드에서 제외합니다. 끄려면
`--no-digest`.

### 목적·키워드 즉석 검색 (`--query`)

테마 파일 없이 **목적어 한 마디**로 검색합니다. 목적 사전에 있는 말은 동의어로
자동 확장되고, 없는 말(예: `AI`, `반도체`)은 그 말 자체가 키워드가 됩니다.
여러 개를 나열하면 각각이 브리프의 [섹션]이 됩니다.

```bash
open_site_clipper --sources knou.json --query 고용 -o 고용.html
open_site_clipper --sources knou.json --query "고용 장학" --state s.json --only-new
```

| 목적어 | 자동 확장되는 동의어 |
|---|---|
| `고용` | 채용 · 모집 · 공채 · 임용 · 인턴 · 일자리 · 취업 · 구인 · 신입 · 경력 |
| `복지` | 장학 · 지원금 · 학자금 · 생활비 · 기숙사 · 상담 · 의료 · 건강 · 보험 · 돌봄 |
| `안전` | 재난 · 화재 · 지진 · 호우 · 안전점검 · 행동요령 · 대피 |
| `입찰` | 공고 · 낙찰 · 계약 · 조달 · 발주 · 제안요청 · RFP |
| `장학` | 장학금 · 학자금 · 등록금 · 면제 · 감면 · 국가장학 |
| `정부투자` | 공모 · 지원사업 · 국고 · 연구비 · R&D · 과제 · 예산 · 출연 · 보조금 · 투자 |
| `학사` | 수강 · 성적 · 졸업 · 등록 · 휴학 · 복학 · 계절학기 · 시험 · 학점 |
| `행사` | 세미나 · 특강 · 설명회 · 박람회 · 포럼 · 축제 · 경진대회 · 공모전 · 워크숍 |

확장 근거는 항목마다 **근거 키워드**로 표기되어 왜 뽑혔는지 검증할 수 있습니다.
동의어 사전은 규칙 기반(무LLM)이며 `purposes.py`에서 수정·추가할 수 있습니다.

> **한국어 처리에 관하여** — 형태소 분석기 pynori(KoreanTokenizer)를 코드
> 수준에서 분석했습니다. 격자 탐색·TRIE 최장일치의 품질 원천은 93MB
> mecab-ko-dic 사전이었고, 스타순 상위 대안(soynlp·Kiwi·KoNLPy)도 대사전·
> 말뭉치·네이티브 코드를 요구합니다. 의존성 0 원칙에 따라 **원리만 증류**해,
> 닫힌 품사(다문자 조사·어미) 최장일치 정규화기(`korean.py`)로 축소
> 구현했습니다 — "지원하는/지원하며"가 집계에서 "지원"으로 합쳐집니다.
> 관련성 매칭 자체는 부분 문자열이라 "채용을·모집합니다"도 원래 잡힙니다.

### 로컬 웹 UI (`--serve`)

cmd 가 불편하면 브라우저로 씁니다.

```bash
open_site_clipper --serve        # http://127.0.0.1:8765 자동 오픈, 종료는 Ctrl+C
```

수집이 도는 동안에는 **진행 화면**이 뜹니다 — 왼쪽에 진행 막대·몇 곳 중 몇 곳·
모은 공지 수·걸린 시간·남은 예상, 오른쪽에 **지금 어느 기관의 어느 주소를
두드리는지**가 실시간으로 보입니다(병렬이라 여러 줄이 동시에 뜹니다). 끝나면
보고서로 자동으로 넘어갑니다.

화면에서 ① **조사할 조직 선택** — 정부·공공기관 / 대학 / 기타 그룹으로 묶여
접이식으로 나오고, 그룹마다 [모두 선택] [모두 해제] 가 있습니다. **체크한
기관만** 조사합니다. 같은 기관이 여러 파일에 흩어져 있어도 한 줄로 합쳐집니다 →
② 옵션(기관→사이트→부서 묶기 · 발췌 유지 · 신규 🆕 · 최근 N일) → ③ 검색어
(넣으면 목적 브리프, 비우면 전체 보고서) → [보고서 만들기]. ④ 조직 추가에
대학 주소를 넣으면 `--discover` 가 돌아 초안을 저장하고 곧바로 ①의 목록에
나타나며, [이 조직으로 바로 보고서] 원클릭도 됩니다.

CLI와 같은 계층을 부르는 얇은 껍데기라 **의존성은 그대로 0**(표준
`http.server`)이고, 127.0.0.1에만 바인딩되어 이 컴퓨터에서만 접속됩니다 —
개인용 로컬 도구이며 인터넷 배포용이 아닙니다. 수집은 실제 요청이라 수십 초
걸릴 수 있습니다.

### 기관 단위 통합 수집 — K2Web 캐스케이드 (`kind: "k2web"`)

한국외국어대학교처럼 본부·처·팀·대학원·연구소가 홈페이지를 따로 운영해도,
같은 CMS(K2Web Wizard)를 쓰므로 **좌표만 주면** 한 기관으로 묶어 수집합니다.
좌표는 URL 세 조각입니다: `host`(도메인), `site_id`(경로의 사이트 코드),
`board_id`(게시판 번호 — 게시판 목록 주소 `/bbs/{site_id}/{board_id}/artclList.do`에서 확인).

```json
{
  "org": "한국외국어대학교", "site": "대학본부",
  "name": "한국외국어대학교 대학본부", "kind": "k2web",
  "host": "www.hufs.ac.kr", "site_id": "hufs",
  "board_id": 2180, "menu_no": 11281, "category": "공지"
}
```

수집은 **네 수단을 순서대로** 시도하고, 앞이 막혀도 멈추지 않습니다.

| 순위 | 수단 | 주소 | 특징 |
|---|---|---|---|
| 1 | `rss` | `/bbs/{site}/{board}/rssList.do?row=50` | 구조화·발췌 포함 |
| 2 | `list` | `/bbs/{site}/{board}/artclList.do` | 목록 표 — **작성 부서를 줌** |
| 3 | `api` | 출처에 설정한 JSON API (선택) | 응답 골격을 경로로 지정 |
| 4 | `page` | `/{site_id}/{menu_no}/subview.do` | `/bbs/`가 막혀도 사는 경로 |

다음 수단으로 넘어가는 조건은 셋입니다 — **robots.txt 차단 · 응답 없음 · 파싱 0건**.
robots 판정은 표준 `urllib.robotparser`로 실행 시점에 우리 User-Agent 기준으로
묻고(무시 옵션은 없음), 전부 실패하면 보고서 표지에 시도 이력이 그대로 남습니다:

```
⚠ 수집 실패 출처: 대학본부 (rss: robots.txt 차단 → list: 응답 없음 → api: 글 0건 → page: 응답 없음)
```

3순위 JSON API는 사이트가 게시판 JSON을 줄 때만 설정합니다. 코드가 아니라
**점 표기 경로**로 응답 골격을 가리킵니다:

```json
"api_url": "https://www.hufs.ac.kr/…/board.do?bbsId=2180",
"api_paths": {
  "items": "data.list", "title": "artclNm",
  "url": "artclUrl", "article_no": "artclNo",
  "date": "regDt", "unit": "deptNm"
}
```

`url`이 없으면 `article_no`(글번호)로 정식 글 주소를 조립합니다. 대학·교내
공지처럼 공공누리 표기 관행이 없는 곳은 등급이 전부 '미상'이라 기본 인용
정책이 발췌를 비우므로, `--quote-mode full`을 함께 쓰면 발췌가 유지됩니다.
결과 보고서는
`--group-by org`로 **기관 → 사이트 → 부서** 3단으로 봅니다. 실측 좌표가 담긴
프리셋은 [`examples/sources-hufs.json`](examples/sources-hufs.json).

### 출처 자동 탐지 (`--discover`)

새 대학·기관을 추가할 때 좌표를 손으로 캐는 대신, **홈페이지 주소 하나**를 줍니다.

```bash
open_site_clipper --discover https://www.knou.ac.kr/knou/index.do -o knou.json
# 탐지 완료: 후보 4건(검증 4건) · 요청 5회 · 기관명 추정 '한국방송통신대학교'
```

무엇을 찾는지 — ① 표준 RSS 자동발견(`<link rel="alternate">`), ② K2Web 좌표
(페이지에 노출된 `artclList/rssList` 링크 + '공지·소식'류 메뉴를 예산 내에서 **한
단계만** 따라가 게시판 번호를 캐냄), ③ 둘 다 없으면 관용 경로(`/rss`, `/feed` 등)
추측. 후보마다 실제로 받아 RSS 여부를 스니핑해 `_verified`로 표시하고, 어디서
찾았는지 `_evidence`에 남깁니다.

결과는 **초안**입니다 — 그대로 `--sources`로 읽히지만, `org·name`을 다듬고
`_verified: false` 항목은 직접 확인하는 것을 전제합니다. robots.txt를 지키고 총
요청 수에 예산(기본 12회)을 두며, JS로만 그리는 메뉴나 비지원 CMS는 못 찾을 수
있습니다(그 경우 게시판 페이지 주소를 직접 `--discover`에 주면 됩니다).

**피드 목록 페이지도 읽습니다.** 정부 사이트는 "RSS 서비스"·"정보구독서비스"
페이지에 피드 주소를 표로 모아 둡니다. 그 주소를 주면 표를 읽어 항목마다 출처를
만듭니다 — 기관·메뉴 이름은 앵커 텍스트("RSS복사")가 아니라 같은 행의 첫 칸에서
가져옵니다.

```bash
# 정부 전체 부처 피드 목록 한 장에서
open_site_clipper --discover https://www.korea.kr/etc/rss.do -o gov.json

# 개별 부처의 공지·인사·보도자료 피드
open_site_clipper --discover https://www.mcst.go.kr/site/s_etc/rss/rssService.jsp -o mcst.json
```

부처 링크는 개편으로 바뀌지만 이 목록 페이지는 정부가 갱신하므로, 주소를 코드에
박아 두지 않아도 그 시점의 목록을 그대로 얻습니다. 부처가 RSS 로 내주지 않는
메뉴(예: 일부 부처의 채용·입찰)는 이 방법으로도 나오지 않습니다.

> 설계 출처: autoscraper('예시 하나→재사용 규칙' — K2Web에선 URL 문법이 곧 규칙),
> feed_seeker(탐지 3원·제한 따라가기), feedfinder(후보·검증 분리). 셋 다
> requests·bs4 의존이라 원리만 표준 라이브러리로 이식했습니다.

### 무엇을 가져오고 무엇을 건너뛰는가

메뉴 **이름으로는 판정할 수 없습니다.** 같은 `정보공개` 가 어떤 기관에선 날짜
붙은 목록이고 어떤 기관에선 설명문 한 장입니다. 그래서 페이지를 열어 **모양**을
봅니다.

| 판정 | 예시 | 처리 |
|---|---|---|
| **목록** (날짜 붙은 글 2건 이상) | 공지사항·인사알림·채용·입찰·보도설명 | ✅ 수집 |
| **안내 페이지** (글 0~1건) | 일반현황·교육지원한눈에 | 건너뜀 |
| **링크 모음** (날짜 없음) | 정책 대분류 메뉴 | 건너뜀 |
| **기관 밖 도메인** | 법령정보(law.go.kr)·공공데이터·국민신문고 | 별도 출처로 등록 |

게시판을 못 찾으면 그 이유를 **숫자로** 남깁니다 — `응답 248KB · <a> 0개
(주소없음 0·data속성 0) · 내부 0·외부제외 0 · 후보 0개`. 메뉴가 JavaScript 로만
그려지는지, 파서가 막혔는지, 주소가 `data-*` 에 숨어 있는지가 한 줄로 드러납니다.
홈을 못 읽어도 거기서 멈추지 않습니다 — **알려진 경로 패턴**(CMS 패밀리 8종)을
사이클로 시도해 게시판을 찾습니다. 첫 경로가 통한 패밀리만 깊게 파므로 요청이
적게 듭니다. 새 패턴은 `data/gov-paths.json` 에만 추가하면 되고 코드는 그대로입니다.
그런 사이트는 **robots.txt 의 `Sitemap:`** 을 읽어(추가 요청 없이) 사이트맵에서
목록 주소를 찾아 우회합니다.

건너뛴 것은 사유와 함께 보고서에 남습니다. 실패는 뭉뚱그리지 않고 원인을
구분합니다 — `접근 거부(403)` · `주소 없음(404)` · `시간 초과(15초)` · `요청 과다(429)`.
일시적으로 보이는 실패는 한 번 재시도합니다.

수집된 항목마다 **어디서 가져왔는지**가 제목 아래 작은 상자로 붙습니다
(`www.korea.kr · korea.kr 피드 · /rss/dept_mcst.xml`,
`www.mcst.go.kr · 게시판 · /kor/s_notice/notice/noticeList.jsp`) — 어느 게시판인지까지. 같은 기관이라도
항목마다 경로가 다를 수 있어, 출처를 눈으로 확인할 수 있게 남깁니다. 기본으로 **최근 2년**(`--since 730`)
자료만 가져오며, 발행일을 알 수 없는 항목은 버리지 않고 포함합니다. 이 규칙
하나로 업무계획 같은 문서 저장소가 정리됩니다 — 최근 것만 남습니다.

### 병렬 수집과 예의 (`--jobs` `--delay`)

```bash
open_site_clipper --sources examples/sources-gov.json --jobs 16 --delay 1.0 -o gov.html
```

기관은 **동시에**, 한 서버에는 **천천히** 보냅니다. 기관마다 서버가 다르므로
동시에 보내도 어느 한 서버에 몰리지 않고, 같은 서버로 가는 요청 사이에는 최소
간격을 지킵니다. 그 간격은 **사이트가 정합니다**:

```
robots.txt 에 Crawl-delay: 5 가 있으면  →  5초를 지킴
없으면                                →  --delay 값(기본 1.0초)
```

숫자를 우리가 정하기 전에 상대에게 먼저 묻는 방식입니다. 65곳 순차 수집이
16분 걸리던 것이 병렬로는 몇 분 안쪽으로 줄어듭니다(`--jobs 1` 이면 순차).

### 정부기관 65곳 한 번에

`examples/sources-gov.json` 에 부(29)·청(18)·위원회(7)·대통령 소속 위원회(11)
**65곳**이 들어 있습니다. 담긴 것은 **홈 주소와 korea.kr 피드 코드뿐**이고,
게시판 경로는 **실행할 때 찾습니다**.

```bash
open_site_clipper --check-access examples/sources-gov.json     # 먼저 진단
open_site_clipper --sources examples/sources-gov.json --agency 문화체육 -o mcst.html
```

기관마다 홈페이지를 한 장 읽어 앵커 텍스트로 카테고리를 판정합니다 —
`채용정보`→채용, `입찰공고`→입찰, `알립니다`→공지, `인사발령`→인사. 그리고
**같은 카테고리에 후보 주소를 여러 개** 모읍니다. 하나가 robots 로 막혀도
캐스케이드가 다음 후보로 넘어갑니다. `RSS 서비스` 링크가 있으면 한 단계
따라가 피드 목록 표까지 읽습니다.

CMS 를 가리지 않습니다. 정부 사이트는 CMS 가 최소 19종으로 갈리지만, 링크
문법이 아니라 **앵커 텍스트와 표 구조**에 기대므로 같은 코드가 돕니다.

> ⚠ 65곳을 한 번에 돌리면 요청이 수백 회입니다. `--check-access` 로 먼저
> 진단하고, `--agency` 나 웹 UI 로 필요한 기관만 고르세요.

파일에 `rights` 를 일부러 비워 두었습니다 — 정부 자료라고 전부 공공누리
1유형이 아닙니다(4유형 실측). 미상이면 제목·링크·날짜·부서는 수집되고 발췌만
비워집니다.

### 전국 학교 356곳

`examples/sources-schools.json` 에 4년제(187)·교육대(10)·과학기술원(4)·특수대(7)·
방송통신대(1)·사이버대(22)·전문대(123)·전공대학(2)이 **홈 주소만** 들어 있습니다.
정부 65곳과 같은 방식으로 실행 시 게시판을 찾고, 학교 게시판은
**입학·장학·학사** 갈래로 따로 분류됩니다(‘신입생 모집’이 채용으로 빠지지 않게).

```bash
open_site_clipper --sources examples/sources-schools.json --agency 한국외국어 -o hufs.html
```

목록은 2026-10 웹 검색으로 통합·폐교·교명 변경을 반영했습니다(강릉원주대→강원대,
원광보건대→원광대, 전남도립대→국립목포대, 거창·남해대→국립창원대 통합, 광양보건대 폐교,
KC대→강서대 등). 대학원대학은 아직 넣지 않았습니다. 웹 화면은 `type`·`region` 으로
유형·지역 거르기를 만듭니다.

### 접근 진단 (`--check-access`)

정부 사이트는 robots.txt 로 막힌 곳이 많은데, **막힌 방식이 두 가지**입니다.
수집을 돌리기 전에 어느 쪽인지 확인합니다.

```bash
open_site_clipper --check-access examples/sources-gov.json
```

```
기관                허용/전체  결론
교육부                1/7  ◐ 일부 허용 — 열린 경로로 수집
                  ✗ 공지/board: https://www.moe.go.kr/boardCnts/listRenew.do?…
문화체육관광부      16/16  ✓ 전 경로 허용
외교부                1/1  — 자체 경로 미설정 — 보도자료만
행정안전부            4/4  ✓ 전 경로 허용

요약: 기관 4곳 — 전 경로 허용 2 · 자체 경로 미설정 1 · 일부 허용 1
※ robots.txt 는 User-Agent 별로 규칙이 다릅니다. 위 판정은 이 도구 기준입니다.
```

- **전면 차단**(`Disallow: /`)이면 어떤 주소를 찾아도 소용없습니다 → korea.kr·
  data.go.kr 경로만 남습니다.
- **경로별 차단**이면 다른 진입 경로가 열려 있을 수 있습니다 → 캐스케이드의
  `alt` 단계가 값을 합니다.

두 번째 줄이 중요한 이유는, **남이 다른 도구로 잰 차단 목록이 우리에게 그대로
적용되지 않기** 때문입니다. robots.txt 는 User-Agent 별로 규칙이 갈리므로
이 도구의 UA 로 직접 물어야 합니다. 진단은 수집을 하지 않고 robots.txt 만
읽습니다(호스트당 1회, 캐시).

### 정부 캐스케이드 (`kind: "govorg"`)

정부는 부처마다 CMS가 달라(실측 19종) 대학처럼 좌표로 주소를 만들 수 없고,
robots.txt가 경로를 막는 곳도 많습니다. 그래서 **메뉴 종류(보도자료·공지·인사·
채용·입찰)마다** 아래 순서로 시도하고, 앞이 막히면 다음으로 넘어갑니다.

| 순위 | 단계 | robots | 얻는 것 |
|---|---|---|---|
| 1 | `rss` | 검사 | 기관 자체 피드 |
| 2 | `board` | 검사 | 기관 게시판 표 |
| 3 | `alt` | 검사 | **같은 목록의 다른 주소** |
| 4 | `datago` | 무관 | 공공데이터포털 API |
| 5 | `korea` | 무관 | korea.kr 부처 피드(보도자료 안전망) |

```json
{ "org": "문화체육관광부", "kind": "govorg", "korea_feed": "dept_mcst",
  "routes": [["공지", "rss", "https://www.mcst.go.kr/common/rss/notice.jsp"],
             ["채용", "board", "https://www.mcst.go.kr/site/s_notice/notice/jobList.jsp"]] }
```

**대학 캐스케이드와 결정적으로 다른 점**: 대학은 4단계가 *같은 글*로 가는 다른
길이라 첫 성공에서 멈췄지만, 정부는 단계마다 주는 것이 달라 **카테고리별로 따로**
폴백합니다. 보도자료가 korea.kr로 성공해도 채용 게시판은 따로 시도합니다.

`alt`는 **우회가 아닙니다.** robots가 막은 주소 대신 같은 내용을 담은 다른 주소
(모바일 도메인·www 유무·영문판 경로)를 만들어 **robots 판정을 다시 받는 것**이고,
거기서도 막히면 그대로 건너뜁니다. 어느 기관에서 통할지는 미지수라 되면 쓰고
안 되면 사유가 남습니다:

```
⚠ 외교부 공지 (board: robots.txt 차단 → alt: robots.txt 차단 → alt: robots.txt 차단)
   ※ 같은 기관의 보도자료는 korea.kr 경로로 수집됨
```

### 정부 부처 한 기관 통합 (`kind: "govweb"`)

부처는 **공지·인사·보도자료·언론설명**을 RSS 로 공개합니다(각 사이트의
"정보구독서비스" 페이지). 반면 **채용·입찰은 RSS 가 없는 경우가 많아**
목록 페이지를 직접 읽어야 합니다 — 그때 `kind: "govweb"` 을 씁니다.
좌표가 필요 없고 **목록 주소만** 적으면 됩니다.

```json
{ "org": "문화체육관광부", "name": "문화체육관광부", "kind": "govweb",
  "url": "https://www.mcst.go.kr/site/s_notice/notice/jobList.jsp",
  "category": "채용", "rights": "kogl_type1" }
```

```bash
# RSS 4종 + 채용·입찰 2종을 한 기관으로
open_site_clipper --sources examples/sources-mcst.json --group-by org -o mcst.html

# 목적으로 좁혀 보기
open_site_clipper --sources examples/sources-mcst.json --query 채용 -o 채용.html
```

파서는 **상세 링크 문법에 의존하지 않습니다.** 이 게시판들은 소속·공공기관
공고를 각 기관 누리집과 연동해 보여주기 때문에 링크가 제각각입니다. 대신 표의
칸 순서(번호→제목→게시일→마감일→조회)에 기대어, 행에서 실제 링크를 단 가장 긴
텍스트 칸을 제목으로, 그 뒤 첫 날짜를 게시일로 읽습니다. 제목 앞 `[기관명]`
접두는 부서로 뽑습니다.

한계: 목록이 표가 아니거나 JavaScript 로만 그려지는 게시판은 읽지 못합니다.
부처마다 RSS 제공 범위가 달라, 있는 것은 RSS 로 없는 것만 `govweb` 으로 채우는
방식이 안전합니다.

### 테마 브리프 (`--theme`)

수집한 공지 **전부**를 나열하는 대신, **테마에 관련된 자료만** 골라 섹션 브리핑을
만듭니다. 관련성 판정은 키워드 규칙(무LLM)이라 같은 입력이면 같은 결과가 나오고,
**채택 근거 키워드와 점수를 항목마다 표기**하므로 왜 이 자료가 실렸는지 검증할 수
있습니다.

```bash
open_site_clipper --theme examples/theme-data-digital.json -o brief.html
open_site_clipper --theme my-theme.json --min-score 5 --only-new --state s.json
```

테마 파일:

```json
{
  "name": "우주",
  "description": "발사체·위성 동향",
  "keywords": { "우주": ["space", "항공우주"] },
  "sections": [
    { "name": "발사체", "keywords": { "발사체": ["로켓"], "재사용": [] } },
    { "name": "위성", "keywords": { "위성": ["satellite", "군집위성"] } }
  ],
  "glossary": { "LEO": "지구 저궤도 — 고도 2,000km 이하" }
}
```

- `keywords`의 키가 **정준 키워드**, 값 배열이 동의어(영문 표기 포함).
- 점수: 제목 3점 · 분류 2점 · 요약 1점, 출처 주제 태그가 겹치면 +1. 기본 하한 3점
  (= 제목 1회 적중)이며 `--min-score`로 조절합니다.
- 같은 사안을 여러 기관이 낸 경우 **대표 1건 + "같은 사안 N건"** 으로 접습니다.
- `sections`가 브리프의 묶음·순서이고, 어디에도 안 맞으면 `기타`로 갑니다.
- `glossary`는 보고서 옆 **용어 각주**로 렌더됩니다.

### 해석 (표·그래프)

브리프에는 계산으로 얻은 해석이 함께 붙습니다 — 서술이 아니라 수치입니다.

- **주별 발행 추이** + 증감 정형 문장(예: 최근 4주 발행량은 이전 4주 대비 +40%…)
- **기관별 활동**(건수·최근 발행일), **주요 사안**(다기관 보도 묶음 크기)
- **최대 사안 타임라인**, `--state` 사용 시 **이번에 새로 등장한 키워드**

그래프는 표준 라이브러리만으로 조립한 **인라인 SVG**라 HTML 파일 하나로 자체
완결되며(외부 요청 0), 같은 입력이면 같은 그림이 나옵니다.

### 출처 정체성 (`topics`) 과 `--group-by`

출처마다 주로 다루는 주제를 태그로 달아 두면(`topics`), 관련성 판정의 가점과
주제별 섹션화에 쓰입니다.

```json
{ "name": "과학기술정보통신부", "kind": "rss", "url": "...", "topics": ["과학기술", "정보보호"] }
```

`--group-by topic`을 주면 기관 대신 **주제별**로 묶은 보고서가 나옵니다.

### 관련 자료 링크 (`--deep-links`)

공지 본문 페이지를 열어 **첨부·관련 자료 링크만** 캐옵니다(보도자료 PDF, 설명자료
HWP 등). **본문 텍스트는 가져오지 않습니다** — 원문 복제를 하지 않는다는 원칙과
등급별 보수적 인용 정책을 그대로 지키며, 변형이 금지된 등급(3·4유형·미상)은
링크 수집도 건너뜁니다. 공지마다 요청이 늘어 느려지므로 기본은 꺼짐이고
`--deep-links-limit`(기본 20건)로 상한을 둡니다.

### 사용자 템플릿 (`--template`)

조직 서식(회람·공문 틀)에 수집 결과만 끼워 넣고 싶을 때 씁니다. 표준
`string.Template` 문법으로, 템플릿 속 `$마커`가 치환됩니다(`$$`는 `$`로,
모르는 마커는 원문 유지). 예시는 [`examples/circular-template.tmpl`](examples/circular-template.tmpl).

| 마커 | 내용 |
|---|---|
| `$title` `$generated_at` | 제목 · 생성 시각 |
| `$count` `$agency_count` `$new_count` | 공지·기관·신규 건수 |
| `$agencies` `$failed_sources` `$since_days` | 기관 목록 · 실패 출처 · 조회 기간 |
| `$body_md` `$digest_md` `$legend_md` | 본문 표·기간 요약·범례 (Markdown) |
| `$body_html` `$digest_html` `$legend_html` | 위와 동일 (HTML 조각) |

### 사용자 정의 출처

`--sources my.json`으로 원하는 기관 피드를 넣을 수 있습니다.

```json
{
  "sources": [
    { "name": "서울특별시", "kind": "rss",
      "url": "https://example.seoul.go.kr/rss", "rights": "kogl_type1" },
    { "name": "공공데이터포털", "kind": "datago",
      "url": "https://apis.data.go.kr/....", "rights": "kogl_type1" }
  ]
}
```

`kind`는 `rss`(RSS/Atom) 또는 `datago`(data.go.kr OpenAPI, JSON), `rights`는
`public_domain` · `kogl_type1`~`kogl_type4` · `unknown` 중 하나입니다.

### 오프라인 재현

인터넷이 막힌 환경(대회 심사·에어갭)이나 결과를 고정하고 싶을 때, 피드를
`<source-id>.xml` 형태로 저장해 두고 `--input`으로 읽습니다.

```bash
open_site_clipper --input ./saved_feeds --format html -o report.html
```

## 공공누리(KOGL) 등급

| 배지 | 등급 | 재이용 조건 |
|---|---|---|
| `제7조` | 저작권법 제7조 | 고시·공고·법령 등 — 자유 이용 |
| `KOGL-1` | 공공누리 제1유형 | 출처표시(상업적 이용·변형 허용) |
| `KOGL-2` | 공공누리 제2유형 | 출처표시 + 비상업적 이용 |
| `KOGL-3` | 공공누리 제3유형 | 출처표시 + 변경 금지 |
| `KOGL-4` | 공공누리 제4유형 | 출처표시 + 비상업 + 변경 금지 |
| `미상` | 등급 미상 | 제목·링크·출처만 보수적으로 인용 |

## 아키텍처

작고 단일 책임인 모듈로 나뉘어 있어, 각 계층을 독립적으로 테스트·교체할 수 있습니다.

```
sources ──▶ fetch ──▶ parse ──▶ collect ──▶ report
 출처 등록    수집(HTTP/   RSS·JSON    중복제거·     Markdown/
 + KOGL등급   오프라인)    → Notice    필터·정렬     HTML/JSON
```

- `sources.py` — 출처 레지스트리(기본 + 사용자 JSON), 각 출처의 KOGL 등급
- `fetch.py` — 표준 urllib 수집(http/https만, fail-open) + 로컬 파일 읽기
- `parse.py` — RSS/Atom·data.go.kr 파싱, HTML 정리, 날짜 정규화, XML 폭탄 차단
- `collect.py` — 오케스트레이션(페처 주입 → 테스트·오프라인이 같은 경로)
- `state.py` — 실행 간 상태(신규 감지) — 순수 JSON, 첫 실행은 기준선
- `digest.py` — 규칙 기반 기간 요약(기관·분류·키워드) — LLM 없음
- `theme.py` — 테마 정의(정준 키워드→동의어·섹션·용어)
- `relevance.py` — 관련성 판정(가중치·근거 기록) — LLM 없음
- `cluster.py` — 유사 사안 묶음(자카드) — LLM 없음
- `insight.py` · `chart.py` — 해석 계산과 인라인 SVG 그래프
- `deeplink.py` — 본문 속 첨부·관련 자료 링크 추출(본문 복제 없음)
- `brief.py` · `brief_report.py` — 테마 브리프 조립·렌더
- `k2web.py` · `k2web_parse.py` · `jsonapi.py` — 기관 CMS 어댑터(4단 폴백)와 목록·JSON 파서
- `robots.py` — robots.txt 준수(호스트별 캐시, fail-open)
- `discover.py` — 출처 자동 탐지(RSS 자동발견·K2Web 좌표·검증 스니핑)
- `webui.py` — 로컬 웹 UI(조직 선택→수집·검색·탐지, 표준 http.server)
- `webapp.py` — 휴대폰 웹 버전의 서버 쪽(기관 목록·기관 하나 수집·경로 캐시·시간 제한·일괄 점검). Vercel 함수(`api/*.py`)와 `--web` 이 같이 쓴다
- `progress.py` — 수집 진행 상황 추적(스레드 안전, 남은 시간 어림)
- `categories.py` — 메뉴 이름·주소 → 대분류(발견과 요약이 공유하는 사전)
- `govweb.py` — 정부 표준홈페이지 게시판 파서(채용·입찰 등 RSS 미제공 목록)
- `cascade.py` · `govcascade.py` — 폴백 공통 뼈대(시도 이력)와 정부 카테고리별 5단 캐스케이드
- `access.py` — 접근 진단(전면/경로별 차단 구분, 우리 UA 기준)
- `govpaths.py` — 경로 패턴 사이클(홈을 못 읽는 기관용, 데이터 기반)
- `govdiscover.py` — 기관 홈에서 수집 경로 자동 발견(후보 수집 → 구조 테스트 선별)
- `probe.py` — 구조 테스트(목록·안내·링크모음·외부 판정)
- `parallel.py` — 병렬 실행기와 호스트별 간격(robots Crawl-delay 우선)
- `purposes.py` — 목적 동의어 사전(--query 즉석 테마)
- `korean.py` — 닫힌 접미(조사·어미) 최장일치 정규화 — pynori 분석의 증류판
- `report.py` — Markdown · 자체 완결형 HTML · JSON · 사용자 템플릿 렌더러
- `rights.py` — 공공누리 등급 상수·라벨·판정
- `model.py` — 도메인 모델(Notice·Report)과 그룹 축(by_agency/by_topic/by_org)
- `cli.py` — 명령줄 진입점(인자 검증·한글 콘솔 방어·친절한 오류)

## 개발

```bash
pip install -e ".[dev]"
pytest -q            # 테스트 265개 — 전부 네트워크 없이 동작(페처 주입)
ruff check src tests # 린트
ruff format src tests
```

CI(GitHub Actions)가 Python 3.10·3.11·3.12 매트릭스로 같은 검사를 돌립니다.

## 한계

- 게시판을 JavaScript 로만 그리는 사이트나 K2Web 이 아닌 CMS 는 `--discover` 가
  못 찾을 수 있습니다 — 그 경우 게시판 페이지 주소를 직접 지정하세요.
- 부처마다 RSS 제공 범위가 다릅니다(문체부는 채용·입찰이 RSS 에 없어 `govweb` 필요).
- 무LLM 원칙상 문단형 요약문은 생성하지 않습니다. 해석은 수치(추이·분포·유사
  묶음)와 정형 문장까지이고, 발췌는 원문 그대로만 씁니다.
- robots.txt 가 모든 경로를 막으면 수집하지 않습니다(우회 옵션을 두지 않음).
  실시간 모니터링이 아닌 실행형 배치 도구입니다.
- 로컬 웹 UI 는 127.0.0.1 전용 개인 도구입니다 — 다중 사용자·원격 접속·인증 없음.

## 라이선스

MIT © 2025 — [`LICENSE`](LICENSE) 참고.

수집 대상 자료의 저작권은 각 발행 기관에 있으며, 재이용 시 보고서에 표기된
공공누리 등급과 출처표시 조건을 따라야 합니다. `open_site_clipper`는 원문 본문을
복제하지 않고 제목·링크·발행일 등 메타데이터만 모읍니다.
