from codenet_eval.dataset import CodeNetDataset


def test_lists_problems_and_representatives(mini_config):
    ds = CodeNetDataset(mini_config)
    assert ds.exists()
    assert ds.list_problem_ids() == ["p00001", "p00002"]

    reps = ds.representatives("p00001", ["C", "Python", "Java"])
    assert reps is not None
    assert set(reps.keys()) == {"C", "Python", "Java"}
    assert reps["C"].submission_id == "s0001"
    assert reps["Python"].path.is_file()


def test_eligible_requires_all_languages(mini_config):
    ds = CodeNetDataset(mini_config)
    eligible = dict(ds.eligible_problems(["C", "Python", "Java"]))
    assert set(eligible) == {"p00001", "p00002"}

    # A language nobody submitted -> no eligible problems.
    eligible_go = dict(ds.eligible_problems(["C", "Go"]))
    assert eligible_go == {}


def test_description_and_sample_io(mini_config):
    ds = CodeNetDataset(mini_config)
    desc = ds.problem_description("p00001")
    assert desc and "divided" in desc

    io = ds.sample_io("p00001")
    assert io is not None
    sample_in, sample_out = io
    assert sample_in.strip() == "7 2"
    assert sample_out.strip() == "3"

    assert ds.sample_io("p00002") is None  # no derived I/O for p00002
