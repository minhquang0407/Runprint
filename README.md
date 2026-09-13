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
- **Tiny Python SDK**: Optional semantic logging (`qr.log`), artifact registration (`qr.artifact`), dataset tracking (`qr.input_dataset`), and notes (`qr.note`).

---

## Installation

Clone the repository and install in editable mode:

```bash
git clone https://github.com/minhquang0407/Runprint.git
cd Runprint
pip install -e .
```

> **Tip**: If `qr` is installed in a user script directory not yet on your system `PATH`, you can execute commands via `python -m qr.cli <command>`.

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
Run completed: exit=0, duration=14.2s (QR-20260914-A7F2)
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
┌──────────────────┬───────────┬──────────────────┬───────────┬──────────┬─────────┬───────┬─────────────────────┐
│ Run ID           │ Status    │ Tags             │ Command   │ Duration │ Commit  │ Dirty │ Started             │
├──────────────────┼───────────┼──────────────────┼───────────┼──────────┼─────────┼───────┼─────────────────────┤
│ QR-20260914-A7F2 │ completed │ baseline, vision │ python... │    14.2s │ 7cc8be0 │  yes  │ 2026-09-14 09:12:04 │
└──────────────────┴───────────┴──────────────────┴───────────┴──────────┴─────────┴───────┴─────────────────────┘
```

---

### 4. Inspect Run Provenance (`qr show`)
Inspect full source code state, hardware, runtime, registered artifacts, and metrics:

```bash
qr show QR-20260914-A7F2
```

**Detailed Report:**
- **Status & Exit Code**: Outcome and total runtime duration.
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
- Compares execution duration and status.
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

The Python SDK is optional and framework-agnostic. If a script is executed outside of `qr run`, all SDK calls gracefully degrade to safe no-ops.

```python
import qr

# 1. Declare input dataset (auto-calculates SHA256 fingerprint if omitted)
qr.input_dataset(
    name="medvqa",
    uri="data/medvqa_v1.csv",
    version="v1.0"
)

# 2. Log structured metrics per step/epoch (saved to metrics.jsonl)
for epoch in range(epochs):
    loss, acc = train_step()
    qr.log({
        "epoch": epoch,
        "loss": round(float(loss), 4),
        "accuracy": round(float(acc), 4)
    })

# 3. Register output artifacts (checksum & size tracked, file not duplicated)
qr.artifact("checkpoints/best_model.pt", kind="model", metadata={"accuracy": 0.88})

# 4. Add human or script annotations
qr.note("Completed warmup phase, learning rate decayed by factor of 0.1")
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
