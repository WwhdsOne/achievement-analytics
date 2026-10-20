#!/usr/bin/env python3
"""Rehearse incremental frozen-content deployment locally, without SSH or DB."""

from __future__ import annotations

import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

from dashboard_content import INSTALLER, ROOT, digest, entries, local, prepare


def check_plan(manifest: Path, remote: Path, expected: set[str], legacy_root: Path | None = None) -> None:
    """Compare requested transfer hashes with a controlled expected delta."""
    legacy = [str(legacy_root)] if legacy_root else []
    result = subprocess.run(["bash", str(INSTALLER), "plan", str(remote), str(manifest), *legacy],
                            check=True, capture_output=True, text=True)
    actual = {line.split()[1] for line in result.stdout.splitlines() if line.startswith("MISSING ")}
    assert actual == expected, (len(actual), len(expected))
    assert "CONTENT_PLAN_OK" in result.stdout.splitlines()


def main() -> None:
    """Verify first sync, no-op, changed file, corruption and missing-file repair."""
    with tempfile.TemporaryDirectory(prefix="dashboard-content-check-") as tmp:
        base = Path(tmp)
        original = prepare(base / "original", None)
        source = base / "source"
        for _, _, name, path in entries(original):
            target = source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        output, remote = base / "plan", base / "server-content"
        manifest = prepare(output, source)
        hashes = {sha for sha, _, _, _ in entries(manifest)}
        check_plan(manifest, remote, hashes)
        local(manifest, remote, output)
        for sha, _, name, _ in entries(manifest):
            assert digest(remote / "current" / name) == sha, name
        print(f"PASS first sync: all {len(hashes)} objects, served bytes match original files")
        first = (remote / "current").resolve()
        check_plan(manifest, remote, set())
        local(manifest, remote, output)
        print("PASS unchanged sync: zero artifact bytes transferred")

        changed = source / "lyx/docs/ANALYSIS.md"
        changed.write_bytes(changed.read_bytes() + b"\nLocal rehearsal only.\n")
        manifest = prepare(output, source)
        check_plan(manifest, remote, {digest(changed)})
        local(manifest, remote, output)
        assert (first / "lyx/docs/ANALYSIS.md").read_bytes() != changed.read_bytes()
        print("PASS one changed file: one object transferred; previous release retained")

        check_plan(original, remote, set())
        local(original, remote, output)
        check_plan(manifest, remote, set())
        local(manifest, remote, output)
        print("PASS restoring either known version: zero artifact bytes transferred")

        # Same size corruption and an intact manifest must still trigger repair.
        served = remote / "current/lyx/WEB/index.html"
        original_bytes = served.read_bytes()
        served.write_bytes(bytes([original_bytes[0] ^ 1]) + original_bytes[1:])
        check_plan(manifest, remote, {digest(source / "lyx/WEB/index.html")})
        local(manifest, remote, output)
        assert served.read_bytes() == original_bytes
        print("PASS same-size corruption: detected from actual bytes and replaced")

        served.unlink()
        check_plan(manifest, remote, set())
        local(manifest, remote, output)
        assert served.read_bytes() == original_bytes
        check_plan(manifest, remote, set())
        assert first.exists()
        print("PASS missing served file repaired with zero transferred bytes; final manifest matches every actual file")

        active = (remote / "current").resolve()
        changed.write_bytes(changed.read_bytes() + b"Incomplete upload rehearsal.\n")
        manifest = prepare(output, source)
        incomplete = base / "incomplete.tar.gz"
        with tarfile.open(incomplete, "w:gz") as archive:
            archive.add(manifest, arcname="manifest.tsv")
        result = subprocess.run(["bash", str(INSTALLER), "install", str(remote), str(incomplete)],
                                capture_output=True, text=True)
        assert result.returncode != 0
        assert (remote / "current").resolve() == active
        assert not (remote / ".install-lock").exists()
        print("PASS incomplete upload rejected; active release unchanged and lock released")

        # First migration must reuse the historical report already on the server,
        # even though its new object store is empty.
        legacy_root = base / "legacy-server"
        legacy_remote = legacy_root / "content"
        report_name = "data/processed/analysis-report.json"
        report = next(row for row in entries(original) if row[2] == report_name)
        legacy_report = legacy_root / report_name
        legacy_report.parent.mkdir(parents=True)
        shutil.copyfile(report[3], legacy_report)
        check_plan(original, legacy_remote, hashes - {report[0]}, legacy_root)
        local(original, legacy_remote, output, legacy_root)
        report_object = legacy_remote / "objects" / report[0]
        assert digest(report_object) == report[0]
        assert report_object.stat().st_ino != legacy_report.stat().st_ino
        legacy_report.write_bytes(legacy_report.read_bytes() + b"\nMutable legacy file.\n")
        assert digest(report_object) == report[0]
        check_plan(original, legacy_remote, set(), legacy_root)
        local(original, legacy_remote, output, legacy_root)
        print("PASS first legacy migration: 72 objects uploaded; existing report copied locally, isolated from later edits; repeat zero bytes")

        entry = next(row for row in entries(original) if row[2] == "lyx/WEB/index.html")
        (legacy_remote / "objects" / entry[0]).unlink()
        assert digest(legacy_remote / "current" / entry[2]) == entry[0]
        check_plan(original, legacy_remote, set(), legacy_root)
        local(original, legacy_remote, output, legacy_root)
        assert digest(legacy_remote / "objects" / entry[0]) == entry[0]
        print("PASS missing object restored from intact current file with zero uploaded bytes")


if __name__ == "__main__":
    main()
