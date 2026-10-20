"""Build Rust images locally, generate the frozen SQLite on this machine, and deploy both.

The server never imports or generates data: import runs here via the freshly built
image against the local Python cache, then the finished database is uploaded.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import ipaddress
import json
import os
import re
import shlex
import shutil
import subprocess
import tarfile
from functools import partial
from pathlib import Path

from dotenv import dotenv_values

HERE = Path(__file__).resolve().parent
ZZY = HERE.parent
ROOT = ZZY.parents[1]
BUILD = HERE / "build/deploy"
EXPECT = r'''
set timeout 3600
if {$env(ACTION) eq "run"} {
    spawn ssh -o StrictHostKeyChecking=accept-new -o PubkeyAuthentication=no -o PreferredAuthentications=password -o NumberOfPasswordPrompts=1 $env(SSH_TARGET) $env(REMOTE_CMD)
} else {
    spawn scp -o StrictHostKeyChecking=accept-new -o PubkeyAuthentication=no -o PreferredAuthentications=password -o NumberOfPasswordPrompts=1 $env(LOCAL_FILE) $env(SSH_TARGET):$env(REMOTE_PATH)/
}
expect {
    -re "(?i)password:" { send "$env(SSH_PASSWORD)\r"; exp_continue }
    "Permission denied" { puts stderr "SSH authentication failed"; exit 1 }
    timeout { puts stderr "SSH timed out"; exit 1 }
    eof
}
catch wait result
exit [lindex $result 3]
'''


def digest(path: Path) -> str:
    """Hash large artifacts using bounded memory."""
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def load_config(path: Path) -> dict[str, str]:
    """Read the existing dashboard dotenv without modifying or executing it."""
    values = {key: value for key, value in dotenv_values(path, interpolate=False).items() if value is not None} if path.is_file() else {}
    values.update(os.environ)
    return values


def prepare(build_image: bool, runtime: dict[str, str]) -> tuple[Path, str]:
    """Whitelist source inputs; optionally build/save a linux/amd64 image locally."""
    BUILD.mkdir(parents=True, exist_ok=True)
    stage = BUILD / "source"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir()
    files = [HERE / "Cargo.toml", HERE / "Cargo.lock", *sorted((HERE / "src").rglob("*.rs"))]
    files += [ZZY / "modeling/recommendation" / name for name in ("game_aliases.json", "display_names_zh.json")]
    identity = hashlib.sha256()
    for source in files:
        if source.is_symlink() or not source.is_file():
            raise ValueError("Build source missing or symlinked: " + str(source.relative_to(ZZY)))
        relative = source.relative_to(ZZY)
        target = stage / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        identity.update(str(relative).encode() + digest(source).encode())
    identity.update((HERE / "Dockerfile").read_bytes())
    shutil.copyfile(HERE / "Dockerfile", stage / "rust-recommendation/Dockerfile")
    # Docker's context-level ignore file belongs at the staged result/ZZY root.
    shutil.copyfile(HERE / ".dockerignore", stage / ".dockerignore")
    image = "achievement-recommendation-rust:" + identity.hexdigest()[:20]
    source_archive = BUILD / "source.tar.gz"
    with tarfile.open(source_archive, "w:gz") as archive:
        archive.add(stage, arcname=".")
    package = BUILD / "package"
    if package.exists():
        shutil.rmtree(package)
    package.mkdir()
    shutil.copyfile(HERE / "docker-compose.yml", package / "docker-compose.yml")
    (package / "release.json").write_text(json.dumps({"image": image, "platform": "linux/amd64"}, indent=2) + "\n")
    (package / "release.env").write_text("".join(f"{key}={value}\n" for key, value in {"RUST_RECOMMENDATION_IMAGE": image, **runtime}.items()))
    if build_image:
        subprocess.run(["docker", "build", "--platform", "linux/amd64", "-f", str(stage / "rust-recommendation/Dockerfile"), "-t", image, str(stage)], check=True)
        image_tar = BUILD / "image.tar"
        subprocess.run(["docker", "save", "--output", str(image_tar), image], check=True)
        with image_tar.open("rb") as source, gzip.open(package / "image.tar.gz", "wb", compresslevel=6) as output:
            shutil.copyfileobj(source, output, 1024 * 1024)
        image_tar.unlink()
    archive = BUILD / "upload.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(package, arcname=".")
    for path in (source_archive, archive):
        with tarfile.open(path) as bundle:
            names = bundle.getnames()
        if any(Path(name).name in (".env", "runtime.env") or ".sqlite" in name or "/runtime/" in name for name in names):
            raise ValueError("Unexpected environment or data file in code package")
        print(f"Prepared {path.name}: {path.stat().st_size:,} bytes; {len(names)} entries", flush=True)
    print("Image: " + image + (" (built locally)" if build_image else " (source prepared; image build skipped)"), flush=True)
    return archive, image


def generate_data(image: str, cache: Path, output: Path) -> Path:
    """Run the import one-shot on this machine against the local Python cache."""
    if not cache.is_dir():
        raise ValueError("本地缓存目录不存在：" + str(cache))
    for stale in (output, output.parent / (output.name + ".sha256")):
        if stale.exists():
            stale.unlink()
    subprocess.run(["docker", "run", "--rm", "--network", "none",
                    "-v", str(cache) + ":/python-cache:ro",
                    "-v", str(output.parent) + ":/data",
                    image, "import", "--cache-root", "/python-cache",
                    "--db", "/data/" + output.name], check=True)
    return output


def transfer(config: dict[str, str], action: str, **values: str) -> str:
    """Pass SSH credentials only to the local Expect process, never to a package."""
    host = config.get("RUST_RECOMMENDATION_DEPLOY_HOST") or config.get("DEPLOY_HOST", "")
    user = config.get("RUST_RECOMMENDATION_DEPLOY_USER") or config.get("DEPLOY_USER", "")
    password = config.get("RUST_RECOMMENDATION_DEPLOY_PASSWORD") or config.get("DEPLOY_PASSWORD", "")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", host) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", user) or not password:
        raise ValueError("Missing/invalid deployment host, user or password")
    result = subprocess.run(["expect", "-c", EXPECT], check=True, capture_output=True, text=True,
                            env={**os.environ, "ACTION": action, "SSH_TARGET": f"{user}@{host}", "SSH_PASSWORD": password, **values})
    # Output contains no credential values; do not print full commands/environment.
    lines = [line for line in result.stdout.splitlines() if line.startswith("RUST_")]
    for line in lines:
        print(line, flush=True)
    return result.stdout


def run_container(image: str, remote: str, arguments: str) -> str:
    """Construct a credential-free one-shot image invocation for read-only checks."""
    mounts = f"-v {shlex.quote(remote + '/data:/data:ro')} -v {shlex.quote(remote + '/scratch:/tmp:rw')}"
    return f"docker run --rm --network none --read-only --pids-limit 64 --cap-drop ALL --security-opt no-new-privileges:true {mounts} {shlex.quote(image)} {arguments}"


def deploy(args: argparse.Namespace, config: dict[str, str], archive: Path, image: str, data_file: Path) -> None:
    """Upload the locally generated SQLite, verify it, then switch a version atomically."""
    remote = config.get("RUST_RECOMMENDATION_DEPLOY_PATH", "/opt/achievement-recommendation-rust")
    if not re.fullmatch(r"/[A-Za-z0-9_./-]+", remote) or ".." in Path(remote).parts or remote.rstrip("/") in ("", "/opt", "/opt/achievement-dashboard", "/opt/achievement-recommendation"):
        raise ValueError("Rust deployment path must be a separate dedicated absolute directory")
    for protected in (config.get("DEPLOY_PATH", "/opt/achievement-dashboard"), config.get("RECOMMENDATION_DEPLOY_PATH", "/opt/achievement-recommendation")):
        if Path(remote) == Path(protected) or Path(protected) in Path(remote).parents:
            raise ValueError("Rust deployment must not write inside dashboard or Python deployment directories")
    path = shlex.quote(remote)
    one_shot = partial(run_container, image, remote)
    transfer(config, "run", REMOTE_CMD=f"set -eu; umask 077; mkdir -p {path}/data/versions {path}/scratch; docker compose version >/dev/null")
    transfer(config, "put", LOCAL_FILE=str(archive), REMOTE_PATH=remote)
    transfer(config, "run", REMOTE_CMD=f"set -eu; cd {path}; tar -xzf upload.tar.gz; gzip -dc image.tar.gz | docker load; rm upload.tar.gz image.tar.gz; echo RUST_IMAGE_LOADED")
    verify = one_shot("verify --db /data/current/recommendation.sqlite")
    sha = digest(data_file)
    probe = transfer(config, "run", REMOTE_CMD=f"set -eu; if [ -f {path}/data/versions/{sha}/recommendation.sqlite ] && [ \"$(sha256sum {path}/data/versions/{sha}/recommendation.sqlite | cut -d ' ' -f 1)\" = '{sha}' ]; then printf '%s\\n' '{sha}' >{path}/data/versions/{sha}/recommendation.sqlite.sha256.next; mv -f {path}/data/versions/{sha}/recommendation.sqlite.sha256.next {path}/data/versions/{sha}/recommendation.sqlite.sha256; echo RUST_DATA_PRESENT; else echo RUST_DATA_MISSING; fi")
    if "RUST_DATA_PRESENT" not in probe.splitlines():
        data_archive = BUILD / "data-upload.tar.gz"
        sidecar = BUILD / "recommendation.sqlite.sha256"
        sidecar.write_text(sha + "\n")
        with tarfile.open(data_archive, "w:gz") as bundle:
            bundle.add(data_file, arcname="recommendation.sqlite")
            bundle.add(sidecar, arcname="recommendation.sqlite.sha256")
        transfer(config, "put", LOCAL_FILE=str(data_archive), REMOTE_PATH=remote)
        transfer(config, "run", REMOTE_CMD=f"set -eu; cd {path}; incoming=$(mktemp -d data/.incoming.XXXXXX); trap 'rm -rf \"$incoming\"' EXIT; tar -xzf data-upload.tar.gz -C \"$incoming\"; [ \"$(sha256sum \"$incoming/recommendation.sqlite\" | cut -d ' ' -f 1)\" = '{sha}' ]; mkdir -p data/versions/{sha}; mv \"$incoming/recommendation.sqlite\" data/versions/{sha}/; mv \"$incoming/recommendation.sqlite.sha256\" data/versions/{sha}/; rm data-upload.tar.gz; echo RUST_DATA_UPLOADED")
    else:
        print("Rust data already present and SHA256 verified; zero data bytes uploaded", flush=True)
    version = sha
    if version:
        verify_version = one_shot(f"verify --db /data/versions/{version}/recommendation.sqlite")
        transfer(config, "run", REMOTE_CMD=f"set -eu; {verify_version}; cd {path}/data; next=current.next.$$; trap 'rm -f \"$next\"' EXIT; ln -s versions/{version} \"$next\"; mv -fT \"$next\" current; echo RUST_DATA_ACTIVE={version}")
    transfer(config, "run", REMOTE_CMD=f"set -eu; cd {path}; docker compose --env-file release.env up -d --force-recreate; for i in $(seq 1 90); do if docker compose --env-file release.env exec -T recommendation-rust /recommendation health --port {args.port} >/dev/null 2>&1; then echo RUST_READY=127.0.0.1:{args.port}; exit 0; fi; sleep 2; done; docker compose --env-file release.env logs --tail 40 recommendation-rust; exit 1")


def main() -> int:
    """Prepare without credentials by default only when --prepare-only is explicit."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--build-image", action="store_true", help="Also build/export image in prepare-only mode")
    parser.add_argument("--env-file", type=Path, default=ROOT / "dashboard/.env")
    parser.add_argument("--data-file", type=Path, help="Frozen SQLite generated on this machine (see --generate-data); required for deploy")
    parser.add_argument("--generate-data", action="store_true", help="Generate recommendation.sqlite locally with the freshly built image, then deploy it")
    parser.add_argument("--local-cache", type=Path, default=ZZY / "runtime/database", help="Local Python cache with latest-startup.json / snapshots / kg")
    parser.add_argument("--port", type=int, default=8606)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    try:
        if not 1 <= args.port <= 65535:
            raise ValueError("Port must be 1..65535")
        if ipaddress.ip_address(args.host).version != 4:
            raise ValueError("Bind address must be IPv4")
        if args.data_file and (args.data_file.is_symlink() or not args.data_file.is_file()):
            raise ValueError("Explicit SQLite data must be a regular file, not a symlink")
        if args.generate_data and args.prepare_only:
            raise ValueError("--generate-data performs a full deploy; drop --prepare-only")
        runtime = {"RUST_RECOMMENDATION_PORT": str(args.port), "RUST_RECOMMENDATION_BIND_HOST": args.host}
        archive, image = prepare(args.build_image or not args.prepare_only, runtime)
        if args.prepare_only:
            print("Prepare-only: no credentials read, no SSH, no database or AI access", flush=True)
            return 0
        if args.data_file and args.generate_data:
            raise ValueError("Choose either --data-file or --generate-data, not both")
        if not args.data_file and not args.generate_data:
            raise ValueError("服务器不再导入或生成数据：请用 --generate-data 本地生成，或 --data-file 指定已生成的 SQLite")
        data_file = generate_data(image, args.local_cache, BUILD / "recommendation.sqlite") if args.generate_data else args.data_file
        deploy(args, load_config(args.env_file), archive, image, data_file)
        return 0
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        # Do not print subprocess commands/env: they may contain local credentials.
        print("Rust deployment failed: " + (str(error) if isinstance(error, ValueError) else type(error).__name__), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
