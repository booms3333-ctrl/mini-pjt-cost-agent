"""MCP 클라이언트 — aws/gcp/azure cost MCP 서버 3개에 접속해 도구를 가져온다.

langchain-mcp-adapters의 MultiServerMCPClient로 mcp_servers/cost_server.py를
프로바이더별로 자식 프로세스 3개(stdio)로 띄우고, 각 서버가 노출한 도구를
LangChain 도구 객체로 변환해 하나의 리스트로 돌려준다. agent.py는 이 도구들을
받아 cost_lookup_agent/optimization_agent에 그대로 bind_tools 한다.
"""

from __future__ import annotations

import asyncio
import sys
from contextlib import AsyncExitStack
from pathlib import Path

SERVER_SCRIPT = str(Path(__file__).resolve().parent.parent / "mcp_servers" / "cost_server.py")
PROVIDERS = ("aws", "gcp", "azure")


def _connections() -> dict:
    return {
        provider: {
            "transport": "stdio",
            "command": sys.executable,
            "args": [SERVER_SCRIPT],
            "env": {"MCP_PROVIDER": provider},
        }
        for provider in PROVIDERS
    }


async def load_mcp_tools() -> list:
    """3개 MCP 서버(aws/gcp/azure)에 접속해 도구 9개(프로바이더당 3개)를 가져온다.

    주의(성능): `client.get_tools()`는 langchain-mcp-adapters 공식 docstring대로
    "도구 호출마다 새 세션(=새 자식 프로세스)을 연다" — 매 MCP 도구 호출마다
    fastmcp/langchain을 처음부터 다시 import하는 비용(실측 약 1.5초)이 반복된다.
    상시 실행되는 서버(app.py)에서는 대신 아래 open_persistent_mcp_tools()를 써서
    세션을 프로세스 수명 동안 재사용해야 한다 — 이 함수는 evaluation/run_eval.py
    등 세션을 오래 들고 있기 애매한 짧은 호출에만 남겨둔다.
    """
    from langchain_mcp_adapters.client import MultiServerMCPClient

    client = MultiServerMCPClient(_connections())
    return await client.get_tools()


def load_mcp_tools_sync() -> list:
    """동기 컨텍스트(FastAPI 시작 시점 등)에서 쓰는 래퍼."""
    return asyncio.run(load_mcp_tools())


async def open_persistent_mcp_tools() -> tuple[list, AsyncExitStack]:
    """MCP 서버 3개에 세션을 한 번만 열어서 프로세스 수명 동안 재사용한다.

    langchain_mcp_adapters.tools.convert_mcp_tool_to_langchain_tool의 실제 구현을
    직접 확인한 결과: `session`을 안 넘기고 `connection`만 주면(=client.get_tools()의
    기본 동작) 도구를 호출할 때마다 `session is None` 분기를 타서 매번 새
    `create_session(...)`(=새 자식 프로세스 기동 + fastmcp 재import)을 연다. 반대로
    이미 초기화된 `session`을 넘기면 `session.call_tool(...)`을 그대로 재사용해
    프로세스를 다시 안 띄운다.

    그래서 여기서는 `client.session(provider)`(연결 후 initialize까지 끝난
    ClientSession)를 AsyncExitStack으로 열어둔 채 `load_mcp_tools(session=...)`에
    넘긴다. 반환된 AsyncExitStack은 호출자가 계속 들고 있어야 세션이 안 닫힌다 —
    app.py의 lifespan처럼 서버가 떠 있는 동안 유지하다가 종료 시 aclose()해야 한다.
    """
    from langchain_mcp_adapters.client import MultiServerMCPClient
    from langchain_mcp_adapters.tools import load_mcp_tools as _load_tools_for_session

    client = MultiServerMCPClient(_connections())
    stack = AsyncExitStack()
    all_tools: list = []
    try:
        for provider in PROVIDERS:
            session = await stack.enter_async_context(client.session(provider))
            all_tools.extend(await _load_tools_for_session(session, server_name=provider))
    except Exception:
        await stack.aclose()
        raise
    return all_tools, stack
