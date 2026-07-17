import pytest

from codenet_eval.config import Config


def test_defaults():
    cfg = Config.from_dict({})
    assert cfg.languages == ["C", "Python", "Java"]
    assert cfg.sampling.percent == 1.0
    assert cfg.pairing.strategy == "reference"
    assert cfg.llm.provider == "openrouter"
    assert cfg.verification.enabled is True
    assert cfg.execution.workers == 4


def test_partial_override_merges(tmp_path):
    path = tmp_path / "cfg.yaml"
    path.write_text(
        "languages: [C, Python]\nsampling:\n  percent: 5\nllm:\n  model: some/model\n",
        encoding="utf-8",
    )
    cfg = Config.load(path)
    assert cfg.languages == ["C", "Python"]
    assert cfg.sampling.percent == 5
    # Untouched nested defaults survive the merge.
    assert cfg.sampling.seed == 42
    assert cfg.llm.model == "some/model"
    assert cfg.llm.base_url == "https://openrouter.ai/api/v1"


def test_derived_paths():
    cfg = Config.from_dict({"data_dir": "/tmp/x"})
    assert str(cfg.dataset_root).endswith("Project_CodeNet")
    assert str(cfg.results_root).endswith("results")
    assert cfg.run_dir("run-1").name == "run-1"


@pytest.mark.parametrize(
    "bad",
    [
        {"languages": ["C"]},                       # need >= 2
        {"languages": ["C", "C"]},                  # duplicates
        {"sampling": {"percent": 0}},               # out of range
        {"sampling": {"percent": 150}},             # out of range
        {"pairing": {"strategy": "nonsense"}},      # unknown strategy
        {"execution": {"workers": 0}},              # need >= 1
        {"dataset": {"type": "nope"}},              # unknown dataset type
    ],
)
def test_validation_rejects_bad_config(bad):
    cfg = Config.from_dict(bad)
    with pytest.raises(ValueError):
        cfg.validate()


def test_reference_language_outside_languages_is_not_fatal():
    # Now a warning + fallback (pairing uses the first language), not an error.
    cfg = Config.from_dict({"languages": ["C++", "Java"], "pairing": {"reference_language": "C"}})
    cfg.validate()  # must not raise


def test_dataset_type_default_and_override():
    assert Config.from_dict({}).dataset.type == "codenet"
    cfg = Config.from_dict({"dataset": {"type": "humaneval_x"}})
    cfg.validate()
    assert cfg.dataset.type == "humaneval_x"
