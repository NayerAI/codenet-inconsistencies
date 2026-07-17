"""Optionally execute both programs on the LLM-proposed input and compare.

This closes the loop on the LLM's claim: given a divergence input, we actually
compile/run each submission in an isolated temp directory (with CPU-time,
memory and wall-clock limits) and check whether their outputs really differ.

Supported toolchains: C (gcc), C++ (g++), Python (python3), Java (javac/java).
Anything else -- or a missing toolchain -- degrades gracefully to an
``unsupported``/``toolchain-missing`` result instead of raising.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from .config import VerificationConfig
from .utils import get_logger

log = get_logger(__name__)

try:  # resource is POSIX-only; the Apptainer image is Linux so this is present.
    import resource
except ImportError:  # pragma: no cover
    resource = None  # type: ignore


# Map language labels to a normalised runtime kind.
_LANG_KIND = {
    "C": "c",
    "C++": "cpp",
    "Python": "python",
    "Java": "java",
    "Go": "go",
    "JavaScript": "js",
}


@dataclass
class RunResult:
    language: str
    supported: bool
    compiled: bool
    ran: bool
    returncode: Optional[int]
    stdout: str
    stderr: str
    timed_out: bool
    error: Optional[str]


def _preexec(cpu_seconds: int, mem_bytes: int):
    """Return a preexec_fn capping CPU time and (optionally) address space.

    ``mem_bytes == 0`` disables the address-space cap.  We disable it for the
    JVM (which reserves a huge virtual address space up front and would fail to
    start under RLIMIT_AS) and instead bound the JVM heap with ``-Xmx``.
    """
    if resource is None:  # pragma: no cover - non-POSIX
        return None

    cpu = max(1, cpu_seconds)

    def _apply():  # pragma: no cover - runs in the child process
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
        if mem_bytes:
            try:
                resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
            except (ValueError, OSError):
                pass

    return _apply


def _run(
    cmd: list[str],
    cwd: Path,
    input_text: str,
    timeout: int,
    cpu_seconds: int,
    mem_bytes: int = 0,
    env: Optional[dict] = None,
) -> subprocess.CompletedProcess:
    preexec = _preexec(cpu_seconds, mem_bytes) if os.name == "posix" else None
    run_env = None
    if env:
        run_env = {**os.environ, **env}
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout,
        preexec_fn=preexec,
        env=run_env,
    )


def _truncate(text: str, limit: int) -> str:
    if len(text) > limit:
        return text[:limit] + f"\n...[truncated {len(text) - limit} bytes]"
    return text


def detect_java_main_class(source: str) -> Optional[str]:
    """Best-effort detection of the class whose ``main`` should be launched."""
    public = re.search(r"public\s+(?:final\s+|abstract\s+)?class\s+(\w+)", source)
    if public:
        return public.group(1)
    classes = list(re.finditer(r"\bclass\s+(\w+)", source))
    if not classes:
        return None
    main_idx = source.find("static void main")
    if main_idx == -1:
        main_idx = source.find("void main")
    if main_idx != -1:
        chosen = None
        for m in classes:
            if m.start() < main_idx:
                chosen = m.group(1)
        if chosen:
            return chosen
    return classes[0].group(1)


def run_program(
    language: str,
    source: str,
    filename_ext: str,
    input_text: str,
    cfg: VerificationConfig,
) -> RunResult:
    kind = _LANG_KIND.get(language)
    if kind is None:
        return RunResult(language, False, False, False, None, "", "", False, "unsupported language")

    with tempfile.TemporaryDirectory(prefix="codenet_verify_") as tmp:
        tmpdir = Path(tmp)
        try:
            if kind == "python":
                return _run_python(tmpdir, source, filename_ext, input_text, cfg, language)
            if kind in ("c", "cpp"):
                return _run_compiled_c(tmpdir, kind, source, filename_ext, input_text, cfg, language)
            if kind == "java":
                return _run_java(tmpdir, source, input_text, cfg, language)
            if kind == "go":
                return _run_go(tmpdir, source, input_text, cfg, language)
            if kind == "js":
                return _run_js(tmpdir, source, input_text, cfg, language)
        except subprocess.TimeoutExpired:
            return RunResult(language, True, True, True, None, "", "", True, "timed out")
        except Exception as exc:  # pragma: no cover - defensive
            return RunResult(language, True, False, False, None, "", "", False, f"exec error: {exc}")
    # Unreachable, keeps type checkers happy.
    return RunResult(language, False, False, False, None, "", "", False, "unreachable")


def _mem_bytes(cfg: VerificationConfig) -> int:
    return cfg.memory_limit_mb * 1024 * 1024 if cfg.memory_limit_mb > 0 else 0


def _run_python(tmpdir, source, ext, input_text, cfg, language) -> RunResult:
    if shutil.which(cfg.python_bin) is None:
        return RunResult(language, True, False, False, None, "", "", False, "python not available")
    src = tmpdir / f"main{ext or '.py'}"
    src.write_text(source, encoding="utf-8")
    proc = _run(
        [cfg.python_bin, str(src)], tmpdir, input_text,
        cfg.run_timeout_seconds, cfg.run_timeout_seconds, _mem_bytes(cfg),
    )
    return RunResult(
        language, True, True, True, proc.returncode,
        _truncate(proc.stdout, cfg.max_output_bytes),
        _truncate(proc.stderr, cfg.max_output_bytes), False, None,
    )


def _run_compiled_c(tmpdir, kind, source, ext, input_text, cfg, language) -> RunResult:
    compiler = cfg.gcc_bin if kind == "c" else cfg.gpp_bin
    if shutil.which(compiler) is None:
        return RunResult(language, True, False, False, None, "", "", False, f"{compiler} not available")
    src = tmpdir / f"main{ext or ('.c' if kind == 'c' else '.cpp')}"
    src.write_text(source, encoding="utf-8")
    exe = tmpdir / "prog"
    compile_cmd = [compiler, "-O2", "-w", "-o", str(exe), str(src)]
    if kind == "c":
        compile_cmd.append("-lm")
    # No address-space cap during compilation (the compiler needs headroom).
    comp = _run(compile_cmd, tmpdir, "", cfg.compile_timeout_seconds, cfg.compile_timeout_seconds, 0)
    if comp.returncode != 0:
        return RunResult(
            language, True, False, False, comp.returncode, "",
            _truncate(comp.stderr, cfg.max_output_bytes), False, "compilation failed",
        )
    proc = _run(
        [str(exe)], tmpdir, input_text,
        cfg.run_timeout_seconds, cfg.run_timeout_seconds, _mem_bytes(cfg),
    )
    return RunResult(
        language, True, True, True, proc.returncode,
        _truncate(proc.stdout, cfg.max_output_bytes),
        _truncate(proc.stderr, cfg.max_output_bytes), False, None,
    )


def _run_java(tmpdir, source, input_text, cfg, language) -> RunResult:
    if shutil.which(cfg.javac_bin) is None or shutil.which(cfg.java_bin) is None:
        return RunResult(language, True, False, False, None, "", "", False, "java toolchain not available")
    main_class = detect_java_main_class(source) or "Main"
    src = tmpdir / f"{main_class}.java"
    src.write_text(source, encoding="utf-8")
    comp = _run(
        [cfg.javac_bin, str(src)], tmpdir, "",
        cfg.compile_timeout_seconds, cfg.compile_timeout_seconds, 0,
    )
    if comp.returncode != 0:
        return RunResult(
            language, True, False, False, comp.returncode, "",
            _truncate(comp.stderr, cfg.max_output_bytes), False, "compilation failed",
        )
    # Bound the JVM heap with -Xmx instead of RLIMIT_AS (mem_bytes=0), since the
    # JVM reserves far more virtual address space than it commits.
    java_cmd = [cfg.java_bin]
    if cfg.memory_limit_mb > 0:
        java_cmd.append(f"-Xmx{cfg.memory_limit_mb}m")
    java_cmd += ["-cp", str(tmpdir), main_class]
    proc = _run(java_cmd, tmpdir, input_text, cfg.run_timeout_seconds, cfg.run_timeout_seconds, 0)
    return RunResult(
        language, True, True, True, proc.returncode,
        _truncate(proc.stdout, cfg.max_output_bytes),
        _truncate(proc.stderr, cfg.max_output_bytes), False, None,
    )


def _run_go(tmpdir, source, input_text, cfg, language) -> RunResult:
    if shutil.which(cfg.go_bin) is None:
        return RunResult(language, True, False, False, None, "", "", False, "go not available")
    src = tmpdir / "main.go"
    src.write_text(source, encoding="utf-8")
    # Run in GOPATH mode with caches inside the temp dir so a single stdlib-only
    # file runs fully offline.
    env = {
        "GO111MODULE": "off",
        "GOCACHE": str(tmpdir / ".gocache"),
        "GOPATH": str(tmpdir / ".gopath"),
        "GOFLAGS": "",
    }
    proc = _run(
        [cfg.go_bin, "run", str(src)], tmpdir, input_text,
        cfg.run_timeout_seconds + cfg.compile_timeout_seconds,
        cfg.run_timeout_seconds + cfg.compile_timeout_seconds, 0, env=env,
    )
    ok = proc.returncode == 0
    return RunResult(
        language, True, True, True, proc.returncode,
        _truncate(proc.stdout, cfg.max_output_bytes),
        _truncate(proc.stderr, cfg.max_output_bytes), False,
        None if ok else "go run failed",
    )


def _run_js(tmpdir, source, input_text, cfg, language) -> RunResult:
    if shutil.which(cfg.node_bin) is None:
        return RunResult(language, True, False, False, None, "", "", False, "node not available")
    src = tmpdir / "main.js"
    src.write_text(source, encoding="utf-8")
    proc = _run(
        [cfg.node_bin, str(src)], tmpdir, input_text,
        cfg.run_timeout_seconds, cfg.run_timeout_seconds, 0,
    )
    return RunResult(
        language, True, True, True, proc.returncode,
        _truncate(proc.stdout, cfg.max_output_bytes),
        _truncate(proc.stderr, cfg.max_output_bytes), False, None,
    )


def normalise_output(text: str) -> str:
    """Strip trailing whitespace per line and trailing blank lines."""
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def verify_divergence(
    cfg: VerificationConfig,
    language_a: str,
    source_a: str,
    ext_a: str,
    language_b: str,
    source_b: str,
    ext_b: str,
    divergence_input: str,
) -> dict:
    """Run both programs on ``divergence_input`` and compare their outputs."""
    if divergence_input is None:
        return {"status": "skipped", "reason": "no divergence input provided"}

    result_a = run_program(language_a, source_a, ext_a, divergence_input, cfg)
    result_b = run_program(language_b, source_b, ext_b, divergence_input, cfg)
    return _compare_results(result_a, result_b, method="programs", extra={"input": divergence_input})


def verify_function_divergence(
    cfg: VerificationConfig,
    language_a: str,
    program_a: Optional[str],
    ext_a: str,
    language_b: str,
    program_b: Optional[str],
    ext_b: str,
    divergence_input: Optional[str] = None,
) -> dict:
    """Execute two LLM-provided driver programs (each calling its function on the
    diverging input and printing the result) and compare their outputs.

    The drivers are self-contained programs, so they are run with empty stdin.
    Used for function-level datasets (TransCoder, HumanEval-X), where there is no
    stdin/stdout harness for the original code.
    """
    if not program_a or not program_b:
        return {
            "status": "skipped",
            "method": "llm_driver",
            "reason": "LLM did not provide runnable driver programs for both languages",
        }

    result_a = run_program(language_a, program_a, ext_a, "", cfg)
    result_b = run_program(language_b, program_b, ext_b, "", cfg)
    return _compare_results(
        result_a, result_b, method="llm_driver", extra={"input": divergence_input}
    )


def _compare_results(result_a, result_b, method: str, extra: dict) -> dict:
    both_ran = result_a.ran and result_b.ran and not result_a.timed_out and not result_b.timed_out
    outputs_differ: Optional[bool] = None
    if both_ran:
        outputs_differ = normalise_output(result_a.stdout) != normalise_output(result_b.stdout)
        status = "confirmed" if outputs_differ else "refuted"
    else:
        status = "inconclusive"

    return {
        "status": status,                 # confirmed | refuted | inconclusive | skipped
        "method": method,                 # "programs" | "llm_driver"
        "outputs_differ": outputs_differ,
        **extra,
        "program_a": asdict(result_a),
        "program_b": asdict(result_b),
    }
