"""관련성 판정·연관 묶음 — 가중치, 동의어, 근거 기록, 섹션 배치, 자카드 그룹핑."""

from __future__ import annotations

from datetime import date

from open_site_clipper import cluster, relevance, theme
from open_site_clipper.model import Notice

SPACE = theme.from_dict(
    {
        "name": "우주",
        "keywords": {"우주": ["space"]},
        "sections": [
            {"name": "발사체", "keywords": {"발사체": ["로켓", "누리호"], "재사용": []}},
            {"name": "위성", "keywords": {"위성": ["satellite", "군집위성"]}},
        ],
    }
)


def _n(title, summary="", category="", topics=(), published=None, url=""):
    return Notice(
        title=title,
        url=url or f"https://g/{abs(hash(title))}",
        agency="기관",
        summary=summary,
        category=category,
        topics=tuple(topics),
        published=published,
    )


def test_field_weights_and_evidence():
    m = relevance.score(_n("누리호 4차 발사 성공", summary="재사용 검증"), SPACE)
    assert m is not None
    # 발사체(제목 동의어 '누리호' 3) + 재사용(요약 1) = 4, 근거는 기여 내림차순.
    assert m.score == 4
    assert m.matched == ("발사체", "재사용")
    assert m.section == "발사체"


def test_substring_matches_korean_compounds():
    # '통신군집위성' 속의 동의어 '군집위성'을 부분 문자열로 잡는다.
    m = relevance.score(_n("통신군집위성 배치 계획"), SPACE)
    assert m is not None and m.section == "위성" and "위성" in m.matched


def test_topic_bonus_and_unrelated_none():
    plain = relevance.score(_n("위성 데이터 개방"), SPACE)
    boosted = relevance.score(_n("위성 데이터 개방", topics=("우주",)), SPACE)
    assert plain is not None and boosted is not None
    assert boosted.score == plain.score + relevance.TOPIC_BONUS
    assert relevance.score(_n("지방세 납부 안내"), SPACE) is None


def test_section_tie_goes_to_theme_order_and_other():
    # 발사체·위성 기여가 동점(제목 3 vs 3)이면 정의 순서상 앞인 발사체.
    tie = relevance.score(_n("발사체 위성 동시 발표"), SPACE)
    assert tie is not None and tie.section == "발사체"
    # 최상위 키워드('우주')에만 맞으면 '기타'.
    top_only = relevance.score(_n("우주 정책 로드맵"), SPACE)
    assert top_only is not None and top_only.section == theme.OTHER_SECTION


def test_select_threshold_and_order():
    notices = [
        _n("예산 편성 요약", summary="space 분야"),  # 요약 1점뿐 → 하한 미달
        _n("누리호 발사", published=date(2025, 7, 1)),
        _n("가나다 로켓 발사", published=date(2025, 7, 3)),  # 동점이면 최신 우선
    ]
    picked = relevance.select(notices, SPACE)
    assert [m.notice.title for m in picked] == ["가나다 로켓 발사", "누리호 발사"]
    # 하한을 낮추면 요약-단독 적중도 들어온다.
    assert len(relevance.select(notices, SPACE, min_score=1)) == 3


def test_group_same_issue_multi_agency():
    a = _n("창정-10B 1단 발사체 회수 성공", published=date(2026, 7, 10))
    b = _n("중국 창정-10B 발사체 회수 성공 발표", published=date(2026, 7, 11))
    c = _n("상업용 우주정거장 사업자 선정 절차", published=date(2026, 7, 12))
    groups = cluster.group([a, b, c], text_of=lambda n: n.title, date_of=lambda n: n.published)
    # 같은 사안 2건이 한 묶음(크기순 첫 번째), 대표는 최신(b).
    assert [len(g) for g in groups] == [2, 1]
    assert groups[0][0] is b and groups[1][0] is c


def test_group_deterministic_and_empty():
    assert cluster.group([], text_of=str) == []
    items = ["누리호 발사 성공", "누리호 발사 성공 브리핑", "위성 개방"]
    g1 = cluster.group(items, text_of=lambda s: s)
    g2 = cluster.group(list(reversed(items)), text_of=lambda s: s)
    assert [sorted(g) for g in g1] == [sorted(g) for g in g2]
