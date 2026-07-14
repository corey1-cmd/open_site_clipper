# open_site_clipper

**정부·공공기관 공지를 수집해 하나의 보고서로.**
공개 RSS/OpenAPI로 흩어진 정부·지자체 공지를 모아, 출처와 **공공누리(KOGL)
라이선스 등급**을 명시한 단일 보고서(Markdown · HTML · JSON)로 만듭니다.

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

- 🔌 **런타임 의존성 0** — 파이썬 표준 라이브러리만. `pip install` 후 바로 실행
- 📴 **오프라인 동작** — 모델·외부 API 없음. 저장한 피드로 재현 가능(`--input`)
- 🧾 **공공누리(KOGL) 인식** — 제7조·1~4유형 등급을 배지·범례로 표기
- 🛡 **견고한 파싱** — RSS 2.0 / Atom / data.go.kr(표준·odcloud) + XML 폭탄 차단
- 🔔 **변경 감지** — `--state`로 이전 실행에 없던 공지만 🆕 표기, `--only-new` 필터
- 📊 **기간 요약** — LLM 없이 규칙(빈도)만으로 기관·분류·키워드 다이제스트
- 📐 **사용자 템플릿** — `$title` `$body_md` 마커 치환으로 조직 서식 그대로 출력
- 🩹 **fail-open** — 한 출처가 죽어도(해외 IP 차단·URL 변경) 나머지로 보고서 완성,
  실패 출처는 표지에 투명 표기
- 🎨 **자체 완결형 HTML** — 인라인 CSS·다크모드 대응, 그대로 열람·인쇄·공유

## 설치

```bash
pip install .            # 저장소 루트에서
# 또는 개발용
pip install -e ".[dev]"
```

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

실제 렌더링 결과는 [`examples/`](examples/) 폴더의 `demo-report.html` · `.md` · `.json`를 참고하세요.

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
      --list-sources                     설정된 출처 출력
      --title TEXT                       보고서 제목 재정의
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
- `report.py` — Markdown · 자체 완결형 HTML · JSON · 사용자 템플릿 렌더러
- `rights.py` — 공공누리 등급 상수·라벨·판정

## 개발

```bash
pip install -e ".[dev]"
pytest -q            # 테스트
ruff check src tests # 린트
ruff format src tests
```

## 라이선스

MIT © 2025 — [`LICENSE`](LICENSE) 참고.

수집 대상 자료의 저작권은 각 발행 기관에 있으며, 재이용 시 보고서에 표기된
공공누리 등급과 출처표시 조건을 따라야 합니다. `open_site_clipper`는 원문 본문을
복제하지 않고 제목·링크·발행일 등 메타데이터만 모읍니다.
