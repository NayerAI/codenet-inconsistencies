# Cross-Language Inconsistency Evaluation

An evaluation framework (Python + Apptainer) that uses an LLM to find **inputs
on which implementations of the same task in different programming languages
produce different outputs**.

Supports three parallel/transpilation datasets through one pipeline:

| `dataset.type` | Source | Unit | Languages | Verification |
|----------------|--------|------|-----------|--------------|
| `codenet` | [IBM Project CodeNet](https://github.com/IBM/Project_CodeNet) | stdin/stdout **program** | C, C++, Python, Java, Go, … | ✅ executed |
| `transcoder` | [TransCoder-test](https://github.com/facebookresearch/CodeGen) (GfG parallel functions) | **function** | C++, Java, Python | ⏭️ skipped |
| `humaneval_x` | [HumanEval-X](https://github.com/THUDM/CodeGeeX) | **function** | Python, C++, Java, JavaScript, Go | ⏭️ skipped |

For a given problem each language has an implementation meant to behave
identically, yet subtle differences — integer overflow, integer vs.
floating-point division, rounding, output precision, parsing, off-by-one edge
cases — can make them disagree. The framework samples problems, sends each
language pair to an LLM (via [OpenRouter](https://openrouter.ai/)), asks it to
find a diverging input, and — for stdin/stdout **programs** (CodeNet) — can then
**actually execute both programs** to confirm the claim. For **function**-level
datasets the LLM detection runs the same way, but execution-verification is
skipped (there is no cross-language calling harness), so those results are
marked `verification: skipped`.

---

## Pipeline

```
download  ──►  sample  ──►  run (LLM + verify)  ──►  report
   │             │                  │                    │
 dataset    manifest.jsonl     results.jsonl        summary.json
```

1. **download** – fetch/prepare the configured dataset into `data/`.
2. **sample** – find every problem solved in *all* configured languages, then
   randomly pick **X %** of them (default 1 %).
3. **run** – for each sampled problem, build the configured **language pairs**
   and ask the LLM to detect an inconsistency and provide a diverging input.
   For CodeNet programs, both are then compiled/run on that input and the
   outputs compared.
4. **report** – aggregate `results.jsonl` into summary statistics.

All persistent data — the dataset **and** every result — lives under a single
`data/` directory (configurable via `data_dir`).

---

## Requirements addressed

| # | Requirement | Where |
|---|-------------|-------|
| 1 | Download CodeNet | `download` command / `download.py` |
| 2 | Choose languages in config (default C, Python, Java) | `languages:` in `config.yaml` |
| 3 | Randomly sample X % of samples (default 1 %) | `sampling.percent` / `sampling.py` |
| 4 | Send all language pairs to a configurable LLM via OpenRouter | `pairing` + `llm` config / `llm.py` |
| 5 | All persistent data under a configurable `data/` folder | `data_dir` / everything writes under it |

**On requirement 4 — how many requests?** The default `pairing.strategy:
reference` compares one reference language against each of the others, i.e.
`n − 1` pairs → **two requests for three languages**, matching the brief. Set
`pairing.strategy: all` to instead compare every unordered pair
(`n·(n−1)/2`).

---

## Quick start (no download needed)

The framework ships a synthetic demo dataset so you can try the full pipeline
without the 7.8 GB download:

```bash
pip install -e .                      # or: pip install -r requirements.txt
export OPENROUTER_API_KEY=sk-or-...

codenet-eval --data-dir ./data demo   # write a tiny synthetic dataset
codenet-eval --data-dir ./data -c config/config.yaml \
    --log-level INFO all --run-name demo1
```

The demo contains deliberately inconsistent pairs (integer vs. float division,
32-bit overflow) and a consistent one, so you can see detections **and**
execution-verified confirmations/refutations.

Preview prompts/costs without spending tokens by adding `--dry-run` to `run`.

---

## Real run

```bash
export OPENROUTER_API_KEY=sk-or-...

# 1. Download + extract CodeNet (large!). Resumable; safe to re-run.
codenet-eval -c config/config.yaml download

# 2+3+4+5. Sample 1% of eligible problems, query the LLM, verify, report.
codenet-eval -c config/config.yaml all
```

Or step by step:

```bash
codenet-eval -c config/config.yaml sample --run-name run1
codenet-eval -c config/config.yaml run    --run-name run1 --limit 50   # cost cap
codenet-eval -c config/config.yaml report --run-name run1
```

`run` is **resumable**: re-running skips language pairs already present in
`results.jsonl`. Use `--limit N` to bound the number of API calls per invocation.

### Choosing a dataset

Set `dataset.type` and pick languages the dataset actually provides (see the
table above). `inspect` reports availability and eligibility.

```bash
# TransCoder-test (C++ / Java / Python parallel functions)
codenet-eval -c config/config.yaml --data-dir ./data \
    all   # with dataset.type: transcoder and languages: [C++, Java, Python]

# HumanEval-X (Python / C++ / Java / JavaScript / Go)
codenet-eval -c config/config.yaml inspect   # dataset.type: humaneval_x
```

A minimal HumanEval-X config:

```yaml
data_dir: ./data
dataset: { type: humaneval_x }
languages: [Python, C++, Java]
pairing: { strategy: reference, reference_language: Python }
```

Notes:

* **TransCoder** downloads a `.tar.gz` of `facebookresearch/CodeGen` and extracts
  only `data/transcoder_evaluation_gfg/`. Point `dataset.transcoder_url` at a
  local archive / `file://` path if the host can't reach GitHub codeload.
* **HumanEval-X** downloads five small `humaneval_<lang>.jsonl.gz` files and
  materialises `prompt + canonical_solution` per task under
  `data/humaneval-x/sources/`.
* Both are **function**-level, so `run` performs LLM detection but marks
  `verification: skipped`. Only CodeNet programs are executed.

### Offline / air-gapped / behind a proxy

The container uses the **host** network. On machines without direct internet
(e.g. HPC compute nodes), the download fails with a DNS/connection error. Three
ways around it:

1. **Proxy** – if your site has an HTTP proxy, set `HTTPS_PROXY` (honoured by
   the downloader) and forward it into the container:
   ```bash
   apptainer run --env "HTTPS_PROXY=$HTTPS_PROXY" --bind "$PWD/data:$PWD/data" \
       codenet-eval.sif -c config/config.yaml download
   ```
2. **Pre-download, then extract offline** – fetch the tarball on a networked
   machine (login node), drop it into `data/`, and extract without any network:
   ```bash
   # login node (has internet):
   wget -O data/Project_CodeNet.tar.gz \
     https://codait-cos-dax.s3.us.cloud-object-storage.appdomain.cloud/dax-project-codenet/1.0.0/Project_CodeNet.tar.gz
   # compute node (offline):
   codenet-eval extract          # or: codenet-eval download --offline
   ```
3. **Point at a local file** – set `dataset.url` to a local path or `file://`
   URL; it is used directly, no download:
   ```yaml
   dataset:
     url: file:///scratch/shared/Project_CodeNet.tar.gz
   ```

Note: the OpenRouter `run`/`all` step always needs outbound HTTPS to
`openrouter.ai` (again via `HTTPS_PROXY` if applicable).

---

## Apptainer

The image contains **only the runtime** — Python + dependencies and the
C / C++ / Python / Java toolchains (so execution-verification works out of the
box). The framework **code is not baked in**: it is read at run time from this
repo's `./src`, which Apptainer mounts automatically. **Editing the code never
requires rebuilding the image** — rebuild only when `requirements.txt` or the
toolchains change.

```bash
# Build the runtime image once (from the repo root):
apptainer build codenet-eval.sif apptainer/codenet-eval.def

# Run from the repo root — ./src and ./data come from the mount:
export OPENROUTER_API_KEY=sk-or-...
apptainer run codenet-eval.sif -c config/config.yaml all
```

Apptainer auto-mounts `$HOME` and the current directory, so when the repo lives
under `$HOME` no `--bind` is needed and `./src` / `./data` just work. Otherwise
bind the repo explicitly and/or point at the source:

```bash
apptainer run --bind /path/to/repo \
    --env CODENET_EVAL_SRC=/path/to/repo/src \
    codenet-eval.sif -c config/config.yaml all
```

`scripts/run.sh <args>` is a convenience wrapper that runs the `.sif` (binding
the repo and setting `CODENET_EVAL_SRC`) if present, and falls back to a native
Python run otherwise.

---

## Configuration

Everything is driven by a YAML file (see [`config/config.yaml`](config/config.yaml)).
A partial file is fine — omitted fields fall back to built-in defaults. Key
fields:

```yaml
data_dir: ./data                 # (5) root for dataset + all results

dataset:
  type: codenet                  # codenet | transcoder | humaneval_x

languages:                       # (2) which languages to compare (>= 2)
  - C
  - Python
  - Java

sampling:
  percent: 1.0                   # (3) X% of eligible problems
  seed: 42                       #     reproducible sampling
  max_samples: null              #     optional hard cap
  require_accepted: true

pairing:
  strategy: reference            # reference (n-1) | all (n*(n-1)/2)
  reference_language: C

llm:                             # (4) OpenRouter model + request settings
  model: anthropic/claude-3.5-sonnet
  base_url: https://openrouter.ai/api/v1
  api_key_env: OPENROUTER_API_KEY
  temperature: 0.0
  max_tokens: 2048
  json_mode: true

verification:
  enabled: true                  # execute both programs to confirm divergence
  run_timeout_seconds: 10
  memory_limit_mb: 1024

execution:
  workers: 4                     # parallel workers for the evaluation stage

output:
  results_dir: results           # relative to data_dir
  run_name: null                 # null -> timestamped run directory
```

Override `data_dir` and `log_level` from the command line with `--data-dir` and
`--log-level`.

### Parallelism

The evaluation stage runs `execution.workers` tasks concurrently (one LLM
request plus its optional verification per task). The work is I/O-bound (HTTP +
subprocess), so this scales close to linearly until you hit the LLM provider's
rate limits — the client retries `429`s with backoff. Set it in the config or
override per invocation:

```bash
codenet-eval -c config/config.yaml run --workers 16
```

`workers: 1` is fully sequential. Results are keyed by `(problem, lang_a,
lang_b)`, so parallel runs stay resumable and never double-write a pair; only
the *order* of lines in `results.jsonl` becomes non-deterministic.

### API key

The OpenRouter key is read from the environment variable named by
`llm.api_key_env` (default `OPENROUTER_API_KEY`). It is never written to disk or
into results.

---

## Output format

Each run produces a directory under `data/results/<run_name>/`:

| file | contents |
|------|----------|
| `config.snapshot.yaml` | the exact effective config used |
| `manifest.jsonl` | one line per sampled problem: chosen submissions + language pairs |
| `results.jsonl` | one line per language pair (LLM verdict + verification) |
| `summary.json` | aggregate statistics (`report`) |

A `results.jsonl` row looks like:

```json
{
  "problem_id": "p03050",
  "language_a": "C", "submission_a": "s123",
  "language_b": "Python", "submission_b": "s456",
  "model": "anthropic/claude-3.5-sonnet",
  "inconsistent": true,
  "confidence": 0.86,
  "category": "integer_vs_float_division",
  "reasoning": "C truncates a/b; Python 3 returns a float.",
  "divergence_input": "7 2\n",
  "expected_output_a": "3",
  "expected_output_b": "3.5",
  "verification": {
    "status": "confirmed",
    "outputs_differ": true,
    "program_a": {"stdout": "3", "...": "..."},
    "program_b": {"stdout": "3.5", "...": "..."}
  }
}
```

Verification `status` is `confirmed` (outputs really differ), `refuted` (they
match — LLM false positive), `inconclusive` (a program failed to compile/run or
timed out), or `skipped`.

---

## Dataset notes

The default `dataset.url` is the full Project CodeNet archive
(`Project_CodeNet.tar.gz`, 7.8 GB compressed, ~180 GB extracted), served from
IBM Cloud Object Storage:

```
https://codait-cos-dax.s3.us.cloud-object-storage.appdomain.cloud/dax-project-codenet/1.0.0/Project_CodeNet.tar.gz
```

It contains the `metadata/`, `data/`, `problem_descriptions/` and
`derived/input_output/` trees this framework reads.

* **URL note:** IBM decommissioned the old `dax-cdn.cdn.appdomain.cloud` CDN
  that early docs reference; the `codait-cos-dax` S3 endpoint above is the URL
  currently published in the [official IBM/Project_CodeNet README](https://github.com/IBM/Project_CodeNet#download-the-dataset).
  If IBM moves it again, just set `dataset.url` accordingly (or point it at a
  local file / `file://` path).
* The download is **resumable** (HTTP range) and re-running `download` is a
  no-op once `metadata/` exists.
* Set `dataset.checksum_sha256` to verify archive integrity.
* Use `--no-keep-archive` to delete the tarball after extraction and save space.
* For a quick functional test without the download, use `codenet-eval demo`.

> Note: IBM's smaller *benchmark* tarballs (e.g. `Project_CodeNet_Java250`) use
> a different, code-only layout and do **not** carry the per-problem metadata
> this pipeline relies on. Use the full archive (or the demo) for real runs.

---

## Development

```bash
pip install -e ".[dev]"
pytest -q
```

The test suite builds a small synthetic CodeNet tree on disk and exercises
config merging/validation, sampling, pairing, metadata parsing, prompt/JSON
parsing, the OpenRouter client (with a stubbed HTTP layer), archive extraction,
and the end-to-end runner — including **real** C/Python/Java compilation and
output comparison in the verification step.

### Layout

```
src/codenet_eval/
  config.py         # YAML config model + validation
  providers.py      # dataset adapters: codenet / transcoder / humaneval_x
  download.py       # resumable download + safe extraction (generic + CodeNet)
  dataset.py        # read CodeNet metadata / submissions / descriptions / I/O
  sampling.py       # reproducible X% sampling
  pairing.py        # language-pair strategies
  prompts.py        # LLM prompt construction (program vs. function)
  llm.py            # OpenRouter (OpenAI-compatible) client + JSON parsing
  verification.py   # compile & run programs, compare outputs (sandboxed)
  runner.py         # orchestration (sample -> query -> verify -> store)
  report.py         # aggregate results into summary
  demo.py           # synthetic dataset generator
  cli.py            # argparse entry point
apptainer/codenet-eval.def
config/config.yaml
scripts/run.sh
tests/
```
