"""Generate a small synthetic CodeNet-shaped dataset.

This lets you exercise the full pipeline (sample -> LLM -> verify -> report)
without downloading the ~40 GiB real dataset.  The demo problems contain a mix
of deliberately inconsistent and consistent cross-language implementations.
"""

from __future__ import annotations

from pathlib import Path

from .config import Config
from .utils import get_logger

log = get_logger(__name__)

_CSV_HEADER = (
    "submission_id,problem_id,user_id,date,language,original_language,"
    "filename_ext,status,cpu_time,memory,code_size,accuracy"
)

_EXT = {"C": ".c", "Python": ".py", "Java": ".java"}

# Each problem: id -> {description, io (input,output) or None, sources per lang}.
_PROBLEMS: dict[str, dict] = {
    # Integer vs. true division -> inconsistent (C/Java truncate, Python doesn't).
    "d00001": {
        "desc": "Read integers a and b and print a divided by b.",
        "io": ("7 2\n", "3\n"),
        "sources": {
            "C": '#include <stdio.h>\nint main(){int a,b;scanf("%d %d",&a,&b);printf("%d\\n",a/b);return 0;}\n',
            "Python": "a,b=map(int,input().split())\nprint(a/b)\n",
            "Java": ("import java.util.*;\npublic class Main{public static void main(String[] x){"
                     "Scanner s=new Scanner(System.in);int a=s.nextInt(),b=s.nextInt();"
                     "System.out.println(a/b);}}\n"),
        },
    },
    # 32-bit overflow -> C/Java overflow, Python doesn't; inconsistent on large n.
    "d00002": {
        "desc": "Read an integer n and print n squared.",
        "io": ("100000\n", "10000000000\n"),
        "sources": {
            "C": '#include <stdio.h>\nint main(){int n;scanf("%d",&n);printf("%d\\n",n*n);return 0;}\n',
            "Python": "n=int(input())\nprint(n*n)\n",
            "Java": ("import java.util.*;\npublic class Main{public static void main(String[] x){"
                     "Scanner s=new Scanner(System.in);int n=s.nextInt();"
                     "System.out.println(n*n);}}\n"),
        },
    },
    # Consistent sum using 64-bit everywhere.
    "d00003": {
        "desc": "Read integers a and b and print their sum.",
        "io": ("10 20\n", "30\n"),
        "sources": {
            "C": '#include <stdio.h>\nint main(){long long a,b;scanf("%lld %lld",&a,&b);printf("%lld\\n",a+b);return 0;}\n',
            "Python": "a,b=map(int,input().split())\nprint(a+b)\n",
            "Java": ("import java.util.*;\npublic class Main{public static void main(String[] x){"
                     "Scanner s=new Scanner(System.in);long a=s.nextLong(),b=s.nextLong();"
                     "System.out.println(a+b);}}\n"),
        },
    },
}


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build_demo_dataset(cfg: Config) -> Path:
    root = cfg.dataset_root
    log.info("Writing synthetic demo dataset to %s", root)
    for i, (pid, spec) in enumerate(_PROBLEMS.items()):
        rows = [_CSV_HEADER]
        for j, (lang, source) in enumerate(spec["sources"].items()):
            ext = _EXT[lang]
            sub_id = f"s{i:02d}{j:02d}"
            rows.append(
                f"{sub_id},{pid},u000,2020-01-01,{lang},{lang},{ext},Accepted,10,256,{len(source)},1.0"
            )
            _write(root / "data" / pid / lang / f"{sub_id}{ext}", source)
        _write(root / "metadata" / f"{pid}.csv", "\n".join(rows) + "\n")
        _write(
            root / "problem_descriptions" / f"{pid}.html",
            f"<html><body><p>{spec['desc']}</p></body></html>",
        )
        if spec.get("io"):
            sample_in, sample_out = spec["io"]
            _write(root / "derived" / "input_output" / "data" / pid / "input.txt", sample_in)
            _write(root / "derived" / "input_output" / "data" / pid / "output.txt", sample_out)

    _write(
        root / "metadata" / "problem_list.csv",
        "id,name\n" + "\n".join(f"{pid},{pid}" for pid in _PROBLEMS) + "\n",
    )
    log.info("Demo dataset ready: %d problems in %s", len(_PROBLEMS), root)
    return root
