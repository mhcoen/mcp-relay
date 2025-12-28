#!/usr/bin/env python3
"""
MCP Relay Server for Claude Desktop <-> Claude Code message passing.

This server provides a persistent message relay buffer accessible via MCP tools.
Both Claude Desktop and Claude Code connect as MCP clients; neither shares
conversation history with the other. Human-controlled send/fetch actions only.

A background thread polls for unread messages and fires system notifications
so you know when something's waiting on either side.

Transport: stdio (standard for Claude Desktop integration)
Buffer: SQLite database at ~/.relay_buffer.db (shared across all clients)
Python: Requires 3.9+

Usage:
    python relay_server.py
"""

import platform
import sqlite3
import subprocess
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

# Valid sender values (for defensive validation)
VALID_SENDERS = {"desktop", "code"}

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
    if len(message) > 200:
        message = message[:197] + "..."

    system = platform.system()

    if system == "Darwin":  # macOS
        message = message.replace('\\', '\\\\').replace('"', '\\"')
        title = title.replace('\\', '\\\\').replace('"', '\\"')
        script = f'display notification "{message}" with title "{title}"'
        subprocess.run(["osascript", "-e", script], capture_output=True)
    elif system == "Linux":
        subprocess.run(["notify-send", title, message], capture_output=True)
    elif system == "Windows":
        ps_script = f'''
        [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
        $template = [Windows.UI.Notifications.ToastTemplateType]::ToastText02
        $xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent($template)
        $xml.GetElementsByTagName("text")[0].AppendChild($xml.CreateTextNode("{title}"))
        $xml.GetElementsByTagName("text")[1].AppendChild($xml.CreateTextNode("{message}"))
        $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("Relay").Show($toast)
        '''
        subprocess.run(["powershell", "-Command", ps_script], capture_output=True)


def _notification_loop() -> None:
    """Background thread: poll for unread messages and notify."""
    notified: set[int] = set()

    while True:
        try:
            with _get_connection() as conn:
                # Find unread messages from either side
                rows = conn.execute("""
                    SELECT id, sender, message
                    FROM messages
                    WHERE (sender = 'desktop' AND read_by_code_at IS NULL)
                       OR (sender = 'code' AND read_by_desktop_at IS NULL)
                """).fetchall()

            for row in rows:
                msg_id = row["id"]
                if msg_id not in notified:
                    sender = row["sender"].title()
                    _send_notification(f"Relay: from {sender}", row["message"])
                    notified.add(msg_id)

        except Exception:
            pass  # Silently ignore errors in background thread

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
def relay_fetch(limit: int = 5, reader: Optional[Literal["desktop", "code"]] = None) -> list[dict]:
    """
    Fetch messages from the other Claude client.

    Use this when the user wants to see what the other client sent, or when checking for
    responses. Phrases like "check the relay", "what did Desktop say", "get Code's response",
    or just "relay" should trigger this tool.

    Args:
        limit: Maximum number of messages to return (default 5, max 20).
        reader: Optional. If provided ("desktop" or "code"), marks fetched messages as read.

    Returns:
        List of message objects with id, sender, message, timestamp, and read timestamps.
    """
    # Clamp limit to valid range
    limit = max(1, min(limit, MAX_MESSAGES))

    with _get_connection() as conn:
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
            # Re-fetch to return post-update timestamps
            rows = conn.execute("""
                SELECT id, sender, message, timestamp, read_by_desktop_at, read_by_code_at
                FROM messages WHERE id IN ({}) ORDER BY id DESC
            """.format(placeholders), ids).fetchall()

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
    try:
        with _get_connection() as conn:
            cursor = conn.execute("DELETE FROM messages")
            deleted = cursor.rowcount
            conn.commit()
        return {"ok": True, "deleted": deleted}
    except sqlite3.Error as e:
        return {"ok": False, "error": f"Database error: {e}"}


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    # Start background notification thread
    _start_notification_thread()
    # Run with stdio transport (standard for Claude Desktop/Code integration)
    # All logging goes to stderr; stdout is reserved for MCP JSON-RPC messages
    mcp.run(transport="stdio")
