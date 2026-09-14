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
- **Dirty Git Snapshotting**: Never lose an experiment to uncommitted changes. `qr` captures `git.diff` alongside the commit hash.
- **Reproducibility Contract**: Transparent categorization of run reproducibility (`TRACEABLE`, `RESTORABLE`, `REPRODUCIBLE`).
- **Live Tee Logging**: Streams `stdout` and `stderr` directly to your terminal while persisting clean log files to disk.
- **Atomic & Crash-Safe**: Runs are protected against `Ctrl+C` and crashes with pre-run manifests and atomic writes.
- **Isolated Worktree Rerun**: Rerun past experiments in clean, dedicated Git worktrees without disturbing your active workspace.
- **Integrity Doctor & Run Diff**: Built-in health diagnostics (`qr doctor`) and side-by-side run comparisons (`qr diff`).
- **In-Code Activation & Context Manager**: Run scripts directly via IDE Run/Compile buttons using `qr.activate()`, or run hyperparameter search loops with `with qr.run()`.
- **Tiny Python SDK**: Semantic logging (`qr.log`), in-code parameters (`qr.params`), block timing (`qr.timer`), artifact registration (`qr.artifact`), dataset tracking (`qr.input_dataset`), and notes (`qr.note`).

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

### 4. Inspect Run Provenance (`qr show`)
Inspect full source code state, hardware, runtime, registered artifacts, and metrics:

```bash
qr show QR-20260914-A7F2
```

**Detailed Report:**
- **Status & Timing**: Outcome, exit code, Started timestamp, Ended timestamp, and formatted duration.
- **Tags**: Assigned experiment tags.
- **Source**: Commit hash, branch, and uncommitted diff indicator.
- **Runtime**: OS platform, Python version, package lock (`environment/pip-freeze.txt`).
- **Hardware**: CPU cores, total RAM, NVIDIA GPU model and driver version.
- **Inputs**: Declared dataset URIs and cryptographic SHA256 fingerprints.
- **Metrics**: Summary of metrics logged via the SDK.
- **Artifacts**: Model checkpoints and output files registered with sizes and checksums.
- **Reproducibility Contract**: Traceability, restorability score, and parent run lineage.

---

### 5. Re-execute an Experiment (`qr rerun`)
Rerun a previous experiment with automated preflight reproducibility validation:

```bash
# Basic rerun (in current working directory)
qr rerun QR-20260914-A7F2

# Isolated rerun in a dedicated temporary Git worktree (Recommended)
qr rerun QR-20260914-A7F2 --isolated

# Bypass dataset fingerprint mismatch if dataset was updated intentionally
qr rerun QR-20260914-A7F2 --allow-dataset-mismatch
```

**Preflight Checks Performed:**
- `[OK] Git Commit`: Verifies commit exists in local git history.
- `[OK] Dirty Patch`: Verifies `git.diff` applies cleanly.
- `[OK] Environment Lock`: Verifies package lock exists.
- `[OK] Dataset Fingerprint`: Re-hashes input datasets and verifies integrity.
- `[!] Hardware/OS Difference`: Warns if rerun is performed on different GPUs or platforms.

The rerun creates a **new run** linked to the parent (`Lineage: Parent=QR-20260914-A7F2`), preserving full historical lineage.

---

### 6. Compare Two Experiments (`qr diff`)
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

### 7. Diagnose & Auto-Repair (`qr doctor`)
Check repository health, detect runs interrupted by power loss or crashes, and sync caches:

```bash
# Run integrity diagnostics
qr doctor

# Auto-repair orphaned runs and rebuild SQLite index
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
