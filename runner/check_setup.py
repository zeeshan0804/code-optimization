"""
runner/check_setup.py
=====================
Run this BEFORE run_all.py to confirm your machine has everything needed.

    python runner/check_setup.py

Exits 0 if all checks pass, 1 if anything is missing.
"""
import sys
import subprocess
import shutil


def check(label: str, ok: bool, detail: str = "") -> bool:
    status = "OK  " if ok else "FAIL"
    suffix = f"  ({detail})" if detail else ""
    print(f"  [{status}] {label}{suffix}")
    return ok


def main() -> None:
    print("=== Pre-flight check ===\n")
    passed = []

    # Python version
    vi = sys.version_info
    ver_str = f"{vi.major}.{vi.minor}.{vi.micro}"
    passed.append(check("Python >= 3.10", vi >= (3, 10), ver_str))

    # Java compiler
    javac = shutil.which("javac")
    if javac:
        try:
            out = subprocess.run(["javac", "-version"], capture_output=True, text=True)
            ver = (out.stdout + out.stderr).strip()
        except Exception:
            ver = "found but version check failed"
        passed.append(check("javac in PATH", True, ver))
    else:
        passed.append(check("javac in PATH", False, "install JDK — e.g. brew install openjdk"))

    # Java runtime
    java = shutil.which("java")
    if java:
        try:
            out = subprocess.run(["java", "-version"], capture_output=True, text=True)
            ver = (out.stdout + out.stderr).splitlines()[0] if (out.stdout + out.stderr) else "ok"
        except Exception:
            ver = "found but version check failed"
        passed.append(check("java in PATH", True, ver))
    else:
        passed.append(check("java in PATH", False, "install JDK"))

    import os
    from pathlib import Path
    samples_dir = Path(__file__).parent.parent / "runs"
    has_samples = samples_dir.exists() and any(samples_dir.iterdir())
    passed.append(check("runs/ exists and not empty", has_samples, str(samples_dir)))

    print()
    if all(passed):
        print("All checks passed. You can run:")
        print("  python runner/run_all.py --samples-dir runs/<setup>/programs --language python")
        print("  python runner/run_all.py --samples-dir runs/<setup>/programs --language java")
        print("\nAfter it finishes, send back the runs/<setup>/programs/ folder.")
        sys.exit(0)
    else:
        print("Some checks failed — fix the issues above before running.")
        sys.exit(1)


if __name__ == "__main__":
    main()
