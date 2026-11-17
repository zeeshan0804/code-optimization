"""
metrics/static_metrics.py
=========================
Computes static code-quality metrics on a source code string.

Python  → radon (Maintainability Index, Cyclomatic Complexity)
           + cognitive-complexity (Sonar-style Cognitive Complexity)
Java    → lizard (Cyclomatic Complexity, lines of code)
           + derived Maintainability Index via the standard formula
           + Cognitive Complexity via lizard extension (falls back to CC)

All functions return a dict so callers can always do dict["metric_name"].
"""
import math
import ast

# ── Python metrics ─────────────────────────────────────────────────────────────

def _python_maintainability(code: str) -> tuple[float | None, str | None]:
    try:
        from radon.metrics import mi_visit, mi_rank
        score = mi_visit(code, multi=True)
        return round(score, 2), mi_rank(score)
    except Exception:
        return None, None


def _python_cyclomatic(code: str) -> tuple[float | None, int | None]:
    try:
        from radon.complexity import cc_visit, average_complexity
        results = cc_visit(code)
        if not results:
            return 0.0, 0
        return round(average_complexity(results), 2), max(r.complexity for r in results)
    except Exception:
        return None, None


def _python_loc(code: str) -> tuple[int | None, int | None]:
    try:
        from radon.raw import analyze
        raw = analyze(code)
        return raw.loc, raw.sloc
    except Exception:
        return None, None


def _python_cognitive(code: str) -> tuple[int | None, int | None]:
    try:
        from cognitive_complexity.api import get_cognitive_complexity
        tree = ast.parse(code)
        scores = [
            get_cognitive_complexity(node)
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        if not scores:
            return 0, 0
        return sum(scores), max(scores)
    except Exception:
        return None, None


def compute_python_metrics(code: str) -> dict:
    mi_score, mi_rank   = _python_maintainability(code)
    cc_avg,   cc_max    = _python_cyclomatic(code)
    loc,      sloc      = _python_loc(code)
    cog_total, cog_max  = _python_cognitive(code)

    return {
        "maintainability_index":       mi_score,
        "maintainability_rank":        mi_rank,
        "cognitive_complexity_total":  cog_total,
        "cognitive_complexity_max":    cog_max,
        "cyclomatic_complexity_avg":   cc_avg,
        "cyclomatic_complexity_max":   cc_max,
        "lines_of_code":               loc,
        "source_lines_of_code":        sloc,
    }


# ── Java metrics ───────────────────────────────────────────────────────────────

def _mi_from_lizard(nloc: int, cc: float, token_count: int) -> float | None:
    """
    Maintainability Index using the standard formula:
      MI = 171 - 5.2·ln(HV) - 0.23·CC - 16.2·ln(LOC)
    Halstead Volume (HV) is approximated from token count.
    Result is normalised to [0, 100].
    """
    if nloc <= 0 or token_count <= 0:
        return None
    hv = token_count * math.log2(max(token_count, 2))
    mi_raw = 171 - 5.2 * math.log(hv) - 0.23 * cc - 16.2 * math.log(nloc)
    return round(max(0.0, min(100.0, (mi_raw * 100) / 171)), 2)


def _mi_rank(mi: float | None) -> str | None:
    if mi is None:
        return None
    if mi >= 85:
        return "A"
    if mi >= 65:
        return "B"
    return "C"


def compute_java_metrics(code: str) -> dict:
    try:
        import lizard
        result    = lizard.analyze_file.analyze_source_code("Temp.java", code)
        functions = result.function_list

        nloc        = result.nloc
        token_count = sum(f.token_count for f in functions) if functions else 0

        if functions:
            cc_avg = sum(f.cyclomatic_complexity for f in functions) / len(functions)
            cc_max = max(f.cyclomatic_complexity for f in functions)

            # Cognitive complexity: use lizard attribute if available, else fall back to CC.
            cog_values = [
                getattr(f, "cognitive_complexity", f.cyclomatic_complexity)
                for f in functions
            ]
            cog_total = sum(cog_values)
            cog_max   = max(cog_values)
        else:
            cc_avg = cc_max = cog_total = cog_max = 0

        mi_score = _mi_from_lizard(nloc, cc_avg, token_count)

        return {
            "maintainability_index":      mi_score,
            "maintainability_rank":       _mi_rank(mi_score),
            "cognitive_complexity_total": round(cog_total, 2),
            "cognitive_complexity_max":   round(cog_max, 2),
            "cyclomatic_complexity_avg":  round(cc_avg, 2),
            "cyclomatic_complexity_max":  cc_max,
            "lines_of_code":              nloc,
            "source_lines_of_code":       nloc,
        }

    except Exception as exc:
        return {
            "maintainability_index":      None,
            "maintainability_rank":       None,
            "cognitive_complexity_total": None,
            "cognitive_complexity_max":   None,
            "cyclomatic_complexity_avg":  None,
            "cyclomatic_complexity_max":  None,
            "lines_of_code":              None,
            "source_lines_of_code":       None,
            "error":                      str(exc),
        }


# ── Public dispatcher ──────────────────────────────────────────────────────────

def compute_metrics(code: str, language: str) -> dict:
    if language == "python":
        return compute_python_metrics(code)
    if language == "java":
        return compute_java_metrics(code)
    raise ValueError(f"Unsupported language: {language!r}")
