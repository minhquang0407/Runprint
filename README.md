# Runprint (QR)

**Reproducible Research Execution Wrapper**

> *"Run anything. Capture everything needed to reproduce it."*

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)

Runprint (`qr`) is a lightweight, framework-agnostic, local-first execution wrapper for AI and scientific research experiments. It sits outside your experiment code, runs any command, and automatically captures code state (including uncommitted Git diffs), runtime environment, hardware configuration, execution logs, and structured metrics into an auditable, reproducible run record.

---

## Key Features

- **Framework-Agnostic**: Wrap any arbitrary process (Python, Bash, C++, simulation binaries) without modifying your training loops.
- **Local-First**: All manifests, metadata, and logs are stored in `.qr/`. Zero accounts, zero cloud dependencies, zero external servers.
- **Complete Git & Untracked File Snapshotting**: Never lose an experiment to uncommitted edits or newly created files. `qr` captures `git.diff` including untracked source files cleanly without dirtying your Git index.
- **1-Click Reproduction (`qr rerun --reproduce`)**: Automatically recreate past experiments in an isolated temporary Git worktree with an isolated reconstructed virtual environment.
- **Environment Drift & Management (`qr env`)**: Inspect package drift between runs and active Python (`qr env diff`), cache virtualenvs, and reclaim disk space (`qr env list`, `qr env clean`).
- **Secure ML Environment Capture**: Records essential ML determinism flags (`CUDA_VISIBLE_DEVICES`, `OMP_NUM_THREADS`, etc.) via a strict security allowlist that never leaks secrets.
- **0–100 Restorability Scoring**: Granular 3-pillar audit scoring (Source Code 35 pts, Environment 35 pts, Data & Inputs 30 pts) with actionable reproducibility checklists in `qr show`.
- **Live Tee Logging**: Streams `stdout` and `stderr` directly to your terminal while persisting clean log files to disk.
- **Atomic & Crash-Safe**: Runs are protected against `Ctrl+C` and crashes with pre-run manifests, atomic writes, and diagnostic auto-repair (`qr doctor`).
- **Tiny Python SDK & In-Code Activation**: In-code runner `qr.activate()` for IDE buttons, hyperparameter loops with `with qr.run()`, semantic logging (`qr.log`), in-code parameters (`qr.params`), block timing (`qr.timer`), artifact registration (`qr.artifact`), dataset tracking (`qr.input_dataset`), and notes (`qr.note`).


---

## Installation

### From PyPI (Recommended)
```bash
pip install runprint
```
*(Both `qr` and `runprint` commands will be available globally in your terminal. You can also invoke them with `python -m qr` or `python -m runprint`).*

### From GitHub
```bash
pip install git+https://github.com/minhquang0407/Runprint.git
```

### Local Development
```bash
git clone https://github.com/minhquang0407/Runprint.git
cd Runprint
pip install -e .
```

---

## CLI Usage Guide

### 1. Initialize a Project (`qr init`)
Initialize a repository for experiment tracking:
```bash
qr init
```
This creates the `.qr/` directory, project configuration (`project.json`), and the local runs store.

---

### 2. Execute an Experiment (`qr run`)
Prefix any command with `qr run --`:

```bash
# Basic run
qr run -- python train.py --config configs/baseline.yaml

# Run with tags
qr run --tag baseline --tag vision -- python train.py --epochs 50

# Run a Bash script or external binary
qr run --tag simulation -- bash scripts/run_eval.sh
```

**Automatic Dirty Tree Detection:**
If your repository has uncommitted changes, `qr` automatically captures the patch into `git.diff`:
```text
[!] Working tree contains uncommitted changes. Snapshotting diff:
  - train.py
  - model.py
  - configs/baseline.yaml

Run QR-20260914-A7F2 [baseline, vision] started (09:12:04)
... training output ...
Run completed: exit=0, duration=14.2s, ended=2026-09-14 09:12:18 (QR-20260914-A7F2)
```

---

### 3. List Recorded Experiments (`qr list`)
View your experiment history:

```bash
# List recent runs
qr list

# Limit results
qr list --limit 10

# Filter by tag
qr list --tag baseline
```

**Example Output:**
```text
                              QR Experiment Runs                               
┌──────────────────┬───────────┬──────────────────┬───────────┬──────────┬─────────┬───────┬─────────────────────┬─────────────────────┐
│ Run ID           │ Status    │ Tags             │ Command   │ Duration │ Commit  │ Dirty │ Started             │ Ended               │
├──────────────────┼───────────┼──────────────────┼───────────┼──────────┼─────────┼───────┼─────────────────────┼─────────────────────┤
│ QR-20260914-A7F2 │ completed │ baseline, vision │ python... │    14.2s │ 7cc8be0 │  yes  │ 2026-09-14 09:12:04 │ 2026-09-14 09:12:18 │
└──────────────────┴───────────┴──────────────────┴───────────┴──────────┴─────────┴───────┴─────────────────────┴─────────────────────┘
```

---

### 4. Inspect Run Provenance & Restorability (`qr show`)
Inspect full source code state, hardware, runtime, registered artifacts, metrics, and the **Restorability Audit Checklist**:

```bash
qr show QR-20260914-A7F2
```

**Restorability Scoring Rubric (0 – 100):**
- **Source Code (Max 35 pts)**: Valid Git commit (+10), clean tree or complete `git.diff` patch (+15), all untracked source files captured (+10).
- **Environment (Max 35 pts)**: Pinned Python version (+10), package lockfile recorded (+15), zero editable/local dependencies (+10).
- **Data & Inputs (Max 30 pts)**: Pure compute with no external data (+30), OR all datasets declared (+10) and 100% verified with SHA-256 fingerprints (+20).

**Score Bands:**
- `90 - 100`: `HIGHLY_RESTORABLE` (Green)
- `70 - 89`: `PARTIALLY_RESTORABLE` (Yellow)
- `< 70`: `LOW_RESTORABILITY` (Red)

The command prints a transparent **Restorability Audit Checklist** and targeted recommendations to help you make your experiment 100% reproducible.

---

### 5. Inspect & Manage Environments (`qr env`)
Inspect package drift and manage isolated virtual environments:

```bash
# Compare recorded packages against active Python environment
qr env diff QR-20260914-A7F2

# List all cached virtual environments in .qr/envs/
qr env list

# Clean cached virtual environments to reclaim disk space
qr env clean --run-id QR-20260914-A7F2
qr env clean --all
```

`qr env diff` identifies:
- **Version Drift**: Packages installed in both environments with differing versions.
- **Missing Packages**: Packages recorded in the experiment that are absent from your current environment.
- **Extra Packages**: Packages present currently that were not installed during the original run.
- **Python Version**: Major.minor Python compatibility match.

---

### 6. 1-Click Reproduction & Rerun (`qr rerun`)
Rerun a previous experiment with automated preflight reproducibility validation and virtual environment restoration:

```bash
# 1-Click full reproduction (isolated git worktree + isolated virtualenv)
qr rerun QR-20260914-A7F2 --reproduce

# Restore exact virtual environment from recorded lockfile into .qr/envs/
qr rerun QR-20260914-A7F2 --restore-env

# Isolated rerun in a dedicated temporary Git worktree
qr rerun QR-20260914-A7F2 --isolated

# Bypass dataset fingerprint mismatch if dataset was updated intentionally
qr rerun QR-20260914-A7F2 --allow-dataset-mismatch

# Bypass package version drift or missing packages
qr rerun QR-20260914-A7F2 --allow-env-mismatch
```

**Preflight Checks Performed:**
- `[OK] Git Commit`: Verifies commit exists in local git history.
- `[OK] Dirty Patch`: Verifies `git.diff` applies cleanly.
- `[OK] Environment Integrity / Restoration`: Verifies package lockfile readiness for automated venv reconstruction (or compares against current environment).
- `[OK] Dataset Fingerprint`: Re-hashes input datasets and verifies integrity.
- `[!] Hardware/OS Difference`: Warns if rerun is performed on different GPUs or platforms.

The rerun creates a **new run** linked to the parent (`Lineage: Parent=QR-20260914-A7F2`), preserving full historical lineage.


---

### 7. Compare Two Experiments (`qr diff`)
Compare configuration, source code, duration, and metrics between two runs:

```bash
qr diff QR-20260914-A7F2 QR-20260914-B8C1
```

**Comparison Matrix:**
- Compares executed command and argument changes.
- Compares Git commits and dirty patches.
- Compares execution timing (`Started`, `Ended`, `Duration`) and status.
- Computes numerical metric deltas (e.g. `accuracy: 0.7550` vs `0.8800 (+0.1250)`).

---

### 8. Diagnose & Auto-Repair (`qr doctor`)
Check repository health, detect runs interrupted by power loss or crashes, and sync caches:

```bash
# Run integrity diagnostics
qr doctor

# Auto-repair orphaned runs, backfill restorability scores, and rebuild SQLite index
qr doctor --fix
```

---

## Tiny Python SDK

The Python SDK is framework-agnostic and supports two execution models:
1. **CLI Wrapper**: Run your script via `qr run -- python train.py`.
2. **In-Code Activation & Context Managers**: Run directly via your IDE's **Run / Compile / Debug** button or standard `python train.py`, with zero CLI overhead.

---

### 1. Semantic Logging & Provenance Tracking

```python
import qr

# 1. Declare input dataset (auto-calculates SHA256 fingerprint if omitted)
qr.input_dataset(
    name="breast_cancer",
    uri="data/cancer_dataset.csv",
    version="v1.0"
)

# 2. Log in-code hyperparameters directly (saved to manifest inputs)
qr.params({
    "model_type": "random_forest",
    "n_estimators": 100,
    "max_depth": 6,
    "learning_rate": 0.05,
})

# 3. Measure pure training duration (logged to metrics.jsonl)
with qr.timer("training_duration_seconds"):
    model.fit(X_train, y_train)

# 4. Log structured metrics per step or epoch
qr.log({
    "accuracy": 0.9561,
    "precision": 0.9583,
    "f1": 0.9583,
})

# 5. Register output artifacts (checksum & size tracked, file not duplicated)
qr.artifact("artifacts/model.pkl", kind="model", metadata={"accuracy": 0.9561})

# 6. Add human or script annotations
qr.note("Trained Random Forest baseline with 5-fold cross-validation")
```

---

### 2. In-Code Activation (`qr.activate()`)

Want to run your code by clicking the **Run** button in VS Code / PyCharm instead of using terminal commands? Simply call `qr.activate()` at the end of your training function or right before `return`:

```python
def train():
    # ... prepare data & train model ...
    qr.input_dataset("dataset", "data/train.csv")
    qr.params({"max_depth": 6, "n_estimators": 100})
    qr.log({"accuracy": acc, "f1": f1})
    qr.artifact("model.pkl", kind="model")

    # Activate & save the experiment run right before return
    qr.activate(tag="random_forest")

    return model

if __name__ == "__main__":
    train()
```

When `qr.activate()` is called:
- Automatically snapshots Git commit, branch, and uncommitted dirty diffs.
- Records hardware (CPU, GPU, RAM) and runtime packages (`pip freeze`).
- Flushes all buffered metrics, artifacts, dataset declarations, and console logs (`stdout`/`stderr`).
- Updates `.qr/index.sqlite` and outputs the completion banner.
- **CLI Compatible:** If you execute the same script later with `qr run -- python train.py`, `qr.activate()` automatically detects the CLI session and seamlessly acts as a no-op without creating duplicate runs.

---

### 3. GridSearch & Multi-Run Context Manager (`with qr.run()`)

For hyperparameter search (GridSearch, Optuna, K-Fold cross-validation), use the `with qr.run()` context manager to automatically isolate each trial into its own reproducible run:

```python
import qr
from sklearn.ensemble import RandomForestClassifier

param_grid = [
    {"max_depth": 3, "n_estimators": 50},
    {"max_depth": 3, "n_estimators": 100},
    {"max_depth": 6, "n_estimators": 50},
    {"max_depth": 6, "n_estimators": 100},
]

# Parent Run: Represents the full optimization session
with qr.run(tag="grid_search_parent", params={"trials": len(param_grid)}) as session:
    qr.input_dataset("cancer_data", "data/cancer_dataset.csv")

    # Child Runs: Each trial is an independent run linked to the parent
    for i, params in enumerate(param_grid, start=1):
        with qr.run(tag="trial", params=params) as trial:
            model = RandomForestClassifier(**params)
            model.fit(X_train, y_train)

            score = model.score(X_test, y_test)
            qr.log({"trial": i, "accuracy": score})
            qr.artifact(f"model_{i}.pkl", kind="model")
        # Exiting with-block automatically finalizes that trial run!
```

#### Compare Trials Side-by-Side (`qr diff`)
Because each trial in the GridSearch is an independent run linked via `Lineage: Parent=<session_id>`, you can directly compare any two configurations:

```bash
qr diff QR-20260914-5BBC QR-20260914-4208
```

```text
┌───────────────────────┬──────────────────────────┬──────────────────────────┐
│ Property              │ QR-20260914-5BBC         │ QR-20260914-4208         │
├───────────────────────┼──────────────────────────┼──────────────────────────┤
│ Status                │ completed (exit=0)       │ completed (exit=0)       │
│ Duration              │ 0.13s                    │ 0.16s                    │
│ Param: --max_depth    │ 3                        │ 3 (0)                    │
│ Param: --n_estimators │ 50                       │ 100 (+50)                │
│ Metric: accuracy      │ 0.9474                   │ 0.9561 (+0.0087)         │
│ Metric: f1            │ 0.9583                   │ 0.9655 (+0.0072)         │
└───────────────────────┴──────────────────────────┴──────────────────────────┘
```

---

## Local Storage Layout

All data is self-contained inside your repository:

```text
my-project/
├── train.py
├── configs/
├── .git/
└── .qr/
    ├── project.json            # Project identification and configuration
    ├── index.sqlite            # Fast local cache for qr list (rebuildable)
    ├── worktrees/              # Temporary checkouts for isolated reruns
    └── runs/
        └── QR-20260914-A7F2/
            ├── manifest.json   # Machine-readable provenance manifest (Schema v0.1)
            ├── git.diff        # Uncommitted diff patch (binary supported)
            ├── stdout.log      # Complete stdout stream
            ├── stderr.log      # Complete stderr stream
            ├── metrics.jsonl   # Structured metrics stream
            ├── artifacts.json  # Registered artifact references and checksums
            └── environment/
                └── pip-freeze.txt  # Snapshot of installed packages
```

---

## Testing

Run the automated test suite:

```bash
pytest tests/ -v
```

---

## License

Licensed under the [Apache License, Version 2.0](LICENSE).
