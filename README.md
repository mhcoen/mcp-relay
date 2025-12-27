# Relay

**A message buffer between Claude Desktop and Claude Code.**

Desktop is great for conversation—planning, review, thinking things through. Code is great for execution—editing files, running commands, iterating on errors. But they don't share context, so you end up copy-pasting between them.

Relay connects them. Both clients connect to a shared SQLite buffer via MCP. You decide what crosses the boundary.

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

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "relay": {
      "command": "/path/to/relay/.venv/bin/python",
      "args": ["/path/to/relay/relay_server.py"]
    }
  }
}
```

Then teach Desktop the conventions by telling it to remember these instructions:

1. "Remember: when I say 'relay:' followed by text, send that text to the relay with sender 'desktop' using relay_send. This is a prompt for Claude Code."

2. "Remember: when I say 'relay' fetch recent messages from the relay MCP to show Code's responses."

(Claude Desktop will save these as memories and apply them in future conversations.)

### Claude Code

1. Add the MCP server to your project's `.mcp.json`:

```json
{
  "mcpServers": {
    "relay": {
      "command": "/path/to/relay/.venv/bin/python",
      "args": ["/path/to/relay/relay_server.py"]
    }
  }
}
```

2. Install the `/relay` slash command (copy to your global commands directory):

```bash
cp /path/to/relay/.claude/commands/relay.md ~/.claude/commands/
```

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
