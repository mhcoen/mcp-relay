#!/usr/bin/env python3
"""MCP Relay Server for Claude Desktop <-> Claude Code message passing.

This server provides a persistent message relay buffer accessible via MCP tools.
Both Claude Desktop and Claude Code connect as MCP clients; neither shares
conversation history with the other.

Check for messages with get (Desktop) or /get (Code). Just say 'ask
Desktop' or 'tell Code' and the model figures it out.

A background thread polls for unread messages and triggers system notifications
so you know when something's waiting on either side.

Transport: stdio (standard for Claude Desktop integration)
Buffer: SQLite database at ~/.relay_buffer.db (shared across all clients)
Python: Requires 3.9+

Usage:
    python relay_server.py

"""

import argparse
import os
import platform
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from mcp.server.fastmcp import FastMCP

__version__ = "1.0"

# =============================================================================
# CONFIGURATION
# =============================================================================

MAX_MESSAGES = 20          # Rolling window size (oldest messages evicted first)
MAX_MESSAGE_SIZE = 65536   # 64 KB per message limit
DB_PATH = Path.home() / ".relay_buffer.db"
NOTIFY_POLL_INTERVAL = 2   # Notification polling interval in seconds
IDLE_TIMEOUT = 3600        # Exit after 1 hour of inactivity

# Valid sender values (for defensive validation)
VALID_SENDERS = {"desktop", "code"}

# Client identity (set via --client argument, used for notification filtering)
_client_identity: Optional[str] = None

# Debug mode (set via --debug argument)
_debug_mode: bool = False
_debug_log_path = Path.home() / ".relay_debug.log"

# Notification sound (set via --sound argument)
_notification_sound: Optional[str] = None
SOUND_DEFAULTS = {
    "Darwin": "blow",
    "Linux": "/usr/share/sounds/freedesktop/stereo/message.oga",
    "Windows": "ms-winsoundevent:Notification.Default"
}


def _debug_log(msg: str) -> None:
    """Write debug message to log file if debug mode is enabled."""
    if not _debug_mode:
        return
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(_debug_log_path, "a") as f:
        f.write(f"[{timestamp}] {msg}\n")

# Track last activity for idle timeout
_last_activity = time.time()
_activity_lock = threading.Lock()


def _touch_activity() -> None:
    """Update last activity timestamp."""
    global _last_activity
    with _activity_lock:
        _last_activity = time.time()


def _is_idle() -> bool:
    """Check if server has been idle past timeout."""
    with _activity_lock:
        return (time.time() - _last_activity) > IDLE_TIMEOUT

# =============================================================================
# DATABASE SETUP
# =============================================================================


def _get_connection() -> sqlite3.Connection:
    """Get a database connection with appropriate settings."""
    conn = sqlite3.connect(DB_PATH, isolation_level="IMMEDIATE")
    conn.row_factory = sqlite3.Row
    return conn


def _init_db() -> None:
    """Initialize the database schema if needed."""
    with _get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender TEXT NOT NULL,
                message TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                read_by_desktop_at TEXT,
                read_by_code_at TEXT
            )
        """)
        # Add columns to existing tables (no-op if they already exist)
        for col in ("read_by_desktop_at", "read_by_code_at"):
            try:
                conn.execute(f"ALTER TABLE messages ADD COLUMN {col} TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists
        conn.commit()


# Initialize on module load
_init_db()

# =============================================================================
# NOTIFICATIONS
# =============================================================================


def _send_notification(title: str, message: str) -> None:
    """Send a system notification."""
    _debug_log(f"_send_notification called: title={title!r}, message={message[:50]!r}...")
    if len(message) > 200:
        message = message[:197] + "..."

    system = platform.system()

    if system == "Darwin":  # macOS
        message = message.replace('\\', '\\\\').replace('"', '\\"')
        title = title.replace('\\', '\\\\').replace('"', '\\"')
        if _notification_sound:
            script = f'display notification "{message}" with title "{title}" sound name "{_notification_sound}"'
        else:
            script = f'display notification "{message}" with title "{title}"'
        result = subprocess.run(["osascript", "-e", script], capture_output=True)
        _debug_log(f"osascript result: returncode={result.returncode}, stderr={result.stderr.decode()!r}")
    elif system == "Linux":
        subprocess.run(["notify-send", title, message], capture_output=True)
        if _notification_sound:
            subprocess.run(["paplay", _notification_sound], capture_output=True)
    elif system == "Windows":
        audio_line = ""
        if _notification_sound:
            audio_line = f'''
        $audio = $xml.CreateElement("audio")
        $audio.SetAttribute("src", "{_notification_sound}")
        $xml.DocumentElement.AppendChild($audio)'''
        ps_script = f'''
        [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
        $template = [Windows.UI.Notifications.ToastTemplateType]::ToastText02
        $xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent($template)
        $xml.GetElementsByTagName("text")[0].AppendChild($xml.CreateTextNode("{title}"))
        $xml.GetElementsByTagName("text")[1].AppendChild($xml.CreateTextNode("{message}")){audio_line}
        $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("Relay").Show($toast)
        '''
        subprocess.run(["powershell", "-Command", ps_script], capture_output=True)


def _notification_loop() -> None:
    """Background thread: poll for unread messages, notify, and check idle timeout."""
    notified: set[int] = set()
    _debug_log(f"Notification loop started: client={_client_identity}")

    while True:
        # Check idle timeout
        if _is_idle():
            _debug_log("Idle timeout reached, exiting")
            sys.exit(0)

        # Skip notifications if client identity not set
        if _client_identity is None:
            time.sleep(NOTIFY_POLL_INTERVAL)
            continue

        try:
            with _get_connection() as conn:
                # Find all unread messages (Desktop notifies for both directions)
                rows = conn.execute("""
                    SELECT id, sender, message
                    FROM messages
                    WHERE (sender = 'code' AND read_by_desktop_at IS NULL)
                       OR (sender = 'desktop' AND read_by_code_at IS NULL)
                """).fetchall()

            for row in rows:
                msg_id = row["id"]
                if msg_id not in notified:
                    sender = row["sender"].title()
                    recipient = "Desktop" if row["sender"] == "code" else "Code"
                    _debug_log(f"New message {msg_id} for {recipient} from {sender}, sending notification")
                    _send_notification(f"New message for {recipient} from {sender}", row["message"])
                    notified.add(msg_id)

        except Exception as e:
            _debug_log(f"Error in notification loop: {e}")

        time.sleep(NOTIFY_POLL_INTERVAL)


def _start_notification_thread() -> None:
    """Start the background notification thread."""
    thread = threading.Thread(target=_notification_loop, daemon=True)
    thread.start()


# =============================================================================
# MCP SERVER SETUP
# =============================================================================

mcp = FastMCP("relay")

# =============================================================================
# RESOURCES
# =============================================================================


@mcp.resource("messages://latest")
def messages_latest() -> str:
    """
    Get the latest messages from the relay buffer.

    Returns messages in chronological order (oldest first).
    Does NOT mark messages as read - use relay_fetch for that.
    """
    with _get_connection() as conn:
        rows = conn.execute("""
            SELECT sender, message, timestamp
            FROM messages
            ORDER BY id DESC LIMIT 10
        """).fetchall()

    if not rows:
        return "No messages in relay buffer."

    lines = []
    for i, row in enumerate(reversed(rows), 1):
        sender = row["sender"].title()
        lines.append(f"{i}. [{sender}]: {row['message']}")
    return "\n\n".join(lines)


# =============================================================================
# TOOLS
# =============================================================================


@mcp.tool()
def relay_send(message: str, sender: Literal["desktop", "code"]) -> dict:
    """
    Send a message to the other Claude client.

    Use this when the user wants to communicate with Claude Desktop (if you're Code)
    or Claude Code (if you're Desktop). Phrases like "ask Desktop", "tell Code",
    "send this to Code", "check with Desktop", or "get Desktop's opinion" should trigger this tool.

    Messages are opaque strings—send prompt fragments, summaries, code excerpts, questions, whatever.

    Args:
        message: The message content (max 64 KB).
        sender: Who is sending—must be "desktop" or "code".

    Returns:
        {"ok": True} on success.
        {"ok": False, "error": "..."} on failure.
    """
    _touch_activity()
    # Defensive sender validation (in addition to Literal type hint)
    if sender not in VALID_SENDERS:
        return {
            "ok": False,
            "error": f"Invalid sender '{sender}'. Must be 'desktop' or 'code'."
        }

    # Validate message size
    message_bytes = len(message.encode("utf-8"))
    if message_bytes > MAX_MESSAGE_SIZE:
        return {
            "ok": False,
            "error": f"Message size ({message_bytes} bytes) exceeds {MAX_MESSAGE_SIZE} byte limit."
        }

    try:
        timestamp = datetime.now(timezone.utc).isoformat()
        with _get_connection() as conn:
            # Insert the new message
            conn.execute(
                "INSERT INTO messages (sender, message, timestamp) VALUES (?, ?, ?)",
                (sender, message, timestamp)
            )
            # Evict oldest messages beyond the rolling window
            conn.execute("""
                DELETE FROM messages WHERE id NOT IN (
                    SELECT id FROM messages ORDER BY id DESC LIMIT ?
                )
            """, (MAX_MESSAGES,))
            conn.commit()
        return {"ok": True}
    except sqlite3.Error as e:
        return {"ok": False, "error": f"Database error: {e}"}


# Column name lookup (avoids SQL injection from f-string interpolation)
_READ_COLUMNS = {"desktop": "read_by_desktop_at", "code": "read_by_code_at"}


@mcp.tool()
def relay_fetch(
    limit: int = 5,
    reader: Optional[Literal["desktop", "code"]] = None,
    unread_only: bool = True
) -> list[dict]:
    """
    Fetch messages from the other Claude client.

    Use this when the user wants to see what the other client sent, or when checking for
    responses. Phrases like "check the relay", "what did Desktop say", "get Code's response",
    or just "relay" should trigger this tool.

    Args:
        limit: Maximum number of messages to return (default 5, max 20).
        reader: Optional. If provided ("desktop" or "code"), marks fetched messages as read.
        unread_only: If true and reader is specified, only return messages unread by that reader.

    Returns:
        List of message objects with id, sender, message, timestamp, and read timestamps.
    """
    _touch_activity()
    # Clamp limit to valid range
    limit = max(1, min(limit, MAX_MESSAGES))

    with _get_connection() as conn:
        # Build query based on unread_only filter (exclude messages sent by reader)
        if unread_only and reader in VALID_SENDERS:
            col = _READ_COLUMNS[reader]
            rows = conn.execute(f"""
                SELECT id, sender, message, timestamp, read_by_desktop_at, read_by_code_at
                FROM messages WHERE {col} IS NULL AND sender != ? ORDER BY id DESC LIMIT ?
            """, (reader, limit)).fetchall()
        elif reader in VALID_SENDERS:
            rows = conn.execute("""
                SELECT id, sender, message, timestamp, read_by_desktop_at, read_by_code_at
                FROM messages WHERE sender != ? ORDER BY id DESC LIMIT ?
            """, (reader, limit)).fetchall()
        else:
            rows = conn.execute("""
                SELECT id, sender, message, timestamp, read_by_desktop_at, read_by_code_at
                FROM messages ORDER BY id DESC LIMIT ?
            """, (limit,)).fetchall()

        # Mark as read if reader is specified
        if reader in VALID_SENDERS and rows:
            col = _READ_COLUMNS[reader]
            ids = [row["id"] for row in rows]
            placeholders = ",".join("?" * len(ids))
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                f"UPDATE messages SET {col} = ? WHERE id IN ({placeholders}) AND {col} IS NULL",
                [now] + ids
            )
            conn.commit()

    # Return in chronological order (oldest first, newest last)
    return [dict(row) for row in reversed(rows)]


@mcp.tool()
def relay_clear() -> dict:
    """
    Delete all messages from the relay buffer.

    Useful for resetting state. This action is irreversible.

    Returns:
        {"ok": True, "deleted": <count>} on success.
        {"ok": False, "error": "..."} on failure.
    """
    _touch_activity()
    try:
        with _get_connection() as conn:
            cursor = conn.execute("DELETE FROM messages")
            deleted = cursor.rowcount
            conn.commit()
        return {"ok": True, "deleted": deleted}
    except sqlite3.Error as e:
        return {"ok": False, "error": f"Database error: {e}"}


# =============================================================================
# SETUP COMMAND
# =============================================================================

PREVIEW_SCRIPT = '''\
#!/usr/bin/env python3
"""Show notification of pending relay messages for SessionStart hook."""
import platform
import sqlite3
import subprocess
from pathlib import Path

DB_PATH = Path.home() / ".relay_buffer.db"

def send_notification(title: str, message: str) -> None:
    """Send a system notification."""
    system = platform.system()
    if system == "Darwin":
        message = message.replace("\\\\", "\\\\\\\\").replace(\'"\', \'\\\\"\')
        title = title.replace("\\\\", "\\\\\\\\").replace(\'"\', \'\\\\"\')
        script = f\'display notification "{message}" with title "{title}"\'
        subprocess.run(["osascript", "-e", script], capture_output=True)
    elif system == "Linux":
        subprocess.run(["notify-send", title, message], capture_output=True)
    elif system == "Windows":
        ps_script = f"""
        [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
        $template = [Windows.UI.Notifications.ToastTemplateType]::ToastText02
        $xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent($template)
        $xml.GetElementsByTagName("text")[0].AppendChild($xml.CreateTextNode("{title}"))
        $xml.GetElementsByTagName("text")[1].AppendChild($xml.CreateTextNode("{message}"))
        $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("Relay").Show($toast)
        """
        subprocess.run(["powershell", "-Command", ps_script], capture_output=True)

def main():
    if not DB_PATH.exists():
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Get unread messages from Desktop (for Code user)
    rows = conn.execute("""
        SELECT sender, message FROM messages
        WHERE sender = \'desktop\' AND read_by_code_at IS NULL
        ORDER BY id DESC LIMIT 5
    """).fetchall()

    conn.close()

    if not rows:
        return

    # Build notification message with previews
    previews = []
    for i, row in enumerate(reversed(rows), 1):
        preview = row["message"][:80]
        if len(row["message"]) > 80:
            preview += "..."
        previews.append(f"{i}. {preview}")

    title = f"📬 {len(rows)} message(s) from Desktop"
    body = "\\n".join(previews[:3])  # Show up to 3 previews
    if len(rows) > 3:
        body += f"\\n...and {len(rows) - 3} more"

    send_notification(title, body)

if __name__ == "__main__":
    main()
'''

GET_COMMAND = '''\
# Get Command

@relay:messages://latest

IMMEDIATELY execute the following without deliberation:

**If $ARGUMENTS is empty:**
1. Read the messages above from @relay:messages://latest
2. Call `relay_fetch(limit=5, reader="code")` to mark them as read
3. Find the most recent message from sender "desktop"
4. Execute those instructions

**If $ARGUMENTS is "status":**
Call `relay_fetch(limit=20, reader=None, unread_only=False)` and report:
- Total message count
- Unread count for Code
- Time of most recent message

**If $ARGUMENTS is "clear":**
Call `relay_clear()` to delete all messages.

**Otherwise (any other $ARGUMENTS):**
Call `relay_send(message="$ARGUMENTS", sender="code")` immediately.

## Arguments
$ARGUMENTS
'''


def _get_claude_dir() -> Path:
    """Get the Claude Code config directory for the current platform."""
    system = platform.system()
    if system == "Windows":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "Claude"
        return Path.home() / "AppData" / "Roaming" / "Claude"
    else:
        return Path.home() / ".claude"


def _get_commands_dir() -> Path:
    """Get the Claude Code commands directory for the current platform."""
    return _get_claude_dir() / "commands"


def _setup_code() -> None:
    """Install the /get slash command, preview script, and SessionStart hook."""
    import json
    import stat

    claude_dir = _get_claude_dir()

    # 1. Install /get command
    commands_dir = claude_dir / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)
    get_path = commands_dir / "get.md"
    get_path.write_text(GET_COMMAND)
    print(f"Installed /get command to {get_path}")

    # 2. Install preview script
    scripts_dir = claude_dir / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    preview_path = scripts_dir / "relay-preview.py"
    preview_path.write_text(PREVIEW_SCRIPT)
    preview_path.chmod(preview_path.stat().st_mode | stat.S_IXUSR)
    print(f"Installed preview script to {preview_path}")

    # 3. Install SessionStart hook (merge with existing settings)
    settings_path = claude_dir / "settings.json"
    settings = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text())
        except json.JSONDecodeError:
            pass

    # Add hook config
    if "hooks" not in settings:
        settings["hooks"] = {}

    settings["hooks"]["SessionStart"] = [
        {
            "hooks": [
                {
                    "type": "command",
                    "command": f"python3 {preview_path}"
                }
            ]
        }
    ]

    settings_path.write_text(json.dumps(settings, indent=2))
    print(f"Installed SessionStart hook to {settings_path}")


# =============================================================================
# ENTRY POINT
# =============================================================================


def main() -> None:
    """Main entry point for the relay server."""
    global _client_identity, _debug_mode, _notification_sound

    parser = argparse.ArgumentParser(description="MCP Relay Server")
    parser.add_argument(
        "--client",
        choices=["desktop", "code"],
        help="Client identity for notification filtering"
    )
    parser.add_argument(
        "--setup-code",
        action="store_true",
        help="Install the /relay slash command for Claude Code and exit"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging to ~/.relay_debug.log"
    )
    parser.add_argument(
        "--sound",
        nargs="?",
        const="default",
        help="Enable notification sound (optional: custom sound identifier)"
    )
    args = parser.parse_args()

    # Handle --setup-code
    if args.setup_code:
        _setup_code()
        return

    # Set debug mode (truncate log on startup for fresh session)
    _debug_mode = args.debug
    if _debug_mode:
        _debug_log_path.write_text("")
        _debug_log(f"=== Relay server starting: client={args.client} ===")

    # Set notification sound
    if args.sound == "default":
        _notification_sound = SOUND_DEFAULTS.get(platform.system())
    else:
        _notification_sound = args.sound

    # Set client identity for notification filtering
    _client_identity = args.client

    # Start background notification thread (Desktop only - Code may have multiple instances)
    if _client_identity == "desktop":
        _start_notification_thread()
    # Run with stdio transport (standard for Claude Desktop/Code integration)
    # All logging goes to stderr; stdout is reserved for MCP JSON-RPC messages
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
