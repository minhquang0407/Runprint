"""
Grid Search Demo with Nested QR Runs
====================================
Demonstrates hyperparameter search using `with qr.run()` context managers:
- 1 Parent Run representing the overall search session.
- 4 Child Runs, each capturing its own hyperparameters, metrics, and model artifact.
- Fully traceable with `qr list`, `qr show`, and `qr diff`.
"""

from pathlib import Path
import pickle
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

import qr


def main():
    script_dir = Path(__file__).resolve().parent
    data_path = script_dir / "data" / "cancer_dataset.csv"
    if not data_path.exists():
        print(f"Dataset not found at {data_path}")
        return

    # Load and prepare data
    df = pd.read_csv(data_path)
    X = df.drop(columns=["target"]).values
    y = df["target"].values
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    scaler = StandardScaler()
    X_train = scaler.fit_transform(X_train)
    X_test = scaler.transform(X_test)

    param_grid = [
        {"max_depth": 3, "n_estimators": 50},
        {"max_depth": 3, "n_estimators": 100},
        {"max_depth": 6, "n_estimators": 50},
        {"max_depth": 6, "n_estimators": 100},
    ]

    print("=" * 65)
    print("STARTING GRID SEARCH WITH QR CONTEXT MANAGERS")
    print("=" * 65)

    best_score = -1.0
    best_params = None
    artifact_dir = script_dir / "artifacts" / "grid_search"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    # 1. Parent Run: wraps the full hyperparameter optimization session
    with qr.run(tag="grid_search_parent", params={"total_trials": len(param_grid), "algorithm": "RandomForest"}) as session:
        qr.input_dataset(name="cancer_data", uri=str(data_path), version="1.0")

        # 2. Child Runs: each trial is an independent run linked to the parent
        for i, params in enumerate(param_grid, start=1):
            with qr.run(tag="trial", params=params) as trial:
                clf = RandomForestClassifier(
                    max_depth=params["max_depth"],
                    n_estimators=params["n_estimators"],
                    random_state=42,
                )
                with qr.timer("training_time"):
                    clf.fit(X_train, y_train)

                preds = clf.predict(X_test)
                acc = float(accuracy_score(y_test, preds))
                f1 = float(f1_score(y_test, preds))

                qr.log({"trial": i, "accuracy": round(acc, 4), "f1": round(f1, 4)})

                model_file = artifact_dir / f"model_d{params['max_depth']}_t{params['n_estimators']}.pkl"
                with open(model_file, "wb") as f:
                    pickle.dump(clf, f)
                qr.artifact(str(model_file), kind="model", metadata={"accuracy": acc, "f1": f1})

                print(f"  [Trial {i}/{len(param_grid)}] depth={params['max_depth']}, trees={params['n_estimators']} -> Acc: {acc*100:.2f}% (Run: {trial.id})")

                if acc > best_score:
                    best_score = acc
                    best_params = params

        qr.log({"best_accuracy": round(best_score, 4)})
        qr.note(f"Best configuration found: {best_params} with accuracy={best_score:.4f}")

    print("\n" + "=" * 65)
    print(f"GRID SEARCH COMPLETED! Best accuracy: {best_score*100:.2f}% ({best_params})")
    print(f"Parent session run: {session.id}")
    print("=" * 65)


if __name__ == "__main__":
    main()
