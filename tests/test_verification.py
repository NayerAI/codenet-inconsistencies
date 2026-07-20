import shutil

import pytest

from codenet_eval.config import VerificationConfig
from codenet_eval.verification import (
    detect_java_main_class,
    normalise_output,
    prepare_program,
    run_program,
    verify_divergence,
    verify_function_divergence,
)
from conftest import C_DIV, JAVA_DIV, JAVA_SUM, PY_DIV, PY_SUM

VCFG = VerificationConfig(run_timeout_seconds=15, compile_timeout_seconds=60)


def test_normalise_output():
    assert normalise_output("3  \n\n\n") == "3"
    assert normalise_output("a\r\nb\r\n") == "a\nb"


def test_detect_java_main_class():
    assert detect_java_main_class(JAVA_DIV) == "Main"
    assert detect_java_main_class("class Foo { public static void main(String[] a){} }") == "Foo"
    assert detect_java_main_class("int x;") is None


@pytest.mark.skipif(shutil.which("python3") is None, reason="python3 required")
def test_run_python_program():
    res = run_program("Python", PY_SUM, ".py", "2 3\n", VCFG)
    assert res.ran and res.returncode == 0
    assert res.stdout.strip() == "5"


@pytest.mark.skipif(shutil.which("gcc") is None or shutil.which("python3") is None,
                    reason="gcc + python3 required")
def test_verify_divergence_confirmed_c_vs_python():
    # C integer division vs Python true division on 7/2 -> 3 vs 3.5.
    result = verify_divergence(
        VCFG, "C", C_DIV, ".c", "Python", PY_DIV, ".py", "7 2\n"
    )
    assert result["status"] == "confirmed"
    assert result["outputs_differ"] is True
    assert result["program_a"]["stdout"].strip() == "3"
    assert result["program_b"]["stdout"].strip() == "3.5"


@pytest.mark.skipif(shutil.which("gcc") is None or shutil.which("python3") is None,
                    reason="gcc + python3 required")
def test_verify_divergence_refuted_for_consistent_pair():
    from conftest import C_SUM

    result = verify_divergence(
        VCFG, "C", C_SUM, ".c", "Python", PY_SUM, ".py", "10 20\n"
    )
    assert result["status"] == "refuted"
    assert result["outputs_differ"] is False


@pytest.mark.skipif(shutil.which("javac") is None or shutil.which("java") is None,
                    reason="java toolchain required")
def test_run_java_program():
    res = run_program("Java", JAVA_SUM, ".java", "4 5\n", VCFG)
    assert res.ran, res.error
    assert res.stdout.strip() == "9"


# --- Go / JavaScript runtimes ---------------------------------------------
@pytest.mark.skipif(shutil.which("go") is None, reason="go required")
def test_run_go_program():
    src = 'package main\nimport "fmt"\nfunc main(){ fmt.Println(7) }\n'
    res = run_program("Go", src, ".go", "", VCFG)
    assert res.ran, res.error
    assert res.stdout.strip() == "7"


@pytest.mark.skipif(shutil.which("node") is None, reason="node required")
def test_run_js_program():
    res = run_program("JavaScript", "console.log(6+1)", ".js", "", VCFG)
    assert res.ran, res.error
    assert res.stdout.strip() == "7"


# --- function-driver verification -----------------------------------------
@pytest.mark.skipif(shutil.which("gcc") is None or shutil.which("python3") is None,
                    reason="gcc + python3 required")
def test_verify_function_divergence_confirmed():
    # Two self-contained drivers that call "the function" and print results.
    prog_py = "def f(x):\n    return x/2\nprint(f(7))\n"          # 3.5
    prog_cpp = '#include <iostream>\nint f(int x){return x/2;}\nint main(){std::cout<<f(7)<<"\\n";}\n'  # 3
    r = verify_function_divergence(VCFG, "Python", prog_py, ".py", "C++", prog_cpp, ".cpp", "f(7)")
    assert r["status"] == "confirmed"
    assert r["method"] == "llm_driver"
    assert r["outputs_differ"] is True


@pytest.mark.skipif(shutil.which("gcc") is None or shutil.which("python3") is None,
                    reason="gcc + python3 required")
def test_verify_function_divergence_refuted():
    prog_py = "def f(x):\n    return x+1\nprint(f(7))\n"
    prog_cpp = '#include <iostream>\nint f(int x){return x+1;}\nint main(){std::cout<<f(7)<<"\\n";}\n'
    r = verify_function_divergence(VCFG, "Python", prog_py, ".py", "C++", prog_cpp, ".cpp", "f(7)")
    assert r["status"] == "refuted"
    assert r["outputs_differ"] is False


def test_verify_function_divergence_missing_driver():
    r = verify_function_divergence(VCFG, "Python", None, ".py", "C++", "x", ".cpp", "f(7)")
    assert r["status"] == "skipped"
    assert r["method"] == "llm_driver"


# --- exit-status-aware classification (regression for false positives) -----
@pytest.mark.skipif(shutil.which("gcc") is None or shutil.which("python3") is None,
                    reason="gcc + python3 required")
def test_syntax_error_is_inconclusive_not_confirmed():
    py2 = 'print "hello"\n'  # SyntaxError under python3 (Py2 print statement)
    c = '#include <stdio.h>\nint main(){printf("world\\n");return 0;}\n'
    r = verify_divergence(VCFG, "Python", py2, ".py", "C", c, ".c", "")
    assert r["status"] == "inconclusive"          # NOT confirmed
    assert r["strong_semantic_diff"] is False
    assert "program_a" in r.get("inconclusive_reason", {})


@pytest.mark.skipif(shutil.which("gcc") is None or shutil.which("python3") is None,
                    reason="gcc + python3 required")
def test_strong_vs_weak_semantic_diff():
    prints_2 = '#include <stdio.h>\nint main(){printf("2\\n");return 0;}\n'
    # both exit 0, both non-empty, differ -> strong
    r = verify_divergence(VCFG, "Python", "print(1)\n", ".py", "C", prints_2, ".c", "")
    assert r["status"] == "confirmed"
    assert r["strong_semantic_diff"] is True
    assert r["both_nonempty"] is True
    # clean run that prints nothing vs one that prints -> confirmed but WEAK
    r2 = verify_divergence(VCFG, "Python", "pass\n", ".py", "C", prints_2, ".c", "")
    assert r2["status"] == "confirmed"
    assert r2["both_nonempty"] is False
    assert r2["strong_semantic_diff"] is False


def test_numpy_available_for_python3():
    import importlib.util
    if importlib.util.find_spec("numpy") is None:
        pytest.skip("numpy not installed")
    src = "import numpy as np\nprint(int(np.array([1,2,3]).sum()))\n"
    res = run_program("Python", src, ".py", "", VCFG)
    assert res.clean, res.error
    assert res.stdout.strip() == "6"


@pytest.mark.skipif(shutil.which("python2") is None, reason="python2 required")
def test_python2_fallback_runs_py2_only_snippet():
    from codenet_eval.config import VerificationConfig
    cfg = VerificationConfig(python_bins=["python3", "python2"])
    res = run_program("Python", 'print "hi"\n', ".py", "", cfg)
    assert res.clean
    assert res.interpreter == "python2"     # python3 failed, python2 rescued it
    assert res.stdout.strip() == "hi"


# --- compile-once / run-many (Program) -------------------------------------
@pytest.mark.skipif(shutil.which("gcc") is None, reason="gcc required")
def test_prepare_program_compiles_once_runs_many():
    # A C program that reads two ints and prints their sum. Compile once via
    # prepare_program, then run several inputs against the SAME binary.
    src = C_SUM_LOCAL
    prog = prepare_program("C", src, ".c", VCFG)
    try:
        assert prog.error_result is None
        exe = prog.tmpdir / "prog"
        assert exe.is_file()                     # compiled artifact exists
        mtime = exe.stat().st_mtime_ns
        for a, b in [(2, 3), (10, 20), (-4, 9)]:
            res = prog.run(f"{a} {b}\n")
            assert res.clean, res.error
            assert res.stdout.strip() == str(a + b)
        assert exe.stat().st_mtime_ns == mtime   # never recompiled between runs
    finally:
        prog.close()
    assert prog._tmp is None                      # temp dir cleaned up on close


@pytest.mark.skipif(shutil.which("gcc") is None, reason="gcc required")
def test_program_context_manager_cleans_up():
    with prepare_program("C", C_SUM_LOCAL, ".c", VCFG) as prog:
        tmpdir = prog.tmpdir
        assert tmpdir.is_dir()
        assert prog.run("1 1\n").stdout.strip() == "2"
    assert not tmpdir.exists()                     # __exit__ removed the temp dir


@pytest.mark.skipif(shutil.which("gcc") is None, reason="gcc required")
def test_prepare_program_compile_error_surfaced_on_every_run():
    prog = prepare_program("C", "int main(){ this is not C }", ".c", VCFG)
    try:
        assert prog.error_result is not None
        r1, r2 = prog.run("x"), prog.run("y")
        assert r1.error == "compilation failed" and not r1.clean
        assert r2.error == "compilation failed"
        assert r1 is not r2                         # a fresh copy per run
    finally:
        prog.close()


# A C program summing two ints, defined locally so these tests don't depend on
# conftest's long-typed variant.
C_SUM_LOCAL = '#include <stdio.h>\nint main(){int a,b;scanf("%d %d",&a,&b);printf("%d\\n",a+b);return 0;}\n'


# --- timeout / process-group robustness ------------------------------------
def test_infinite_loop_program_times_out_bounded():
    import time
    cfg = VerificationConfig(run_timeout_seconds=2, compile_timeout_seconds=15)
    src = "import time\nwhile True:\n    time.sleep(1)\n"   # no CPU -> wall-clock timeout
    t = time.time()
    res = run_program("Python", src, ".py", "", cfg)
    assert res.timed_out
    assert time.time() - t < 15


def test_forking_child_does_not_hang_timeout():
    # Parent forks a child that keeps the stdout pipe open and both hang. Without
    # killing the whole process group, communicate() would block ~60s.
    import time
    cfg = VerificationConfig(run_timeout_seconds=2, compile_timeout_seconds=15)
    src = ("import os, time\n"
           "if os.fork() == 0:\n"
           "    time.sleep(60)\n"      # child holds the inherited stdout
           "else:\n"
           "    time.sleep(60)\n")     # parent hangs too
    t = time.time()
    res = run_program("Python", src, ".py", "", cfg)
    assert res.timed_out
    assert time.time() - t < 15, "process-group kill should reap the child quickly"
