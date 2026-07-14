# 기여 안내 (Contributing)

open_site_clipper에 관심 가져주셔서 감사합니다. 작은 도구인 만큼 규칙도 단순합니다.

## 개발 환경

```bash
pip install -e ".[dev]"
pytest -q
ruff check src tests && ruff format --check src tests
```

Python 3.10+ 만 있으면 됩니다(런타임 의존성 없음).

## 원칙

- **런타임 의존성 0 유지** — 새 기능이 외부 패키지를 요구하면, 표준 라이브러리로
  가능한지 먼저 검토해주세요. 불가피하면 이슈에서 논의합니다.
- **fail-open** — 한 출처/항목의 실패가 전체 보고서를 막아선 안 됩니다.
- **출처·라이선스 무생략** — 어떤 출력에서도 기관·발행일·원문 링크·공공누리
  등급을 빠뜨리지 않습니다(이 도구의 존재 이유).
- **테스트 동반** — 파싱·수집·렌더 변경에는 테스트를 함께 올려주세요.

## 새 출처 추가

`src/open_site_clipper/sources.py`의 `DEFAULT_SOURCES`에 `Source(...)`를 추가하고,
공공누리 등급(`rights`)을 보수적으로 부여합니다(불확실하면 `UNKNOWN`).

## 새 기관 응답 형식 지원

data.go.kr는 기관마다 필드명이 다릅니다. `parse._first_field`의 후보 키
튜플에 새 필드명을 추가하고, `tests/test_parse.py`에 케이스를 더해주세요.

## PR 전 체크리스트

- [ ] `pytest -q` 통과
- [ ] `ruff check` · `ruff format --check` 통과
- [ ] 사용자 표면(CLI·출력)이 바뀌면 `README.md` 갱신
