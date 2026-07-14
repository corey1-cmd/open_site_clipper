"""실행 간 상태 — 첫 실행 기준선, 신규 표기, 병합·상한, 깨진 파일 fail-open."""

from __future__ import annotations

import json

from open_site_clipper import state
from open_site_clipper.model import Notice


def _n(url: str) -> Notice:
    return Notice(title="t", url=url, agency="기관")


def test_missing_file_is_first_run(tmp_path):
    assert state.load(tmp_path / "none.json") is None


def test_corrupt_file_fails_open(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{보고서", encoding="utf-8")
    assert state.load(p) is None
    p.write_text('{"seen": "문자열이면 안 됨"}', encoding="utf-8")
    assert state.load(p) is None


def test_save_then_load_roundtrip(tmp_path):
    p = tmp_path / "state.json"
    state.save(p, current_keys={"https://g/1", "https://g/2"}, previous=None, updated_at="T")
    loaded = state.load(p)
    assert loaded is not None and set(loaded) == {"https://g/1", "https://g/2"}
    payload = json.loads(p.read_text(encoding="utf-8"))
    assert payload["version"] == state.STATE_VERSION
    assert payload["updated_at"] == "T"


def test_mark_new_flags_unseen_only():
    notices = [_n("https://g/old"), _n("https://g/new")]
    marked = state.mark_new(notices, seen=["https://g/old"])
    flags = {n.url: n.is_new for n in marked}
    assert flags == {"https://g/old": False, "https://g/new": True}
    # 원본은 불변(frozen) — 새 목록으로 반환된다.
    assert all(not n.is_new for n in notices)


def test_save_merges_and_prioritizes_current(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_MAX_KEYS", 3)
    p = tmp_path / "state.json"
    state.save(p, current_keys={"a"}, previous=["x", "y", "z"], updated_at="T")
    kept = state.load(p)
    # 이번 실행 키(a)가 먼저 보존되고, 과거 키는 상한까지만 밀려 들어온다.
    assert kept is not None and kept[0] == "a" and len(kept) == 3
