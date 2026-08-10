"""메뉴 이름 → 대분류. 요약이 읽을 수 있으려면 종수가 폭발하면 안 된다.

실측에서 분류가 **400종**까지 늘었다(`외 390종 4,189건`). 기관마다 메뉴명이
달라서, 사전에 없는 이름이 그대로 분류가 됐기 때문이다.
"""

from __future__ import annotations

from open_site_clipper import categories, digest
from open_site_clipper.model import Notice

REAL_MENUS = {
    "공지사항": "공지",
    "알립니다": "공지",
    "사전정보공표": "공지",
    "채용공고": "채용",
    "일자리 정보": "채용",
    "입찰정보": "입찰",
    "계약현황": "입찰",
    "인사발령": "인사",
    "표창": "인사",
    "보도자료": "보도자료",
    "설명자료": "보도자료",
    "새소식": "소식",
    "간행물": "자료",
    "통계자료": "자료",
    "정책자료실": "자료",
    "국정성과": "정책",
    "감사결과": "정책",
    "업무계획": "정책",
}


def test_real_menu_names_map_to_canonical():
    for name, expected in REAL_MENUS.items():
        assert categories.canonical(name) == expected, name


def test_unknown_names_fall_back_to_etc():
    """모르는 이름이 와도 새 분류를 만들지 않는다 — 이것이 400종의 원인이었다."""
    for name in ("업무추진비", "조직도", "찾아오시는 길", "배너모음", ""):
        assert categories.canonical(name) == categories.ETC


def test_classify_returns_empty_for_unknown():
    """classify 는 '모름'을 빈 문자열로 알려 준다(canonical 과 역할이 다르다)."""
    assert categories.classify("조직도") == ""
    assert categories.classify("공지사항") == "공지"


def test_digest_summarises_by_canonical_not_raw():
    """표에는 세부 이름이 남고, 요약은 대분류로만 센다."""
    notices = [
        Notice(title=f"t{i}", url=f"https://x/{i}", agency="기관", category=name)
        for i, name in enumerate(REAL_MENUS)
    ]
    d = digest.build(notices)
    names = {n for n, _c in d.categories}
    assert names <= set(categories.ORDER)  # 대분류 밖의 이름이 없다
    assert d.category_total <= len(categories.ORDER)
    # 세부는 공지 항목에 그대로 남아 있다.
    assert notices[0].category == "공지사항"


def test_canonical_count_stays_small_with_many_menus():
    """메뉴가 수백 개여도 요약은 아홉 갈래를 넘지 않는다."""
    notices = [
        Notice(title=f"t{i}", url=f"https://x/{i}", agency="기관", category=f"메뉴{i}")
        for i in range(300)
    ]
    d = digest.build(notices)
    assert d.category_total == 1 and d.categories[0][0] == categories.ETC
