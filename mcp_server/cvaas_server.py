#!/usr/bin/env python3
"""
MCP Server for Arista CVaaS Integration
Exposes CVaaS data as tools that can be called via MCP protocol
"""

import os
import sys
import json
from typing import Any
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# Debug logging to stderr (stdout is used by MCP protocol)
def debug_log(message: str):
    print(f"[CVaaS MCP] {message}", file=sys.stderr, flush=True)

# CVaaS Configuration
CVAAS_URL = os.environ.get("CVAAS_URL", "https://www.arista.io/api/v3")
CVAAS_TOKEN = os.environ.get("CVAAS_TOKEN", "")

debug_log(f"CVaaS URL: {CVAAS_URL}")
debug_log(f"CVaaS Token configured: {'Yes' if CVAAS_TOKEN else 'No'}")

# Initialize MCP Server
server = Server("cvaas-mcp-server")


class CVaaSClient:
    """Client for interacting with Arista CVaaS API using cvprac"""
    
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._client = None
    
    def _get_client(self):
        """Get or create cvprac client connection"""
        if self._client is None:
            try:
                from cvprac.cvp_client import CvpClient
                self._client = CvpClient()
                # Extract hostname from URL
                import re
                hostname = re.sub(r'^https?://', '', self.base_url).split('/')[0]
                debug_log(f"Connecting to CVaaS at: {hostname}")
                self._client.connect(
                    nodes=[hostname],
                    username='',  # Not needed with token
                    password='',  # Not needed with token
                    is_cvaas=True,
                    api_token=self.token
                )
                debug_log("CVaaS connection established")
            except ImportError:
                debug_log("cvprac not installed - falling back to REST API")
                raise ImportError("cvprac package required. Install with: pip install cvprac")
        return self._client
    
    def get(self, endpoint: str) -> dict:
        """Make a direct GET request to CVaaS API"""
        client = self._get_client()
        return client.get(endpoint)
    
    def post(self, endpoint: str, data: dict) -> dict:
        """Make a direct POST request to CVaaS API"""
        client = self._get_client()
        return client.post(endpoint, data=data)
    
    async def get_device_inventory(self, device_id: str = None) -> dict:
        """Get device inventory from CVaaS"""
        try:
            client = self._get_client()
            inventory = client.api.get_inventory()
            
            if device_id:
                # Filter for specific device
                for device in inventory:
                    if device.get('serialNumber') == device_id or device.get('hostname') == device_id:
                        return {"device": device}
                return {"error": f"Device {device_id} not found"}
            
            return {"devices": inventory, "total": len(inventory)}
        except Exception as e:
            debug_log(f"get_device_inventory error: {e}")
            raise
    
    async def get_active_events(self, severity: str = None, days_back: int = 30) -> dict:
        """Get events/alerts from CVaaS with time range support"""
        from datetime import datetime, timedelta
        
        try:
            # Ensure client is connected
            self._get_client()
            
            # Calculate time range
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(days=days_back)
            
            # Format as ISO 8601
            start_str = start_time.strftime("%Y-%m-%dT%H:%M:%SZ")
            end_str = end_time.strftime("%Y-%m-%dT%H:%M:%SZ")
            
            debug_log(f"Fetching events from {start_str} to {end_str}")
            
            # Map severity to CVaaS enum values
            severity_map = {
                'info': 'EVENT_SEVERITY_INFO',
                'warning': 'EVENT_SEVERITY_WARNING',
                'error': 'EVENT_SEVERITY_ERROR',
                'critical': 'EVENT_SEVERITY_CRITICAL'
            }
            
            if severity and severity.lower() in severity_map:
                # Use POST with filter for severity
                event_url = '/api/resources/event/v1/Event/all'
                payload = {
                    "partialEqFilter": [{"severity": severity_map[severity.lower()]}],
                    "time": {
                        "start": start_str,
                        "end": end_str
                    }
                }
                debug_log(f"POST {event_url} with payload: {payload}")
                response = self.post(event_url, payload)
            else:
                # CVaaS Resource API for events with time range
                event_url = f'/api/resources/event/v1/Event/all?time.start={start_str}&time.end={end_str}'
                debug_log(f"GET {event_url}")
                response = self.get(event_url)
            
            events = response.get('data', []) if response else []
            
            return {
                "events": events,
                "total": len(events),
                "time_range": {
                    "start": start_str,
                    "end": end_str,
                    "days": days_back
                },
                "severity_filter": severity
            }
            
        except Exception as e:
            debug_log(f"get_active_events error: {type(e).__name__}: {e}")
            return {
                "events": [],
                "error": str(e),
                "note": "Events API may require specific permissions. Ensure your service account has Events read access."
            }
    
    async def get_bgp_status(self) -> dict:
        """Get BGP peering status across the fabric"""
        try:
            client = self._get_client()
            inventory = client.api.get_inventory()
            bgp_info = []
            
            for device in inventory:
                hostname = device.get('hostname', 'unknown')
                bgp_info.append({
                    "hostname": hostname,
                    "serialNumber": device.get('serialNumber'),
                    "ipAddress": device.get('ipAddress'),
                    "streamingStatus": device.get('streamingStatus'),
                    "status": device.get('status')
                })
            
            return {
                "devices": bgp_info, 
                "total": len(bgp_info),
                "note": "For detailed BGP neighbor status, query individual devices via EOS API"
            }
        except Exception as e:
            debug_log(f"get_bgp_status error: {e}")
            raise
    
    async def get_mlag_status(self) -> dict:
        """Get MLAG status across devices"""
        try:
            client = self._get_client()
            inventory = client.api.get_inventory()
            return {
                "devices": [
                    {
                        "hostname": d.get('hostname'),
                        "serialNumber": d.get('serialNumber'),
                        "mlagEnabled": d.get('mlagEnabled', False),
                        "streamingStatus": d.get('streamingStatus')
                    }
                    for d in inventory
                ],
                "total": len(inventory)
            }
        except Exception as e:
            debug_log(f"get_mlag_status error: {e}")
            raise
    
    async def get_evpn_status(self) -> dict:
        """Get EVPN VXLAN status"""
        try:
            client = self._get_client()
            inventory = client.api.get_inventory()
            return {
                "devices": [
                    {
                        "hostname": d.get('hostname'),
                        "serialNumber": d.get('serialNumber'),
                        "modelName": d.get('modelName'),
                        "streamingStatus": d.get('streamingStatus')
                    }
                    for d in inventory
                ],
                "total": len(inventory),
                "note": "EVPN details require device-specific queries"
            }
        except Exception as e:
            debug_log(f"get_evpn_status error: {e}")
            raise
    
    async def get_config_compliance(self) -> dict:
        """Get configuration compliance status"""
        try:
            client = self._get_client()
            inventory = client.api.get_inventory()
            compliance_info = []
            
            for device in inventory:
                compliance_info.append({
                    "hostname": device.get('hostname'),
                    "serialNumber": device.get('serialNumber'),
                    "complianceCode": device.get('complianceCode'),
                    "complianceIndication": device.get('complianceIndication', 'UNKNOWN'),
                    "streamingStatus": device.get('streamingStatus')
                })
            
            return {"devices": compliance_info, "total": len(compliance_info)}
        except Exception as e:
            debug_log(f"get_config_compliance error: {e}")
            raise
    
    async def get_topology(self) -> dict:
        """Get fabric topology information"""
        try:
            client = self._get_client()
            inventory = client.api.get_inventory()
            
            # Group devices by type/role
            topology = {
                "devices": [
                    {
                        "hostname": d.get('hostname'),
                        "serialNumber": d.get('serialNumber'),
                        "modelName": d.get('modelName'),
                        "systemMacAddress": d.get('systemMacAddress'),
                        "streamingStatus": d.get('streamingStatus'),
                        "parentContainerKey": d.get('parentContainerKey')
                    }
                    for d in inventory
                ],
                "total": len(inventory)
            }
            
            return topology
        except Exception as e:
            debug_log(f"get_topology error: {e}")
            raise


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
            description="Get events and alerts from CVaaS with time range support. Can filter by severity (critical, warning, error, info) and specify how many days back to search (default 30 days).",
            inputSchema={
                "type": "object",
                "properties": {
                    "severity": {
                        "type": "string",
                        "enum": ["critical", "warning", "error", "info"],
                        "description": "Filter events by severity level"
                    },
                    "days_back": {
                        "type": "integer",
                        "description": "Number of days to look back (default: 30)",
                        "default": 30
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
    debug_log(f"Tool called: {name} with arguments: {arguments}")
    
    try:
        if name == "get_device_status":
            result = await cvaas.get_device_inventory(arguments.get("device_id"))
        elif name == "get_active_events":
            result = await cvaas.get_active_events(
                arguments.get("severity"),
                arguments.get("days_back", 30)
            )
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
            debug_log(f"Unknown tool: {name}")
            return [TextContent(type="text", text=f"Unknown tool: {name}")]
        
        debug_log(f"Tool {name} completed successfully")
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    except Exception as e:
        error_msg = f"Error executing tool {name}: {type(e).__name__}: {str(e)}"
        debug_log(f"Tool {name} exception: {error_msg}")
        return [TextContent(type="text", text=error_msg)]


async def main():
    """Run the MCP server"""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
