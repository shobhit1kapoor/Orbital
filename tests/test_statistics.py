from orbital_shared.stats import wilson_interval, zero_failure_upper_bound


def test_zero_failure_bound_meets_contract_at_one_thousand_runs():
    assert zero_failure_upper_bound(1000) < 0.005


def test_wilson_interval_penalizes_small_samples():
    small_low, _ = wilson_interval(10, 10)
    large_low, _ = wilson_interval(1000, 1000)
    assert small_low < large_low
    assert large_low > 0.99
