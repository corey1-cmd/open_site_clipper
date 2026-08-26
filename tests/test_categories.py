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
    for name in ("조직도", "찾아오시는 길", "배너모음", "비전 및 목표", ""):
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


def test_dictionary_covers_real_government_menus():
    """사전이 얕으면 '기타'가 지배한다 — 실측에서 69%가 기타로 떨어졌다."""
    menus = (
        "업무추진비",
        "정보공개",
        "청렴",
        "국민참여",
        "예규",
        "훈령",
        "민원",
        "신고센터",
        "포토뉴스",
        "영상",
        "행사",
        "일정",
        "모집",
        "공모",
        "지원사업",
        "시험",
        "자격",
        "교육",
        "재정",
        "입법예고",
        "행정예고",
        "공청회",
        "설문",
        "제안",
        "자주묻는질문",
        "명단공표",
        "수의계약",
    )
    etc = [m for m in menus if categories.canonical(m) == categories.ETC]
    assert not etc, f"사전에서 빠진 메뉴명: {etc}"


def test_participation_category_exists():
    """민원·신고·제안은 공지와 성격이 달라 따로 묶는다."""
    assert categories.canonical("민원안내") == "참여"
    assert categories.canonical("국민신문고") == "참여"
    assert "참여" in categories.ORDER
