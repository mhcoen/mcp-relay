# Relay

A wonderfully simple tool that moves information—files, code, data, conversation context—between Claude Desktop and Claude Code.

Both clients connect to a shared buffer via MCP. Just say "ask Desktop" or "send this to Code"—the models handle the rest. The models will also sometimes automatically consult each other. Unobtrusive system notifications let you know when something's waiting on the other side.

**Why?** Desktop and Code have different strengths. Desktop is better for conversation—planning, brainstorming, reviewing, iterating on prose. Code is better for execution—editing files, running commands, working through errors. But they don't share context. If you draft something in Desktop and want Code to implement it, or you want Desktop's opinion on code you're writing, you're copy-pasting between apps.

Relay connects them without requiring you manually specify questions and cut & paste between windows. This is basic functionality that should have been integrated by Anthropic. 

## Example

```
[In Code]
You:     My classifier's stuck at 72% accuracy. Send the
         training config and last epoch's metrics to Desktop.
Code:    [sends config.yaml and metrics via relay]

[In Desktop]
You:     relay
Desktop: [fetches config and metrics]
         The loss curve suggests you're underfitting. Learning
         rate 1e-5 is conservative for a model this size...

You:     What would you try?
Desktop: Bump to 3e-5, add warmup steps, and your batch size
         of 8 is small—if memory allows, try 16. Also the
         class imbalance is brutal: 80/15/5 split. Consider
         weighted loss or oversampling the minority classes.

You:     Specify the changes.
Desktop: [sends updated config via relay]

[In Code]
You:     /relay
Code:    Got it. Updating config.yaml and adding class weights
         to the loss function.
         [edits files, starts training run]

         Epoch 12: accuracy up to 79%, but precision on
         class 2 dropped. Want Desktop's take?

You:     Yeah, send the confusion matrix.
Code:    [sends via relay]

[In Desktop]
You:     relay
Desktop: Class 2 is getting confused with class 0—they may be
         semantically close. I need more examples.
         [sends request to automatically Code via relay]
```

## Usage

Type `relay` in Desktop or `/relay` in Code to check for messages from the other side. That's the primary interaction.

Sending is usually implicit. When you say "Ask Desktop if this looks right" or "Send the README to Code," the models recognize the intent and call the relay automatically. Explicit send syntax exists—`relay: <message>` in Desktop, `/relay <message>` in Code—but you'll rarely need it.

## Note 

In general, for messages that would be a page or two in length this is quite fast. If you want to send a long file, however, it is faster to just manually drag it into the LLM-interface that you want to access it. You can still send accompanying messages using relay but the architectures of Claude Desktop and Claude Code don't optimize file transport via an MCP server.


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

**Note:** After adding the MCP server config, restart both Claude Desktop and Claude Code for the relay to connect.

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

If you switch projects in Code, the relay comes with you. Old messages from the previous project may still be there; use `relay_clear()` if you want a fresh start. If you want separate conversations in Desktop for different projects, just start a new chat there.

## Tools

| Tool | Description |
|------|-------------|
| `relay_send(message, sender)` | Send a message (sender: "desktop" or "code") |
| `relay_fetch(limit, reader, unread_only)` | Fetch recent messages, optionally mark as read |
| `relay_clear()` | Delete all messages from the buffer |

## Technical Details

- Buffer: SQLite at `~/.relay_buffer.db`
- Rolling window: 20 messages max (oldest evicted first)
- Message limit: 64 KB per message
- Idle timeout: 1 hour (server exits automatically when inactive)
- Transport: stdio (standard MCP)
- Python: 3.9+

## Seamless Mode

A version that auto-fetches incoming messages without typing `relay` exists but isn't included in this repository.

## Author

Michael Coen — mhcoen@alum.mit.edu · mhcoen@gmail.com
