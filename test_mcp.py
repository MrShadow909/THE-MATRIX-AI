import asyncio
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession

async def test():
    params = StdioServerParameters(
        command="python",
        args=["-m", "neo_code.connector.mcp_server"],
        env={"PYTHONPATH": "C:\\Users\\HP\\Desktop\\ENTER THE MATRIX"}
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("Initialize OK")
            
            tools = await session.list_tools()
            print(f"Tools: {[t.name for t in tools.tools]}")
            
            result = await session.call_tool("neo_list_providers", {})
            print(f"Providers: {result.content[0].text}")
            
            result = await session.call_tool("neo_status", {})
            print(f"Status: {result.content[0].text}")

asyncio.run(test())
