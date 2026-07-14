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
```

### 예시 출력 (`--demo --format markdown`)

```markdown
# 정부·공공기관 공지 보고서

- 생성 시각: 2025-07-07T09:00:00+09:00
- 공지 5건 · 기관 2곳

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
      --list-sources                     설정된 출처 출력
      --title TEXT                       보고서 제목 재정의
```

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
- `report.py` — Markdown · 자체 완결형 HTML · JSON 렌더러
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
