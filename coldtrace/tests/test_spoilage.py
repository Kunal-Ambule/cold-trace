"""Shelf-life burn math: pure functions, no I/O."""
from app.domain.commodities import get as get_com
from app.services.spoilage import assess, interval_burn, level_for


def test_no_burn_within_band():
    tomato = get_com("tomato")
    assert interval_burn(tomato, tomato.t_opt, 5.0) == 0.0


def test_burn_increases_with_temperature_and_time():
    tomato = get_com("tomato")
    low = interval_burn(tomato, tomato.t_max + 2, 1.0)
    high = interval_burn(tomato, tomato.t_max + 8, 1.0)
    assert 0 < low < high
    assert interval_burn(tomato, tomato.t_max + 2, 2.0) > low


def test_chill_injury_below_min():
    tomato = get_com("tomato")  # chill-sensitive
    assert interval_burn(tomato, tomato.t_min - 3, 1.0) > 0


def test_budget_mode_biologics():
    bio = get_com("biologics")
    # exactly at the budget: 120 minutes out of range should burn the whole value
    burn = interval_burn(bio, bio.t_max + 1, 2.0)
    assert abs(burn - 1.0) < 1e-9


def test_assess_empty_readings():
    tomato = get_com("tomato")
    a = assess(tomato, [], 100000)
    assert a["n"] == 0 and a["loss_frac"] == 0.0


def test_level_thresholds_are_monotonic():
    levels = [level_for(x) for x in (0.0, 0.003, 0.01, 0.04, 0.5)]
    order = {"low": 0, "moderate": 1, "high": 2, "critical": 3}
    assert [order[l] for l in levels] == sorted(order[l] for l in levels)
