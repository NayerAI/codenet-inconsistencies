from codenet_eval.pairing import language_pairs


def test_reference_strategy_is_n_minus_one():
    pairs = language_pairs(["C", "Python", "Java"], "reference", "C")
    assert pairs == [("C", "Python"), ("C", "Java")]
    assert len(pairs) == 2  # two requests for three languages


def test_reference_fallback_when_ref_missing():
    pairs = language_pairs(["Python", "Java"], "reference", "C")
    # Falls back to the first language as reference.
    assert pairs == [("Python", "Java")]


def test_all_strategy_is_all_combinations():
    pairs = language_pairs(["C", "Python", "Java"], "all")
    assert set(pairs) == {("C", "Python"), ("C", "Java"), ("Python", "Java")}
    assert len(pairs) == 3


def test_single_language_gives_no_pairs():
    assert language_pairs(["C"], "all") == []
