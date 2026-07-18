"""예외 상황 보강 — EUC-KR 폴백, 출력 실패, 음수 인자, 상태 저장 실패, 스킴 보정."""

from __future__ import annotations

import pytest

from open_site_clipper import cli, discover, fetch, k2web_parse, state

CP949_PAGE = """
<table><tr>
  <td>1</td>
  <td><a href="/bbs/old/10/77/artclView.do">신입생 등록금 납부 안내</a></td>
  <td>재무회계팀</td><td>2026.03.02</td><td>10</td>
</tr></table>
""".encode("cp949")


def test_decode_text_fallback_chain():
    assert fetch.decode_text("한글".encode()) == "한글"
    assert fetch.decode_text("한글".encode("cp949")) == "한글"  # 구형 사이트
    broken = b"\xff\xfe\x00garbage"
    assert isinstance(fetch.decode_text(broken), str)  # 어떤 바이트든 생존


def test_k2web_parser_survives_euckr_page():
    """EUC-KR 페이지에서 제목·부서가 깨지지 않고 복원된다(모지바케 방지)."""
    (row,) = k2web_parse.parse_list(CP949_PAGE, "https://old.ac.kr/bbs/old/10/")
    assert row.title == "신입생 등록금 납부 안내"
    assert row.unit == "재무회계팀"


def test_output_write_failure_is_friendly():
    with pytest.raises(SystemExit) as e:
        cli.main(["--demo", "-o", "/없는폴더/없는하위/x.html"])
    assert "출력 파일을 쓸 수 없습니다" in str(e.value)


def test_negative_args_rejected():
    for argv in (["--demo", "--since", "-3"], ["--demo", "--deep-links-limit", "-1"]):
        with pytest.raises(SystemExit):  # argparse 사용법 오류(코드 2)
            cli.main(argv)


def test_state_save_failure_degrades_to_warning(tmp_path, monkeypatch, capsys):
    """상태 저장 실패는 크래시가 아니라 경고 — 보고서는 이미 전달됐다."""

    def boom(*a, **k):
        raise OSError("디스크 가득 참")

    monkeypatch.setattr(state, "save", boom)
    out = tmp_path / "r.html"
    rc = cli.main(["--demo", "--state", str(tmp_path / "s.json"), "-o", str(out)])
    assert rc == 0 and out.exists()  # 보고서는 살아서 나감
    assert "상태 파일을 저장하지 못했습니다" in capsys.readouterr().err


def test_discover_autofixes_missing_scheme():
    calls: list[str] = []

    def fx(url: str) -> bytes | None:
        calls.append(url)
        return b"<html><title>x</title><body></body></html>" if len(calls) == 1 else None

    res = discover.discover("plain.example", fetcher=fx, check_robots=False)
    assert res.start_url == "https://plain.example"
    assert calls[0] == "https://plain.example"  # 보정된 주소로 시작 요청
    # 이후 요청(관용 경로 추측)도 전부 보정된 스킴을 쓴다.
    assert all(c.startswith("https://plain.example") for c in calls)
