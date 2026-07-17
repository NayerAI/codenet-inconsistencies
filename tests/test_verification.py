import shutil

import pytest

from codenet_eval.config import VerificationConfig
from codenet_eval.verification import (
    detect_java_main_class,
    normalise_output,
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
