"""
runner/measure_python.py
========================
Measures execution latency and peak memory of a Python script by running it
as a subprocess with stdin input — the correct approach for competitive
programming code that uses input() rather than function arguments.

Each entry in inputs.json has:
    "args": ["1 1"]        — list of lines to feed via stdin (joined with \\n)

Latency  : wall-clock time around subprocess.run() (perf_counter)
Memory   : peak heap via a tracemalloc wrapper executed inside the child process

Usage
-----
    python measure_python.py <script.py> <inputs.json> [--iterations 5]
    python measure_python.py <script.py> <inputs.json> --out results.json
"""
import sys
import os
import json
import time
import subprocess
import tempfile
import argparse
from pathlib import Path

# ── Memory wrapper ─────────────────────────────────────────────────────────────
# Written to a temp file and executed as a child process.
# Redirects stdin, runs the target script with tracemalloc, prints peak MB.
_MEMORY_WRAPPER_SRC = """\
import sys, io, tracemalloc, runpy, os

script     = sys.argv[1]
stdin_data = sys.argv[2] if len(sys.argv) > 2 else ""
sys.stdin  = io.StringIO(stdin_data)

tracemalloc.start()
try:
    runpy.run_path(script, run_name="__main__")
except SystemExit:
    pass
except Exception:
    pass
_, peak = tracemalloc.get_traced_memory()
tracemalloc.stop()
print(f"PEAK_MB:{peak / 1_048_576:.6f}", flush=True)
"""


def _stdin_str(args: list) -> str:
    """Join args list into a newline-separated stdin string."""
    return "\n".join(str(a) for a in args)


SUBPROCESS_TIMEOUT = 60  # seconds per single run (O(n³) samples can be slow)


def _measure_latency(script_path: str, stdin_data: str, iterations: int) -> tuple[list[float], list[str]]:
    """Run the script N times via subprocess, return (latency_ms_list, errors)."""
    latencies = []
    errors    = []
    for _ in range(iterations):
        try:
            t0     = time.perf_counter()
            result = subprocess.run(
                [sys.executable, script_path],
                input=stdin_data,
                capture_output=True,
                text=True,
                timeout=SUBPROCESS_TIMEOUT,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1_000
            if result.returncode == 0:
                latencies.append(round(elapsed_ms, 4))
            else:
                errors.append(result.stderr.strip()[:200])
        except subprocess.TimeoutExpired:
            errors.append(f"timeout (>{SUBPROCESS_TIMEOUT}s)")
        except Exception as exc:
            errors.append(str(exc))
    return latencies, errors


def _measure_memory(script_path: str, stdin_data: str, wrapper_path: str) -> float | None:
    """Run the script once inside the tracemalloc wrapper, return peak MB."""
    try:
        result = subprocess.run(
            [sys.executable, wrapper_path, script_path, stdin_data],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT * 2,
        )
        for line in (result.stdout + result.stderr).splitlines():
            if line.startswith("PEAK_MB:"):
                return round(float(line.split(":")[1]), 6)
    except Exception:
        pass
    return None


def measure_file(script_path: str, inputs_path: str, iterations: int = 5) -> dict:
    """
    Core measurement function — importable by run_all.py.

    Returns a dict with per-input measurements and cross-input aggregates.
    """
    result = {
        "file":        script_path,
        "inputs_file": inputs_path,
        "iterations":  iterations,
        "mode":        "subprocess_stdin",
        "measurements": [],
        "aggregate":   None,
        "errors":      [],
    }

    # Load inputs
    try:
        inputs: list[dict] = json.loads(Path(inputs_path).read_text())
    except Exception as exc:
        result["errors"].append(f"inputs_load: {exc}")
        return result

    # Write memory wrapper to a temp file
    tmp_wrapper = tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    )
    tmp_wrapper.write(_MEMORY_WRAPPER_SRC)
    tmp_wrapper.close()
    wrapper_path = tmp_wrapper.name

    all_latencies: list[float] = []
    all_memories:  list[float] = []

    try:
        for i, inp in enumerate(inputs):
            stdin_data  = _stdin_str(inp.get("args", []))
            description = inp.get("input_description", "")

            print(f"    input {i+1}/{len(inputs)}: {description[:50]}...", end=" ", flush=True)
            latencies, errors = _measure_latency(script_path, stdin_data, iterations)
            peak_mb           = _measure_memory(script_path, stdin_data, wrapper_path)
            print(f"{'OK' if latencies else 'FAILED'}", flush=True)

            entry = {
                "input_description": description,
                "stdin_input":       stdin_data[:120],
                "successful_runs":   len(latencies),
                "errors":            errors,
                "latency_ms": {
                    "mean": round(sum(latencies) / len(latencies), 4) if latencies else None,
                    "min":  round(min(latencies), 4)                  if latencies else None,
                    "max":  round(max(latencies), 4)                  if latencies else None,
                    "all":  latencies,
                },
                "peak_memory_mb": peak_mb,
            }
            result["measurements"].append(entry)

            if latencies:
                all_latencies.append(entry["latency_ms"]["mean"])
            if peak_mb is not None:
                all_memories.append(peak_mb)

    finally:
        os.unlink(wrapper_path)

    if all_latencies:
        result["aggregate"] = {
            "latency_ms": {
                "mean_across_inputs": round(sum(all_latencies) / len(all_latencies), 4),
                "max_across_inputs":  round(max(all_latencies), 4),
                "min_across_inputs":  round(min(all_latencies), 4),
            },
            "peak_memory_mb": {
                "mean_across_inputs": round(sum(all_memories) / len(all_memories), 6) if all_memories else None,
                "max_across_inputs":  round(max(all_memories), 6)                     if all_memories else None,
            },
        }

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("script_file",  help="Path to Python script")
    parser.add_argument("inputs_file",  help="Path to inputs.json")
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--out",        help="Optional output JSON path")
    args = parser.parse_args()

    data = measure_file(args.script_file, args.inputs_file, args.iterations)
    print(json.dumps(data, indent=2))

    if args.out:
        with open(args.out, "w") as f:
            json.dump(data, f, indent=2)
