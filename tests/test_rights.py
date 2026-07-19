"""공공누리(KOGL) 등급 로직 계약."""

from __future__ import annotations

from open_site_clipper import rights


def test_normalize_unknown_folds_to_unknown():
    assert rights.normalize("kogl_type1") == rights.KOGL_TYPE1
    assert rights.normalize("KOGL_TYPE1") == rights.KOGL_TYPE1
    assert rights.normalize("nonsense") == rights.UNKNOWN
    assert rights.normalize(None) == rights.UNKNOWN


def test_derivative_gate():
    # 변형 허용: 제7조·1·2유형
    assert rights.allows_derivative(rights.PUBLIC_DOMAIN)
    assert rights.allows_derivative(rights.KOGL_TYPE1)
    assert rights.allows_derivative(rights.KOGL_TYPE2)
    # 변경 금지: 3·4유형·미상
    assert not rights.allows_derivative(rights.KOGL_TYPE3)
    assert not rights.allows_derivative(rights.KOGL_TYPE4)
    assert not rights.allows_derivative(rights.UNKNOWN)


def test_label_and_badge_present_for_all_tiers():
    for tier in (
        rights.PUBLIC_DOMAIN,
        rights.KOGL_TYPE1,
        rights.KOGL_TYPE2,
        rights.KOGL_TYPE3,
        rights.KOGL_TYPE4,
        rights.UNKNOWN,
    ):
        assert rights.label(tier)
        assert rights.badge(tier)
