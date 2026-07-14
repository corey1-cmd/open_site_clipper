"""테마 정의·출처 정체성 — 로드/검증, 키워드 병합, topics 승계."""

from __future__ import annotations

import json

import pytest

from open_site_clipper import collect, theme
from open_site_clipper.sources import Source, from_dicts

THEME = {
    "name": "우주",
    "description": "발사체·위성 동향",
    "keywords": {"우주": ["space"]},
    "sections": [
        {"name": "발사체", "keywords": {"발사체": ["로켓", "로켓"], "재사용": None}},
        {"name": "위성", "keywords": {"위성": ["satellite"]}},
    ],
    "glossary": {"LEO": "지구 저궤도", " ": "무시됨"},
}


def test_load_and_merge(tmp_path):
    p = tmp_path / "t.json"
    p.write_text(json.dumps(THEME, ensure_ascii=False), encoding="utf-8")
    t = theme.load(p)
    assert t.name == "우주" and t.sections[0].name == "발사체"
    # 동의어 중복 제거 + None 은 빈 배열 취급.
    assert t.sections[0].keywords["발사체"] == ("로켓",)
    assert t.sections[0].keywords["재사용"] == ()
    merged = t.all_keywords()
    # 테마명·최상위·섹션 키워드가 전부 병합된다.
    assert set(merged) == {"우주", "발사체", "재사용", "위성"}
    assert t.glossary == {"LEO": "지구 저궤도"}


@pytest.mark.parametrize(
    "payload, msg",
    [
        ([], "JSON 객체"),
        ({}, '"name"'),
        ({"name": "x", "sections": {}}, "배열"),
        ({"name": "x", "sections": [{"keywords": {}}]}, '"name"'),
        ({"name": "x", "keywords": []}, "keywords"),
        ({"name": "x", "keywords": {"a": "문자열"}}, "배열"),
    ],
)
def test_validation_errors(payload, msg):
    with pytest.raises(ValueError, match=msg):
        theme.from_dict(payload)


def test_load_missing_file():
    with pytest.raises(ValueError, match="읽을 수 없습니다"):
        theme.load("/없는/경로/t.json")


RSS = (
    '<?xml version="1.0"?><rss><channel>'
    "<item><title>누리호 4차 발사</title><link>https://g/1</link></item>"
    "</channel></rss>"
)


def test_topics_inherited_to_notice():
    src = Source(id="s", name="기관", kind="rss", url="x", topics=("우주", "발사체"))
    (n,) = collect.collect([src], fetcher=lambda _s: RSS.encode()).notices
    assert n.topics == ("우주", "발사체")


def test_user_sources_accept_topics():
    (src,) = from_dicts([{"name": "기관", "kind": "rss", "url": "u", "topics": ["우주", " ", 3]}])
    assert src.topics == ("우주", "3")
