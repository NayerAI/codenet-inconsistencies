from codenet_eval.config import Config
from codenet_eval.dataset import CodeNetDataset
from conftest import CSV_HEADER


def _write_problem(root, pid, rows):
    """rows: list of (submission_id, language, ext, status, code_size, source)."""
    lines = [CSV_HEADER]
    for sub_id, language, ext, status, size, source in rows:
        lines.append(
            f"{sub_id},{pid},u0,2020-01-01,{language},{language},{ext},{status},10,256,{size},1.0"
        )
        src = root / "data" / pid / language / f"{sub_id}{ext}"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text(source, encoding="utf-8")
    meta = root / "metadata" / f"{pid}.csv"
    meta.parent.mkdir(parents=True, exist_ok=True)
    meta.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_accepted_status_is_filtered_before_sampling(tmp_path):
    """Only problems with an Accepted submission in every language are eligible,
    and the chosen representative is always an Accepted one."""
    root = tmp_path / "data" / "Project_CodeNet"
    (root / "metadata").mkdir(parents=True)

    # p10001: Java has ONLY a Wrong Answer submission -> not eligible.
    _write_problem(
        root,
        "p10001",
        [
            ("s1", "C", ".c", "Accepted", 50, "int main(){}"),
            ("s2", "Python", ".py", "Accepted", 50, "pass"),
            ("s3", "Java", ".java", "Wrong Answer", 50, "class Main{}"),
        ],
    )
    # p10002: C has a SMALLER Wrong Answer plus an Accepted one -> the Accepted
    # submission must be picked despite the WA being smaller.
    _write_problem(
        root,
        "p10002",
        [
            ("s4", "C", ".c", "Wrong Answer", 5, "x"),
            ("s5", "C", ".c", "Accepted", 50, "int main(){}"),
            ("s6", "Python", ".py", "Accepted", 50, "pass"),
            ("s7", "Java", ".java", "Accepted", 50, "class Main{}"),
        ],
    )

    ds = CodeNetDataset(Config.from_dict({"data_dir": str(tmp_path / "data")}))

    eligible = dict(ds.eligible_problems(["C", "Python", "Java"], require_accepted=True))
    assert "p10001" not in eligible                    # WA-only Java excluded
    assert "p10002" in eligible
    assert eligible["p10002"]["C"].submission_id == "s5"   # Accepted, not the smaller WA
    assert eligible["p10002"]["C"].status == "Accepted"

    # Relaxing the filter makes the WA-only problem eligible again.
    eligible_all = dict(ds.eligible_problems(["C", "Python", "Java"], require_accepted=False))
    assert "p10001" in eligible_all


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
