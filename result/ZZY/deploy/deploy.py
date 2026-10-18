"""独立打包并部署 ZZY 推荐容器；配置来自 dashboard/.env，不上传 SSH 凭据。"""

from __future__ import annotations

import argparse
import ipaddress
import os
import re
import shlex
import shutil
import subprocess
import tarfile
from pathlib import Path

from dotenv import dotenv_values

HERE = Path(__file__).resolve().parent
ZZY = HERE.parent
REPOSITORY = ZZY.parents[1]
BUILD = ZZY / "build/deploy"
DATABASE_KEYS = (
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_SSLMODE",
)
EXPECT = r"""
set timeout 1800
if {$env(DEPLOY_ACTION) eq "run"} {
    spawn ssh -o StrictHostKeyChecking=accept-new -o PubkeyAuthentication=no -o PreferredAuthentications=password -o NumberOfPasswordPrompts=1 $env(SSH_TARGET) $env(REMOTE_CMD)
} else {
    spawn scp -o StrictHostKeyChecking=accept-new -o PubkeyAuthentication=no -o PreferredAuthentications=password -o NumberOfPasswordPrompts=1 $env(LOCAL_FILE) $env(SSH_TARGET):$env(REMOTE_PATH)/
}
expect {
    -re "(?i)password:" { send "$env(SSH_PASSWORD)\r"; exp_continue }
    "Permission denied" { puts stderr "SSH 认证失败"; exit 1 }
    timeout { puts stderr "SSH 操作超时"; exit 1 }
    eof
}
catch wait result
exit [lindex $result 3]
"""


def load_config(path: Path) -> dict[str, str]:
    """读取已有配置，环境变量优先；不执行 shell 或打印凭据。"""
    if not path.is_file():
        raise ValueError(
            "缺少配置文件，请先填写 dashboard/.env，模板见 dashboard/.env.example"
        )
    values = {
        key: value
        for key, value in dotenv_values(path, interpolate=False).items()
        if value is not None
    }
    values.update(os.environ)
    return values


def port(value: str, key: str) -> str:
    """把有效端口规范成十进制文本，无效时只提示配置项名称。"""
    if not value.isascii() or not value.isdecimal() or not 1 <= int(value) <= 65535:
        raise ValueError(key + " 必须是1–65535的整数")
    return str(int(value))


def runtime_config(config: dict[str, str]) -> dict[str, str]:
    """仅传数据库、推荐参数及指定 DeepSeek 配置，不上传 SSH/其他源密钥。"""
    missing = [key for key in DATABASE_KEYS[:5] if not config.get(key)]
    if missing:
        raise ValueError("缺少数据库配置：" + ", ".join(missing))
    runtime = {key: config[key] for key in DATABASE_KEYS if config.get(key)}
    runtime["POSTGRES_PORT"] = port(runtime["POSTGRES_PORT"], "POSTGRES_PORT")
    runtime["RECOMMENDATION_PORT"] = port(
        config.get("RECOMMENDATION_PORT", "8605"), "RECOMMENDATION_PORT"
    )
    bind = config.get("RECOMMENDATION_BIND_HOST", "127.0.0.1")
    try:
        address = ipaddress.ip_address(bind)
    except ValueError:
        raise ValueError("RECOMMENDATION_BIND_HOST 须为本机或私网 IPv4 地址") from None
    if address.version != 4:
        raise ValueError("推荐服务当前 HTTPServer 使用 IPv4 监听，请填写 IPv4 地址")
    runtime["RECOMMENDATION_BIND_HOST"] = bind
    ds_file = Path(
        config.get(
            "RECOMMENDATION_DEEPSEEK_ENV_FILE", str(REPOSITORY / "result/WWH/5/.env")
        )
    )
    ds = dotenv_values(ds_file, interpolate=False) if ds_file.is_file() else {}
    for key in ("DEEPSEEK_API_KEY", "DEEPSEEK_MODEL", "DEEPSEEK_BASE_URL"):
        value = config.get(key) or ds.get(key)
        if value:
            runtime[key] = value
    if config.get("COMMENTARY_PUBLIC_ORIGINS"):
        runtime["COMMENTARY_PUBLIC_ORIGINS"] = config["COMMENTARY_PUBLIC_ORIGINS"]
    if any(
        "\n" in value or "\r" in value or "\0" in value for value in runtime.values()
    ):
        raise ValueError("运行配置必须是单行文本")
    return runtime


def runtime_text(config: dict[str, str]) -> str:
    """Compose raw env_file 保留数据库密码中的引号、$、反斜杠和空格。"""
    return "".join(f"{key}={value}\n" for key, value in config.items())


def prepare(runtime: dict[str, str]) -> Path:
    """按白名单复制源码、页面和锁定依赖，不复制数据库缓存、报告或密钥。"""
    BUILD.mkdir(parents=True, exist_ok=True)
    BUILD.chmod(0o700)
    stage = BUILD / "stage"
    if stage.exists():
        shutil.rmtree(stage)
    (stage / "result/ZZY").mkdir(parents=True)
    for name in (
        "Dockerfile",
        "docker-compose.yml",
        ".dockerignore",
        "pyproject.toml",
        "uv.lock",
        "health.py",
    ):
        shutil.copy2(HERE / name, stage / name)
    shutil.copy2(
        ZZY / "dashboard_service.py", stage / "result/ZZY/dashboard_service.py"
    )
    suffixes = {".py", ".json", ".js", ".css", ".html"}
    for directory in (ZZY / "modeling", ZZY / "process"):
        for source in directory.rglob("*"):
            if (
                not source.is_file()
                or source.suffix not in suffixes
                or "__pycache__" in source.parts
            ):
                continue
            if source.is_symlink():
                raise ValueError("部署源码不接受符号链接")
            target = stage / "result/ZZY" / source.relative_to(ZZY)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    # .env 仅用于 Compose 插值；含数据库密码的 runtime.env 采用 raw 格式。
    for name, values in (
        (
            ".env",
            {
                key: runtime[key]
                for key in ("RECOMMENDATION_PORT", "RECOMMENDATION_BIND_HOST")
            },
        ),
        ("runtime.env", runtime),
    ):
        env = stage / name
        env.write_text(runtime_text(values), encoding="utf-8")
        env.chmod(0o600)
    archive = BUILD / "upload.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(stage, arcname=".")
    archive.chmod(0o600)
    return archive


def transfer(config: dict[str, str], action: str, **values: str) -> None:
    """复用现有 expect 密码登录方式，变量经环境传入，避免 Tcl 源码插值。"""
    host = config.get("RECOMMENDATION_DEPLOY_HOST") or config.get("DEPLOY_HOST", "")
    user = config.get("RECOMMENDATION_DEPLOY_USER") or config.get("DEPLOY_USER", "")
    password = config.get("RECOMMENDATION_DEPLOY_PASSWORD") or config.get(
        "DEPLOY_PASSWORD", ""
    )
    if not host or not user or not password:
        raise ValueError(
            "缺少推荐部署凭据；默认使用 dashboard/.env 的 DEPLOY_HOST/USER/PASSWORD"
        )
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", host) or not re.fullmatch(
        r"[a-zA-Z_][a-zA-Z0-9_.-]*", user
    ):
        raise ValueError("DEPLOY_HOST 须为 IPv4 或主机名，DEPLOY_USER 须为有效用户名")
    if shutil.which("expect") is None:
        raise ValueError("本机缺少 expect，无法进行密码登录")
    subprocess.run(
        ["expect", "-c", EXPECT],
        check=True,
        env={
            **os.environ,
            "DEPLOY_ACTION": action,
            "SSH_TARGET": f"{user}@{host}",
            "SSH_PASSWORD": password,
            **values,
        },
    )


def main() -> int:
    """准备独立部署包；只有未指定 --prepare-only 时才连接目标服务器。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=REPOSITORY / "dashboard/.env")
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="仅生成并检查本地部署包，不连接服务器或数据库",
    )
    parser.add_argument(
        "--refresh-data",
        action="store_true",
        help="部署时显式刷新服务数据卷中的快照与图谱",
    )
    parser.add_argument(
        "--health-timeout",
        type=int,
        default=900,
        help="等待首次只读加载和图谱准备的秒数",
    )
    args = parser.parse_args()
    try:
        if not 1 <= args.health_timeout <= 3600:
            raise ValueError("health-timeout 须为1–3600秒")
        config = load_config(args.env_file)
        runtime = runtime_config(config)
        archive = prepare(runtime)
        print(
            f"部署包已准备：{archive}（{archive.stat().st_size // 1024} KiB）",
            flush=True,
        )
        print("运行配置仅含：" + ", ".join(runtime), flush=True)
        if args.prepare_only:
            print("仅打包完成，未连接服务器或数据库。", flush=True)
            return 0
        remote = config.get(
            "RECOMMENDATION_DEPLOY_PATH", "/opt/achievement-recommendation"
        )
        if (
            not re.fullmatch(r"/[a-zA-Z0-9_./-]+", remote)
            or ".." in Path(remote).parts
            or remote.strip("/") == ""
        ):
            raise ValueError("RECOMMENDATION_DEPLOY_PATH 须为专用的绝对目录")
        if Path(remote) == Path(
            config.get("DEPLOY_PATH", "/opt/achievement-dashboard")
        ):
            raise ValueError("推荐服务部署目录不能与 dashboard 部署目录相同")
        path = shlex.quote(remote)
        transfer(
            config,
            "run",
            REMOTE_CMD=f"umask 077; docker compose version >/dev/null && mkdir -p {path}",
        )
        transfer(config, "put", LOCAL_FILE=str(archive), REMOTE_PATH=remote)
        command = f"cd {path} && tar -xzf upload.tar.gz && rm upload.tar.gz && chmod 600 .env runtime.env && docker compose build"
        if args.refresh_data:
            command += " && docker compose run --rm recommendation --cache-root /runtime --prepare-only --refresh-data"
        command += " && docker compose up -d --force-recreate"
        transfer(config, "run", REMOTE_CMD=command)
        health = (
            "docker compose exec -T recommendation /app/.venv/bin/python /app/health.py"
        )
        transfer(
            config,
            "run",
            REMOTE_CMD=f"""cd {path} || exit 1
deadline=$(( $(date +%s) + {args.health_timeout} ))
while [ "$(date +%s)" -lt "$deadline" ]; do
  if {health} >/dev/null 2>&1; then docker compose ps; exit 0; fi
  sleep 5
done
docker compose logs --tail 40 recommendation
echo '推荐服务尚未就绪，请检查只读加载或图谱准备日志' >&2
exit 1""",
        )
        print(
            "推荐服务部署完成。面板连接配置为 RECOMMENDATION_HOST/PORT；单独运行 dashboard/deploy.sh 更新面板。"
        )
        return 0
    except ValueError as exc:
        print("推荐服务配置错误：" + str(exc), flush=True)
        return 1
    except (OSError, subprocess.CalledProcessError):
        # 部署配置含凭据，不打印可能包含其值的底层异常或完整环境。
        print(
            "推荐服务部署失败；请检查上述非敏感输出、配置项与服务器状态。", flush=True
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
