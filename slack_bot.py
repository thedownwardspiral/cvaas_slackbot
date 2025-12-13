#!/usr/bin/env python3
"""
Slack Bot with MCP Client for CVaaS Analysis
Receives Slack messages, queries CVaaS via MCP, and uses Claude for analysis
"""

import os
import json
import asyncio
import logging
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from anthropic import Anthropic
import anthropic as anthropic_module
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from contextlib import asynccontextmanager

# Configure logging with verbose debug output
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()  # Output to console
    ]
)
logger = logging.getLogger(__name__)

# Also enable debug logging for httpx to see API requests
logging.getLogger("httpx").setLevel(logging.DEBUG)
logging.getLogger("anthropic").setLevel(logging.DEBUG)

# Environment variables
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.environ.get("SLACK_APP_TOKEN")  # For Socket Mode
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

# Initialize Slack app
app = AsyncApp(token=SLACK_BOT_TOKEN)

# Initialize Anthropic client
anthropic = Anthropic(api_key=ANTHROPIC_API_KEY)

# MCP Server configuration
MCP_SERVER_PATH = os.environ.get("MCP_SERVER_PATH", "./mcp_server/cvaas_server.py")


class MCPClientManager:
    """Manages MCP client connections"""
    
    def __init__(self, server_path: str):
        self.server_path = server_path
        self._session = None
        self._tools = []
    
    @asynccontextmanager
    async def connect(self):
        """Connect to the MCP server"""
        server_params = StdioServerParameters(
            command="python",
            args=[self.server_path],
            env={
                **os.environ,
                "CVAAS_URL": os.environ.get("CVAAS_URL", ""),
                "CVAAS_TOKEN": os.environ.get("CVAAS_TOKEN", "")
            }
        )
        
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                self._session = session
                
                # Get available tools
                tools_response = await session.list_tools()
                self._tools = tools_response.tools
                
                yield self
                
                self._session = None
    
    def get_tools_for_anthropic(self) -> list[dict]:
        """Convert MCP tools to Anthropic tool format"""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.inputSchema
            }
            for tool in self._tools
        ]
    
    async def call_tool(self, name: str, arguments: dict) -> str:
        """Call an MCP tool and return the result"""
        if not self._session:
            raise RuntimeError("MCP session not connected")
        
        result = await self._session.call_tool(name, arguments)
        
        # Extract text content from result
        if result.content:
            return result.content[0].text
        return "No result returned"


# Initialize MCP client manager
mcp_manager = MCPClientManager(MCP_SERVER_PATH)


async def process_with_claude(user_message: str) -> str:
    """
    Process user message with Claude, using MCP tools for CVaaS data
    Implements an agentic loop for tool use
    """
    async with mcp_manager.connect() as mcp:
        tools = mcp.get_tools_for_anthropic()
        
        # System prompt for network analysis
        system_prompt = """You are a network operations assistant with access to Arista CloudVision as a Service (CVaaS).
You help network engineers monitor and troubleshoot their network infrastructure.

When asked about network status, health, or issues:
1. Use the available tools to gather relevant data from CVaaS
2. Analyze the data to identify issues, patterns, or insights
3. Provide clear, actionable recommendations

Be concise but thorough. Highlight critical issues first. Use technical terminology appropriate for network engineers."""

        messages = [{"role": "user", "content": user_message}]
        
        # Agentic loop - continue until Claude stops calling tools
        while True:
            try:
                logger.debug(f"Sending request to Anthropic API with model: claude-sonnet-4-5-20250929")
                logger.debug(f"Messages: {json.dumps(messages, indent=2, default=str)}")
                logger.debug(f"Tools available: {[t['name'] for t in tools]}")
                
                response = anthropic.messages.create(
                    # model="claude-sonnet-4-20250514",
                    # model="claude-sonnet-4-5-20250929",
                    model="claude-opus-4-5-20251101",
                    max_tokens=4096,
                    system=system_prompt,
                    tools=tools,
                    messages=messages
                )
                
                logger.debug(f"Response received - stop_reason: {response.stop_reason}")
                logger.debug(f"Response content: {response.content}")
                
            except Exception as api_error:
                logger.error(f"Anthropic API Error: {type(api_error).__name__}: {api_error}")
                logger.error(f"Full exception details:", exc_info=True)
                raise
            
            # Check if we need to process tool calls
            if response.stop_reason == "tool_use":
                # Process each tool use in the response
                assistant_content = response.content
                tool_results = []
                
                for block in assistant_content:
                    if block.type == "tool_use":
                        logger.info(f"Calling tool: {block.name} with args: {block.input}")
                        
                        try:
                            result = await mcp.call_tool(block.name, block.input)
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": result
                            })
                        except Exception as e:
                            logger.error(f"Tool call failed: {e}")
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": f"Error: {str(e)}",
                                "is_error": True
                            })
                
                # Add assistant response and tool results to messages
                messages.append({"role": "assistant", "content": assistant_content})
                messages.append({"role": "user", "content": tool_results})
                
            else:
                # No more tool calls - extract final text response
                final_response = ""
                for block in response.content:
                    if hasattr(block, "text"):
                        final_response += block.text
                
                return final_response


def format_slack_response(text: str) -> list[dict]:
    """Format response for Slack with blocks"""
    # Split long responses into chunks if needed
    max_length = 3000
    
    if len(text) <= max_length:
        return [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": text}
            }
        ]
    
    # Split into multiple blocks for long responses
    blocks = []
    chunks = [text[i:i+max_length] for i in range(0, len(text), max_length)]
    
    for chunk in chunks:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": chunk}
        })
    
    return blocks


@app.event("app_mention")
async def handle_mention(event, say):
    """Handle @mentions of the bot"""
    user_message = event.get("text", "")
    channel = event.get("channel")
    thread_ts = event.get("thread_ts") or event.get("ts")
    
    # Remove bot mention from message
    user_message = " ".join(user_message.split()[1:])
    
    if not user_message.strip():
        await say(
            text="Hi! I can help you monitor your network. Try asking about device status, BGP peers, MLAG health, or active alerts.",
            channel=channel,
            thread_ts=thread_ts
        )
        return
    
    # Send initial "thinking" message
    thinking_msg = await say(
        text="🔍 Analyzing your network...",
        channel=channel,
        thread_ts=thread_ts
    )
    
    try:
        # Process with Claude + MCP
        response = await process_with_claude(user_message)
        
        # Update with actual response
        await app.client.chat_update(
            channel=channel,
            ts=thinking_msg["ts"],
            text=response,
            blocks=format_slack_response(response)
        )
        
    except Exception as e:
        logger.error(f"Error processing request: {e}")
        await app.client.chat_update(
            channel=channel,
            ts=thinking_msg["ts"],
            text=f"❌ Sorry, I encountered an error: {str(e)}"
        )


@app.event("message")
async def handle_direct_message(event, say):
    """Handle direct messages to the bot"""
    # Only process DMs (no channel)
    if event.get("channel_type") != "im":
        return
    
    # Ignore bot's own messages
    if event.get("bot_id"):
        return
    
    user_message = event.get("text", "")
    channel = event.get("channel")
    
    if not user_message.strip():
        return
    
    # Send thinking indicator
    thinking_msg = await say(
        text="🔍 Analyzing your network...",
        channel=channel
    )
    
    try:
        response = await process_with_claude(user_message)
        
        await app.client.chat_update(
            channel=channel,
            ts=thinking_msg["ts"],
            text=response,
            blocks=format_slack_response(response)
        )
        
    except Exception as e:
        logger.error(f"Error processing request: {e}")
        await app.client.chat_update(
            channel=channel,
            ts=thinking_msg["ts"],
            text=f"❌ Sorry, I encountered an error: {str(e)}"
        )


# Slash command for quick status
@app.command("/network-status")
async def handle_status_command(ack, respond, command):
    """Handle /network-status slash command"""
    await ack()
    
    await respond("🔍 Fetching network status...")
    
    try:
        response = await process_with_claude(
            "Give me a quick overview of network health: check for any critical events, BGP issues, and MLAG problems."
        )
        await respond(response)
        
    except Exception as e:
        logger.error(f"Error in status command: {e}")
        await respond(f"❌ Error: {str(e)}")


async def main():
    """Start the Slack bot"""
    logger.info("=" * 60)
    logger.info("CVaaS Slack Bot Starting")
    logger.info("=" * 60)
    logger.info(f"Anthropic SDK version: {anthropic_module.__version__}")
    logger.info(f"Model configured: claude-sonnet-4-5-20250929")
    logger.info(f"MCP Server Path: {MCP_SERVER_PATH}")
    logger.info("=" * 60)
    
    handler = AsyncSocketModeHandler(app, SLACK_APP_TOKEN)
    logger.info("🚀 Starting CVaaS Slack Bot...")
    await handler.start_async()


if __name__ == "__main__":
    asyncio.run(main())
