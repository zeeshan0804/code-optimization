"""
latency_checks.py
=================
Checks on what the latency numbers measure, using the second latency run
in latency_rerun/ (the only run with program output captured).

  1. Java latency split by what happened to java.util.Scanner
  2. Latency medians on all trials vs output-matched trials
  3. Python originals with no function definitions
  4. Size of the generated test inputs

    python latency_checks.py

Output: reports/LATENCY_CHECKS_REPORT.md
"""
import ast
import json
import re
import warnings
from pathlib import Path
from statistics import median

import lizard

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "reports" / "LATENCY_CHECKS_REPORT.md"

ARMS = [
    # (label, programs dir, model key, java file, python file) in latency_rerun/
    ("gpt no-reasoning", "runs/gpt_no_reasoning/programs", "gpt5_4_mini",
     "gpt_no_reasoning_java.json", "gpt_no_reasoning_python.json"),
    ("gpt medium", "runs/gpt_medium/programs", "gpt5_4_mini",
     "gpt_medium_java.json", "gpt_medium_python.json"),
    ("qwen", "runs/qwen/programs", "qwen3_6_27b",
     "qwen_java.json", "qwen_python.json"),
    ("haiku", "runs/haiku/programs", "claude_haiku_4_5",
     "haiku_java.json", "haiku_python.json"),
]
TECHNIQUES = ["zero_shot", "few_shot", "chain_of_thought"]
SCANNER = re.compile(r"\bnew\s+Scanner\b")

# some corpus programs contain invalid escape sequences; ast.parse warns but parses them
warnings.filterwarnings("ignore", category=SyntaxWarning)


def load(name):
    return json.loads((ROOT / "latency_rerun" / name).read_text(encoding="utf-8"))


def med(values):
    return f"{median(values):+.2f} ({len(values)})" if values else "- (0)"


def nloc(code):
    return lizard.analyze_file.analyze_source_code("T.java", code).nloc


def scanner_split(lines):
    lines += [
        "## 1. Java latency by what happened to `Scanner`",
        "",
        "Median latency change in %, with n. A Java run starts a fresh JVM, so loading",
        "`java.util.Scanner` is a large part of a short program's time.",
        "",
        "| Configuration | Technique | Original has no Scanner | Scanner removed | Scanner kept | SLOC change, Scanner removed | SLOC change, other |",
        "|---|---|---|---|---|---|---|",
    ]
    for label, samples, model, java_file, _ in ARMS:
        for t in TECHNIQUES:
            groups = {"none": [], "removed": [], "kept": []}
            sloc = {"removed": [], "other": []}
            for r in load(java_file):
                if r["strategy"] != t or r["latency_ms_pct_change"] is None:
                    continue
                d = ROOT / samples / f"{model}_{t}" / r["sample_id"]
                orig = (d / "original.java").read_text(encoding="utf-8")
                opt = (d / "optimized.java").read_text(encoding="utf-8")
                if not SCANNER.search(orig):
                    g = "none"
                elif SCANNER.search(opt):
                    g = "kept"
                else:
                    g = "removed"
                groups[g].append(r["latency_ms_pct_change"])
                sloc["removed" if g == "removed" else "other"].append(nloc(opt) - nloc(orig))
            lines.append(f"| {label} | {t} | {med(groups['none'])} | {med(groups['removed'])} | "
                         f"{med(groups['kept'])} | {med(sloc['removed'])} | {med(sloc['other'])} |")
    originals = list((ROOT / ARMS[0][1] / f"{ARMS[0][2]}_zero_shot").glob("java_*/original.java"))
    uses = sum(bool(SCANNER.search(p.read_text(encoding="utf-8"))) for p in originals)
    lines += ["", f"{uses} of {len(originals)} Java originals use `Scanner`.", ""]


def equivalence(lines):
    lines += [
        "## 2. Latency on all trials vs output-matched trials",
        "",
        "Median latency change in %, with n. Matched: `outputs_match` is true (inputs with no",
        "output on either side are ignored). Strict: all five inputs produced output and matched.",
        "",
        "| Language | Configuration | Technique | All | Matched | Strict | Median original ms |",
        "|---|---|---|---|---|---|---|",
    ]
    for lang, idx in (("java", 3), ("python", 4)):
        for arm in ARMS:
            recs = load(arm[idx])
            for t in TECHNIQUES:
                rows = [r for r in recs if r["strategy"] == t and r["latency_ms_pct_change"] is not None]
                matched = [r["latency_ms_pct_change"] for r in rows if r["outputs_match"] is True]
                strict = [r["latency_ms_pct_change"] for r in rows
                          if r["outputs_match_per_input"] and all(x is True for x in r["outputs_match_per_input"])]
                base = [r["latency_ms_orig"] for r in rows if r["latency_ms_orig"]]
                lines.append(f"| {lang} | {arm[0]} | {t} | {med([r['latency_ms_pct_change'] for r in rows])} | "
                             f"{med(matched)} | {med(strict)} | {median(base):.1f} |")
    lines.append("")


def python_functions(lines):
    originals = list((ROOT / ARMS[0][1] / f"{ARMS[0][2]}_zero_shot").glob("python_*/original.py"))
    none = sum(
        not any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))))
        for p in originals
    )
    lines += [
        "## 3. Python originals without functions",
        "",
        f"{none} of {len(originals)} Python originals define no function. Cognitive and cyclomatic",
        "complexity are only counted inside functions, so these programs score 0 on both.",
        "",
    ]


def input_sizes(lines):
    sizes, short, total = [], 0, 0
    for p in (ROOT / ARMS[0][1] / f"{ARMS[0][2]}_zero_shot").glob("*/inputs.json"):
        for inp in json.loads(p.read_text(encoding="utf-8")):
            tokens = "\n".join(inp["args"]).split()
            sizes.append(len(tokens))
            total += 1
            if tokens and tokens[0].isdigit() and int(tokens[0]) >= 200 and len(tokens) < int(tokens[0]):
                short += 1
    lines += [
        "## 4. Test input size",
        "",
        f"Median stdin size is {median(sizes):g} tokens per input (max {max(sizes)}).",
        f"{short} of {total} inputs start with a count n >= 200 but contain fewer than n values.",
        "",
    ]


def main():
    lines = ["# Latency checks", "", "Generated by `latency_checks.py` from `latency_rerun/`.", ""]
    scanner_split(lines)
    equivalence(lines)
    python_functions(lines)
    input_sizes(lines)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT.name}")


if __name__ == "__main__":
    main()
