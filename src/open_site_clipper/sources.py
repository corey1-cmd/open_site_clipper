"""공지 출처 레지스트리 — 어떤 정부·공공기관 피드를 어떤 등급으로 수집할지.

출처는 코드에 하드코딩하지 않고 이 레지스트리(+ 사용자 JSON)로 관리한다.
기관이 URL을 개편해도 여기(또는 --sources 파일)만 고치면 된다.

kind:
  - "rss"    표준 RSS 2.0 / Atom 피드
  - "datago" 공공데이터포털(data.go.kr) OpenAPI(JSON) — 인증키 필요(선택)

rights: 공공누리 등급(rights.py). 보도자료 채널은 통상 제1유형이나, 페이지
단위 예외가 있으므로 보수적으로 부여한다. 미상은 UNKNOWN.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import rights


@dataclass(frozen=True, slots=True)
class Source:
    """수집 대상 하나."""

    id: str
    name: str  # 기관 표시명 → Notice.agency 로 승계
    kind: str  # "rss" | "datago"
    url: str
    rights: str = rights.UNKNOWN
    category: str = ""
    enabled: bool = True


# 기본 출처 — 공개 RSS 위주(인증키 불필요). data.go.kr 채널은 예시로 꺼둔 채
# 심어 두고, 사용자가 인증키(GOVBRIEF_DATAGO_KEY)를 넣고 켜면 동작한다.
#
# 주의: 일부 정부 서버(korea.kr 등)는 해외 IP를 차단할 수 있다. 국내에서
# 실행하면 정상 수집되고, 수집 실패한 출처는 보고서 표지에 "수집 실패"로
# 투명하게 표기된다(한 출처의 실패가 전체 보고서를 막지 않는다).
DEFAULT_SOURCES: tuple[Source, ...] = (
    Source(
        id="korea-policy",
        name="대한민국 정책브리핑",
        kind="rss",
        url="https://www.korea.kr/rss/policy.xml",
        rights=rights.KOGL_TYPE1,
        category="정책",
    ),
    Source(
        id="korea-dept",
        name="정부 부처 보도자료",
        kind="rss",
        url="https://www.korea.kr/rss/dept_all.xml",
        rights=rights.KOGL_TYPE1,
        category="보도자료",
    ),
    Source(
        id="mois",
        name="행정안전부",
        kind="rss",
        url="https://www.mois.go.kr/gpms/view/jsp/rss/rss.jsp?ctxCd=1012",
        rights=rights.KOGL_TYPE1,
        category="보도자료",
    ),
    Source(
        id="mcst",
        name="문화체육관광부",
        kind="rss",
        url="https://www.mcst.go.kr/common/rss/press.jsp",
        rights=rights.KOGL_TYPE1,
        category="보도자료",
    ),
    Source(
        id="kisa",
        name="한국인터넷진흥원",
        kind="rss",
        url="https://www.kisa.or.kr/rss/401",
        rights=rights.KOGL_TYPE1,
        category="공지",
    ),
    Source(
        id="mss",
        name="중소벤처기업부",
        kind="rss",
        url="https://www.mss.go.kr/rss/smba/board/86.do",
        rights=rights.KOGL_TYPE1,
        category="보도자료",
    ),
    Source(
        id="gg",
        name="경기도 뉴스포털",
        kind="rss",
        url="https://gnews.gg.go.kr/rss/gnews_rss_main.do",
        rights=rights.KOGL_TYPE1,
        category="지자체",
    ),
    # data.go.kr OpenAPI 예시(꺼짐). GOVBRIEF_DATAGO_KEY 발급 후 enabled=True로.
    Source(
        id="datago-example",
        name="공공데이터포털 예시",
        kind="datago",
        url="https://apis.data.go.kr/1721000/msitpressexplaininfo/getPressList",
        rights=rights.KOGL_TYPE1,
        category="보도자료",
        enabled=False,
    ),
)


def default_sources(*, include_disabled: bool = False) -> list[Source]:
    """기본 출처 목록(기본은 enabled만)."""
    return [s for s in DEFAULT_SOURCES if include_disabled or s.enabled]


def demo_sources() -> list[Source]:
    """--demo 전용 출처 — 번들 샘플과 1:1로 짝지어져 네트워크 없이 동작한다.

    url은 실제로 쓰이지 않는다(데모 페처가 소스 id로 샘플을 찾는다).
    """
    return [
        Source(
            id="mois",
            name="행정안전부",
            kind="rss",
            url="sample://mois",
            rights=rights.KOGL_TYPE1,
            category="보도자료",
        ),
        Source(
            id="datago-example",
            name="과학기술정보통신부",
            kind="datago",
            url="sample://datago",
            rights=rights.KOGL_TYPE1,
            category="보도자료",
        ),
    ]


def from_dicts(items: list[dict[str, object]]) -> list[Source]:
    """사용자 JSON(--sources file.json)을 Source 목록으로 변환한다.

    최소 필드: name, kind, url. 나머지는 기본값. 등급은 정규화된다.
    """
    out: list[Source] = []
    for i, raw in enumerate(items):
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        url = str(raw.get("url") or "").strip()
        kind = str(raw.get("kind") or "rss").strip().lower()
        if not name or not url or kind not in ("rss", "datago"):
            continue
        out.append(
            Source(
                id=str(raw.get("id") or f"src-{i}"),
                name=name,
                kind=kind,
                url=url,
                rights=rights.normalize(str(raw.get("rights") or rights.UNKNOWN)),
                category=str(raw.get("category") or ""),
                enabled=bool(raw.get("enabled", True)),
            )
        )
    return out
