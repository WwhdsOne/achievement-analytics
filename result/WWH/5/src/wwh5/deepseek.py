"""Model-only annotations with auditable retries and exact successful-call resume.

**并行单位是「游戏」，不是「请求」**：不同游戏之间互不影响，而同一款游戏内批次
必须**严格串行**——第二批起要把第一批的 game_dimensions 原样重复回去，程序会校验
一致，不一致整批作废。所以并行只能在游戏粒度上做（见 ``run_labeling`` 的 workers）。

所有 SQLite 访问共用一条连接、由 ``db_lock`` 串行化：**网络请求在锁外，数据库操作
在锁内**。这样 N 路并发时只有短促的写库会排队，慢的网络等待不会互相阻塞。
使用这条连接时有一条硬约束：**每次持锁期间必须 commit 或 rollback，不允许把未提交
的事务带出临界区**，否则别的线程 commit 时会连带提交你写了一半的东西。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
import fcntl
import json
import math
import logging
from pathlib import Path
import sqlite3
import threading
import time
from typing import Callable, Iterator

import httpx

from . import config
from . import params
from . import storage

PROMPT_VERSION = "wwh5-ds-v3"
CATEGORIES = {"main", "side", "collection", "challenge", "other", "uncertain"}
GAMEPLAY = {
    "action",
    "adventure",
    "rpg",
    "strategy",
    "simulation",
    "puzzle",
    "platformer",
    "racing",
    "sports",
    "survival",
    "rhythm",
    "casual",
    "other",
    "uncertain",
}
SCOPES = {"base", "dlc", "uncertain"}
STAGES = {"start", "early", "middle", "late", "end"}
logger = logging.getLogger(__name__)


class FatalAPIError(RuntimeError):
    """Authentication, billing or configuration failure requiring the run to stop."""


class RequestLimit(RuntimeError):
    """Actual HTTP request budget exhausted, including failed attempts."""


def _confidence(value: object) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= 1
    ):
        raise ValueError("confidence must be a finite number in [0,1]")


def _text_fields(item: dict, uncertainty: bool = True) -> None:
    if not isinstance(item.get("evidence"), str) or not item["evidence"].strip():
        raise ValueError("evidence must be nonempty text")
    if uncertainty and not isinstance(item.get("uncertainty"), str):
        raise ValueError("uncertainty must be text")
    _confidence(item.get("confidence"))


def validate_classification(data: dict, ids: list[str]) -> dict:
    """Reject incomplete, duplicated, unknown or ill-typed classifications."""
    if not isinstance(data, dict) or not isinstance(data.get("game_dimensions"), dict):
        raise ValueError("game_dimensions object required")
    dims = data["game_dimensions"]
    for field in ("gameplay", "theme", "presentation", "player_mode"):
        if not isinstance(dims.get(field), list) or any(
            not isinstance(x, str) or not x.strip() for x in dims[field]
        ):
            raise ValueError(f"{field} must be a list of text labels")
        if len(set(dims[field])) != len(dims[field]):
            raise ValueError(f"{field} must not contain duplicate labels")
    if not dims["gameplay"] or not set(dims["gameplay"]) <= GAMEPLAY:
        raise ValueError("gameplay must use nonempty controlled coarse categories")
    _text_fields(dims)
    labels = data.get("achievements")
    if not isinstance(labels, list):
        raise ValueError("achievements must be an array")
    found = []
    for a in labels:
        if not isinstance(a, dict) or not isinstance(a.get("id"), str):
            raise ValueError("achievement id must be a string")
        found.append(a["id"])
        if a.get("primary_category") not in CATEGORIES or a.get("scope") not in SCOPES:
            raise ValueError("invalid category or scope")
        if (
            a.get("requires_multiplayer") is not None
            and type(a["requires_multiplayer"]) is not bool
        ):
            raise ValueError("requires_multiplayer must be boolean or null")
        if "requires_multiplayer" not in a:
            raise ValueError("requires_multiplayer required")
        _text_fields(a)
    if (
        len(found) != len(ids)
        or len(set(found)) != len(found)
        or set(found) != set(ids)
    ):
        raise ValueError("achievement coverage must match input IDs exactly once")
    return data


def validate_story(data: dict, ids: list[str]) -> dict:
    """Validate one global story selection; IDs are not plot order and may be omitted."""
    if not isinstance(data, dict) or type(data.get("unified_ending")) is not bool:
        raise ValueError("unified_ending must be boolean")
    _text_fields(data)
    points = data.get("checkpoints")
    if not isinstance(points, list):
        raise ValueError("checkpoints must be an ordered array")
    found = []
    for point in points:
        if not isinstance(point, dict) or not isinstance(point.get("id"), str):
            raise ValueError("checkpoint id must be text")
        found.append(point["id"])
        if point.get("stage") not in STAGES or point.get("route") not in {
            "common",
            "branch",
        }:
            raise ValueError("invalid stage or route")
        if type(point.get("requires_start")) is not bool:
            raise ValueError("requires_start must be boolean")
        _text_fields(point, uncertainty=False)
    if len(set(found)) != len(found) or not set(found) <= set(ids):
        raise ValueError("unknown or duplicate story checkpoint IDs")
    return data


def response_content(body: object) -> str:
    """Reject malformed or truncated chat envelopes as retryable validation failures."""
    if not isinstance(body, dict):
        raise ValueError("response body must be an object")
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ValueError("choices must contain a choice object")
    choice = choices[0]
    if choice.get("finish_reason") != "stop":
        raise ValueError("incomplete/truncated model output")
    message = choice.get("message")
    if not isinstance(message, dict):
        raise ValueError("choice message must be an object")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("choice content must be nonempty text")
    return content


def prompt_input(game: dict, achievements: list[dict]) -> dict:
    """Strict allowlist: titles, tags and display text; never outcome variables."""
    tags = [
        tag["tag"] if isinstance(tag, dict) else tag for tag in game.get("tags", [])
    ]
    return {
        "title": game["name_en"],
        "localized_title": game.get("name_zh"),
        "tags": tags,
        "achievements": [
            {
                "id": str(a["local_id"]),
                "display_name": a["display_name"],
                "description": a.get("description") or "",
            }
            for a in achievements
        ],
    }


def classification_messages(
    game: dict, achievements: list[dict], dimensions: dict | None = None
) -> list[dict]:
    """Build JSON-mode classification instructions without heuristics or outcome leakage."""
    example = {
        "game_dimensions": {
            "gameplay": ["uncertain"],
            "theme": [],
            "presentation": [],
            "player_mode": [],
            "confidence": 0.5,
            "evidence": "supplied text",
            "uncertainty": "explain",
        },
        "achievements": [
            {
                "id": "input-id",
                "primary_category": "uncertain",
                "scope": "uncertain",
                "requires_multiplayer": None,
                "confidence": 0.5,
                "evidence": "supplied text",
                "uncertainty": "explain",
            }
        ],
    }
    instruction = (
        "Return one valid json object, no markdown. Classify every supplied achievement ID exactly once. "
        "primary_category enum main/side/collection/challenge/other/uncertain; scope base/dlc/uncertain; "
        "requires_multiplayer boolean or null. Derive gameplay/theme/presentation/player_mode dimensions "
        "as lists of labels. Confidence is a number [0,1]. Every label has evidence and uncertainty text. "
        "gameplay is a CLOSED ENUM, not free text: it must be nonempty and every entry must be exactly one "
        "of action/adventure/rpg/strategy/simulation/puzzle/platformer/racing/sports/survival/rhythm/casual/"
        "other/uncertain. Never copy store tags into gameplay — values such as sandbox, crafting, building, "
        "exploration or open world are NOT enum members; map that tag to the closest enum value "
        "(e.g. survival, simulation, adventure) or use other. theme/presentation/player_mode are free text "
        "and may keep the original tag wording. Put the PRIMARY gameplay first, others secondary. "
        "All dimension lists have unique labels; use uncertain gameplay rather than an empty list. "
        "Use supplied achievement display text and tags and your uncertain model knowledge; disclose uncertainty. "
        "Do not invent citations, URLs, or claims of human validation. IDs are surrogate keys, NOT story order. "
        "Use uncertain when evidence is weak; multiplayer is an independent attribute, not a category. "
        "Game dimensions are authoritative from the first batch; if supplied, repeat them exactly. "
        "Reminder: gameplay may contain ONLY enum values from the list above. "
        "Output json example: " + storage.canonical(example)
    )
    payload = prompt_input(game, achievements)
    if dimensions is not None:
        payload["authoritative_game_dimensions"] = dimensions
    return [
        {"role": "system", "content": instruction},
        {"role": "user", "content": storage.canonical(payload)},
    ]


def story_messages(game: dict, achievements: list[dict]) -> list[dict]:
    """Choose checkpoints once from ALL main candidates, preserving narrative order."""
    example = {
        "checkpoints": [
            {
                "id": "input-id",
                "stage": "start",
                "route": "common",
                "requires_start": False,
                "confidence": 0.5,
                "evidence": "supplied text",
            }
        ],
        "unified_ending": False,
        "confidence": 0.5,
        "evidence": "supplied text",
        "uncertainty": "explain",
    }
    instruction = (
        "Return valid json only. These are ALL main-story candidates for one game. Select global ordered "
        "checkpoints by narrative prerequisites, never by ID order. stage enum start/early/middle/late/end; "
        "route common/branch. requires_start means this checkpoint necessarily requires the chosen start. "
        "Choose at most one explicit start and one unified common ending; if separate endings cannot be "
        "represented by one achievement, unified_ending=false. Never merge/sum alternative endings. "
        "If no defensible linear story exists (sandbox/live service etc.), return empty checkpoints and "
        "unified_ending=false. Select only supplied IDs, each at most once; omission is allowed. "
        "Confidence number [0,1], evidence text, disclose uncertain model knowledge. No fake citations or "
        "human-validation claims. The complete candidate set is supplied in this ONE call. json example: "
        + storage.canonical(example)
    )
    return [
        {"role": "system", "content": instruction},
        {
            "role": "user",
            "content": storage.canonical(prompt_input(game, achievements)),
        },
    ]


class DeepSeekClient:
    """Thin injectable synchronous HTTP transport; retries and persistence live in the runner."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        prompt_version: str = PROMPT_VERSION,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.api_key = config.DEEPSEEK_API_KEY if api_key is None else api_key
        self.model = model or config.DEEPSEEK_MODEL
        self.base_url = (base_url or config.DEEPSEEK_BASE_URL).rstrip("/")
        self.prompt_version = prompt_version
        self.sleep = sleep
        self.http = httpx.Client(
            transport=transport, timeout=httpx.Timeout(120, connect=10)
        )

    def close(self) -> None:
        """Close the underlying transport."""
        self.http.close()

    def request(self, messages: list[dict]) -> httpx.Response:
        """Issue exactly one request without ever persisting credentials."""
        return self.http.post(
            self.base_url + "/chat/completions",
            headers={"Authorization": "Bearer " + self.api_key},
            json={
                "model": self.model,
                "messages": messages,
                "response_format": {"type": "json_object"},
                "thinking": {"type": "disabled"},
                "temperature": params.TEMPERATURE,
                "max_tokens": params.MAX_TOKENS,
            },
        )


@contextmanager
def _run_lock(path: str | Path) -> Iterator[None]:
    lock = Path(str(storage.owned_path(path)) + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError(
                "Another labeling process holds this SQLite lock"
            ) from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _successful(
    conn: sqlite3.Connection, appid: int, model: str, version: str, input_hash: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM model_calls WHERE appid=? AND model=? AND prompt_version=? AND input_hash=? AND status='success' ORDER BY id DESC LIMIT 1",
        (appid, model, version, input_hash),
    ).fetchone()


def _execute(
    conn: sqlite3.Connection,
    db_lock: threading.Lock,
    game: dict,
    kind: str,
    messages: list[dict],
    validate: Callable[[dict], dict],
    client: DeepSeekClient,
    budget: dict,
    save: Callable[[int, dict], None],
) -> dict | None:
    """发一次调用（含重试）。

    锁的边界：**查库/写库在 ``db_lock`` 内，网络请求在锁外**——否则慢请求会把
    其他线程的数据库操作全堵住，并行等于没做。
    """
    input_hash = storage.digest(messages)
    with db_lock:
        prior = _successful(
            conn, game["appid"], client.model, client.prompt_version, input_hash
        )
    if prior:
        body = json.loads(prior["response_body"])
        return json.loads(body["choices"][0]["message"]["content"])
    if not client.api_key:
        raise RuntimeError(
            "DEEPSEEK_API_KEY is required for label; export/status/dry-run do not need it"
        )
    for attempt in range(1, params.MAX_ATTEMPTS + 1):
        # 「判断还有没有名额」和「占用一个名额」必须在同一个锁里做完，
        # 否则 N 个线程会同时看到还剩 1 个名额，一起发出去造成超发。
        with budget["lock"]:
            if budget["limit"] is not None and budget["requests"] >= budget["limit"]:
                raise RequestLimit()
            budget["requests"] += 1
            used = budget["requests"]
        with db_lock:
            cur = conn.execute(
                "INSERT INTO model_calls(appid,kind,model,prompt_version,input_hash,request_messages,status,attempt,started_at) VALUES (?,?,?,?,?,?,'running',?,?)",
                (
                    game["appid"],
                    kind,
                    client.model,
                    client.prompt_version,
                    input_hash,
                    storage.canonical(messages),
                    attempt,
                    storage.now(),
                ),
            )
            call_id = cur.lastrowid
            conn.commit()  # 立刻提交：running 行要能被别的线程/进程看到
        logger.info(
            "appid=%s %s request=%s attempt=%s",
            game["appid"],
            kind,
            used,
            attempt,
        )
        body_text, usage, delay, http_status = (
            None,
            None,
            params.RETRY_BACKOFF_BASE**attempt,
            None,
        )
        fatal = False
        try:
            response = client.request(messages)  # 网络：不持 db_lock
            http_status = response.status_code
            body_text = response.text.replace(client.api_key, "[REDACTED]")
            try:
                raw_usage = response.json().get("usage", {})
                usage = storage.canonical(storage.numeric_usage(raw_usage)).replace(
                    client.api_key, "[REDACTED]"
                )
            except (ValueError, AttributeError, TypeError):
                pass
            if response.status_code in (400, 401, 402, 403, 404, 422):
                fatal = True
                raise FatalAPIError(
                    f"DeepSeek HTTP {response.status_code}: authentication/payment/configuration failure"
                )
            if response.status_code != 200:
                try:
                    delay = min(
                        params.RETRY_MAX_WAIT_SEC,
                        max(delay, float(response.headers.get("Retry-After", "0"))),
                    )
                except ValueError:
                    pass
                raise ValueError(f"DeepSeek HTTP {response.status_code}")
            body = response.json()
            result = validate(json.loads(response_content(body)))
            if client.api_key in storage.canonical(result):
                raise ValueError("response contains secret material")
            # 标签写入与调用状态更新在同一事务，断点后不会重复付费已成功的请求
            with db_lock, conn:
                conn.execute(
                    "UPDATE model_calls SET status='success',response_body=?,usage=?,finished_at=? WHERE id=?",
                    (body_text, usage, storage.now(), call_id),
                )
                save(call_id, result)
            logger.info("appid=%s %s success", game["appid"], kind)
            return result
        except (
            httpx.HTTPError,
            ValueError,
            KeyError,
            IndexError,
            TypeError,
            FatalAPIError,
        ) as exc:
            # Never serialize transport exception text: request URLs/error bodies may contain secrets.
            error = (
                str(exc)
                if isinstance(exc, FatalAPIError)
                else (
                    f"HTTP {http_status}; {type(exc).__name__}: response validation failed"
                    if http_status is not None
                    else f"{type(exc).__name__}: transport failed"
                )
            )
            with db_lock, conn:
                conn.execute(
                    "UPDATE model_calls SET status='error',response_body=?,usage=?,error=?,finished_at=? WHERE id=?",
                    (body_text, usage, error, storage.now(), call_id),
                )
            logger.warning(
                "appid=%s %s attempt=%s %s", game["appid"], kind, attempt, error
            )
            if fatal:
                raise
            if attempt < params.MAX_ATTEMPTS:
                with budget["lock"]:
                    exhausted = (
                        budget["limit"] is not None
                        and budget["requests"] >= budget["limit"]
                    )
                if exhausted:
                    raise RequestLimit()
                client.sleep(delay)
        except BaseException:
            with db_lock, conn:
                conn.execute(
                    "UPDATE model_calls SET status='interrupted',error='interrupted',finished_at=? WHERE id=?",
                    (storage.now(), call_id),
                )
            raise
    return None


def _dimensions(conn: sqlite3.Connection, appid: int) -> dict | None:
    row = conn.execute(
        "SELECT payload FROM game_labels WHERE appid=?", (appid,)
    ).fetchone()
    return json.loads(row[0]) if row else None


def _select_games(
    games: list[dict], max_games: int | None, result: dict, stats_lock: threading.Lock
) -> list[dict]:
    """按 frame_rank 顺序挑出要处理的游戏。

    被 blocked_reason 挡住的只计数、不处理，也**不占用 ``--max-games`` 名额**
    ——保持「先固定排名再记录缺口、不用下一名递补」的样本口径。
    """
    todo: list[dict] = []
    for game in games:
        if storage.blocked_reason(game):
            with stats_lock:
                result["blocked"] += 1
            continue
        if max_games is not None and len(todo) >= max_games:
            break
        todo.append(game)
    return todo


def _process_game(
    conn: sqlite3.Connection,
    db_lock: threading.Lock,
    game: dict,
    client: DeepSeekClient,
    budget: dict,
    batch_size: int,
    dry_run: bool,
    result: dict,
    stats_lock: threading.Lock,
) -> None:
    """处理一款游戏：先分批分类，全部成功后再排一次主线。

    ⚠️ 批次必须**串行**：第二批起要把第一批的 ``game_dimensions`` 原样带回，校验
    不一致整批作废。所以并行只能在游戏之间做（见 ``run_labeling``），不能在游戏内做。
    """
    appid = game["appid"]
    labels = game["achievements"]
    with db_lock:
        dims = _dimensions(conn, appid)
    failed = False
    for offset in range(0, len(labels), batch_size):
        batch = labels[offset : offset + batch_size]
        messages = classification_messages(game, batch, None if offset == 0 else dims)
        with db_lock:
            prior = _successful(
                conn,
                appid,
                client.model,
                client.prompt_version,
                storage.digest(messages),
            )
        if prior:
            # 已成功过：直接复用已存响应，不发请求（断点续跑靠这条，也避免重复付费）
            if offset == 0:
                dims = json.loads(
                    json.loads(prior["response_body"])["choices"][0]["message"][
                        "content"
                    ]
                )["game_dimensions"]
            continue
        with stats_lock:
            result["pending_batch_calls"] += 1
        if dry_run:
            continue

        # 用默认参数绑定本轮的值，避免闭包在并发下取到别的批次
        def validator(
            data: dict, batch: list = batch, offset: int = offset, dims: dict = dims
        ) -> dict:
            validate_classification(data, [str(a["local_id"]) for a in batch])
            if offset > 0 and data["game_dimensions"] != dims:
                raise ValueError("game dimensions changed between batches")
            return data

        def save(
            call_id: int, data: dict, offset: int = offset, appid: int = appid
        ) -> None:
            if offset == 0:
                conn.execute(
                    "INSERT OR REPLACE INTO game_labels VALUES (?,?,?)",
                    (appid, call_id, storage.canonical(data["game_dimensions"])),
                )
            for a in data["achievements"]:
                conn.execute(
                    "INSERT OR REPLACE INTO achievement_labels VALUES (?,?,?,?)",
                    (appid, a["id"], call_id, storage.canonical(a)),
                )

        data = _execute(
            conn,
            db_lock,
            game,
            "classification",
            messages,
            validator,
            client,
            budget,
            save,
        )
        if data is None:
            # 3 次都没过校验：记 error，该游戏本轮不排主线，下次重跑再补
            with stats_lock:
                result["errors"] += 1
            failed = True
            break
        if offset == 0:
            dims = data["game_dimensions"]
    if failed:
        return
    with db_lock:
        existing_story = conn.execute(
            "SELECT 1 FROM story_labels WHERE appid=?", (appid,)
        ).fetchone()
    if existing_story:
        return
    with stats_lock:
        result["pending_story_calls"] += 1
    if dry_run:
        # 分类批次数是精确值；主线每款待标注游戏算 1 次是**上界估计**
        # （只有被判为 main 的候选才发，而 main 数要分类完才知道）
        return
    with db_lock:
        known = {
            row[0]: json.loads(row[1])
            for row in conn.execute(
                "SELECT local_id,payload FROM achievement_labels WHERE appid=?",
                (appid,),
            )
        }
    candidates = [
        a for a in labels if known[a["local_id"]]["primary_category"] == "main"
    ]
    messages = story_messages(game, candidates)

    def save_story(call_id: int, data: dict, appid: int = appid) -> None:
        conn.execute(
            "INSERT OR REPLACE INTO story_labels VALUES (?,?,?)",
            (appid, call_id, storage.canonical(data)),
        )

    data = _execute(
        conn,
        db_lock,
        game,
        "story",
        messages,
        lambda data, candidates=candidates: validate_story(
            data, [a["local_id"] for a in candidates]
        ),
        client,
        budget,
        save_story,
    )
    if data is None:
        with stats_lock:
            result["errors"] += 1


def run_labeling(
    path: str | Path = storage.DEFAULT_DB,
    *,
    client: DeepSeekClient | None = None,
    dry_run: bool = False,
    batch_size: int = params.LABEL_BATCH_SIZE,
    max_requests: int | None = None,
    max_games: int | None = None,
    workers: int = params.LABEL_WORKERS,
) -> dict:
    """Resume model calls under a process lock; cap ACTUAL requests including retries.

    ``workers`` 是**并行处理的游戏数**，不是并发请求数的硬上限：重试会让瞬时请求数
    略高于它。``workers=1`` 与旧的串行行为完全一致。

    为什么按游戏并行而不是按请求：同一款游戏的批次必须串行（见 ``_process_game``）。
    不同游戏之间没有任何共享状态，所以并行不会改变结果，只是把等待时间重叠起来。

    预算（``max_requests``，含重试）由 ``budget["lock"]`` 保证原子占用，并发下不会超发。
    致命错误（认证/计费）会取消其余游戏的提交并向上抛出；``RequestLimit`` 只标记
    ``request_limit_reached``，已完成的部分照常保留（本来就支持断点续跑）。
    """
    if (
        batch_size < 1
        or (max_requests is not None and max_requests < 0)
        or (max_games is not None and max_games < 1)
        or workers < 1
    ):
        raise ValueError("Invalid batch/request/game/worker limit")
    owned_client = client is None
    client = client or DeepSeekClient()
    # budget 三个字段：limit 上限、requests 已用、lock 保护「判断+占用」的原子性
    budget = {"limit": max_requests, "requests": 0, "lock": threading.Lock()}
    db_lock = threading.Lock()
    stats_lock = threading.Lock()
    result = {
        "requests": 0,
        "errors": 0,
        "blocked": 0,
        "pending_batch_calls": 0,
        "pending_story_calls": 0,
        "story_count_is_estimate": True,
    }
    try:
        with _run_lock(path), storage.connect(path, check_same_thread=False) as conn:
            meta = storage.metadata(conn)
            if not meta.get("dataset_version"):
                raise RuntimeError("Run export first: no frozen dataset version")
            binding = {
                "model": client.model,
                "prompt_version": client.prompt_version,
                "batch_size": batch_size,
            }
            if meta.get("active_annotation") and meta["active_annotation"] != binding:
                raise RuntimeError(
                    "Active model/prompt version or batch size differs; use a separate --db"
                )
            games = storage.load_games(conn)
            if not dry_run and max_requests != 0 and not client.api_key:
                pending = any(
                    not storage.blocked_reason(g)
                    and not conn.execute(
                        "SELECT 1 FROM story_labels WHERE appid=?", (g["appid"],)
                    ).fetchone()
                    for g in games
                )
                if pending:
                    raise RuntimeError("DEEPSEEK_API_KEY is required for label")
            if not dry_run and max_requests != 0:
                storage.put_metadata(conn, "active_annotation", binding)
                conn.execute(
                    "UPDATE model_calls SET status='interrupted',error='recovered interrupted run',finished_at=? WHERE status='running'",
                    (storage.now(),),
                )
                conn.commit()
            selected = _select_games(games, max_games, result, stats_lock)
            if dry_run or workers == 1:
                # dry_run 只扫描本地库、不发请求，并行没有意义，一律串行
                if not dry_run:
                    logger.info("开始标注：%s 款游戏，串行（workers=1）", len(selected))
                for index, game in enumerate(selected, 1):
                    if not dry_run:
                        logger.info(
                            "game=%s/%s appid=%s", index, len(selected), game["appid"]
                        )
                    _process_game(
                        conn,
                        db_lock,
                        game,
                        client,
                        budget,
                        batch_size,
                        dry_run,
                        result,
                        stats_lock,
                    )
            else:
                lanes = min(workers, len(selected))
                logger.info(
                    "开始标注：%s 款游戏，%s 路并行（同一游戏内批次仍串行）",
                    len(selected),
                    lanes,
                )
                with ThreadPoolExecutor(
                    max_workers=lanes, thread_name_prefix="label"
                ) as pool:
                    futures = [
                        pool.submit(
                            _process_game,
                            conn,
                            db_lock,
                            game,
                            client,
                            budget,
                            batch_size,
                            False,
                            result,
                            stats_lock,
                        )
                        for game in selected
                    ]
                    try:
                        for future in as_completed(futures):
                            future.result()  # 把子线程里的异常在主线程重新抛出
                    except (RequestLimit, FatalAPIError):
                        # 预算用尽或认证/计费错误：不再开新的游戏，
                        # 已发出的请求等它收尾（取消只对「还没开始」的生效）
                        for future in futures:
                            future.cancel()
                        raise
    except RequestLimit:
        result["request_limit_reached"] = True
    finally:
        if owned_client:
            client.close()
    result["requests"] = budget["requests"]
    return result
