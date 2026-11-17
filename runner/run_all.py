"""
runner/run_all.py
=================
Batch dynamic-metrics runner. Run this on the TARGET machine.

Walks every sample directory under --samples-dir (default runs/),
detects the language, calls the appropriate measure_*.py function,
and writes dynamic_results.json into each directory.

After this completes, run merge_results.py on the main machine to fold
the dynamic results back into the master JSON.

Usage
-----
    # Every setup under runs/
    python runner/run_all.py

    # One setup
    python runner/run_all.py --samples-dir runs/haiku/programs

    # Specific language only
    python runner/run_all.py --language python

    # Control iterations and parallelism
    python runner/run_all.py --iterations 5 --workers 4

    # Re-run even if dynamic_results.json already exists
    python runner/run_all.py --force
"""
import os
import sys
import json
import argparse
import traceback
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# Allow importing from repo root even when run from target machine
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from runner.measure_python import measure_file as measure_python
from runner.measure_java import measure_java_pair


def _find_sample_dirs(base_dir: Path) -> list[Path]:
    """Return every directory under base_dir that holds original.*, optimized.* and inputs.json."""
    if not base_dir.exists():
        return []
    return [
        p.parent for p in sorted(base_dir.rglob("inputs.json"))
        if list(p.parent.glob("original.*")) and list(p.parent.glob("optimized.*"))
    ]


def _detect_language(sample_dir: Path) -> str | None:
    if list(sample_dir.glob("original.py")):
        return "python"
    if list(sample_dir.glob("original.java")):
        return "java"
    return None


def _process_sample(sample_dir: Path, iterations: int, force: bool) -> dict:
    out_file = sample_dir / "dynamic_results.json"

    if out_file.exists() and not force:
        return {"path": str(sample_dir), "status": "skipped", "reason": "already done"}

    language = _detect_language(sample_dir)
    if language is None:
        return {"path": str(sample_dir), "status": "error", "reason": "unknown language"}

    inputs_path = sample_dir / "inputs.json"

    try:
        if language == "python":
            original_path  = next(sample_dir.glob("original.py"))
            optimized_path = next(sample_dir.glob("optimized.py"))

            original_data  = measure_python(str(original_path),  str(inputs_path), iterations)
            optimized_data = measure_python(str(optimized_path), str(inputs_path), iterations)

            # Compute improvement
            improvement = _python_improvement(original_data, optimized_data)
            result = {
                "original":    original_data,
                "optimized":   optimized_data,
                "improvement": improvement,
            }

        else:  # java
            original_path  = next(sample_dir.glob("original.java"))
            optimized_path = next(sample_dir.glob("optimized.java"))

            result = measure_java_pair(
                str(original_path),
                str(optimized_path),
                str(inputs_path),
                iterations,
            )

        with open(out_file, "w") as f:
            json.dump(result, f, indent=2)

        status = "ok"
        # Summarize for the progress line
        try:
            if language == "python":
                orig_lat = result["original"]["aggregate"]["latency_ms"]["mean_across_inputs"]
                opt_lat  = result["optimized"]["aggregate"]["latency_ms"]["mean_across_inputs"]
                pct = round((opt_lat - orig_lat) / orig_lat * 100, 1) if orig_lat else None
                detail = f"latency {orig_lat:.2f}→{opt_lat:.2f} ms ({pct:+.1f}%)" if pct is not None else "done"
            else:
                imp = result.get("improvement") or {}
                pct = imp.get("latency_ms_pct_change")
                detail = f"latency {pct:+.1f}%" if pct is not None else "done"
        except (TypeError, KeyError):
            detail = "done"

        return {"path": str(sample_dir), "status": status, "detail": detail}

    except Exception as exc:
        tb = traceback.format_exc()
        error_result = {"error": str(exc), "traceback": tb}
        with open(sample_dir / "dynamic_error.json", "w") as f:
            json.dump(error_result, f, indent=2)
        return {"path": str(sample_dir), "status": "error", "reason": str(exc)}


def _python_improvement(orig: dict, opt: dict) -> dict | None:
    try:
        orig_lat = orig["aggregate"]["latency_ms"]["mean_across_inputs"]
        opt_lat  = opt["aggregate"]["latency_ms"]["mean_across_inputs"]
        orig_mem = orig["aggregate"]["peak_memory_mb"]["mean_across_inputs"]
        opt_mem  = opt["aggregate"]["peak_memory_mb"]["mean_across_inputs"]

        lat_delta = round(opt_lat - orig_lat, 4) if (orig_lat and opt_lat) else None
        mem_delta = round(opt_mem - orig_mem, 6) if (orig_mem is not None and opt_mem is not None) else None

        return {
            "latency_ms_delta":       lat_delta,
            "latency_ms_pct_change":  round(lat_delta / orig_lat * 100, 2) if lat_delta and orig_lat else None,
            "latency_improved":       lat_delta < 0 if lat_delta is not None else None,
            "peak_memory_mb_delta":   mem_delta,
            "memory_improved":        mem_delta < 0 if mem_delta is not None else None,
        }
    except (TypeError, KeyError):
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch dynamic metric runner for all samples")
    parser.add_argument("--language",  choices=["python", "java"], help="Only run one language")
    parser.add_argument("--iterations", type=int, default=5, help="Runs per input per file (default 5)")
    parser.add_argument("--workers",    type=int, default=1,
                        help="Parallel workers (default 1 — keep at 1 for accurate latency)")
    parser.add_argument("--force",  action="store_true", help="Re-measure even if dynamic_results.json exists")
    parser.add_argument("--samples-dir", default="runs", help="Directory to search for sample folders")
    args = parser.parse_args()

    base_dir = Path(args.samples_dir)
    all_dirs = _find_sample_dirs(base_dir)

    # Filter by language
    if args.language:
        all_dirs = [d for d in all_dirs if _detect_language(d) == args.language]

    if not all_dirs:
        print("[run_all] No sample directories found. Check --samples-dir.")
        sys.exit(0)

    print(f"[run_all] Found {len(all_dirs)} sample directories.")
    print(f"[run_all] Iterations per input: {args.iterations}")
    print(f"[run_all] Workers: {args.workers}")
    if args.workers > 1:
        print("[run_all] WARNING: parallel workers may inflate latency measurements. Use --workers 1 for accuracy.")
    print()

    ok = skipped = errors = 0

    if args.workers == 1:
        for i, sample_dir in enumerate(all_dirs, 1):
            print(f"  [{i:4d}/{len(all_dirs)}] {sample_dir.name} ...", end=" ", flush=True)
            res = _process_sample(sample_dir, args.iterations, args.force)
            if res["status"] == "ok":
                ok += 1
                print(f"OK — {res.get('detail', '')}")
            elif res["status"] == "skipped":
                skipped += 1
                print("skipped")
            else:
                errors += 1
                print(f"ERROR: {res.get('reason', '')}")
    else:
        futures = {}
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for sample_dir in all_dirs:
                f = pool.submit(_process_sample, sample_dir, args.iterations, args.force)
                futures[f] = sample_dir

        done = 0
        for future in as_completed(futures):
            done += 1
            res = future.result()
            sample_dir = futures[future]
            if res["status"] == "ok":
                ok += 1
                print(f"  [{done:4d}/{len(all_dirs)}] {sample_dir.name} OK — {res.get('detail', '')}")
            elif res["status"] == "skipped":
                skipped += 1
            else:
                errors += 1
                print(f"  [{done:4d}/{len(all_dirs)}] {sample_dir.name} ERROR: {res.get('reason', '')}")

    print()
    print(f"[run_all] Done. OK={ok}  Skipped={skipped}  Errors={errors}")
    print(f"[run_all] Next step: on the main machine, run:")
    print(f"  python merge_results.py <results-dir>/raw/<experiment_id>_all_results.json")


if __name__ == "__main__":
    main()
