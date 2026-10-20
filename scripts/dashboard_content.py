#!/usr/bin/env python3
"""Prepare frozen dashboard content and transfer only missing SHA-256 objects.

No dependencies, credentials, network access or database reads. ``local`` uses the
same POSIX shell installer as production against an explicitly supplied directory.
The generic ``--source-dir`` layout can also package another service's artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = Path(__file__).with_name("dashboard_content.sh")


def digest(path: Path) -> str:
    """Hash the actual file bytes without loading large artifacts into memory."""
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def entries(manifest: Path) -> list[tuple[str, int, str, Path]]:
    """Load the local manifest and its private source-path index."""
    rows = []
    sources = manifest.with_suffix(".sources").read_text().splitlines()
    lines = manifest.read_text().splitlines()
    if len(sources) != len(lines):
        raise ValueError("manifest/source index length mismatch")
    for line, source in zip(lines, sources):
        sha, size, name = line.split("\t")
        rows.append((sha, int(size), name, Path(source)))
    return rows


def prepare(output: Path, source_dir: Path | None) -> Path:
    """Build a deterministic manifest; no artifact bytes are copied here."""
    if source_dir:
        files = [(p.relative_to(source_dir).as_posix(), p) for p in source_dir.rglob("*") if p.is_file()]
    else:
        dashboard = ROOT / "dashboard"
        files = [(p.relative_to(dashboard).as_posix(), p)
                 for directory in ("lyx", "figures")
                 for p in (dashboard / directory).rglob("*") if p.is_file()]
        files.append(("data/processed/analysis-report.json", ROOT / "data/processed/analysis-report.json"))
        files += [(name, dashboard / name) for name in ("cluster-data.json", "trend-data.json")]
    if not files:
        raise ValueError("content tree is empty")
    output.mkdir(parents=True, exist_ok=True)
    lines, sources = [], []
    for name, source in sorted(files):
        if source.is_symlink() or not re.fullmatch(r"[A-Za-z0-9_./-]+", name) or ".." in name.split("/"):
            raise ValueError(f"unsafe content path: {name}")
        lines.append(f"{digest(source)}\t{source.stat().st_size}\t{name}\n")
        sources.append(str(source.resolve()) + "\n")
    manifest = output / "manifest.tsv"
    manifest.write_text("".join(lines))
    manifest.with_suffix(".sources").write_text("".join(sources))
    print(f"Content: {len(files)} files, {sum(p.stat().st_size for _, p in files):,} bytes; manifest {digest(manifest)[:16]}")
    return manifest


def payload(manifest: Path, probe: Path, output: Path) -> int:
    """Archive only blobs whose actual remote bytes failed verification."""
    rows = entries(manifest)
    missing = set(re.findall(r"^MISSING ([a-f0-9]{64})\r?$", probe.read_text(), re.M))
    if "CONTENT_PLAN_OK" not in probe.read_text().splitlines():
        raise ValueError("remote content plan incomplete; refusing to infer an empty delta")
    known = {sha for sha, _, _, _ in rows}
    if missing - known:
        raise ValueError("remote plan contains unknown hashes")
    sent, total = set(), 0
    with tarfile.open(output, "w:gz") as archive:
        archive.add(manifest, arcname="manifest.tsv")
        for sha, size, _, source in rows:
            if sha in missing and sha not in sent:
                if digest(source) != sha:
                    raise ValueError(f"content changed during packaging: {source}")
                archive.add(source, arcname=f"objects/{sha}")
                sent.add(sha)
                total += size
    print(f"Content delta: {len(sent)} objects, {total:,} bytes; unchanged bytes skipped")
    return len(sent)


def local(manifest: Path, remote: Path, output: Path, legacy_root: Path | None = None) -> None:
    """Exercise the production plan/payload/install against a local directory."""
    probe = output / "probe.log"
    legacy = [str(legacy_root.resolve())] if legacy_root else []
    result = subprocess.run(["bash", str(INSTALLER), "plan", str(remote.resolve()), str(manifest.resolve()), *legacy],
                            check=True, capture_output=True, text=True)
    probe.write_text(result.stdout)
    delta = output / "content-delta.tar.gz"
    payload(manifest, probe, delta)
    subprocess.run(["bash", str(INSTALLER), "install", str(remote.resolve()), str(delta.resolve()), *legacy], check=True)


def main() -> None:
    """Expose preparation, delta packaging and local deployment rehearsal."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "payload", "local"))
    parser.add_argument("--output", type=Path, default=ROOT / "dashboard/build/content-plan")
    parser.add_argument("--source-dir", type=Path, help="Generic frozen content root (default: dashboard research + report)")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--probe", type=Path)
    parser.add_argument("--remote-dir", type=Path)
    parser.add_argument("--legacy-root", type=Path, help="Explicit older on-disk layout to reuse after SHA256 verification")
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.output, args.source_dir)
    elif args.action == "payload":
        if not args.manifest or not args.probe:
            parser.error("payload requires --manifest and --probe")
        payload(args.manifest, args.probe, args.output)
    else:
        if not args.remote_dir:
            parser.error("local requires --remote-dir")
        manifest = args.manifest or prepare(args.output, args.source_dir)
        local(manifest, args.remote_dir, args.output, args.legacy_root)


if __name__ == "__main__":
    main()
