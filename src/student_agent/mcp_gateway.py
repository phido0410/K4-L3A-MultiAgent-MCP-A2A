from __future__ import annotations

import json
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from .contracts import Contracts


class TransientGatewayError(BaseException):
    """The MCP transport failed (dropped stream, 5xx, timeout), not the tool itself.

    Derives from BaseException on purpose: agents catch ``Exception`` to turn a missing
    record into a signal, and a network hiccup must not be mistaken for missing data.
    It propagates to the CLI, which reconnects and re-runs the case.
    """


class EvidenceGateway:
    def __init__(self, session: ClientSession, contracts: Contracts) -> None:
        self._session = session
        self._contracts = contracts
        #: Tools whose call failed during the current case; reset by the coordinator.
        self.failed_tools: list[str] = []

    async def list_tools(self) -> list[str]:
        response = await self._session.list_tools()
        return sorted(tool.name for tool in response.tools)

    async def call(self, tool_name: str, *, case_id: str, **arguments: str) -> dict[str, Any]:
        payload = {"case_id": case_id, **arguments}
        try:
            result = await self._session.call_tool(tool_name, arguments=payload)
        except Exception as exc:
            self.failed_tools.append(tool_name)
            raise TransientGatewayError(f"{tool_name}: {type(exc).__name__}: {exc}") from exc
        is_error = getattr(result, "is_error", getattr(result, "isError", False))
        if is_error:
            self.failed_tools.append(tool_name)
            message = " ".join(
                block.text for block in result.content if getattr(block, "text", None)
            )
            raise RuntimeError(f"MCP tool {tool_name} failed: {message or 'unknown error'}")
        evidence = getattr(result, "structuredContent", None)
        if evidence is None:
            evidence = getattr(result, "structured_content", None)
        if evidence is None:
            text_blocks = [block.text for block in result.content if getattr(block, "text", None)]
            if len(text_blocks) != 1:
                raise ValueError(f"MCP tool {tool_name} did not return one evidence object")
            evidence = json.loads(text_blocks[0])
        self._contracts.validate_evidence(evidence, f"MCP tool {tool_name}")
        return evidence


def _build_http_client(team_api_key: str) -> httpx2.AsyncClient:
    """Tạo HTTP client cho MCP, ưu tiên HTTP/2.

    Transport streamable-http giữ một SSE stream mở đồng thời với các POST gửi
    request. Trên HTTP/1.1 việc đó cần hai kết nối TCP cùng lúc, và kết nối thứ
    hai bị chặn trên hạ tầng của cuộc thi — biểu hiện là `httpx2.ConnectTimeout`
    ngay khi gọi tool đầu tiên, dù `initialize` đã thành công.

    HTTP/2 ghép mọi luồng vào một kết nối nên không còn vấn đề. Cần gói `h2`;
    nếu thiếu thì lùi về HTTP/1.1 kèm cảnh báo thay vì hỏng hẳn.
    """
    headers = {"Authorization": f"Bearer {team_api_key}"}
    timeout = httpx2.Timeout(300.0, connect=30.0, write=30.0, pool=30.0)
    try:
        return httpx2.AsyncClient(headers=headers, timeout=timeout, http2=True)
    except ImportError:
        print(
            "CẢNH BÁO: thiếu gói 'h2' nên phải dùng HTTP/1.1; "
            "tool call nhiều khả năng sẽ ConnectTimeout. Chạy: pip install -e '.[dev]'",
            file=sys.stderr,
        )
        return httpx2.AsyncClient(headers=headers, timeout=timeout)


@asynccontextmanager
async def connect_gateway(
    endpoint: str, team_api_key: str, contracts: Contracts
) -> AsyncIterator[EvidenceGateway]:
    async with (
        _build_http_client(team_api_key) as http_client,
        streamable_http_client(endpoint, http_client=http_client) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        yield EvidenceGateway(session, contracts)
