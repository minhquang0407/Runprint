"""
Machine Learning Training Pipeline
==================================
Real-world classification pipeline demonstrating Runprint (QR) provenance tracking,
input datasets, metrics logging, and artifact registration.
"""

import argparse
import os
import pickle
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
import yaml

# Import QR SDK (safely no-ops if run outside qr run)
import qr


def parse_args():
    parser = argparse.ArgumentParser(description="Train classification model with QR experiment tracking")
    parser.add_argument("--config", type=str, default=None, help="Path to YAML configuration file")
    parser.add_argument("--model", type=str, default=None, choices=["random_forest", "gradient_boosting", "logistic_regression"], help="Model type")
    parser.add_argument("--n-estimators", type=int, default=None, help="Number of estimators/trees")
    parser.add_argument("--max-depth", type=int, default=None, help="Maximum tree depth")
    parser.add_argument("--lr", type=float, default=None, help="Learning rate (for boosting)")
    parser.add_argument("--seed", type=int, default=None, help="Random seed")
    return parser.parse_args()


def load_config(config_path: str) -> dict:
    if config_path and Path(config_path).exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}


def main():
    args = parse_args()
    cfg = load_config(args.config) if args.config else {}

    # Merge configuration: CLI flags override config file
    model_type = args.model or cfg.get("model", {}).get("type", "random_forest")
    n_estimators = args.n_estimators or cfg.get("model", {}).get("n_estimators", 100)
    max_depth = args.max_depth or cfg.get("model", {}).get("max_depth", 5)
    lr = args.lr or cfg.get("model", {}).get("learning_rate", 0.1)
    seed = args.seed if args.seed is not None else cfg.get("experiment", {}).get("seed", 42)

    # Locate dataset path robustly regardless of whether invoked from repo root or ml_experiment/
    script_dir = Path(__file__).resolve().parent
    raw_dataset_path = cfg.get("dataset", {}).get("path", "data/cancer_dataset.csv")

    candidates = [
        Path(raw_dataset_path),
        script_dir / raw_dataset_path,
        script_dir / "data" / "cancer_dataset.csv",
    ]
    if raw_dataset_path.startswith("ml_experiment/"):
        candidates.insert(1, script_dir / raw_dataset_path[len("ml_experiment/"):])

    data_file = None
    for c in candidates:
        if c.exists():
            data_file = c
            break

    if data_file is None:
        data_file = script_dir / "data" / "cancer_dataset.csv"

    print("=" * 60)
    print(f"EXPERIMENT: Model={model_type} | Trees={n_estimators} | Depth={max_depth} | Seed={seed}")
    print("=" * 60)

    # Register hyperparameters directly in-code
    qr.params({
        "model_type": model_type,
        "n_estimators": n_estimators,
        "max_depth": max_depth,
        "learning_rate": lr,
        "seed": seed,
    })

    # 1. Ensure dataset exists and register input dataset provenance with QR
    if not data_file.exists():
        print(f"Dataset not found at {data_file}. Generating now...")
        try:
            from ml_experiment.prepare_data import main as prep_data
        except ModuleNotFoundError:
            from prepare_data import main as prep_data
        prep_data()

    qr.input_dataset(
        name="breast_cancer_wisconsin",
        uri=str(data_file),
        version="v1.0",
    )

    # 2. Load & preprocess data
    df = pd.read_csv(data_file)
    X = df.drop(columns=["target"]).values
    y = df["target"].values

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=seed, stratify=y
    )

    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    # 3. Model Initialization
    with qr.timer("model_initialization"):
        if model_type == "random_forest":
            clf = RandomForestClassifier(
                n_estimators=n_estimators,
                max_depth=max_depth,
                random_state=seed,
        )
        elif model_type == "gradient_boosting":
            clf = GradientBoostingClassifier(
                n_estimators=n_estimators,
                learning_rate=lr,
                max_depth=max_depth,
                random_state=seed,
            )
        else:
            clf = LogisticRegression(random_state=seed, max_iter=1000)

    # 4. Train Model
    with qr.timer("train_model"):
        print(f"Training {model_type} on {X_train.shape[0]} samples...")
        clf.fit(X_train_scaled, y_train)
    

    # 5. Evaluate Performance
    y_pred = clf.predict(X_test_scaled)
    y_proba = clf.predict_proba(X_test_scaled)[:, 1] if hasattr(clf, "predict_proba") else y_pred

    acc = round(accuracy_score(y_test, y_pred), 4)
    prec = round(precision_score(y_test, y_pred), 4)
    rec = round(recall_score(y_test, y_pred), 4)
    f1 = round(f1_score(y_test, y_pred), 4)
    roc_auc = round(roc_auc_score(y_test, y_proba), 4)

    print("\nEVALUATION RESULTS:")
    print(f"  • Accuracy:  {acc:.4f}")
    print(f"  • Precision: {prec:.4f}")
    print(f"  • Recall:    {rec:.4f}")
    print(f"  • F1 Score:  {f1:.4f}")
    print(f"  • ROC AUC:   {roc_auc:.4f}")

    # 6. Log structured metrics to QR
    qr.log({
        "accuracy": acc,
        "precision": prec,
        "recall": rec,
        "f1": f1,
        "roc_auc": roc_auc,
    })

    # 7. Save & register model artifact
    artifact_dir = script_dir / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    model_path = artifact_dir / f"model_{model_type}.pkl"
    with open(model_path, "wb") as f:
        pickle.dump({"model": clf, "scaler": scaler}, f)

    qr.artifact(
        str(model_path),
        kind="model",
        metadata={"accuracy": acc, "f1": f1, "model_type": model_type},
    )

    # 8. Generate & register confusion matrix plot
    cm = confusion_matrix(y_test, y_pred)
    fig, ax = plt.subplots(figsize=(5, 4))
    im = ax.imshow(cm, interpolation="nearest", cmap=plt.cm.Blues)
    ax.figure.colorbar(im, ax=ax)
    ax.set(
        xticks=np.arange(cm.shape[1]),
        yticks=np.arange(cm.shape[0]),
        xticklabels=["Malignant", "Benign"],
        yticklabels=["Malignant", "Benign"],
        ylabel="True Label",
        xlabel="Predicted Label",
        title=f"Confusion Matrix ({model_type})\nAccuracy: {acc*100:.1f}%",
    )
    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            ax.text(j, i, format(cm[i, j], "d"), ha="center", va="center", color="black")
    plt.tight_layout()

    plot_path = artifact_dir / f"confusion_matrix_{model_type}.png"
    plt.savefig(plot_path, dpi=120)
    plt.close(fig)

    qr.artifact(str(plot_path), kind="plot")
    qr.note(f"Trained {model_type} with acc={acc}, f1={f1}")

    print(f"\nArtifacts saved and registered:")
    print(f"  - Model: {model_path}")
    print(f"  - Plot:  {plot_path}")
    print("=" * 60)

    # 9. Activate and save experiment run (enables running via Python button or CLI)
    qr.activate(tag=model_type)

    return clf


if __name__ == "__main__":
    main()

