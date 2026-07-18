"""Configuration model and loader.

The configuration is a small tree of dataclasses.  ``Config.load`` reads a YAML
file, deep-merges it on top of the built-in defaults, and returns a validated
``Config`` object.  Every field therefore has a sensible default and a partial
YAML file is enough to override just what you care about.
"""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

# --- Default dataset location -------------------------------------------------
# The full IBM Project CodeNet archive (7.8 GB compressed) on IBM Cloud Object
# Storage. IBM decommissioned the old dax-cdn.cdn.appdomain.cloud CDN; this
# codait-cos-dax S3 endpoint is the URL currently published in the official
# IBM/Project_CodeNet README.
DEFAULT_DATASET_URL = (
    "https://codait-cos-dax.s3.us.cloud-object-storage.appdomain.cloud/"
    "dax-project-codenet/1.0.0/Project_CodeNet.tar.gz"
)


DATASET_TYPES = ("codenet", "transcoder", "humaneval_x")


@dataclass
class DatasetConfig:
    # Which dataset to evaluate: "codenet" (stdin/stdout programs),
    # "transcoder" or "humaneval_x" (parallel functions across languages).
    type: str = "codenet"

    # --- CodeNet ------------------------------------------------------------
    url: str = DEFAULT_DATASET_URL
    # Name of the downloaded archive inside ``data_dir``.
    archive_name: str = "Project_CodeNet.tar.gz"
    # Name of the top-level directory contained in the archive.
    root_name: str = "Project_CodeNet"
    # Optional SHA-256 to verify the archive after download.
    checksum_sha256: Optional[str] = None

    # --- TransCoder-test (parallel GfG functions in facebookresearch/CodeGen) -
    # A .tar.gz/.zip of the CodeGen repo, or a local path / file:// URL to one.
    transcoder_url: str = (
        "https://codeload.github.com/facebookresearch/CodeGen/tar.gz/refs/heads/main"
    )
    # Sub-path inside the archive holding the parallel functions.
    transcoder_subdir: str = "data/transcoder_evaluation_gfg"

    # --- HumanEval-X (THUDM/CodeGeeX) ---------------------------------------
    # Base URL under which per-language humaneval_<lang>.jsonl.gz files live.
    humaneval_x_base_url: str = (
        "https://raw.githubusercontent.com/THUDM/CodeGeeX/main/"
        "codegeex/benchmark/humaneval-x"
    )


@dataclass
class SamplingConfig:
    # Percentage of *eligible* problems to sample (0-100). Default 1%.
    percent: float = 1.0
    seed: int = 42
    # Hard cap on the number of sampled problems (applied after the percentage).
    max_samples: Optional[int] = None
    # Only consider "Accepted" submissions as representatives.
    require_accepted: bool = True


@dataclass
class PairingConfig:
    # "reference": compare a reference language against every other language
    #              (n-1 pairs -> 2 requests for 3 languages).
    # "all":       compare every unordered language pair (n*(n-1)/2 pairs).
    strategy: str = "reference"
    reference_language: str = "C"


@dataclass
class LLMConfig:
    provider: str = "openrouter"
    model: str = "anthropic/claude-3.5-sonnet"
    base_url: str = "https://openrouter.ai/api/v1"
    # Name of the environment variable that holds the API key.
    api_key_env: str = "OPENROUTER_API_KEY"
    temperature: float = 0.0
    max_tokens: int = 2048
    request_timeout: int = 120
    max_retries: int = 4
    retry_backoff: float = 2.0
    # Per-submission code is truncated to this many characters to bound tokens.
    max_code_chars: int = 16000
    include_problem_description: bool = True
    # Request a JSON object via the API's response_format. Disable for models
    # proxied by OpenRouter that reject the parameter (parsing still works).
    json_mode: bool = True
    # Extra HTTP headers (OpenRouter recommends HTTP-Referer / X-Title).
    extra_headers: dict[str, str] = field(default_factory=dict)


@dataclass
class VerificationConfig:
    # When enabled, LLM-proposed divergences are executed and outputs compared.
    #   * program datasets (CodeNet): run the ORIGINAL programs on the diverging
    #     stdin.
    #   * function datasets (TransCoder, HumanEval-X): the LLM also returns a
    #     complete runnable driver per language that calls the function on the
    #     diverging input; both drivers are executed and their outputs compared
    #     (see function_drivers).
    # Requires the relevant toolchains -- all present in the Apptainer image.
    enabled: bool = True
    # For function datasets, ask the LLM for per-language driver programs and
    # execute them to verify. Costs extra output tokens; set false to skip.
    function_drivers: bool = True
    run_timeout_seconds: int = 10
    compile_timeout_seconds: int = 30
    max_output_bytes: int = 100_000
    # Address-space limit per executed program (MiB); 0 disables the limit.
    memory_limit_mb: int = 1024
    # CodeNet mixes Python 2 and 3. Interpreters are tried in order; the first
    # that runs cleanly (exit 0) is used, so a Py2-only snippet still runs.
    python_bins: list[str] = field(default_factory=lambda: ["python3", "python2"])
    python_bin: str = "python3"   # legacy fallback if python_bins is empty
    gcc_bin: str = "gcc"
    gpp_bin: str = "g++"
    javac_bin: str = "javac"
    java_bin: str = "java"
    go_bin: str = "go"
    node_bin: str = "node"


@dataclass
class ExecutionConfig:
    # Number of parallel workers for the evaluation stage (one LLM request plus
    # its optional verification per task). 1 = fully sequential. Because the
    # work is I/O-bound (HTTP + subprocess), threads parallelise it well.
    # Too high may trip the LLM provider's rate limits (the client retries 429s).
    workers: int = 4


@dataclass
class OutputConfig:
    # Results directory, relative to ``data_dir`` (or absolute).
    results_dir: str = "results"
    # Sub-directory for a single run; defaults to a timestamp when omitted.
    run_name: Optional[str] = None


@dataclass
class Config:
    # Root for *all* persistent data (dataset + results).
    data_dir: str = "./data"
    languages: list[str] = field(default_factory=lambda: ["C", "Python", "Java"])
    log_level: str = "INFO"
    dataset: DatasetConfig = field(default_factory=DatasetConfig)
    sampling: SamplingConfig = field(default_factory=SamplingConfig)
    pairing: PairingConfig = field(default_factory=PairingConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    verification: VerificationConfig = field(default_factory=VerificationConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    output: OutputConfig = field(default_factory=OutputConfig)

    # --- derived paths -------------------------------------------------------
    @property
    def data_path(self) -> Path:
        return Path(self.data_dir).expanduser()

    @property
    def dataset_root(self) -> Path:
        """Directory that contains ``data/``, ``metadata/`` etc."""
        return self.data_path / self.dataset.root_name

    @property
    def archive_path(self) -> Path:
        return self.data_path / self.dataset.archive_name

    @property
    def transcoder_root(self) -> Path:
        """Directory holding the extracted TransCoder parallel functions."""
        return self.data_path / "transcoder"

    @property
    def humaneval_x_root(self) -> Path:
        """Directory holding the materialised HumanEval-X solutions."""
        return self.data_path / "humaneval-x"

    @property
    def results_root(self) -> Path:
        results = Path(self.output.results_dir).expanduser()
        if results.is_absolute():
            return results
        return self.data_path / results

    def run_dir(self, run_name: str) -> Path:
        return self.results_root / run_name

    # --- (de)serialisation ---------------------------------------------------
    @classmethod
    def load(cls, path: Optional[str | Path]) -> "Config":
        merged = _defaults_dict()
        if path is not None:
            raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
            if not isinstance(raw, dict):
                raise ValueError(f"Config file {path} must contain a YAML mapping")
            merged = _deep_merge(merged, raw)
        cfg = cls.from_dict(merged)
        cfg.validate()
        return cfg

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        data = copy.deepcopy(data)
        return cls(
            data_dir=data.get("data_dir", "./data"),
            languages=list(data.get("languages", ["C", "Python", "Java"])),
            log_level=data.get("log_level", "INFO"),
            dataset=DatasetConfig(**data.get("dataset", {})),
            sampling=SamplingConfig(**data.get("sampling", {})),
            pairing=PairingConfig(**data.get("pairing", {})),
            llm=LLMConfig(**data.get("llm", {})),
            verification=VerificationConfig(**data.get("verification", {})),
            execution=ExecutionConfig(**data.get("execution", {})),
            output=OutputConfig(**data.get("output", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def dump_yaml(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(self.to_dict(), sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

    # --- validation ----------------------------------------------------------
    def validate(self) -> None:
        if self.dataset.type not in DATASET_TYPES:
            raise ValueError(
                f"dataset.type must be one of {DATASET_TYPES}, got {self.dataset.type!r}"
            )
        if len(self.languages) < 2:
            raise ValueError("At least two languages are required for pairwise comparison")
        if len(set(self.languages)) != len(self.languages):
            raise ValueError("Duplicate entries in 'languages'")
        if not (0 < self.sampling.percent <= 100):
            raise ValueError("sampling.percent must be in (0, 100]")
        if self.execution.workers < 1:
            raise ValueError("execution.workers must be >= 1")
        if self.pairing.strategy not in ("reference", "all"):
            raise ValueError("pairing.strategy must be 'reference' or 'all'")
        # A reference language outside 'languages' is not fatal: pairing falls
        # back to the first language (and warns). This keeps multi-dataset use
        # smooth, where the natural reference differs (e.g. C++ vs C).


def _defaults_dict() -> dict[str, Any]:
    return asdict(Config())


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result
