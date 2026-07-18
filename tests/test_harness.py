"""Tests for the deterministic function->program wrapper generator."""

import shutil

import pytest

from codenet_eval.config import VerificationConfig
from codenet_eval.harness import (
    UnsupportedSignature,
    build_wrapper,
    entry_name,
    parse_signature,
)
from codenet_eval import verification as V

VCFG = VerificationConfig(run_timeout_seconds=20, compile_timeout_seconds=90)

# A HumanEval-X-style problem: add two integers.
PY = ("from typing import List\n\ndef add(a: int, b: int) -> int:\n    return a + b\n")
PY_DECL = "def add(a: int, b: int) -> int:"
CPP = ("#include <bits/stdc++.h>\nusing namespace std;\nint add(int a, int b){ return a + b; }\n")
CPP_DECL = "int add(int a, int b)"
JAVA = ("import java.util.*;\nclass Solution {\n    public int add(int a, int b) { return a + b; }\n}\n")
JAVA_DECL = "public int add(int a, int b)"
GO = ('func Add(a int, b int) int { return a + b }\n')  # HumanEval-X Go: no package line
GO_DECL = "func Add(a int, b int) int"


def test_signature_parsing():
    s = parse_signature("C++", "bool has_close_elements(vector<float> numbers, float threshold)")
    assert s.entry == "has_close_elements"
    assert s.ret.kind == "bool"
    assert s.args[0].kind == "list" and s.args[0].elem.kind == "float"
    assert s.args[0].native == "vector<float>"

    j = parse_signature("Java", "public boolean hasCloseElements(List<Double> numbers, double threshold)")
    assert j.entry == "hasCloseElements" and j.args[0].native == "List<Double>"

    g = parse_signature("Go", "func HasCloseElements(numbers []float64, threshold float64) bool")
    assert g.entry == "HasCloseElements" and g.args[0].native == "[]float64"


def test_unsupported_types_raise():
    with pytest.raises(UnsupportedSignature):
        parse_signature("Java", "public int f(Optional<Integer> x)")
    with pytest.raises(UnsupportedSignature):
        parse_signature("Go", "func F(x interface{}) int")


def test_python_wrapper_runs():
    w = build_wrapper("Python", PY, PY_DECL)
    res = V.run_program("Python", w, ".py", "3\n4\n", VCFG)
    assert res.clean, res.error
    assert res.stdout.strip() == "7"


@pytest.mark.skipif(shutil.which("node") is None, reason="node required")
def test_js_wrapper_runs():
    js = "const add = (a, b) => { return a + b; }\n"
    w = build_wrapper("JavaScript", js, "")
    res = V.run_program("JavaScript", w, ".js", "3\n4\n", VCFG)
    assert res.clean, res.error
    assert res.stdout.strip() == "7"


@pytest.mark.skipif(shutil.which("gcc") is None, reason="g++ required")
def test_cpp_wrapper_runs():
    w = build_wrapper("C++", CPP, CPP_DECL)
    res = V.run_program("C++", w, ".cpp", "3\n4\n", VCFG)
    assert res.clean, res.error
    assert res.stdout.strip() == "7"


@pytest.mark.skipif(shutil.which("javac") is None, reason="javac required")
def test_java_wrapper_runs():
    w = build_wrapper("Java", JAVA, JAVA_DECL)
    res = V.run_program("Java", w, ".java", "3\n4\n", VCFG)
    assert res.clean, res.error
    assert res.stdout.strip() == "7"


@pytest.mark.skipif(shutil.which("go") is None, reason="go required")
def test_go_wrapper_runs():
    w = build_wrapper("Go", GO, GO_DECL)
    res = V.run_program("Go", w, ".go", "3\n4\n", VCFG)
    assert res.clean, res.error
    assert res.stdout.strip() == "7"


@pytest.mark.skipif(shutil.which("gcc") is None, reason="g++ required")
def test_list_and_float_canonicalisation():
    # sum a list of floats; check canonical output (3.0 -> "3", integer-valued).
    cpp = ("#include <bits/stdc++.h>\nusing namespace std;\n"
           "double total(vector<double> xs){ double s=0; for(double x: xs) s+=x; return s; }\n")
    w = build_wrapper("C++", cpp, "double total(vector<double> xs)")
    res = V.run_program("C++", w, ".cpp", "[1.5, 1.5]\n", VCFG)
    assert res.clean, res.error
    assert res.stdout.strip() == "3"  # 3.0 canonicalised to "3"
