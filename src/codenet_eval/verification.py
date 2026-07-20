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
import signal
import subprocess
import tempfile
from dataclasses import asdict, dataclass, replace
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
    # For Python: which interpreter actually produced this result (py2/py3).
    interpreter: Optional[str] = None

    @property
    def clean(self) -> bool:
        """A trustworthy run: it executed, did not time out, and exited 0."""
        return self.ran and not self.timed_out and self.returncode == 0


def _preexec(cpu_seconds: int, mem_bytes: int):
    """preexec_fn that (a) starts a new session so the child + any processes it
    spawns form one killable group, and (b) caps CPU time and address space.

    ``mem_bytes == 0`` disables the address-space cap.  We disable it for the
    JVM (which reserves a huge virtual address space up front and would fail to
    start under RLIMIT_AS) and instead bound the JVM heap with ``-Xmx``.
    """
    if os.name != "posix":  # pragma: no cover - non-POSIX
        return None

    cpu = max(1, cpu_seconds)

    def _apply():  # pragma: no cover - runs in the child process
        os.setsid()  # own session/process group -> killable as a unit on timeout
        if resource is not None:
            resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
            if mem_bytes:
                try:
                    resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
                except (ValueError, OSError):
                    pass

    return _apply


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except OSError:
            pass


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
    run_env = {**os.environ, **env} if env else None
    proc = subprocess.Popen(
        cmd, cwd=str(cwd),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, preexec_fn=preexec, env=run_env,
    )
    try:
        out, err = proc.communicate(input=input_text, timeout=timeout)
    except subprocess.TimeoutExpired:
        # Kill the whole process group so orphaned children can't keep the
        # stdout pipe open and hang communicate() forever.
        _kill_group(proc)
        try:
            proc.communicate(timeout=5)
        except Exception:  # pragma: no cover - defensive
            pass
        raise
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


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
    """Compile (if needed) and run a program once on ``input_text``.

    Thin convenience wrapper around :func:`prepare_program`. When you need to run
    the *same* program on many inputs, prepare it once and call
    :meth:`Program.run` per input so compilation happens only once.
    """
    prog = prepare_program(language, source, filename_ext, cfg)
    try:
        return prog.run(input_text)
    finally:
        prog.close()


@dataclass
class Program:
    """A compiled/prepared program that can be executed on many inputs.

    Build it with :func:`prepare_program` (which compiles C/C++/Java/Go exactly
    once), then call :meth:`run` per input. Call :meth:`close` -- or use it as a
    context manager -- to remove its temp directory.

    If preparation failed (missing toolchain, unsupported language, compile
    error), ``error_result`` holds the verdict and every :meth:`run` returns a
    copy of it, mirroring the old per-input ``run_program`` behaviour.
    """

    language: str
    cfg: VerificationConfig
    kind: Optional[str] = None
    _tmp: Optional[tempfile.TemporaryDirectory] = None
    tmpdir: Optional[Path] = None
    run_cmd: Optional[list] = None
    env: Optional[dict] = None
    mem_bytes: int = 0
    run_error: Optional[str] = None            # error text when a run exits != 0
    python_bins: Optional[list] = None
    src_path: Optional[Path] = None
    error_result: Optional[RunResult] = None   # set if prepare failed

    # -- lifecycle -----------------------------------------------------------
    def close(self) -> None:
        if self._tmp is not None:
            self._tmp.cleanup()
            self._tmp = None

    def __enter__(self) -> "Program":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- execution -----------------------------------------------------------
    def run(self, input_text: str) -> RunResult:
        if self.error_result is not None:
            return replace(self.error_result)   # same verdict for every input
        try:
            if self.kind == "python":
                return self._run_python(input_text)
            return self._run_cmd(input_text)
        except subprocess.TimeoutExpired:
            return RunResult(self.language, True, True, True, None, "", "", True, "timed out")
        except Exception as exc:  # pragma: no cover - defensive
            return RunResult(self.language, True, False, False, None, "", "", False,
                             f"exec error: {exc}")

    def _run_python(self, input_text: str) -> RunResult:
        cfg = self.cfg
        last: Optional[RunResult] = None
        for interpreter in self.python_bins or []:
            proc = _run(
                [interpreter, str(self.src_path)], self.tmpdir, input_text,
                cfg.run_timeout_seconds, cfg.run_timeout_seconds, self.mem_bytes,
            )
            res = RunResult(
                self.language, True, True, True, proc.returncode,
                _truncate(proc.stdout, cfg.max_output_bytes),
                _truncate(proc.stderr, cfg.max_output_bytes), False,
                None if proc.returncode == 0 else f"{interpreter} exited {proc.returncode}",
                interpreter=interpreter,
            )
            if proc.returncode == 0:
                return res              # first interpreter that runs cleanly wins
            last = res
        return last  # type: ignore[return-value]  # python_bins is non-empty here

    def _run_cmd(self, input_text: str) -> RunResult:
        cfg = self.cfg
        proc = _run(
            self.run_cmd, self.tmpdir, input_text,
            cfg.run_timeout_seconds, cfg.run_timeout_seconds, self.mem_bytes, env=self.env,
        )
        ok = proc.returncode == 0
        return RunResult(
            self.language, True, True, True, proc.returncode,
            _truncate(proc.stdout, cfg.max_output_bytes),
            _truncate(proc.stderr, cfg.max_output_bytes), False,
            None if ok else (self.run_error or f"exited {proc.returncode}"),
        )


def prepare_program(
    language: str,
    source: str,
    filename_ext: str,
    cfg: VerificationConfig,
) -> Program:
    """Compile/prepare a program once so it can be run on many inputs.

    Missing toolchains, unsupported languages and compile errors do not raise:
    they are captured in the returned :class:`Program`'s ``error_result`` and
    surfaced from every :meth:`Program.run` call.
    """
    kind = _LANG_KIND.get(language)
    if kind is None:
        return Program(
            language, cfg,
            error_result=RunResult(language, False, False, False, None, "", "", False,
                                   "unsupported language"),
        )
    tmp = tempfile.TemporaryDirectory(prefix="codenet_verify_")
    prog = Program(language, cfg, kind=kind, _tmp=tmp, tmpdir=Path(tmp.name))
    try:
        if kind == "python":
            _prepare_python(prog, source, filename_ext)
        elif kind in ("c", "cpp"):
            _prepare_compiled_c(prog, kind, source, filename_ext)
        elif kind == "java":
            _prepare_java(prog, source)
        elif kind == "go":
            _prepare_go(prog, source)
        elif kind == "js":
            _prepare_js(prog, source)
    except subprocess.TimeoutExpired:
        prog.error_result = RunResult(language, True, False, False, None, "", "", True, "timed out")
    except Exception as exc:  # pragma: no cover - defensive
        prog.error_result = RunResult(language, True, False, False, None, "", "", False,
                                      f"prepare error: {exc}")
    return prog


def _mem_bytes(cfg: VerificationConfig) -> int:
    return cfg.memory_limit_mb * 1024 * 1024 if cfg.memory_limit_mb > 0 else 0


def _python_bins(cfg) -> list:
    """Interpreters to try, in order. CodeNet mixes Python 2 and 3, so we try
    each and accept the first that runs cleanly (exit 0)."""
    bins = list(getattr(cfg, "python_bins", None) or [cfg.python_bin])
    return [b for b in bins if shutil.which(b) is not None]


def _prepare_python(prog: Program, source: str, ext: str) -> None:
    cfg = prog.cfg
    bins = _python_bins(cfg)
    if not bins:
        prog.error_result = RunResult(prog.language, True, False, False, None, "", "", False,
                                      "python not available")
        return
    src = prog.tmpdir / f"main{ext or '.py'}"
    src.write_text(source, encoding="utf-8")
    prog.src_path = src
    prog.python_bins = bins          # try each; first clean run (exit 0) wins
    prog.mem_bytes = _mem_bytes(cfg)


def _prepare_compiled_c(prog: Program, kind: str, source: str, ext: str) -> None:
    cfg = prog.cfg
    compiler = cfg.gcc_bin if kind == "c" else cfg.gpp_bin
    if shutil.which(compiler) is None:
        prog.error_result = RunResult(prog.language, True, False, False, None, "", "", False,
                                      f"{compiler} not available")
        return
    src = prog.tmpdir / f"main{ext or ('.c' if kind == 'c' else '.cpp')}"
    src.write_text(source, encoding="utf-8")
    exe = prog.tmpdir / "prog"
    compile_cmd = [compiler, "-O2", "-w", "-o", str(exe), str(src)]
    if kind == "c":
        compile_cmd.append("-lm")
    # Compile ONCE here (no address-space cap; the compiler needs headroom).
    comp = _run(compile_cmd, prog.tmpdir, "", cfg.compile_timeout_seconds,
                cfg.compile_timeout_seconds, 0)
    if comp.returncode != 0:
        prog.error_result = RunResult(prog.language, True, False, False, comp.returncode, "",
                                      _truncate(comp.stderr, cfg.max_output_bytes), False,
                                      "compilation failed")
        return
    prog.run_cmd = [str(exe)]
    prog.mem_bytes = _mem_bytes(cfg)


def _prepare_java(prog: Program, source: str) -> None:
    cfg = prog.cfg
    if shutil.which(cfg.javac_bin) is None or shutil.which(cfg.java_bin) is None:
        prog.error_result = RunResult(prog.language, True, False, False, None, "", "", False,
                                      "java toolchain not available")
        return
    main_class = detect_java_main_class(source) or "Main"
    src = prog.tmpdir / f"{main_class}.java"
    src.write_text(source, encoding="utf-8")
    comp = _run([cfg.javac_bin, str(src)], prog.tmpdir, "",
                cfg.compile_timeout_seconds, cfg.compile_timeout_seconds, 0)
    if comp.returncode != 0:
        prog.error_result = RunResult(prog.language, True, False, False, comp.returncode, "",
                                      _truncate(comp.stderr, cfg.max_output_bytes), False,
                                      "compilation failed")
        return
    # Bound the JVM heap with -Xmx instead of RLIMIT_AS (mem_bytes=0), since the
    # JVM reserves far more virtual address space than it commits.
    java_cmd = [cfg.java_bin]
    if cfg.memory_limit_mb > 0:
        java_cmd.append(f"-Xmx{cfg.memory_limit_mb}m")
    java_cmd += ["-cp", str(prog.tmpdir), main_class]
    prog.run_cmd = java_cmd
    prog.mem_bytes = 0


def _prepare_go(prog: Program, source: str) -> None:
    cfg = prog.cfg
    if shutil.which(cfg.go_bin) is None:
        prog.error_result = RunResult(prog.language, True, False, False, None, "", "", False,
                                      "go not available")
        return
    src = prog.tmpdir / "main.go"
    src.write_text(source, encoding="utf-8")
    exe = prog.tmpdir / "prog"
    # Build ONCE in GOPATH mode with caches inside the temp dir so a single
    # stdlib-only file builds fully offline; the native binary is then run per
    # input (much cheaper than 'go run', which recompiles every time).
    env = {
        "GO111MODULE": "off",
        "GOCACHE": str(prog.tmpdir / ".gocache"),
        "GOPATH": str(prog.tmpdir / ".gopath"),
        "GOFLAGS": "",
    }
    comp = _run(
        [cfg.go_bin, "build", "-o", str(exe), str(src)], prog.tmpdir, "",
        cfg.run_timeout_seconds + cfg.compile_timeout_seconds,
        cfg.run_timeout_seconds + cfg.compile_timeout_seconds, 0, env=env,
    )
    if comp.returncode != 0:
        prog.error_result = RunResult(prog.language, True, False, False, comp.returncode, "",
                                      _truncate(comp.stderr, cfg.max_output_bytes), False,
                                      "compilation failed")
        return
    prog.run_cmd = [str(exe)]
    prog.run_error = "go program failed"
    prog.mem_bytes = 0


def _prepare_js(prog: Program, source: str) -> None:
    cfg = prog.cfg
    if shutil.which(cfg.node_bin) is None:
        prog.error_result = RunResult(prog.language, True, False, False, None, "", "", False,
                                      "node not available")
        return
    src = prog.tmpdir / "main.js"
    src.write_text(source, encoding="utf-8")
    prog.run_cmd = [cfg.node_bin, str(src)]
    prog.mem_bytes = 0


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


def _runresult_from_dict(d: dict) -> RunResult:
    return RunResult(
        language=d.get("language", ""),
        supported=d.get("supported", True),
        compiled=d.get("compiled", True),
        ran=d.get("ran", False),
        returncode=d.get("returncode"),
        stdout=d.get("stdout") or "",
        stderr=d.get("stderr") or "",
        timed_out=d.get("timed_out", False),
        error=d.get("error"),
        interpreter=d.get("interpreter"),
    )


def reclassify_verification(v: Optional[dict]) -> Optional[dict]:
    """Recompute a verification verdict from its stored program run data, with no
    re-execution. Applies the current (exit-status-aware) rules so old results
    where a crash/SyntaxError was mislabelled 'confirmed' become 'inconclusive'."""
    if not v or "program_a" not in v or "program_b" not in v:
        return v  # skipped / no execution data -> leave untouched
    a = _runresult_from_dict(v["program_a"])
    b = _runresult_from_dict(v["program_b"])
    extra = {"input": v["input"]} if "input" in v else {}
    return _compare_results(a, b, v.get("method", "programs"), extra)


def _run_reason(result: RunResult) -> Optional[str]:
    if not result.ran:
        return result.error or "did not run"
    if result.timed_out:
        return "timed out"
    if result.returncode != 0:
        return result.error or f"exited {result.returncode}"
    return None


def _compare_results(result_a, result_b, method: str, extra: dict) -> dict:
    out_a = normalise_output(result_a.stdout)
    out_b = normalise_output(result_b.stdout)

    outputs_differ: Optional[bool] = None
    if result_a.ran and result_b.ran:
        outputs_differ = out_a != out_b

    # A difference only counts if BOTH sides ran cleanly (executed, no timeout,
    # exit code 0). Otherwise a crash / SyntaxError / missing import would masquerade
    # as a semantic divergence -- these are 'inconclusive', not 'confirmed'.
    both_clean = result_a.clean and result_b.clean
    if both_clean:
        status = "confirmed" if outputs_differ else "refuted"
    else:
        status = "inconclusive"

    both_nonempty = bool(out_a) and bool(out_b)
    # Strongest evidence of differing semantics: both exit 0, both print
    # something, and the outputs differ.
    strong = bool(both_clean and outputs_differ and both_nonempty)

    reasons = {}
    ra, rb = _run_reason(result_a), _run_reason(result_b)
    if ra:
        reasons["program_a"] = ra
    if rb:
        reasons["program_b"] = rb

    record = {
        "status": status,                 # confirmed | refuted | inconclusive | skipped
        "method": method,                 # "programs" | "llm_driver"
        "outputs_differ": outputs_differ,
        "both_exit_zero": bool(result_a.returncode == 0 and result_b.returncode == 0),
        "both_nonempty": both_nonempty,
        "strong_semantic_diff": strong,
        **extra,
        "program_a": asdict(result_a),
        "program_b": asdict(result_b),
    }
    if reasons:
        record["inconclusive_reason"] = reasons
    return record
