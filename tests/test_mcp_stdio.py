"""Exercise the actual SDK stdio transport, not just registered functions."""

import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_stdio_protocol_round_trip(tmp_path: Path) -> None:
    async def exercise() -> None:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "dataloom.server"],
            env={"DATALOOM_WORKSPACE": str(tmp_path)},
        )
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            assert len(listed.tools) == 6
            packs = await session.call_tool("list_domain_packs", {"args": {}})
            assert not packs.isError
            assert packs.structuredContent is not None
            assert any(p["name"] == "healthcare" for p in packs.structuredContent["packs"])

    asyncio.run(exercise())
