"""Email tools for ProxyAPI tool calling — stdlib only (imaplib, smtplib, ssl, email.*)."""

from __future__ import annotations

import email
import email.header
import email.mime.multipart
import email.mime.text
import imaplib
import re
import smtplib
import ssl
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_commander.session.extension_store import ExtensionStore

_PROVIDER_SETTINGS: dict[str, dict] = {
    "yandex_mail": {
        "imap_host": "imap.yandex.ru",
        "imap_port": 993,
        "smtp_host": "smtp.yandex.ru",
        "smtp_port": 465,
    },
    "google": {
        "imap_host": "imap.gmail.com",
        "imap_port": 993,
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 465,
    },
}

EMAIL_TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "email_list_emails",
            "description": "List emails in a mailbox folder. Returns From/Subject/Date/UID for each message.",
            "parameters": {
                "type": "object",
                "properties": {
                    "folder": {
                        "type": "string",
                        "description": "Mailbox folder name (default: INBOX).",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of messages to return (default: 10, max: 50).",
                    },
                    "only_unread": {
                        "type": "boolean",
                        "description": "If true, return only unread messages (default: false).",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "email_get_email",
            "description": "Fetch the full body of an email by its UID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "uid": {
                        "type": "string",
                        "description": "UID of the message to fetch.",
                    },
                    "folder": {
                        "type": "string",
                        "description": "Mailbox folder name (default: INBOX).",
                    },
                },
                "required": ["uid"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "email_send_email",
            "description": "Send an email via SMTP.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "description": "Recipient email address.",
                    },
                    "subject": {
                        "type": "string",
                        "description": "Email subject.",
                    },
                    "body": {
                        "type": "string",
                        "description": "Plain-text body of the email.",
                    },
                },
                "required": ["to", "subject", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "email_search_emails",
            "description": "Search emails by keyword in From or Subject fields using IMAP SEARCH.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search keyword to look for in From or Subject.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default: 10, max: 50).",
                    },
                },
                "required": ["query"],
            },
        },
    },
]


# ── Credential / settings helpers ─────────────────────────────────────────────


def _find_email_extension(extension_store: "ExtensionStore") -> tuple[dict, dict] | None:
    """Return (credentials, provider_settings) for first connected email extension.

    Returns None if no connected email extension is found.
    """
    for ext in extension_store.list_extensions():
        if ext.status != "connected":
            continue
        settings = _PROVIDER_SETTINGS.get(ext.provider)
        if settings is None:
            continue
        creds = ext.credentials
        if not creds.get("email") or not creds.get("token"):
            continue
        return creds, settings
    return None


# ── IMAP helpers ───────────────────────────────────────────────────────────────


def _imap_connect(creds: dict, settings: dict) -> imaplib.IMAP4_SSL:
    """Open an authenticated IMAP4_SSL connection."""
    ctx = ssl.create_default_context()
    client = imaplib.IMAP4_SSL(settings["imap_host"], settings["imap_port"], ssl_context=ctx)
    client.login(creds["email"], creds["token"])
    return client


def _decode_header_value(value: str | None) -> str:
    """Decode an RFC 2047-encoded header value to a plain string."""
    if not value:
        return ""
    parts: list[str] = []
    for decoded, charset in email.header.decode_header(value):
        if isinstance(decoded, bytes):
            parts.append(decoded.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(str(decoded))
    return "".join(parts)


def _extract_text_body(msg: email.message.Message) -> str:
    """Extract plain-text body from a parsed email message."""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition") or "")
            if ct == "text/plain" and "attachment" not in cd:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
        # fallback: try text/html
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return _html_to_text(payload.decode(charset, errors="replace"))
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
            if msg.get_content_type() == "text/html":
                return _html_to_text(text)
            return text
    return ""


def _html_to_text(raw: str) -> str:
    """Minimal HTML → plain text: strip tags, collapse whitespace."""
    text = re.sub(r"<(script|style)[^>]*>.*?</(script|style)>", "", raw, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<p[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r" {2,}", " ", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _fetch_messages(client: imaplib.IMAP4_SSL, criteria: str, limit: int) -> list[dict]:
    """Search IMAP with criteria, fetch envelope headers, return list of dicts."""
    _status, data = client.uid("search", None, criteria)  # type: ignore[arg-type]
    uids = data[0].split() if data and data[0] else []
    # newest first
    uids = list(reversed(uids))[:limit]

    messages: list[dict] = []
    for uid in uids:
        _s, raw = client.uid("fetch", uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")  # type: ignore[arg-type]
        if not raw or not raw[0]:
            continue
        header_bytes = raw[0][1] if isinstance(raw[0], tuple) else b""
        if not isinstance(header_bytes, bytes):
            continue
        msg = email.message_from_bytes(header_bytes)
        messages.append({
            "uid": uid.decode("ascii") if isinstance(uid, bytes) else str(uid),
            "from": _decode_header_value(msg.get("From")),
            "subject": _decode_header_value(msg.get("Subject")),
            "date": _decode_header_value(msg.get("Date")),
        })
    return messages


# ── Tool implementations ───────────────────────────────────────────────────────


def _tool_list_emails(creds: dict, settings: dict, folder: str, limit: int, only_unread: bool) -> str:
    folder = folder or "INBOX"
    limit = max(1, min(limit or 10, 50))
    criteria = "UNSEEN" if only_unread else "ALL"

    client = _imap_connect(creds, settings)
    try:
        client.select(folder, readonly=True)
        messages = _fetch_messages(client, criteria, limit)
    finally:
        try:
            client.logout()
        except Exception:
            pass

    if not messages:
        return f"No messages found in {folder} (criteria: {criteria})."

    lines = [f"Found {len(messages)} message(s) in {folder}:\n"]
    for m in messages:
        lines.append(f"UID: {m['uid']}")
        lines.append(f"  From:    {m['from']}")
        lines.append(f"  Subject: {m['subject']}")
        lines.append(f"  Date:    {m['date']}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _tool_get_email(creds: dict, settings: dict, uid: str, folder: str) -> str:
    folder = folder or "INBOX"

    client = _imap_connect(creds, settings)
    try:
        client.select(folder, readonly=True)
        _s, raw = client.uid("fetch", uid.encode(), "(RFC822)")  # type: ignore[arg-type]
    finally:
        try:
            client.logout()
        except Exception:
            pass

    if not raw or not raw[0] or not isinstance(raw[0], tuple):
        return f"Error: message UID {uid} not found in {folder}."

    msg_bytes = raw[0][1]
    if not isinstance(msg_bytes, bytes):
        return f"Error: unexpected data type for message UID {uid}."

    msg = email.message_from_bytes(msg_bytes)
    from_val = _decode_header_value(msg.get("From"))
    subject = _decode_header_value(msg.get("Subject"))
    date = _decode_header_value(msg.get("Date"))
    body = _extract_text_body(msg)

    result = f"From:    {from_val}\nSubject: {subject}\nDate:    {date}\n\n{body}"
    # Truncate very long bodies
    if len(result) > 20_000:
        result = result[:20_000] + f"\n... (truncated, {len(result)} total chars)"
    return result


def _tool_send_email(creds: dict, settings: dict, to: str, subject: str, body: str) -> str:
    sender = creds["email"]
    password = creds["token"]

    mime_msg = email.mime.multipart.MIMEMultipart()
    mime_msg["From"] = sender
    mime_msg["To"] = to
    mime_msg["Subject"] = subject
    mime_msg.attach(email.mime.text.MIMEText(body, "plain", "utf-8"))

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(settings["smtp_host"], settings["smtp_port"], context=ctx) as smtp:
        smtp.login(sender, password)
        smtp.sendmail(sender, [to], mime_msg.as_string())

    return f"Email sent successfully to {to} with subject '{subject}'."


def _tool_search_emails(creds: dict, settings: dict, query: str, limit: int) -> str:
    limit = max(1, min(limit or 10, 50))

    # IMAP SEARCH: OR FROM <query> SUBJECT <query>
    # RFC 3501: search key arguments must be quoted strings
    safe_query = query.replace('"', "").replace("\\", "")
    criteria = f'OR FROM "{safe_query}" SUBJECT "{safe_query}"'

    client = _imap_connect(creds, settings)
    try:
        client.select("INBOX", readonly=True)
        messages = _fetch_messages(client, criteria, limit)
    finally:
        try:
            client.logout()
        except Exception:
            pass

    if not messages:
        return f"No messages found matching '{query}'."

    lines = [f"Found {len(messages)} message(s) matching '{query}':\n"]
    for m in messages:
        lines.append(f"UID: {m['uid']}")
        lines.append(f"  From:    {m['from']}")
        lines.append(f"  Subject: {m['subject']}")
        lines.append(f"  Date:    {m['date']}")
        lines.append("")
    return "\n".join(lines).rstrip()


# ── Public execute function ────────────────────────────────────────────────────


def execute_email_tool(
    name: str,
    args: dict,
    extension_store: "ExtensionStore",
) -> str:
    """Dispatch an email_* tool call.

    Finds the first connected email extension, derives IMAP/SMTP settings,
    and calls the appropriate implementation.
    """
    found = _find_email_extension(extension_store)
    if found is None:
        return "Error: no connected email extension found. Connect an email account in Extensions settings."

    creds, settings = found

    try:
        if name == "email_list_emails":
            return _tool_list_emails(
                creds=creds,
                settings=settings,
                folder=args.get("folder", "INBOX"),
                limit=args.get("limit", 10),
                only_unread=bool(args.get("only_unread", False)),
            )
        elif name == "email_get_email":
            uid = str(args.get("uid", "")).strip()
            if not uid:
                return "Error: uid is required"
            return _tool_get_email(
                creds=creds,
                settings=settings,
                uid=uid,
                folder=args.get("folder", "INBOX"),
            )
        elif name == "email_send_email":
            to = str(args.get("to", "")).strip()
            subject = str(args.get("subject", "")).strip()
            body = str(args.get("body", "")).strip()
            if not to:
                return "Error: to is required"
            if not subject:
                return "Error: subject is required"
            if not body:
                return "Error: body is required"
            return _tool_send_email(creds=creds, settings=settings, to=to, subject=subject, body=body)
        elif name == "email_search_emails":
            query = str(args.get("query", "")).strip()
            if not query:
                return "Error: query is required"
            return _tool_search_emails(
                creds=creds,
                settings=settings,
                query=query,
                limit=args.get("limit", 10),
            )
        else:
            return f"Error: unknown email tool '{name}'"
    except imaplib.IMAP4.error as exc:
        return f"Error: IMAP error: {exc}"
    except smtplib.SMTPException as exc:
        return f"Error: SMTP error: {exc}"
    except OSError as exc:
        return f"Error: connection error: {exc}"
    except Exception as exc:
        return f"Error executing {name}: {exc}"
