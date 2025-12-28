#!/usr/bin/env python3
"""
Notification daemon for the MCP relay.

Watches the relay buffer and sends system notifications when unread messages
appear. No arguments needed—it figures out who to notify based on read status.

Usage:
    python relay_notify.py

macOS: Uses osascript for notifications
Linux: Uses notify-send (install libnotify)
"""

import platform
import sqlite3
import subprocess
import time
from pathlib import Path

DB_PATH = Path.home() / ".relay_buffer.db"
POLL_INTERVAL = 2  # seconds


def send_notification(title: str, message: str):
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


def get_unread_messages() -> list[tuple[int, str, str, bool, bool]]:
    """Get all messages with their read status.

    Returns list of (id, sender, message, read_by_desktop, read_by_code).
    """
    if not DB_PATH.exists():
        return []
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute("""
            SELECT id, sender, message,
                   read_by_desktop_at IS NOT NULL as read_by_desktop,
                   read_by_code_at IS NOT NULL as read_by_code
            FROM messages
            ORDER BY id
        """)
        rows = [(r[0], r[1], r[2], bool(r[3]), bool(r[4])) for r in cursor.fetchall()]
        conn.close()
        return rows
    except sqlite3.Error:
        return []


def main():
    print("Watching for unread relay messages...")
    print(f"Polling every {POLL_INTERVAL}s. Press Ctrl+C to stop.")

    # Track which messages we've already notified about
    notified_for_desktop: set[int] = set()
    notified_for_code: set[int] = set()

    try:
        while True:
            messages = get_unread_messages()

            for msg_id, sender, content, read_by_desktop, read_by_code in messages:
                # Message from Desktop, not yet read by Code
                if sender == "desktop" and not read_by_code:
                    if msg_id not in notified_for_code:
                        send_notification("Relay: from Desktop", content)
                        notified_for_code.add(msg_id)

                # Message from Code, not yet read by Desktop
                if sender == "code" and not read_by_desktop:
                    if msg_id not in notified_for_desktop:
                        send_notification("Relay: from Code", content)
                        notified_for_desktop.add(msg_id)

            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
