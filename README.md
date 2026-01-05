<!-- mcp-name: io.github.mhcoen/mcp-relay -->

# Relay

A wonderfully simple tool that moves information—files, code, data, comments, directions, etc.—between Claude Desktop and Claude Code while keeping their main context windows separate.

Both Claudes can send messages autonomously—when they need input from the other side, they just do it. You get a system notification when something arrives. You fetch when you're ready.

**Why?** Desktop and Code have different strengths. Desktop is better for conversation—planning, brainstorming, reviewing, iterating on prose. Code is better for execution—editing files, running commands, working through errors. But they don't share context. If you draft something in Desktop and want Code to implement it, or you want Desktop's opinion on code you're writing, you're copy-pasting between apps.

Relay connects them without requiring you to manually specify questions and cut & paste between windows. This is basic functionality that should have been integrated by Anthropic.

**You're always in control.** Messages sit in the buffer until you explicitly fetch them. The models can't pull from the relay on their own—you have to type `get` or `/get`. This means there's no runaway inter-LLM conversation burning through your tokens. You see a notification, you decide whether to check it.

## Quick Example

```
[In Desktop]
You:     Send my last error message to Code.
Desktop: [sends via relay]

[notification pops up in Code's terminal]

[In Code]
You:     /get (You can also type "get" but /get is faster.)
Code:    Got it. That's from line 47 in parser.py—the regex isn't matching.
         [fixes the bug]
```

## Extended Example

```
[In Code]
You:     My classifier's stuck at 72% accuracy. Send the
         training config and last epoch's metrics to Desktop.
Code:    [sends config.yaml and metrics via relay]

[System notification appears that a message has been sent to Desktop]

[In Desktop]
You:     get
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

[System notification appears that a message has been sent to Code]

[In Code]
You:     /get
Code:    Got it. Updating config.yaml and adding class weights
         to the loss function.
         [edits files, starts training run]

         Epoch 12: accuracy up to 79%, but precision on
         class 2 dropped. Want Desktop's take?

You:     Yeah, send the confusion matrix.
Code:    [sends via relay]

[In Desktop]
You:     get
Desktop: Class 2 is getting confused with class 0—they may be
         semantically close. I need more examples.
         [automatically sends request to Code via relay]
```

## Usage

Type `get` in Desktop or `/get` in Code to check for messages from the other side. That's the primary interaction.

**Command variants:**
- `/get` — Fetch and execute messages from Desktop
- `/get status` — Show message count and last activity
- `/get clear` — Clear all messages from the buffer
- `/get <message>` — Send a message to Desktop

**Resource access:** You can also reference messages directly with `@relay:messages://latest`. This is faster than `/get` and works in plan mode.

**Startup preview:** When Code starts, you'll see a preview of any pending messages from Desktop. Use `/get` to read them in full.

Sending is easy and implicit. When you say "Ask Desktop if this looks right" or "Send the README to Code," the models recognize the intent and call the relay automatically.

## Notifications

When a message arrives, you'll get a system notification so you know to check the other side. No need to poll manually.

<img src="https://raw.githubusercontent.com/mhcoen/mcp-relay/main/screenshot.png" width="346">

| Platform | Method | Notes |
|----------|--------|-------|
| macOS | osascript | Native notification center |
| Linux | notify-send | Requires libnotify |
| Windows | PowerShell toast | Native toast notifications |

**Sound:** Add `--sound` to enable notification sounds. Without a value, uses platform defaults. With a value, uses the specified sound:

| Platform | Default | Custom example |
|----------|---------|----------------|
| macOS | `blow` | `--sound tink` |
| Linux | freedesktop message sound | `--sound /path/to/sound.oga` |
| Windows | system default | `--sound ms-winsoundevent:Notification.IM` |

Duration and display behavior are controlled by your OS settings.

## Setup

**What's uvx?** [uvx](https://docs.astral.sh/uv/) runs Python packages directly without installing them globally. It handles dependencies automatically. If you don't have it: `curl -LsSf https://astral.sh/uv/install.sh | sh` (See [astral.sh/uv](https://astral.sh/uv) for more info.)

### 1. Configure Claude Desktop

Add to your Claude Desktop config:
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "relay": {
      "command": "uvx",
      "args": ["mcp-server-relay", "--client", "desktop", "--sound"]
    }
  }
}
```

Restart Claude Desktop, then tell it to remember this instruction:

> Remember: When the user says "get" or "/get" alone, fetch recent messages from the relay using relay_fetch.

You can verify it was recorded by saying "Show me my memory edits."

### 2. Configure Claude Code

Add to `.mcp.json` in your project root:

```json
{
  "mcpServers": {
    "relay": {
      "command": "uvx",
      "args": ["mcp-server-relay", "--client", "code"]
    }
  }
}
```

Note: Only Desktop needs `--sound` since it handles notifications for both sides.

### 3. Install the `/get` slash command (optional)

```bash
uvx mcp-server-relay --setup-code
```

This copies the slash command to `~/.claude/commands/`.

### Alternative: Install from GitHub

If you prefer not to use uvx, clone the repository and run directly:

```bash
git clone https://github.com/mhcoen/mcp-relay.git
cd mcp-relay
python -m venv .venv
.venv/bin/pip install -e .
```

Then use the full path in your configs:

**Claude Desktop** (`claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "relay": {
      "command": "/path/to/mcp-relay/.venv/bin/python",
      "args": ["/path/to/mcp-relay/relay_server.py", "--client", "desktop", "--sound"]
    }
  }
}
```

**Claude Code** (`.mcp.json`):
```json
{
  "mcpServers": {
    "relay": {
      "command": "/path/to/mcp-relay/.venv/bin/python",
      "args": ["/path/to/mcp-relay/relay_server.py", "--client", "code"]
    }
  }
}
```

Replace `/path/to/mcp-relay` with your actual clone location.

## Design Philosophy

**Transport, not memory.** The relay is a message bus. It does not summarize, compress, rewrite, or interpret messages. There is no shared hidden context, merged system prompts, or cross-agent planning. Messages pass through unchanged. This keeps concerns cleanly separated and avoids epistemic corruption.

**Primarily user-controlled.** Fetching messages is typically an explicit user action (`get` or `/get`), not a background process. This prevents runaway context growth and feedback loops. However, models may send or fetch autonomously when they decide they need input from the other side—the system allows this without encouraging it.

**Independent interfaces.** Desktop and Code remain fully usable on their own. You can have a long conversation in Desktop without Code, or spend hours debugging in Code without Desktop. The relay connects them when you want; it doesn't couple them. This also means no API costs—both interfaces use your existing subscriptions.

**Minimal surface area.** The relay does three things: send, fetch, clear. It does not attempt to provide orchestration, arbitration, consensus, or autonomous behavior. This restraint is intentional. Most multi-agent designs fail by blurring boundaries that should remain clear.

**Scales naturally.** Multiple Code sessions connect to the same Desktop—you direct messages to the appropriate conversation. Additional MCP-speaking peers, alternative storage backends, per-project buffers, and read-only observers all extend cleanly from this design.

This defines a distinct class of infrastructure: a human-mediated, explicitly synchronized multi-agent message bus.

## Design Notes

**The relay is global.** The buffer at `~/.relay_buffer.db` is shared across all projects. Desktop has no concept of which project you're working on, so per-project isolation isn't practical. This is intentional: one user, one machine, one relay.

If you switch projects in Code, the relay comes with you. Old messages from the previous project may still be there; use `/get clear` if you want a fresh start.

**Large files are slow.** For messages a page or two in length, the relay is fast. For large files, it's faster to drag them directly into the interface you want. You can still send accompanying context via relay.

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

## Author

Michael Coen — mhcoen@alum.mit.edu · mhcoen@gmail.com
<!-- mcp-name: io.github.mhcoen/mcp-relay -->
