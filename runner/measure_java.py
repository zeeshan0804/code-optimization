"""
runner/measure_java.py
======================
Measures execution latency for two Java source files (original vs optimized)
using the same stdin-based test inputs — identical approach to measure_python.py.

Requires JDK (javac + java) on PATH. Memory measurement is omitted for Java
since accurate heap tracking requires a JVM agent; latency alone is used.

Usage
-----
    python measure_java.py <original.java> <optimized.java> <inputs.json>
                           [--iterations 5] [--out dynamic_results.json]
"""
import sys
import os
import json
import time
import subprocess
import shutil
import tempfile
import re
import argparse
from pathlib import Path


COMPILE_TIMEOUT = 30   # seconds
RUN_TIMEOUT     = 30   # seconds per single run — O(n³) samples can be slow


def _detect_public_class(java_source: str) -> str | None:
    """Return the public class name so we can invoke it correctly."""
    m = re.search(r"public\s+class\s+(\w+)", java_source)
    return m.group(1) if m else None


def _stdin_str(args: list) -> str:
    return "\n".join(str(a) for a in args)


def _compile(java_source: str, tmpdir: str, class_name: str) -> str | None:
    """
    Write source to tmpdir, compile with javac.
    Returns error string on failure, None on success.
    """
    src_file = os.path.join(tmpdir, f"{class_name}.java")
    Path(src_file).write_text(java_source, encoding="utf-8")

    result = subprocess.run(
        ["javac", src_file],
        capture_output=True, text=True,
        timeout=COMPILE_TIMEOUT, cwd=tmpdir,
    )
    if result.returncode != 0:
        return result.stderr.strip()[:500]
    return None


def _measure_latency(tmpdir: str, class_name: str, stdin_data: str,
                     iterations: int) -> tuple[list[float], list[str]]:
    latencies = []
    errors    = []
    for _ in range(iterations):
        try:
            t0 = time.perf_counter()
            result = subprocess.run(
                ["java", "-Xmx256m", "-cp", tmpdir, class_name],
                input=stdin_data,
                capture_output=True, text=True,
                timeout=RUN_TIMEOUT,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1_000
            if result.returncode == 0:
                latencies.append(round(elapsed_ms, 4))
            else:
                errors.append(result.stderr.strip()[:200])
        except subprocess.TimeoutExpired:
            errors.append(f"timeout (>{RUN_TIMEOUT}s)")
        except Exception as exc:
            errors.append(str(exc))
    return latencies, errors


def _measure_one_file(java_source: str, inputs: list[dict], iterations: int) -> dict:
    class_name = _detect_public_class(java_source)
    if not class_name:
        return {
            "error": "Could not detect public class name.",
            "measurements": [], "aggregate": None,
        }

    tmpdir = tempfile.mkdtemp()
    try:
        compile_error = _compile(java_source, tmpdir, class_name)
        if compile_error:
            return {
                "error": f"Compile error: {compile_error}",
                "measurements": [], "aggregate": None,
            }

        measurements  = []
        all_latencies = []

        for i, inp in enumerate(inputs):
            stdin_data  = _stdin_str(inp.get("args", []))
            description = inp.get("input_description", "")

            print(f"    input {i+1}/{len(inputs)}: {description[:50]}...", end=" ", flush=True)
            latencies, errors = _measure_latency(tmpdir, class_name, stdin_data, iterations)
            print(f"{'OK' if latencies else 'FAILED'}", flush=True)

            entry = {
                "input_description": description,
                "stdin_preview":     stdin_data[:120],
                "successful_runs":   len(latencies),
                "errors":            errors,
                "latency_ms": {
                    "mean": round(sum(latencies) / len(latencies), 4) if latencies else None,
                    "min":  round(min(latencies), 4)                  if latencies else None,
                    "max":  round(max(latencies), 4)                  if latencies else None,
                    "all":  latencies,
                },
                "peak_memory_mb": None,
            }
            measurements.append(entry)
            if latencies:
                all_latencies.append(entry["latency_ms"]["mean"])

        aggregate = None
        if all_latencies:
            aggregate = {
                "latency_ms": {
                    "mean_across_inputs": round(sum(all_latencies) / len(all_latencies), 4),
                    "max_across_inputs":  round(max(all_latencies), 4),
                    "min_across_inputs":  round(min(all_latencies), 4),
                },
                "peak_memory_mb": {
                    "mean_across_inputs": None,
                    "max_across_inputs":  None,
                },
            }

        return {
            "file":         java_source[:80] + "..." if len(java_source) > 80 else java_source,
            "class_name":   class_name,
            "measurements": measurements,
            "aggregate":    aggregate,
        }

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def measure_java_pair(
    original_path: str,
    optimized_path: str,
    inputs_path: str,
    iterations: int = 5,
) -> dict:
    original_code  = Path(original_path).read_text(encoding="utf-8")
    optimized_code = Path(optimized_path).read_text(encoding="utf-8")
    inputs: list[dict] = json.loads(Path(inputs_path).read_text(encoding="utf-8"))

    original_results  = _measure_one_file(original_code,  inputs, iterations)
    optimized_results = _measure_one_file(optimized_code, inputs, iterations)

    improvement = None
    try:
        orig_mean = original_results["aggregate"]["latency_ms"]["mean_across_inputs"]
        opt_mean  = optimized_results["aggregate"]["latency_ms"]["mean_across_inputs"]
        delta     = round(opt_mean - orig_mean, 4)
        improvement = {
            "latency_ms_delta":      delta,
            "latency_ms_pct_change": round(delta / orig_mean * 100, 2) if orig_mean else None,
            "latency_improved":      opt_mean < orig_mean,
        }
    except (TypeError, KeyError):
        pass

    return {
        "original":    original_results,
        "optimized":   optimized_results,
        "improvement": improvement,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("original",     help="original.java path")
    parser.add_argument("optimized",    help="optimized.java path")
    parser.add_argument("inputs",       help="inputs.json path")
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--out",        help="Optional output JSON path")
    args = parser.parse_args()

    result = measure_java_pair(args.original, args.optimized, args.inputs, args.iterations)
    print(json.dumps(result, indent=2))

    if args.out:
        with open(args.out, "w") as f:
            json.dump(result, f, indent=2)
        print(f"Saved to {args.out}", file=sys.stderr)
