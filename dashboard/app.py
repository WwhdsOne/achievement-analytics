"""dashboard.app — 数据抓取状态面板（内部工具）

一个零额外依赖的小型 web 应用（仅用标准库 http.server），给全组看两件事：

1. **队列还剩多少活**：总任务数、各状态分布、逐源进度（读 ``ingest_progress`` 视图）
2. **单款游戏查询与补抓**：输入 appid 查它的任务状态；若还没爬，点一下
   「立即抓取」——补进 ``fetch_tasks`` 任务队列后用 worker 机制立刻处理
   （复用 :func:`cleaning.worker.run` 的原子抢占，与跑批的机器完全同一路径，
   **不是**绕开队列的野路子）

启动::

    uv run python -m dashboard.app            # 默认 127.0.0.1:8600
    uv run python -m dashboard.app --port 8600 --host 0.0.0.0

设计要点：
- **任务式补抓**：新 appid 先补一行最小 ``games`` 记录（FK 要求），再物化该游戏的
  全部任务，后台线程跑一次 ``worker.run(appid=...)``；SteamSpy 因 Cloudflare
  challenge 临时排除（见 cleaning.worker / learning-logs/2026-09-22.md）
- **单飞锁**：同一时刻只允许一个补抓任务在跑，避免 recorder 全局状态互相覆盖
- 面板只读，唯一的写路径就是「补抓」——不会碰 DDL，不会动任务以外的数据
"""

from __future__ import annotations

import argparse
import json
import logging
import threading
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from sqlalchemy import text

from cleaning.db import get_engine
from cleaning.seed import materialize_tasks
from cleaning.worker import run as worker_run

logger = logging.getLogger(__name__)

INDEX_HTML = Path(__file__).resolve().parent / "index.html"

# 补抓时的默认排除源（当前为空：SteamSpy 已恢复且取消了自设日限，
# 保留这个常量是为了临时挂起某个源时改一行即可）
DEFAULT_EXCLUDE: set[str] = set()

# 单飞锁：同一时刻最多一个「立即抓取」任务
_fetch_lock = threading.Lock()
_fetch_state: dict[str, Any] = {"appid": None, "started_at": None, "error": None}


def _stats_payload() -> dict[str, Any]:
    """队列总览：各状态计数 + 逐源进度（复用 ingest_progress 视图）。"""
    engine = get_engine()
    with engine.connect() as conn:
        by_status = {
            r[0]: int(r[1])
            for r in conn.execute(
                text("SELECT status, count(*) FROM fetch_tasks GROUP BY status")
            )
        }
        total = conn.execute(text("SELECT count(*) FROM fetch_tasks")).scalar()
        games_total = conn.execute(text("SELECT count(*) FROM games")).scalar()
        sources = [
            {
                "source": r[0], "total": r[1], "ok": r[2], "empty": r[3],
                "skipped": r[4], "error": r[5], "exhausted": r[6],
                "pending": r[7], "actionable": r[8],
            }
            for r in conn.execute(
                text(
                    "SELECT source, total, ok, empty, skipped, error, exhausted,"
                    " pending, actionable FROM ingest_progress WHERE total > 0"
                    " ORDER BY source"
                )
            )
        ]
    return {
        "total": int(total),
        "games": int(games_total),
        "by_status": by_status,
        "sources": sources,
        "remaining": by_status.get("pending", 0) + by_status.get("error", 0),
        "fetching": dict(_fetch_state),
    }


def _game_payload(appid: int) -> dict[str, Any] | None:
    """单款游戏状态：任务分布、逐源数据落地、全部成就清单。"""
    engine = get_engine()
    with engine.connect() as conn:
        game = conn.execute(
            text("SELECT appid, name_en, name_zh FROM games WHERE appid = :a"),
            {"a": appid},
        ).first()
        tasks = {
            r[0]: {"source": r[0], "status": r[1], "attempts": r[2], "error": r[3]}
            for r in conn.execute(
                text(
                    "SELECT source, status, attempts, last_error FROM fetch_tasks"
                    " WHERE appid = :a"
                ),
                {"a": appid},
            )
        }
        ach = conn.execute(
            text(
                "SELECT position, api_name, display_name, percent FROM achievements"
                " WHERE appid = :a ORDER BY position"
            ),
            {"a": appid},
        ).all()
        counts = {
            "achievements": len(ach),
            "appdetails": int(conn.execute(
                text("SELECT count(*) FROM steam_appdetails WHERE appid = :a"),
                {"a": appid},
            ).scalar()),
            "steamspy": int(conn.execute(
                text("SELECT count(*) FROM steamspy_games WHERE appid = :a"),
                {"a": appid},
            ).scalar()),
            "rawg": int(conn.execute(
                text("SELECT count(*) FROM rawg_games WHERE appid = :a"), {"a": appid}
            ).scalar()),
            "tags": int(conn.execute(
                text("SELECT count(*) FROM game_tags WHERE appid = :a"), {"a": appid}
            ).scalar()),
        }
        last_log = conn.execute(
            text("SELECT max(fetched_at) FROM ingest_log WHERE appid = :a"),
            {"a": appid},
        ).scalar()
        # 三张信息表的完整行（查得到才有 key），日期转字符串保证可 JSON 序列化
        app_row = conn.execute(
            text(
                "SELECT type, is_free, price_cents, release_date, developers,"
                " publishers, valve_genres, valve_categories, recommendations"
                " FROM steam_appdetails WHERE appid = :a"
            ),
            {"a": appid},
        ).mappings().first()
        spy_row = conn.execute(
            text(
                "SELECT owners, ccu, positive, negative, average_forever,"
                " median_forever FROM steamspy_games WHERE appid = :a"
            ),
            {"a": appid},
        ).mappings().first()
        rawg_row = conn.execute(
            text(
                "SELECT metacritic, rating, ratings_count, genres, playtime,"
                " added_count, status_yet, status_owned, status_beaten,"
                " status_toplay, status_dropped, status_playing"
                " FROM rawg_games WHERE appid = :a"
            ),
            {"a": appid},
        ).mappings().first()

    def _jsonable(row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        out = {}
        for k, v in dict(row).items():
            if hasattr(v, "isoformat"):
                v = v.isoformat()
            elif isinstance(v, Decimal):  # NUMERIC 列（如 rating）默认是 Decimal
                v = float(v)
            out[k] = v
        return out

    if game is None and not tasks:
        return None

    # 逐源数据落地：任务状态 + 对应数据表是否有行。ok 但表空、或任务未到终态
    # 都算「缺失」，面板上一眼看出还缺哪个源。
    data_of = {
        "appdetails_en": counts["appdetails"], "appdetails_zh": counts["appdetails"],
        "global_ach": counts["achievements"], "community_ach": counts["achievements"],
        "steamspy": counts["steamspy"], "rawg": counts["rawg"],
    }
    source_rows = []
    for source in ("appdetails_en", "appdetails_zh", "global_ach",
                   "community_ach", "steamspy", "rawg"):
        t = tasks.get(source)
        status = t["status"] if t else "no_task"
        data = data_of[source] > 0
        missing = status in ("pending", "error", "exhausted", "no_task") or (
            status == "ok" and not data
        )
        source_rows.append({
            "source": source, "status": status,
            "attempts": t["attempts"] if t else 0,
            "error": t["error"] if t else None,
            "data": data, "missing": missing,
        })

    return {
        "appid": appid,
        "name": game[1] if game else None,
        "name_zh": (game[2] if game and len(game) > 2 else None),
        "in_frame": game is not None,
        "tasks": sorted(tasks.values(), key=lambda t: t["source"]),
        "sources": source_rows,
        "missing_sources": [s["source"] for s in source_rows if s["missing"]],
        "achievements_list": [
            {"position": r[0], "api_name": r[1], "display_name": r[2],
             "percent": float(r[3])}
            for r in ach
        ],
        "counts": counts,
        "appdetails": _jsonable(app_row),
        "steamspy": _jsonable(spy_row),
        "rawg": _jsonable(rawg_row),
        "last_fetched_at": last_log.isoformat() if last_log else None,
        "fetching": _fetch_state["appid"] == appid and _fetch_lock.locked(),
    }


def _crawl_job(appid: int) -> None:
    """后台线程：用 worker 机制处理这一款游戏的全部任务（单飞锁内）。"""
    try:
        engine = get_engine()
        worker_run(engine, appid=appid, exclude=DEFAULT_EXCLUDE)
        _fetch_state["error"] = None
    except Exception as exc:  # noqa: BLE001 — 后台线程兜底，状态要能被前端看到
        logger.exception("补抓 appid=%s 失败", appid)
        _fetch_state["error"] = str(exc)[:300]
    finally:
        _fetch_lock.release()


def _enqueue_crawl(appid: int) -> dict[str, Any]:
    """把一款游戏补进队列并立即用 worker 机制处理。

    流程：games 无此行 → 先抓一次 appdetails 拿官方名补最小记录（FK 要求）；
    物化该游戏 × 逐款源的任务；起后台线程跑 ``worker.run(appid=...)``。
    """
    if not _fetch_lock.acquire(blocking=False):
        busy = _fetch_state.get("appid")
        return {"ok": False, "error": f"已有补抓任务在跑（appid={busy}），稍后再试"}

    _fetch_state.update(appid=appid, started_at=None, error=None)
    try:
        engine = get_engine()
        with engine.begin() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM games WHERE appid = :a"), {"a": appid}
            ).first()
        name = None
        if not exists:
            # 未入库的游戏：抓一次 appdetails 拿官方名，补最小 games 行
            from crawler.steam_api import fetch_appdetails

            data = fetch_appdetails([appid]).get(str(appid))
            if not data or not data.get("name"):
                return {"ok": False, "error": f"appid={appid} 在 Steam 上不存在或无商店页"}
            name = data["name"]
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO games (appid, name_en) VALUES (:a, :n)"
                        " ON CONFLICT (appid) DO NOTHING"
                    ),
                    {"a": appid, "n": name},
                )
        created = materialize_tasks(engine, [appid])
        threading.Thread(target=_crawl_job, args=(appid,), daemon=True).start()
        return {"ok": True, "created_tasks": created, "name": name, "fetching": True}
    except Exception:
        _fetch_lock.release()  # 线程没起来，锁要还回去
        raise


def _genres_payload() -> dict[str, Any]:
    """游戏类型词云数据：把 ``valve_genres`` 摊平计数（Steam 官方类型）。

    覆盖面随全量抓取实时增长——已抓 appdetails 的游戏才计入。
    """
    engine = get_engine()
    with engine.connect() as conn:
        genres = [
            {"genre": r[0], "count": int(r[1])}
            for r in conn.execute(
                text(
                    "SELECT genre, count(*) AS n FROM steam_appdetails,"
                    " unnest(valve_genres) AS genre"
                    " GROUP BY 1 ORDER BY 2 DESC"
                )
            )
        ]
        total = int(conn.execute(
            text(
                "SELECT count(*) FROM steam_appdetails"
                " WHERE array_length(valve_genres, 1) > 0"
            )
        ).scalar())
    return {"games_with_genres": total, "genres": genres}


def _tags_payload() -> dict[str, Any]:
    """SteamSpy 玩家标签词云数据：按「带该标签的游戏数」聚合。

    与 ``valve_genres``（官方类型，粗粒度）互补——这里是玩家自己打的细粒度标签
    （Souls-like / Metacritic / Atmospheric / Difficult 这类），随 SteamSpy 抓取增长。
    实测 SteamSpy 标签集不含「Steam Achievements」这类平台元数据，
    故不做过虑。
    """
    engine = get_engine()
    with engine.connect() as conn:
        tags = [
            {"tag": r[0], "games": int(r[1]), "votes": int(r[2] or 0)}
            for r in conn.execute(
                text(
                    "SELECT tag, count(*) AS games, coalesce(sum(votes), 0) AS votes"
                    " FROM game_tags WHERE source = 'steamspy'"
                    " GROUP BY tag ORDER BY games DESC"
                )
            )
        ]
        covered = int(conn.execute(
            text("SELECT count(DISTINCT appid) FROM game_tags WHERE source = 'steamspy'")
        ).scalar())
    return {"games_with_tags": covered, "tags": tags}


class Handler(BaseHTTPRequestHandler):
    """极简路由：/（面板）/api/progress /api/game /api/game/crawl。"""

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: Any, code: int = 200) -> None:
        self._send(
            code, json.dumps(payload, ensure_ascii=False).encode(), "application/json"
        )

    def do_GET(self) -> None:  # noqa: N802 — http.server 命名约定
        url = urlparse(self.path)
        try:
            if url.path == "/":
                self._send(200, INDEX_HTML.read_bytes(), "text/html; charset=utf-8")
            elif url.path == "/api/progress":
                self._json(_stats_payload())
            elif url.path == "/api/genres":
                self._json(_genres_payload())
            elif url.path == "/api/tags":
                self._json(_tags_payload())
            elif url.path == "/api/game":
                appid = int(parse_qs(url.query).get("appid", ["0"])[0])
                payload = _game_payload(appid)
                if payload is None:
                    self._json({"error": f"appid={appid} 不在库中"}, 404)
                else:
                    self._json(payload)
            else:
                self._json({"error": "not found"}, 404)
        except Exception as exc:  # noqa: BLE001 — API 层兜底，别让面板 500 白屏
            logger.exception("GET %s 失败", self.path)
            self._json({"error": str(exc)[:300]}, 500)

    def do_POST(self) -> None:  # noqa: N802
        try:
            if urlparse(self.path).path != "/api/game/crawl":
                self._json({"error": "not found"}, 404)
                return
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            appid = int(body.get("appid", 0))
            if appid <= 0:
                self._json({"error": "appid 必须是正整数"}, 400)
                return
            self._json(_enqueue_crawl(appid))
        except Exception as exc:  # noqa: BLE001
            logger.exception("POST %s 失败", self.path)
            self._json({"error": str(exc)[:300]}, 500)

    def log_message(self, fmt: str, *args: Any) -> None:  # 安静模式
        logger.debug(fmt, *args)


def main() -> None:
    """CLI 入口。"""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="数据抓取状态面板")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认仅本机）")
    parser.add_argument("--port", type=int, default=8600)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"面板已启动：http://{args.host}:{args.port}  （Ctrl-C 退出）")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")


if __name__ == "__main__":
    main()
