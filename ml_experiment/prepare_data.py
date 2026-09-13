"""
Data Preparation Script
=======================
Prepares and exports the Breast Cancer dataset to CSV for reproducible ML experiments.
"""

from pathlib import Path
import pandas as pd
from sklearn.datasets import load_breast_cancer


def main():
    data_dir = Path(__file__).parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    csv_path = data_dir / "cancer_dataset.csv"

    print("Loading Breast Cancer Wisconsin dataset from scikit-learn...")
    dataset = load_breast_cancer(as_frame=True)
    df = dataset.frame

    df.to_csv(csv_path, index=False)
    print(f"Dataset successfully saved to: {csv_path} ({df.shape[0]} samples, {df.shape[1]} features)")


if __name__ == "__main__":
    main()
