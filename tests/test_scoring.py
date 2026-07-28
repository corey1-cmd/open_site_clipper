"""후보 점수·순서 — 같은 카테고리가 갈리지 않게, 음역 주소도 잡히게."""

from __future__ import annotations

from open_site_clipper import korean
from open_site_clipper.govdiscover import _fair_order, _romanized_hints, board_score


# ── 음역 주소 (searxng 의 '정규화 별칭 함께 등록' 원리를 한글에 적용) ───────
def test_romanize_basic():
    assert korean.romanize("공지사항") == "gongjisahang"
    assert korean.romanize("알림") == "alrim"
    assert korean.romanize("채용") == "chaeyong"
    assert korean.romanize("") == ""


def test_romanized_aliases_include_short_form():
    aliases = korean.romanized_aliases("공지사항")
    assert "gongjisahang" in aliases and "gongji" in aliases  # 줄여 쓰는 관행
    assert korean.romanized_aliases("가") == ()  # 너무 짧으면 별칭 없음


def test_hints_generated_from_dictionary():
    """사전을 고치면 음역 별칭이 자동으로 따라온다 — 따로 관리할 것이 없다."""
    _romanized_hints.cache_clear()
    hints = _romanized_hints()
    assert "gongji" in hints and "alrim" in hints and "chaeyong" in hints


def test_transliterated_urls_now_score_positive():
    """예전엔 음수로 밀리던 음역 주소가 잡힌다."""
    assert board_score("/gongji/list.html", "공지사항") > 0
    assert board_score("/alrim/board.do", "알림") > 0


def test_code_style_urls_scored_by_query_params():
    """`?mid=&bid=` 코드형 주소는 경로에 단서가 없다 — 파라미터로 잡는다."""
    assert board_score("/menu.es?mid=a1050&bid=0015", "공지") > board_score("/menu.es", "공지")


def test_multiple_keyword_hits_rank_higher():
    """키워드가 여러 개 맞은 주소가 위로(crawl4ai KeywordRelevanceScorer 원리)."""
    many = board_score("/frt/bbs/type010/commonSelectBoardList.do", "알립니다")
    one = board_score("/x/list.do", "알립니다")
    assert many > one


def test_intro_pages_still_pushed_down():
    assert board_score("/intro/greeting.do", "장관 인사말") < 0
    assert board_score("/about/history.do", "연혁") < board_score(
        "/board/notice/list.do", "공지사항"
    )


# ── 카테고리 공평 배분 ──────────────────────────────────────────────────────
def test_fair_order_interleaves_categories():
    """같은 카테고리가 자리를 독식하지 않고, 카테고리가 통째로 빠지지도 않는다."""
    cands = [
        ("채용", "board", "/board/job/list.do"),
        ("채용", "board", "/hr/employ.jsp"),
        ("채용", "board", "/menu.es?mid=a1&bid=07"),
        ("공지", "board", "/notice/list.do"),
        ("공지", "board", "/gongji/list.html"),
        ("입찰", "board", "/bid/list.do"),
    ]
    ordered = _fair_order(cands)
    top3 = {c for c, _k, _u in ordered[:3]}
    assert top3 == {"채용", "공지", "입찰"}  # 앞 3개에 세 카테고리가 모두 든다
    assert len(ordered) == len(cands)  # 하나도 잃지 않는다


def test_fair_order_is_deterministic():
    cands = [
        ("공지", "board", "/a/list.do"),
        ("채용", "board", "/b/list.do"),
        ("공지", "board", "/c/list.do"),
    ]
    assert _fair_order(cands) == _fair_order(list(reversed(cands)))


def test_fair_order_best_first_within_category():
    cands = [
        ("채용", "board", "/intro/employ.do"),
        ("채용", "board", "/board/job/list.do"),
    ]
    ordered = _fair_order(cands)
    assert ordered[0][2] == "/board/job/list.do"  # 카테고리 안에서는 점수순


def test_fair_order_empty():
    assert _fair_order([]) == []
