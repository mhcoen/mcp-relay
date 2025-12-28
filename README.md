# Relay

A simple tool that moves information—files, code, data, conversation context—between Claude Desktop and Claude Code.

Both clients connect to a shared buffer via MCP. Just say "ask Desktop" or "send this to Code"—the model handles the rest. Unobtrusive system notifications let you know when something's waiting on the other side.

**Why?** Desktop and Code have different strengths. Desktop is better for conversation—planning, brainstorming, reviewing, iterating on prose. Code is better for execution—editing files, running commands, working through errors. But they don't share context. If you draft something in Desktop and want Code to implement it, or you want Desktop's opinion on code you're writing, you're copy-pasting between apps.

Relay connects them. You stay in the flow.

## Example

```
[In Code]
You:     Send the README to Desktop, I want to improve it.
Code:    [sends README via relay]

[In Desktop]
You:     Get the README and make it more appealing.
Desktop: [fetches from relay, sees README, responds with suggestions]

You:     Good, but the intro is too glib.
Desktop: [refines and sends via relay]
         "Sent. Go type /relay in Code."

[In Code]
You:     /relay
Code:    Done. Updated README.md with the revised intro.

You:     Ask Desktop if this is ready to go.
Code:    [sends via relay]
         "Sent to Desktop."
```

## Usage

Type `relay` in Desktop or `/relay` in Code to check for messages from the other side. That's the primary interaction.

Sending is usually implicit. When you say "Ask Desktop if this looks right" or "Send the README to Code," the model recognizes the intent and calls the relay automatically. Explicit send syntax exists—`relay: <message>` in Desktop, `/relay <message>` in Code—but you'll rarely need it.

## Setup

### Install

```bash
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
```

### Claude Desktop

Add the relay server to your Claude Desktop config:

| Platform | Config location |
|----------|-----------------|
| macOS    | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Linux    | `~/.config/Claude/claude_desktop_config.json` |
| Windows  | `%APPDATA%\Claude\claude_desktop_config.json` |

Add this to the `mcpServers` section (adjust paths for your system):

```json
{
  "mcpServers": {
    "relay": {
      "command": "/path/to/mcp-relay/.venv/bin/python",
      "args": ["/path/to/mcp-relay/relay_server.py"]
    }
  }
}
```

Then teach Desktop the conventions by telling it to remember these instructions:

1. "Remember: when I say 'relay:' followed by text, send that text to the relay with sender 'desktop' using relay_send. This is a prompt for Claude Code."

2. "Remember: when I say 'relay' fetch recent messages from the relay MCP to show Code's responses."

(Claude Desktop will save these as memories and apply them in future conversations.)

### Claude Code

1. Add the MCP server to your project's `.mcp.json`. This file tells Claude Code which MCP servers to connect to—copy `example.mcp.json` and adjust paths:

```bash
cp /path/to/mcp-relay/example.mcp.json /your/project/.mcp.json
# Edit .mcp.json to fix the paths for your system
```

2. Install the `/relay` slash command:

```bash
cp /path/to/mcp-relay/relay.md ~/.claude/commands/
```

## Notifications

The server includes built-in notifications. A background thread polls for unread messages and fires system alerts so you know when something's waiting.

| Platform | Method | Notes |
|----------|--------|-------|
| macOS | osascript | Native notification center |
| Linux | notify-send | Requires libnotify |
| Windows | PowerShell toast | Native toast notifications |

Notification duration and behavior are controlled by your OS settings, not the script.

## Design Notes

**The relay is global.** The buffer at `~/.relay_buffer.db` is shared across all projects. Claude Desktop has no concept of which project you're working on—it's a general-purpose chat interface—so per-project isolation isn't practical. This is intentional: one user, one machine, one relay.

If you switch projects in Code, the relay comes with you. Old messages from the previous project may still be there; use `relay_clear()` or `/relay clear` if you want a fresh start.

## Tools

| Tool | Description |
|------|-------------|
| `relay_send(message, sender)` | Send a message (sender: "desktop" or "code") |
| `relay_fetch(limit, reader)` | Fetch recent messages, optionally mark as read |
| `relay_clear()` | Delete all messages from the buffer |

## Technical Details

- Buffer: SQLite at `~/.relay_buffer.db`
- Rolling window: 20 messages max (oldest evicted first)
- Message limit: 64 KB per message
- Transport: stdio (standard MCP)
- Python: 3.9+

## Author

Michael Coen — mhcoen@alum.mit.edu · mhcoen@gmail.com
