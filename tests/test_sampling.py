from codenet_eval.sampling import sample_count, select_problem_ids


def test_sample_count_rounds_and_floors_to_one():
    assert sample_count(0, 1.0, None) == 0
    assert sample_count(1000, 1.0, None) == 10
    assert sample_count(1000, 0.01, None) == 1  # never below 1 when percent > 0
    assert sample_count(1000, 100.0, None) == 1000
    assert sample_count(1000, 50.0, 5) == 5     # max_samples cap


def test_selection_is_deterministic_for_seed():
    ids = [f"p{n:05d}" for n in range(200)]
    a = select_problem_ids(ids, percent=10, seed=7)
    b = select_problem_ids(ids, percent=10, seed=7)
    assert a == b
    assert len(a) == 20
    assert a == sorted(a)  # returned sorted


def test_different_seed_changes_selection():
    ids = [f"p{n:05d}" for n in range(200)]
    a = select_problem_ids(ids, percent=10, seed=1)
    b = select_problem_ids(ids, percent=10, seed=2)
    assert a != b


def test_smaller_fraction_is_subset_of_larger():
    # The seed must not depend on the fraction: 0.1% ⊂ 1% ⊂ 5%.
    ids = [f"p{n:05d}" for n in range(2429)]
    s01 = set(select_problem_ids(ids, percent=0.1, seed=42))
    s1 = set(select_problem_ids(ids, percent=1.0, seed=42))
    s5 = set(select_problem_ids(ids, percent=5.0, seed=42))
    assert s01 <= s1 <= s5
    assert len(s01) < len(s1) < len(s5)
