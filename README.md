# LLM code optimisation study

This repo has the code, data and results for our study on LLM-based code optimisation. We wanted to know whether the prompting technique and the choice of model make a real difference to the code you get back.

We took 300 accepted Codeforces solutions from CodeComplex (150 Java, 150 Python, 25 for each complexity class) and asked four model setups to optimise every one of them with zero-shot, few-shot and chain-of-thought prompts. That's 3,600 trials in total. For each one we compared the optimised program with the original on Maintainability Index, Cognitive Complexity, average Cyclomatic Complexity, SLOC and runtime latency (5 inputs, 5 runs each).

| Setup | Model | Reasoning | Run ID |
|---|---|---|---|
| gpt no-reasoning | `gpt-5.4-mini` (OpenAI) | off | `exp_20260617_074246` |
| gpt medium | `gpt-5.4-mini` (OpenAI) | `reasoning_effort="medium"` | `exp_20260708_055801` |
| qwen | `qwen/qwen3.6-27b` (OpenRouter) | always on | `exp_20260628_134335` |
| haiku | `anthropic/claude-haiku-4.5` (OpenRouter) | off | `exp_20260801_182915` |

All four had a 16,384-token output limit. gpt no-reasoning, qwen and haiku ran at temperature 0.2. For gpt medium we didn't send a temperature, so it used the API default.

## What's in here

```
dataset/                  the CodeComplex corpus, the 300 samples we picked and their test inputs
runs/                     one folder per setup: gpt_no_reasoning, gpt_medium, qwen, haiku
latency_rerun/            the second latency run, with program output saved (see below)
reports/                  all the reports, the statistics tables and the dataset figures
paper/                    LaTeX source and figures
```

Each folder in `runs/` looks the same:

```
generations.json          900 rows: prompt, response, code and static metrics for each trial
summary.json              averages per model, technique and language
latency_java.json         Java latency and compile results
latency_python.json       Python latency (haiku only, see below)
programs/<model>_<technique>/<sample_id>/
    original.*, optimized.*, inputs.json
    dynamic_results.json  Python latency per sample (the three other setups)
```

The scripts are all in the root:

```
sample_dataset.py                    picks the 300 samples
preprocess.py, input_generator.py    makes 5 test inputs per sample with gpt-4o-mini
prompts.py                           prompt templates
config.py, models.py                 model settings and API client
experiment.py, analysis.py           generation, static metrics and summary.json
metrics/static_metrics.py            static metrics
runner/                              latency measurement (we ran this on a separate Windows machine)
merge_results.py                     merges per-sample latency into a result file
reconstruct_results.py               rebuilt the gpt no-reasoning result file (see below)
test_providers.py                    checks whether OpenRouter providers can turn off Qwen's reasoning

statistical_tests.py                 Friedman and Holm-corrected Wilcoxon tests
latency_checks.py                    breakdown of the latency results
build_*_report.py                    Java, Python and combined reports (.md, .pdf, .xlsx)
generate_report.py, visualize_*.py   dataset report and figures
```

## Rerunning things

You'll need Python 3.13. Nothing here calls an API, so you don't need any keys.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python statistical_tests.py
python build_combined_report.py
python build_excel_report.py
python latency_checks.py
cd paper && python make_figures.py
```

Everything is written to `reports/`. The reports in the repo came from exactly these commands. If you run them again, the PDF and XLSX files will only differ in their timestamps.

To measure latency yourself you need Python 3 and a JDK:

```bash
python runner/check_setup.py
cp -r runs/haiku/programs /tmp/haiku_programs
python runner/run_all.py --samples-dir /tmp/haiku_programs --iterations 5
```

`run_all.py` writes a `dynamic_results.json` into each sample folder, which is why you should run it on a copy: otherwise it writes into the published data. It skips any folder that already has a `dynamic_results.json` unless you pass `--force`, and the gpt and qwen Python folders already have one. Your timings won't match ours in milliseconds, so compare the percentage changes.

You can also rerun generation. Copy `.env.example` to `.env`, fill in your keys and run `python experiment.py --models <key>`. By default a new run goes to `runs/new/`, with its result files in `raw/` and `summary/` and the programs in `programs/<experiment_id>/`. It also writes a small `run.py` or `run.sh` next to each program, which we removed from the published runs because `run_all.py` doesn't need them. Don't expect the same outputs as ours, though. Hosted models change over time, which is why we kept every generated program. The same goes for `preprocess.py`: running it again gives you new test inputs.

## Things worth knowing about the data

### generations.json

Each row has the original and optimised code with their static metrics, the difference between them (`static_metrics_improvement`), the prompt we sent, the token counts and raw response (`llm_metadata`), and an `errors` list. Rows with errors are left out of the static analysis. The `saved_paths` field records where the files were written during the run, before we reorganised the folders, so those paths no longer exist.

### Why haiku's Python latency is in a different place

For gpt and qwen we have the raw runner output for every Python sample (`dynamic_results.json`, including peak memory). For haiku we only have the merged table, `runs/haiku/latency_python.json`, which has the same columns as the Java files and no memory.

### How latency is computed

For each sample we average 5 runs per input, then average over the 5 inputs. Every run starts a new process, so the time includes starting the Python interpreter or the JVM. The change is (optimised - original) / original x 100, and a trial only counts if both versions produced a time.

### The second latency run

`latency_rerun/` is a later measurement of the same programs, with one Java and one Python file per setup, and this time we also saved what each program printed. `outputs_match_per_input` is true, false or null for each input. It's null when one side printed nothing. Otherwise the outputs are compared after trimming whitespace at the ends of the output and of each line. `outputs_match` skips the nulls and is true only if every remaining input matches.

The reports are built from the first run (the latency files in `runs/`). On Java the two runs agree closely. On Python the gap between them is about as big as the effects we're measuring, so take the Python latency numbers with a grain of salt.

### Not every optimised program does the same thing

In 3,039 trials both versions printed something, and in 19.9% of those the optimised program's output differs from the original's. These trials are still in the latency medians. Keeping only matching trials changes some Java numbers a lot. For example, gpt no-reasoning with chain-of-thought goes from -32.2% to -16.4% if all five inputs have to match.

### Where the Java speed-ups come from

Mostly from one change. 95 of the 150 Java originals read their input with `java.util.Scanner`, and with a fresh JVM for every run, loading it takes up a good share of a short program's time. When gpt or qwen replace it with a faster reader, the median latency drops by 33-39%. When `Scanner` stays, or was never there, the change is between 0 and -4% (one cell of 3 programs is at -8%). Haiku hardly ever makes the swap.

That accounts for most of the differences between models and techniques on Java. gpt no-reasoning, for instance, swaps the reader in 71 of 89 programs with zero-shot but only 27 of 89 with few-shot. The new reader code is also where most of the extra Java SLOC comes from. Run `latency_checks.py` for the full tables (they end up in `reports/LATENCY_CHECKS_REPORT.md`).

### Known issues

- A resume bug overwrote the gpt no-reasoning result file during the run. We rebuilt it from the saved programs with `reconstruct_results.py`, but its token counts and raw responses are lost.
- `runs/gpt_no_reasoning/latency_java.json` still has 450 old Python rows in it. Every script filters on `language == "java"`, so they're ignored.
- Four Java originals don't compile: `java_cubic_004`, `java_linear_013`, `java_logn_014` and `java_nlogn_008`. About 10 Python originals fail on their generated inputs.
- 51 of the 3,600 outputs are just the original with whitespace or comments changed. They're listed in `latency_rerun/noop_optimizations.csv`.
- The test inputs are small, no more than about 50 values per line, so start-up time is a big part of the measured latency.

### Metric caveats

- Python complexity is only counted inside functions. Many of the programs don't define any, so they score 0.
- `lizard` doesn't compute cognitive complexity, so for Java we use the sum of cyclomatic complexity over all methods instead.
- Java MI uses the usual formula, but the Halstead volume is estimated from the token count.
- Python peak memory comes from `tracemalloc`. We didn't measure memory for Java, or for haiku on Python.

## Data source

The programs come from CodeComplex (`codeparrot/codecomplex` on Hugging Face), a collection of Codeforces submissions. If you reuse them, please cite CodeComplex.
