#!/usr/bin/env python3
"""
MCP Server for Arista CVaaS Integration
Exposes CVaaS data as tools that can be called via MCP protocol
"""

import os
import json
import httpx
from typing import Any
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# CVaaS Configuration
CVAAS_URL = os.environ.get("CVAAS_URL", "https://www.arista.io/api/v3")
CVAAS_TOKEN = os.environ.get("CVAAS_TOKEN", "")

# Initialize MCP Server
server = Server("cvaas-mcp-server")


class CVaaSClient:
    """Client for interacting with Arista CVaaS API"""
    
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
    
    async def _request(self, method: str, endpoint: str, data: dict = None) -> dict:
        """Make authenticated request to CVaaS API"""
        async with httpx.AsyncClient() as client:
            url = f"{self.base_url}/{endpoint.lstrip('/')}"
            response = await client.request(
                method=method,
                url=url,
                headers=self.headers,
                json=data,
                timeout=30.0
            )
            response.raise_for_status()
            return response.json()
    
    async def get_device_inventory(self, device_id: str = None) -> dict:
        """Get device inventory from CVaaS"""
        # Using Resource API for device inventory
        endpoint = "services/arista.inventory.v1.DeviceService/GetAll"
        if device_id:
            endpoint = f"services/arista.inventory.v1.DeviceService/GetOne"
            data = {"key": {"deviceId": device_id}}
        else:
            data = {}
        return await self._request("POST", endpoint, data)
    
    async def get_active_events(self, severity: str = None) -> dict:
        """Get active events/alerts from CVaaS"""
        endpoint = "services/arista.event.v1.EventService/GetAll"
        data = {"filter": {"ack": False}}  # Get unacknowledged events
        if severity:
            data["filter"]["severity"] = severity.upper()
        return await self._request("POST", endpoint, data)
    
    async def get_bgp_status(self) -> dict:
        """Get BGP peering status across the fabric"""
        endpoint = "services/arista.bgp.v1.BgpPeerService/GetAll"
        return await self._request("POST", endpoint, {})
    
    async def get_mlag_status(self) -> dict:
        """Get MLAG status across devices"""
        endpoint = "services/arista.mlag.v1.MlagService/GetAll"
        return await self._request("POST", endpoint, {})
    
    async def get_evpn_status(self) -> dict:
        """Get EVPN VXLAN status"""
        endpoint = "services/arista.evpn.v1.EvpnService/GetAll"
        return await self._request("POST", endpoint, {})
    
    async def get_config_compliance(self) -> dict:
        """Get configuration compliance status"""
        endpoint = "services/arista.configstatus.v1.ConfigDiffService/GetAll"
        return await self._request("POST", endpoint, {})
    
    async def get_topology(self) -> dict:
        """Get fabric topology information"""
        endpoint = "services/arista.topology.v1.TopologyService/GetAll"
        return await self._request("POST", endpoint, {})


# Initialize CVaaS client
cvaas = CVaaSClient(CVAAS_URL, CVAAS_TOKEN)


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available CVaaS tools"""
    return [
        Tool(
            name="get_device_status",
            description="Get device inventory and status from CVaaS. Optionally specify a device ID for details on a specific device.",
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {
                        "type": "string",
                        "description": "Optional: specific device ID/serial number to query"
                    }
                }
            }
        ),
        Tool(
            name="get_active_events",
            description="Get active events and alerts from CVaaS. Can filter by severity (critical, warning, info).",
            inputSchema={
                "type": "object",
                "properties": {
                    "severity": {
                        "type": "string",
                        "enum": ["critical", "warning", "info"],
                        "description": "Filter events by severity level"
                    }
                }
            }
        ),
        Tool(
            name="get_bgp_status",
            description="Get BGP peering status and neighbor information across the fabric.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="get_mlag_status",
            description="Get MLAG peer status and health across the fabric.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="get_evpn_status",
            description="Get EVPN VXLAN status including VTEP peers, tunnels, and VNI information.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="get_config_compliance",
            description="Check configuration compliance status against configlets.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="get_topology",
            description="Get fabric topology information including spine/leaf device relationships.",
            inputSchema={"type": "object", "properties": {}}
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Execute a CVaaS tool and return results"""
    try:
        if name == "get_device_status":
            result = await cvaas.get_device_inventory(arguments.get("device_id"))
        elif name == "get_active_events":
            result = await cvaas.get_active_events(arguments.get("severity"))
        elif name == "get_bgp_status":
            result = await cvaas.get_bgp_status()
        elif name == "get_mlag_status":
            result = await cvaas.get_mlag_status()
        elif name == "get_evpn_status":
            result = await cvaas.get_evpn_status()
        elif name == "get_config_compliance":
            result = await cvaas.get_config_compliance()
        elif name == "get_topology":
            result = await cvaas.get_topology()
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]
        
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    except httpx.HTTPStatusError as e:
        return [TextContent(type="text", text=f"CVaaS API error: {e.response.status_code} - {e.response.text}")]
    except Exception as e:
        return [TextContent(type="text", text=f"Error executing tool: {str(e)}")]


async def main():
    """Run the MCP server"""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
