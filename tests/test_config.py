"""config._parse_zone: accept valid polygons, reject malformed / out-of-range input."""

import pytest

import config


def test_valid_zone_parses_to_pairs():
    assert config._parse_zone("0,0, 1,0, 1,1") == [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]


def test_too_few_points_rejected():
    with pytest.raises(ValueError):
        config._parse_zone("0,0, 1,1")


def test_odd_value_count_rejected():
    with pytest.raises(ValueError):
        config._parse_zone("0,0, 1,0, 1")


def test_non_finite_rejected():
    with pytest.raises(ValueError):
        config._parse_zone("nan,0, 1,0, 1,1")


def test_out_of_range_rejected():
    with pytest.raises(ValueError):
        config._parse_zone("0,0, 1,0, 2,1")
