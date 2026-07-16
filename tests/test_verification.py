import shutil

import pytest

from codenet_eval.config import VerificationConfig
from codenet_eval.verification import (
    detect_java_main_class,
    normalise_output,
    run_program,
    verify_divergence,
)
from conftest import C_DIV, JAVA_DIV, JAVA_SUM, PY_DIV, PY_SUM

VCFG = VerificationConfig(run_timeout_seconds=15, compile_timeout_seconds=40)


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
