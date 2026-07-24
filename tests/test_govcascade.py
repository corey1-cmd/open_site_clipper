"""정부 캐스케이드 — 카테고리별 5단 폴백(rss→board→alt→datago→korea).

대학 캐스케이드와 다른 점 두 가지를 검증한다:
  ① 후보 주소를 좌표로 생성하지 않고 설정(routes)에서 받는다
  ② 기관 단위가 아니라 **카테고리 단위**로 폴백한다 — 보도자료가 korea.kr 로
     됐다고 채용 게시판을 건너뛰지 않는다
"""

from __future__ import annotations

from open_site_clipper import collect, govcascade, robots
from open_site_clipper.sources import Source, from_dicts

RSS = (
    '<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>'
    "<item><title>정책 브리핑 발표</title><link>https://www.korea.kr/n/1</link></item>"
    "</channel></rss>"
).encode()

BOARD = """
<table><thead><tr><th>번호</th><th>제목</th><th>게시일</th></tr></thead><tbody>
<tr><td>1</td><td><a href="/site/job/view.jsp?p=1">[본부] 공무원 채용 공고</a></td><td>2026.07.20.</td></tr>
<tr><td>2</td><td><a href="/site/job/view.jsp?p=2">[소속기관] 연구직 채용</a></td><td>2026.07.19.</td></tr>
</tbody></table>
""".encode()

MCST = Source(
    id="mcst",
    name="문화체육관광부",
    kind="govorg",
    url="",
    org="문화체육관광부",
    korea_feed="dept_mcst",
    routes=(
        ("공지", "rss", "https://www.mcst.go.kr/common/rss/notice.jsp"),
        ("보도자료", "rss", "https://www.mcst.go.kr/common/rss/press.jsp"),
        ("채용", "board", "https://www.mcst.go.kr/site/s_notice/notice/jobList.jsp"),
    ),
)


def test_stage_order_and_alt_derivation():
    stages = govcascade.stages_for(MCST, "채용")
    kinds = [k for k, _ in stages]
    assert kinds[0] == "board"  # 설정된 것이 먼저
    assert "alt" in kinds  # 그 주소에서 대체 후보가 파생된다
    alts = [u for k, u in stages if k == "alt"]
    assert any(u.startswith("https://m.mcst.go.kr/") for u in alts)  # 모바일 도메인
    assert any(u.startswith("https://mcst.go.kr/") for u in alts)  # www 제거
    # 보도자료에는 korea.kr 안전망이 마지막에 붙는다.
    press = [k for k, _ in govcascade.stages_for(MCST, "보도자료")]
    assert press[0] == "rss" and press[-1] == "korea"
    # 채용에는 korea.kr 이 없다 — 보도자료 전용이기 때문.
    assert "korea" not in kinds


def test_alt_urls_variants():
    alts = govcascade.alt_urls("https://www.opm.go.kr/kor/news/list.do")
    assert "https://m.opm.go.kr/kor/news/list.do" in alts
    assert "https://opm.go.kr/kor/news/list.do" in alts
    assert "https://www.opm.go.kr/eng/news/list.do" in alts  # 영문판 경로
    assert govcascade.alt_urls("not-a-url") == []


def test_falls_through_to_alt_when_original_blocked(monkeypatch):
    """원 주소가 robots 로 막히면 대체 주소로 판정을 다시 받는다(우회 아님)."""
    monkeypatch.setattr(
        robots, "allowed", lambda url, **k: not url.startswith("https://www.mcst.go.kr/site")
    )
    out = govcascade.collect_category(MCST, "채용", fetcher=lambda _u: BOARD)
    assert out.strategy == "alt" and len(out.notices) == 2
    assert out.attempts[0].reason == "robots.txt 차단"
    assert "board: robots.txt 차단 → alt: 2건" in out.trail()


def test_korea_feed_rescues_blocked_press(monkeypatch):
    """기관 사이트가 전부 막혀도 보도자료는 korea.kr 로 살아난다."""
    monkeypatch.setattr(robots, "allowed", lambda url, **k: "korea.kr" in url)
    out = govcascade.collect_category(MCST, "보도자료", fetcher=lambda _u: RSS)
    assert out.strategy == "korea" and len(out.notices) == 1
    assert out.attempts[-1].url == "https://www.korea.kr/rss/dept_mcst.xml"
    assert out.trail().endswith("korea: 1건")


def test_category_cascade_is_independent(monkeypatch):
    """보도자료가 성공해도 채용은 따로 시도된다 — 대학과 다른 핵심."""
    monkeypatch.setattr(robots, "allowed", lambda url, **k: "korea.kr" in url)

    def fx(url: str) -> bytes | None:
        return RSS if "korea.kr" in url else None

    notices, failures = govcascade.collect_org(MCST, fetcher=fx)
    assert len(notices) == 1  # 보도자료만 성공
    # 공지·채용은 각각 실패 사유가 남는다(조용한 실패 금지).
    joined = " | ".join(failures)
    assert "공지" in joined and "채용" in joined
    assert "robots.txt 차단" in joined


def test_all_stages_fail_records_full_trail():
    out = govcascade.collect_category(MCST, "채용", fetcher=lambda _u: None, check_robots=False)
    assert out.notices == [] and out.strategy == ""
    assert out.trail().startswith("board: 응답 없음 → alt: 응답 없음")


def test_collect_end_to_end_and_from_dicts():
    (src,) = from_dicts(
        [
            {
                "name": "문화체육관광부",
                "kind": "govorg",
                "org": "문화체육관광부",
                "korea_feed": "dept_mcst",
                "routes": [["보도자료", "rss", "https://www.mcst.go.kr/common/rss/press.jsp"]],
            }
        ]
    )
    assert src.korea_feed == "dept_mcst" and len(src.routes) == 1
    rep = collect.collect([src], fetcher=lambda _s: RSS)
    assert len(rep.notices) == 1 and rep.notices[0].org == "문화체육관광부"
    # routes·korea_feed 가 모두 없으면 채택하지 않는다.
    assert from_dicts([{"name": "x", "kind": "govorg"}]) == []
