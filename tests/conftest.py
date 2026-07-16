"""Shared pytest fixtures: a tiny synthetic CodeNet tree on disk.

Building the dataset programmatically keeps the tests hermetic (no network, no
multi-GiB download) while exercising the real metadata/submission layout.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make ``src/`` importable without an editable install.
SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from codenet_eval.config import Config  # noqa: E402

CSV_HEADER = (
    "submission_id,problem_id,user_id,date,language,original_language,"
    "filename_ext,status,cpu_time,memory,code_size,accuracy"
)

# p00001: integer- vs float-division divergence (C/Java integer, Python float).
C_DIV = '#include <stdio.h>\nint main(){int a,b;scanf("%d %d",&a,&b);printf("%d\\n",a/b);return 0;}\n'
PY_DIV = "a,b=map(int,input().split())\nprint(a/b)\n"
JAVA_DIV = (
    "import java.util.Scanner;\n"
    "public class Main{public static void main(String[] args){\n"
    "Scanner s=new Scanner(System.in);int a=s.nextInt(),b=s.nextInt();\n"
    "System.out.println(a/b);}}\n"
)

# p00002: consistent sum a+b in all three languages.
C_SUM = '#include <stdio.h>\nint main(){long a,b;scanf("%ld %ld",&a,&b);printf("%ld\\n",a+b);return 0;}\n'
PY_SUM = "a,b=map(int,input().split())\nprint(a+b)\n"
JAVA_SUM = (
    "import java.util.Scanner;\n"
    "public class Main{public static void main(String[] args){\n"
    "Scanner s=new Scanner(System.in);long a=s.nextLong(),b=s.nextLong();\n"
    "System.out.println(a+b);}}\n"
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _problem_csv(problem_id: str, entries: list[tuple[str, str, str]]) -> str:
    # entries: (submission_id, language, filename_ext)
    lines = [CSV_HEADER]
    for sub_id, language, ext in entries:
        lines.append(
            f"{sub_id},{problem_id},u000,2020-01-01,{language},{language},"
            f"{ext},Accepted,10,256,100,1.0"
        )
    return "\n".join(lines) + "\n"


def build_mini_codenet(root: Path) -> None:
    """Create a minimal but structurally faithful CodeNet tree under ``root``."""
    meta = root / "metadata"
    data = root / "data"
    desc = root / "problem_descriptions"
    io_dir = root / "derived" / "input_output" / "data"

    _write(meta / "problem_list.csv", "id,name\np00001,divide\np00002,sum\n")

    # --- p00001 ----------------------------------------------------------------
    _write(
        meta / "p00001.csv",
        _problem_csv(
            "p00001",
            [("s0001", "C", ".c"), ("s0002", "Python", ".py"), ("s0003", "Java", ".java")],
        ),
    )
    _write(data / "p00001" / "C" / "s0001.c", C_DIV)
    _write(data / "p00001" / "Python" / "s0002.py", PY_DIV)
    _write(data / "p00001" / "Java" / "s0003.java", JAVA_DIV)
    _write(desc / "p00001.html", "<html><body><p>Read a and b, print a divided by b.</p></body></html>")
    _write(io_dir / "p00001" / "input.txt", "7 2\n")
    _write(io_dir / "p00001" / "output.txt", "3\n")

    # --- p00002 ----------------------------------------------------------------
    _write(
        meta / "p00002.csv",
        _problem_csv(
            "p00002",
            [("s0004", "C", ".c"), ("s0005", "Python", ".py"), ("s0006", "Java", ".java")],
        ),
    )
    _write(data / "p00002" / "C" / "s0004.c", C_SUM)
    _write(data / "p00002" / "Python" / "s0005.py", PY_SUM)
    _write(data / "p00002" / "Java" / "s0006.java", JAVA_SUM)
    _write(desc / "p00002.html", "<html><body><p>Read a and b, print their sum.</p></body></html>")


@pytest.fixture
def mini_config(tmp_path: Path) -> Config:
    """A Config whose data_dir contains the synthetic CodeNet tree."""
    data_dir = tmp_path / "data"
    root = data_dir / "Project_CodeNet"
    build_mini_codenet(root)
    cfg = Config.from_dict(
        {
            "data_dir": str(data_dir),
            "languages": ["C", "Python", "Java"],
            "sampling": {"percent": 100.0, "seed": 1},
            "verification": {"run_timeout_seconds": 15, "compile_timeout_seconds": 40},
        }
    )
    cfg.validate()
    return cfg
