"""Unit tests for environment drift detection and lockfile parsing."""

from qr.env import canonicalize_package_name, diff_environments, parse_freeze_text


def test_canonicalize_package_name():
    assert canonicalize_package_name("PyTorch-Lightning") == "pytorch-lightning"
    assert canonicalize_package_name("scikit_learn") == "scikit-learn"
    assert canonicalize_package_name("typing.extensions") == "typing-extensions"


def test_parse_freeze_text_formats():
    freeze_sample = """
# Some comment
torch==2.1.0
numpy>=1.24.0
scipy~=1.11.0
my-pkg @ https://github.com/org/pkg/archive/main.zip
-e git+https://github.com/org/editable.git#egg=editable-pkg
click
"""
    pkgs = parse_freeze_text(freeze_sample)
    assert pkgs["torch"] == "2.1.0"
    assert pkgs["numpy"] == ">=1.24.0"
    assert pkgs["scipy"] == "~=1.11.0"
    assert "https://github.com/org/pkg" in pkgs["my-pkg"]
    assert pkgs["editable-pkg"] == "editable"
    assert pkgs["click"] == "installed"


def test_diff_environments_exact_match():
    lock_text = "torch==2.1.0\nnumpy==1.24.3\n"
    current_pkgs = {"torch": "2.1.0", "numpy": "1.24.3"}

    report = diff_environments(lock_text, current_packages=current_pkgs)
    assert not report.missing_packages
    assert not report.version_mismatches
    assert not report.extra_packages
    assert len(report.matching_packages) == 2
    assert not report.has_drift


def test_diff_environments_version_drift_and_missing():
    lock_text = "torch==2.1.0\nnumpy==1.24.3\npandas==2.0.0\n"
    # Current has different numpy, missing pandas, and extra scipy
    current_pkgs = {"torch": "2.1.0", "numpy": "2.0.0", "scipy": "1.11.0"}

    report = diff_environments(lock_text, current_packages=current_pkgs)
    assert report.has_drift is True
    assert "numpy" in report.version_mismatches
    assert report.version_mismatches["numpy"] == ("1.24.3", "2.0.0")
    assert "pandas" in report.missing_packages
    assert report.missing_packages["pandas"] == "2.0.0"
    assert "scipy" in report.extra_packages
    assert len(report.matching_packages) == 1  # torch
