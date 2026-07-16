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
