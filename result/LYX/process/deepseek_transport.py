"""串行 DeepSeek 请求的可取消传输、总时限与等待进度；不读写业务文件。"""

from __future__ import annotations

import asyncio
import codecs
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx


Progress = dict[str, Any]


@dataclass(frozen=True)
class HTTPResult:
    """已经完整接收并关闭响应后的 HTTP 结果。"""

    status_code: int
    text: str
    retry_after: str


class TransportTimeout(Exception):
    """保留总时限或读取超时现场；部分正文不能作为完整响应复用。"""

    def __init__(self, kind: str, progress: Progress, partial_response_text: str) -> None:
        """保存超时种类、进度副本和已接收正文。"""
        self.kind = kind
        self.progress = dict(progress)
        self.partial_response_text = partial_response_text
        label = "请求总时限" if kind == "total" else "网络读取超时"
        super().__init__(f"{label}，已等待 {progress.get('elapsed_seconds', 0):.1f} 秒")


class AsyncHTTPTransport:
    """在同一惰性事件循环内复用客户端，提供同步入口和可靠取消。"""

    def __init__(
        self,
        read_timeout_seconds: float = 300,
        connect_timeout_seconds: float = 15,
        progress_interval_seconds: float = 15,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """配置网络时限和心跳间隔；构造时不创建连接或事件循环。"""
        if read_timeout_seconds <= 0 or connect_timeout_seconds <= 0 or progress_interval_seconds <= 0:
            raise ValueError("传输超时与进度间隔必须大于 0")
        self.read_timeout_seconds = read_timeout_seconds
        self.connect_timeout_seconds = connect_timeout_seconds
        self.progress_interval_seconds = progress_interval_seconds
        self._transport = transport
        self._runner: asyncio.Runner | None = None
        self._client: httpx.AsyncClient | None = None
        self.last_progress: Progress = {}
        self.partial_response_text = ""

    def request(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
        deadline: float,
        started_monotonic: float,
        on_progress: Callable[[Progress], None],
    ) -> HTTPResult:
        """接收完整响应；绝对总时限由调用者给定，可覆盖多次尝试与退避。"""
        if self._runner is None:
            self._runner = asyncio.Runner()
        return self._runner.run(self._request(
            url,
            headers=headers,
            payload=payload,
            deadline=deadline,
            started_monotonic=started_monotonic,
            on_progress=on_progress,
        ))

    def close(self) -> None:
        """关闭客户端再关闭其所属事件循环；没有初始化时无操作。"""
        runner = self._runner
        if runner is None:
            return
        try:
            runner.run(self._close_client())
        finally:
            runner.close()
            self._runner = None
            self._client = None

    async def _close_client(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    def _snapshot(self, *, deadline: float, started_monotonic: float) -> Progress:
        now = time.monotonic()
        self.last_progress.update({
            "elapsed_seconds": round(max(0.0, now - started_monotonic), 3),
            "remaining_seconds": round(max(0.0, deadline - now), 3),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        return dict(self.last_progress)

    def _publish(
        self,
        on_progress: Callable[[Progress], None],
        *,
        deadline: float,
        started_monotonic: float,
    ) -> None:
        on_progress(self._snapshot(deadline=deadline, started_monotonic=started_monotonic))

    async def _request(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
        deadline: float,
        started_monotonic: float,
        on_progress: Callable[[Progress], None],
    ) -> HTTPResult:
        self.partial_response_text = ""
        self.last_progress = {
            "phase": "awaiting_headers",
            "received_bytes": 0,
            "has_non_whitespace_body": False,
            "last_data_at": None,
            "http_status": None,
            "retry_after": "",
            "response_complete": False,
        }
        timeout = asyncio.timeout(max(0.0, deadline - time.monotonic()))
        try:
            self._publish(on_progress, deadline=deadline, started_monotonic=started_monotonic)
            async with timeout:
                if self._client is None:
                    self._client = httpx.AsyncClient(
                        timeout=httpx.Timeout(self.read_timeout_seconds, connect=self.connect_timeout_seconds),
                        transport=self._transport,
                    )
                return await self._with_heartbeat(
                    url,
                    headers=headers,
                    payload=payload,
                    deadline=deadline,
                    started_monotonic=started_monotonic,
                    on_progress=on_progress,
                )
        except httpx.ReadTimeout as exc:
            progress = self._snapshot(deadline=deadline, started_monotonic=started_monotonic)
            raise TransportTimeout("read", progress, self.partial_response_text) from exc
        except TimeoutError as exc:
            if not timeout.expired():
                raise
            progress = self._snapshot(deadline=deadline, started_monotonic=started_monotonic)
            raise TransportTimeout("total", progress, self.partial_response_text) from exc
        finally:
            # KeyboardInterrupt/CancelledError 也留下可供调用方收尾的最终进度。
            self._snapshot(deadline=deadline, started_monotonic=started_monotonic)

    async def _with_heartbeat(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
        deadline: float,
        started_monotonic: float,
        on_progress: Callable[[Progress], None],
    ) -> HTTPResult:
        reader = asyncio.create_task(self._read_response(
            url,
            headers=headers,
            payload=payload,
            deadline=deadline,
            started_monotonic=started_monotonic,
            on_progress=on_progress,
        ))
        heartbeat = asyncio.create_task(self._heartbeat(
            on_progress,
            deadline=deadline,
            started_monotonic=started_monotonic,
        ))
        try:
            done, _ = await asyncio.wait({reader, heartbeat}, return_when=asyncio.FIRST_COMPLETED)
            if heartbeat in done:
                # 写进度/输出失败同样取消在途请求，不能只让心跳任务悄悄失败。
                heartbeat.result()
            return await reader
        finally:
            for task in (reader, heartbeat):
                if not task.done():
                    task.cancel()
            # 先等响应上下文关闭和心跳退出，才向调用者返回结果或异常。
            await asyncio.gather(reader, heartbeat, return_exceptions=True)

    async def _heartbeat(
        self,
        on_progress: Callable[[Progress], None],
        *,
        deadline: float,
        started_monotonic: float,
    ) -> None:
        while True:
            await asyncio.sleep(self.progress_interval_seconds)
            self._publish(on_progress, deadline=deadline, started_monotonic=started_monotonic)

    async def _read_response(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
        deadline: float,
        started_monotonic: float,
        on_progress: Callable[[Progress], None],
    ) -> HTTPResult:
        assert self._client is not None
        async with self._client.stream("POST", url, headers=headers, json=payload) as response:
            self.last_progress.update({
                "phase": "reading_response",
                "http_status": response.status_code,
                "retry_after": response.headers.get("Retry-After", ""),
            })
            self._publish(on_progress, deadline=deadline, started_monotonic=started_monotonic)
            try:
                decoder_type = codecs.getincrementaldecoder(response.encoding or "utf-8")
            except LookupError:
                decoder_type = codecs.getincrementaldecoder("utf-8")
            decoder = decoder_type(errors="replace")
            async for chunk in response.aiter_bytes():
                text = decoder.decode(chunk)
                self.partial_response_text += text
                self.last_progress["received_bytes"] += len(chunk)
                self.last_progress["has_non_whitespace_body"] |= bool(text.strip())
                self.last_progress["last_data_at"] = datetime.now(timezone.utc).isoformat()
            final_text = decoder.decode(b"", final=True)
            self.partial_response_text += final_text
            self.last_progress["has_non_whitespace_body"] |= bool(final_text.strip())
            result = HTTPResult(response.status_code, self.partial_response_text,
                                response.headers.get("Retry-After", ""))
        self.last_progress.update({"phase": "received", "response_complete": True})
        self._publish(on_progress, deadline=deadline, started_monotonic=started_monotonic)
        return result
