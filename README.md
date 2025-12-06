# CVaaS Slack Bot with MCP + Anthropic

A Slack bot that queries Arista CloudVision as a Service (CVaaS) using the Model Context Protocol (MCP) and analyzes results with Claude.

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Slack     │────▶│  Slack Bot  │────▶│ MCP Client  │────▶│ MCP Server  │
│   User      │◀────│  (Bolt)     │◀────│             │◀────│  (CVaaS)    │
└─────────────┘     └──────┬──────┘     └─────────────┘     └──────┬──────┘
                           │                                       │
                           ▼                                       ▼
                    ┌─────────────┐                         ┌─────────────┐
                    │  Claude     │                         │   CVaaS     │
                    │  (Sonnet)   │                         │    API      │
                    └─────────────┘                         └─────────────┘
```

## Features

- **Device Status**: Query device inventory and streaming status
- **Active Events**: Get alerts filtered by severity (critical/warning/info)
- **BGP Status**: Check BGP peering health across the fabric
- **MLAG Status**: Monitor MLAG peer relationships
- **EVPN Status**: View EVPN VXLAN tunnel and VNI information
- **Config Compliance**: Check for configuration drift
- **Topology**: View fabric topology relationships

## Prerequisites

1. **Arista CVaaS Account** with API access
2. **Slack Workspace** with permissions to create apps
3. **Anthropic API Key**
4. **Python 3.10+**

## Setup

### 1. Clone and Install Dependencies

```bash
cd cvaas-slackbot
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Create Slack App

1. Go to [Slack API Apps](https://api.slack.com/apps)
2. Click **Create New App** → **From scratch**
3. Name it (e.g., "CVaaS Assistant") and select your workspace

#### Configure Bot Token Scopes

Under **OAuth & Permissions**, add these Bot Token Scopes:
- `app_mentions:read`
- `chat:write`
- `commands`
- `im:history`
- `im:read`
- `im:write`

#### Enable Socket Mode

1. Go to **Socket Mode** and enable it
2. Create an App-Level Token with `connections:write` scope
3. Save this token as `SLACK_APP_TOKEN`

#### Enable Events

Under **Event Subscriptions**, enable and subscribe to:
- `app_mention`
- `message.im`

#### Create Slash Command (Optional)

Under **Slash Commands**, create `/network-status`:
- Command: `/network-status`
- Description: "Get quick network health overview"

#### Install to Workspace

1. Go to **Install App**
2. Click **Install to Workspace**
3. Copy the **Bot User OAuth Token** as `SLACK_BOT_TOKEN`

### 3. Get CVaaS API Token

1. Log in to [Arista CVaaS](https://www.arista.io)
2. Go to **Settings** → **Access Control** → **Service Accounts**
3. Create a service account with appropriate roles
4. Generate and copy the API token

### 4. Configure Environment Variables

Create a `.env` file or export these variables:

```bash
# Slack Configuration
export SLACK_BOT_TOKEN="xoxb-your-bot-token"
export SLACK_APP_TOKEN="xapp-your-app-token"

# Anthropic Configuration
export ANTHROPIC_API_KEY="sk-ant-your-api-key"

# CVaaS Configuration
export CVAAS_URL="https://www.arista.io/api/v3"
export CVAAS_TOKEN="your-cvaas-service-account-token"

# MCP Server Path
export MCP_SERVER_PATH="./mcp_server/cvaas_server.py"
```

### 5. Run the Bot

```bash
source .env  # or set environment variables
python slack_bot.py
```

## Usage

### In Slack

**Mention the bot:**
```
@CVaaS Assistant What's the current health of our network?
@CVaaS Assistant Show me any critical alerts
@CVaaS Assistant Check BGP status for all spine switches
@CVaaS Assistant Are there any config compliance issues?
```

**Direct Message:**
Just DM the bot with your question.

**Slash Command:**
```
/network-status
```

## Example Queries

| Query | What It Does |
|-------|--------------|
| "Show device inventory" | Lists all devices with streaming status |
| "Any critical events?" | Retrieves critical severity alerts |
| "Check BGP peers" | Shows BGP neighbor status |
| "MLAG health check" | Displays MLAG peer relationships |
| "Config drift report" | Shows devices out of compliance |
| "Network topology overview" | Displays spine/leaf relationships |

## Project Structure

```
cvaas-slackbot/
├── slack_bot.py           # Main Slack bot with MCP client
├── mcp_server/
│   └── cvaas_server.py    # MCP server exposing CVaaS tools
├── requirements.txt       # Python dependencies
└── README.md             # This file
```

## Customization

### Adding New Tools

1. Add the API method in `CVaaSClient` class
2. Add the tool definition in `list_tools()`
3. Add the handler in `call_tool()`

### Modifying the System Prompt

Edit the `system_prompt` in `process_with_claude()` to customize Claude's behavior and response style.

### Adjusting CVaaS API Endpoints

The MCP server uses CVaaS Resource APIs. Update endpoints in `CVaaSClient` methods based on your CVaaS version and available services.

## Troubleshooting

**Bot not responding:**
- Check Socket Mode is enabled and connected
- Verify `SLACK_APP_TOKEN` and `SLACK_BOT_TOKEN` are correct
- Ensure bot is invited to the channel

**CVaaS API errors:**
- Verify `CVAAS_TOKEN` has appropriate permissions
- Check `CVAAS_URL` matches your CVaaS region
- Test API access with curl first

**MCP connection issues:**
- Ensure MCP server path is correct
- Check Python environment has all dependencies
- Review MCP server logs for errors

## Security Notes

- Store all tokens securely (use secrets management in production)
- CVaaS service account should have minimal required permissions
- Consider adding rate limiting for production use
- Audit bot access and queries regularly

## License

MIT
