"""딥링크 — 첨부/관련 링크만 추출, 본문은 취하지 않음. 등급 게이팅·상한 준수."""

from __future__ import annotations

from open_site_clipper import collect, deeplink, rights
from open_site_clipper.model import Notice

PAGE = """
<html><body>
  <h1>보도자료 제목</h1>
  <p>본문 문단은 수집 대상이 아니다.</p>
  <a href="/files/press.pdf">보도자료 전문</a>
  <a href="../data/통계.xlsx">  통계   자료 </a>
  <a href="/board/fileDown.do?id=7">붙임</a>
  <a href="https://other.go.kr/a.hwp"></a>
  <a href="/notice/list">목록</a>
  <a href="#top">맨 위로</a>
  <a href="javascript:void(0)">첨부 열기</a>
  <a href="/files/press.pdf">중복 링크</a>
</body></html>
"""


def test_extract_only_related_links():
    links = deeplink.extract(PAGE.encode(), "https://g.go.kr/board/view/1")
    labels = [(x.label, x.kind) for x in links]
    # 확장자·문구로 판별된 것만, 중복 URL은 1회.
    assert ("보도자료 전문", "PDF") in labels
    assert ("통계 자료", "XLS") in labels  # 공백 정규화
    assert ("붙임", "링크") in labels  # 확장자 없어도 문구로 판별
    assert ("a.hwp", "HWP") in labels  # 라벨 없으면 파일명으로
    # 내비게이션·앵커·javascript·본문은 제외.
    assert all(x.label not in ("목록", "맨 위로") for x in links)
    assert all(not x.url.startswith("javascript") for x in links)
    assert "본문 문단" not in str(links)
    assert len(links) == 4


def test_relative_urls_resolved():
    links = deeplink.extract(PAGE.encode(), "https://g.go.kr/board/view/1")
    urls = {x.url for x in links}
    assert "https://g.go.kr/files/press.pdf" in urls
    assert "https://g.go.kr/board/data/통계.xlsx" in urls


def test_limit_and_broken_html():
    links = deeplink.extract(PAGE.encode(), "https://g.go.kr/x", limit=2)
    assert len(links) == 2
    assert deeplink.extract(b"<a href=", "https://g.go.kr/x") == []
    assert deeplink.extract(b"", "https://g.go.kr/x") == []


def _n(url="https://g.go.kr/n/1", tier=rights.KOGL_TYPE1):
    return Notice(title="t", url=url, agency="기관", rights=tier)


def test_enrich_respects_rights_gate_and_limit():
    calls: list[str] = []

    def fx(url: str) -> bytes:
        calls.append(url)
        return PAGE.encode()

    open_n = _n()
    closed = _n("https://g.go.kr/n/2", rights.KOGL_TYPE3)  # 변형 금지 → 건너뜀
    out = collect.enrich_links([open_n, closed], fetcher=fx)
    assert len(out[0].links) == 4 and out[1].links == ()
    assert calls == ["https://g.go.kr/n/1"]

    # 상한 초과분은 원본 그대로.
    many = [_n(f"https://g.go.kr/n/{i}") for i in range(4)]
    out2 = collect.enrich_links(many, fetcher=fx, limit=2)
    assert [bool(x.links) for x in out2] == [True, True, False, False]


def test_enrich_fail_open_on_fetch_error():
    out = collect.enrich_links([_n()], fetcher=lambda _u: None)
    assert out[0].links == ()  # 실패해도 공지 자체는 살아남는다
