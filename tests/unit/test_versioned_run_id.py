import re
from pathlib import Path
from click.testing import CliRunner

from qr.storage.local import (
    generate_run_id,
    extract_base_run_id,
    generate_next_version_run_id,
    resolve_run_id,
    RunStorage,
)
from qr.manifest import RunManifest, Timestamps, RuntimeSnapshot, HardwareSnapshot
from qr.cli import main


def test_generate_run_id_format():
    rid = generate_run_id()
    assert re.match(r"^QR-\d{8}-[0-9A-F]{4}-v1$", rid)

    rid_v3 = generate_run_id(version=3)
    assert rid_v3.endswith("-v3")


def test_extract_base_run_id():
    assert extract_base_run_id("QR-20260914-1DF6-v1") == "QR-20260914-1DF6"
    assert extract_base_run_id("QR-20260914-1DF6-v99") == "QR-20260914-1DF6"
    assert extract_base_run_id("QR-20260914-1DF6") == "QR-20260914-1DF6"
    assert extract_base_run_id("custom-run-name") == "custom-run-name"


def test_generate_next_version_run_id(tmp_path: Path):
    qr_dir = tmp_path / ".qr"
    runs_dir = qr_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    base = "QR-20260914-TEST"

    # Case 1: Only v1 exists
    (runs_dir / f"{base}-v1").mkdir()
    next_id = generate_next_version_run_id(f"{base}-v1", qr_dir)
    assert next_id == f"{base}-v2"

    # Case 2: v1 and v2 exist, rerun from v2
    (runs_dir / f"{base}-v2").mkdir()
    next_id = generate_next_version_run_id(f"{base}-v2", qr_dir)
    assert next_id == f"{base}-v3"

    # Case 3: v1, v2 exist, rerun from v1 again -> should still produce v3 (linear sequence)
    next_id_from_v1 = generate_next_version_run_id(f"{base}-v1", qr_dir)
    assert next_id_from_v1 == f"{base}-v3"

    # Case 4: Legacy run without -v suffix
    legacy = "QR-20260914-LEGACY"
    (runs_dir / legacy).mkdir()
    next_legacy = generate_next_version_run_id(legacy, qr_dir)
    assert next_legacy == f"{legacy}-v2"


def test_resolve_run_id(tmp_path: Path):
    qr_dir = tmp_path / ".qr"
    runs_dir = qr_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    base = "QR-20260914-AAAA"
    (runs_dir / f"{base}-v1").mkdir()
    (runs_dir / f"{base}-v2").mkdir()

    # Exact match
    assert resolve_run_id(qr_dir, f"{base}-v1") == f"{base}-v1"
    assert resolve_run_id(qr_dir, f"{base}-v2") == f"{base}-v2"

    # Shorthand base without version -> resolves to highest version (v2)
    assert resolve_run_id(qr_dir, base) == f"{base}-v2"

    # Non-existent
    assert resolve_run_id(qr_dir, "non-existent") == "non-existent"


def test_cli_run_and_rerun_versioning(tmp_path: Path, monkeypatch):
    from qr.project import init_project

    runner = CliRunner()
    init_project(tmp_path)
    monkeypatch.setattr("qr.cli.find_project_root", lambda *args, **kwargs: tmp_path)

    # 1. Run creates v1
    res1 = runner.invoke(main, ["run", "--", "python", "-c", "print('v1')"])
    assert res1.exit_code == 0
    m = re.search(r"(QR-\d{8}-[0-9A-F]{4}-v1)", res1.output)
    assert m, f"Output should contain -v1 run id: {res1.output}"
    v1_id = m.group(1)

    # 2. Show v1 displays correctly
    res_show1 = runner.invoke(main, ["show", v1_id])
    assert res_show1.exit_code == 0
    assert "COMPLETED" in res_show1.output

    # 3. Rerun v1 creates v2
    res2 = runner.invoke(main, ["rerun", v1_id, "--allow-env-mismatch"])
    assert res2.exit_code == 0
    v2_id = v1_id.replace("-v1", "-v2")
    assert v2_id in res2.output

    # 4. Show v2 displays parent lineage
    res_show2 = runner.invoke(main, ["show", v2_id])
    assert res_show2.exit_code == 0
    assert f"Parent = {v1_id}" in res_show2.output

    # 5. Show with base ID resolves to latest (v2)
    base_id = extract_base_run_id(v1_id)
    res_show_base = runner.invoke(main, ["show", base_id])
    assert res_show_base.exit_code == 0
    assert f"Parent = {v1_id}" in res_show_base.output

    # 6. Rerun v2 creates v3
    res3 = runner.invoke(main, ["rerun", v2_id, "--allow-env-mismatch"])
    assert res3.exit_code == 0
    v3_id = v1_id.replace("-v1", "-v3")
    assert v3_id in res3.output

    # 7. Show v3 displays parent v2
    res_show3 = runner.invoke(main, ["show", v3_id])
    assert res_show3.exit_code == 0
    assert f"Parent = {v2_id}" in res_show3.output

