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


# ── 주소에서 분류 읽기 (앵커 이름이 없을 때) ────────────────────────────────
def test_from_url_reads_path_signals():
    """사이트맵·경로 사이클로 찾은 게시판은 앵커 텍스트가 없다 — 주소를 읽는다."""
    cases = {
        "/news/notice/noticeList.do": "공지",
        "/site/s_notice/notice/jobList.jsp": "채용",
        "/site/s_notice/notice/bidList.jsp": "입찰",
        "/common/rss/press.jsp": "보도자료",
        "/minwon/list.do": "참여",
        "/gongji/list.html": "공지",  # 로마자 표기도 잡는다
    }
    for url, expected in cases.items():
        assert categories.from_url(url) == expected, url


def test_from_url_ignores_query_string():
    """`?bid=0015`(게시판 번호)가 'bid(입찰)'로 읽히던 오판을 막는다."""
    assert categories.from_url("/board/board.es?mid=a205&bid=0015") == categories.ETC
    assert categories.from_url("/x/list.do?key=00641") == categories.ETC


def test_from_url_falls_back_when_no_signal():
    assert categories.from_url("/article/list.do") == categories.ETC
    assert categories.from_url("") == categories.ETC
    assert categories.from_url("/x/y", fallback="소식") == "소식"


# ── 라벨 결정 순서와 '기타' 진단 ────────────────────────────────────────────
def test_label_prefers_name_then_url_then_raw():
    """이름이 안 잡히면 주소를 본다 — 예전에는 곧장 앵커 원문을 썼다."""
    from open_site_clipper import govdiscover

    # '더보기' 는 분류가 안 되지만 주소에 notice 가 있으면 공지로.
    html = (
        "<html><head><title>OO</title></head><body>"
        '<a href="/news/notice/noticeList.do">더보기</a>'
        "</body></html>"
    ).encode()
    board = (
        "<table><thead><tr><th>번호</th><th>제목</th><th>등록일</th></tr></thead><tbody>"
        '<tr><td>2</td><td><a href="/v?id=2">2026년 채용 공고</a></td><td>2026.07.20</td></tr>'
        '<tr><td>1</td><td><a href="/v?id=1">정기 입찰 공고</a></td><td>2026.07.19</td></tr>'
        "</tbody></table>"
    ).encode()
    pages = {
        "https://x.go.kr/": html,
        "https://x.go.kr/news/notice/noticeList.do": board,
    }
    from open_site_clipper import robots

    robots.reset_cache()
    robots._CACHE["https://x.go.kr"] = None
    robots._SITEMAPS["https://x.go.kr"] = []
    routes, _n = govdiscover.find_routes(
        "https://x.go.kr/", fetcher=lambda u: pages.get(u, b""), check_robots=False
    )
    assert routes and routes[0][0] == "공지"  # '더보기' 가 아니라
    robots.reset_cache()


def test_digest_shows_what_is_inside_etc():
    """'기타' 가 크면 그 안에 무엇이 들었는지 보여 준다 — 사전 보강의 근거."""
    from open_site_clipper import report
    from open_site_clipper.model import Report

    notices = [
        Notice(
            title=f"t{i}",
            url=f"https://x/{i}",
            agency="기관",
            category=["더보기", "바로가기", "공지사항"][i % 3],
        )
        for i in range(30)
    ]
    d = digest.build(notices)
    names = {n for n, _c in d.etc_samples}
    assert names == {"더보기", "바로가기"}  # 분류된 '공지사항' 은 빠진다
    md = report.render_markdown(Report(notices=notices, digest=d))
    assert "기타 내역(" in md and "더보기" in md
    assert "이름 2종" in md  # 롱테일인지 덩어리인지 바로 드러난다


# ── 실측 '기타 내역'에서 드러난 세 갈래 ─────────────────────────────────────
def test_meaningless_anchors_are_not_labels():
    """'전체'·'더보기'는 게시판 이름이 아니라 조작용 단어다(실측 78·40·38건)."""
    from open_site_clipper.govdiscover import _raw_label

    for word in ("전체", "더보기", "바로가기", "목록", "상세보기", "새창열림", "기타"):
        assert _raw_label(word) == categories.ETC, word
    # 진짜 게시판 이름은 그대로 남는다.
    assert _raw_label("수목원/정원") == "수목원/정원"


def test_dictionary_gaps_from_real_run():
    """실측 기타 내역에서 드러난 누락을 메웠다."""
    assert categories.canonical("예결산") == "정책"
    assert categories.canonical("국고보조금 정보") == "정책"
    assert categories.canonical("국회 관련 정보") == "정책"
    assert categories.canonical("칭찬합시다") == "참여"


def test_institution_specific_names_stay_etc():
    """기관 고유 게시판은 억지로 묶지 않는다 — 기타가 정직하다."""
    assert categories.canonical("수목원/정원") == categories.ETC


def test_etc_names_count_reveals_long_tail():
    """상위 몇 개가 전체의 일부뿐이면 사전으로는 못 잡는 롱테일이다."""
    notices = [
        Notice(title=f"t{i}", url=f"https://x/{i}", agency="기관", category=f"특화{i}")
        for i in range(40)
    ]
    d = digest.build(notices)
    assert d.etc_names == 40  # 이름이 40종 — 상위 10개로는 4분의 1뿐
    assert len(d.etc_samples) == 10


def test_school_boards_get_school_categories():
    """학교 게시판은 '모집'을 써도 채용이 아니다 — 입학·장학·학사가 먼저다."""
    cases = {
        "학사공지": "학사",
        "장학공지": "장학",
        "입학공지": "입학",
        "신입생 모집": "입학",
        "장학생 모집": "장학",
        "학사 시험 일정": "학사",
        "취업정보": "채용",
        "일반공지": "공지",
        "채용공고": "채용",
        "공무원 시험": "채용",
    }
    for name, expected in cases.items():
        assert categories.canonical(name) == expected, name


def test_school_url_romanization_reads_sound_spelling():
    """학교 주소는 받침을 소리대로 적는다(haksa·janghak·ipsi) — 글자대로만 보면 놓친다."""
    assert categories.from_url("https://x.ac.kr/haksa/notice/list.do") == "학사"
    assert categories.from_url("https://x.ac.kr/janghak/list.do") == "장학"
    assert categories.from_url("https://x.ac.kr/ipsi/board/list") == "입학"
    # 정부 주소는 그대로
    assert categories.from_url("https://x.go.kr/news/notice/noticeList.do") == "공지"
