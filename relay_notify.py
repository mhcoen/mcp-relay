#!/usr/bin/env python3
"""
Notification daemon for the MCP relay.

Watches the relay buffer and sends system notifications when messages arrive
from the other side. Run this in the background to get notified without polling.

Usage:
    python relay_notify.py --for code     # Notify when Desktop sends to Code
    python relay_notify.py --for desktop  # Notify when Code sends to Desktop

macOS: Uses osascript for notifications
Linux: Uses notify-send (install libnotify)
"""

import argparse
import platform
import sqlite3
import subprocess
import time
from pathlib import Path

DB_PATH = Path.home() / ".relay_buffer.db"
POLL_INTERVAL = 2  # seconds


def get_last_message_id() -> int:
    """Get the ID of the most recent message."""
    if not DB_PATH.exists():
        return 0
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute("SELECT MAX(id) FROM messages")
        result = cursor.fetchone()[0]
        conn.close()
        return result or 0
    except sqlite3.Error:
        return 0


def get_new_messages(since_id: int, from_sender: str) -> list[tuple[int, str]]:
    """Get messages from a sender since the given ID."""
    if not DB_PATH.exists():
        return []
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            "SELECT id, message FROM messages WHERE id > ? AND sender = ? ORDER BY id",
            (since_id, from_sender)
        )
        rows = [(row["id"], row["message"]) for row in cursor.fetchall()]
        conn.close()
        return rows
    except sqlite3.Error:
        return []


def send_notification(title: str, message: str):
    """Send a system notification."""
    # Truncate long messages
    if len(message) > 200:
        message = message[:197] + "..."

    system = platform.system()

    if system == "Darwin":  # macOS
        script = f'display notification "{message}" with title "{title}"'
        subprocess.run(["osascript", "-e", script], capture_output=True)
    elif system == "Linux":
        subprocess.run(["notify-send", title, message], capture_output=True)
    elif system == "Windows":
        # Basic PowerShell notification
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


def main():
    parser = argparse.ArgumentParser(description="Relay notification daemon")
    parser.add_argument(
        "--for",
        dest="recipient",
        choices=["desktop", "code"],
        required=True,
        help="Who to notify (desktop or code)"
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=POLL_INTERVAL,
        help=f"Poll interval in seconds (default: {POLL_INTERVAL})"
    )
    args = parser.parse_args()

    # Notify recipient when the OTHER side sends
    from_sender = "code" if args.recipient == "desktop" else "desktop"

    print(f"Watching for messages from {from_sender}...")
    print(f"Polling every {args.interval}s. Press Ctrl+C to stop.")

    last_id = get_last_message_id()

    try:
        while True:
            new_messages = get_new_messages(last_id, from_sender)

            for msg_id, content in new_messages:
                title = f"Relay: message from {from_sender.title()}"
                send_notification(title, content)
                last_id = msg_id

            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
