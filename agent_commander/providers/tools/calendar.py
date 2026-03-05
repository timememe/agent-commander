"""Google Calendar tools — Google Calendar REST API via stdlib urllib (no extra dependencies)."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_commander.session.extension_store import ExtensionStore

CALENDAR_TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "calendar_list_events",
            "description": "List upcoming events from the user's primary Google Calendar.",
            "parameters": {
                "type": "object",
                "properties": {
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of events to return (default: 10, max: 50).",
                    },
                    "time_min": {
                        "type": "string",
                        "description": "Lower bound for event start time (ISO 8601 / RFC 3339). Defaults to now.",
                    },
                    "query": {
                        "type": "string",
                        "description": "Free-text search terms to filter events.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calendar_create_event",
            "description": "Create a new event in the user's primary Google Calendar.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Title of the event.",
                    },
                    "start": {
                        "type": "string",
                        "description": (
                            "Start time in ISO 8601 format with timezone offset, "
                            "e.g. '2024-03-15T10:00:00+03:00'. "
                            "For all-day events use 'YYYY-MM-DD' (no time part)."
                        ),
                    },
                    "end": {
                        "type": "string",
                        "description": (
                            "End time in same format. For all-day events, use the day after start."
                        ),
                    },
                    "description": {
                        "type": "string",
                        "description": "Event description (optional).",
                    },
                    "location": {
                        "type": "string",
                        "description": "Location of the event (optional).",
                    },
                    "attendees": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of attendee email addresses (optional).",
                    },
                },
                "required": ["summary", "start", "end"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calendar_delete_event",
            "description": "Delete an event from the user's primary Google Calendar by its ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {
                        "type": "string",
                        "description": "ID of the event to delete (use calendar_list_events to get IDs).",
                    },
                },
                "required": ["event_id"],
            },
        },
    },
]

_BASE = "https://www.googleapis.com/calendar/v3"


# ── Internal helpers ───────────────────────────────────────────────────────────


def _request(token: str, method: str, url: str, body: dict | None = None) -> dict:
    headers: dict[str, str] = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    data: bytes | None = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        err = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Google Calendar API {exc.code}: {err}") from exc


def _find_google_creds(
    extension_store: "ExtensionStore",
    active_ids: list[str] | None,
) -> str | None:
    """Return the OAuth token of the first active connected Google extension."""
    exts = extension_store.list_extensions()
    if active_ids:
        exts = [e for e in exts if e.id in active_ids]
    for ext in exts:
        if ext.status != "connected" or ext.provider != "google":
            continue
        token = ext.credentials.get("token", "")
        if token:
            return token
    return None


# ── Tool implementations ───────────────────────────────────────────────────────


def _tool_list_events(token: str, max_results: int, time_min: str, query: str) -> str:
    max_results = max(1, min(max_results or 10, 50))
    if not time_min:
        time_min = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    params: dict[str, str] = {
        "maxResults": str(max_results),
        "timeMin": time_min,
        "singleEvents": "true",
        "orderBy": "startTime",
    }
    if query:
        params["q"] = query

    qs = urllib.parse.urlencode(params)
    url = f"{_BASE}/calendars/primary/events?{qs}"
    data = _request(token, "GET", url)

    items = data.get("items", [])
    if not items:
        return "No upcoming events found."

    lines = [f"Found {len(items)} event(s):\n"]
    for ev in items:
        start_obj = ev.get("start", {})
        start = start_obj.get("dateTime") or start_obj.get("date", "")
        end_obj = ev.get("end", {})
        end = end_obj.get("dateTime") or end_obj.get("date", "")
        lines.append(f"ID:       {ev.get('id', '')}")
        lines.append(f"  Title:  {ev.get('summary', '(no title)')}")
        lines.append(f"  Start:  {start}")
        lines.append(f"  End:    {end}")
        if ev.get("location"):
            lines.append(f"  Where:  {ev['location']}")
        if ev.get("description"):
            desc = ev["description"][:120].replace("\n", " ")
            lines.append(f"  Desc:   {desc}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _tool_create_event(
    token: str,
    summary: str,
    start: str,
    end: str,
    description: str,
    location: str,
    attendees: list[str],
) -> str:
    is_date_only = "T" not in start
    if is_date_only:
        start_obj: dict = {"date": start}
        end_obj: dict = {"date": end}
    else:
        start_obj = {"dateTime": start}
        end_obj = {"dateTime": end}

    body: dict = {"summary": summary, "start": start_obj, "end": end_obj}
    if description:
        body["description"] = description
    if location:
        body["location"] = location
    if attendees:
        body["attendees"] = [{"email": a} for a in attendees]

    url = f"{_BASE}/calendars/primary/events"
    data = _request(token, "POST", url, body)
    ev_id = data.get("id", "")
    link = data.get("htmlLink", "")
    start_back = (data.get("start") or {})
    start_str = start_back.get("dateTime") or start_back.get("date", start)
    return f"Event created successfully.\nID:    {ev_id}\nStart: {start_str}\nLink:  {link}"


def _tool_delete_event(token: str, event_id: str) -> str:
    url = f"{_BASE}/calendars/primary/events/{urllib.parse.quote(event_id, safe='')}"
    headers = {"Authorization": f"Bearer {token}"}
    req = urllib.request.Request(url, headers=headers, method="DELETE")
    try:
        with urllib.request.urlopen(req):
            pass
        return f"Event '{event_id}' deleted successfully."
    except urllib.error.HTTPError as exc:
        err = exc.read().decode("utf-8", errors="replace")
        return f"Error: Google Calendar API {exc.code}: {err}"


# ── Public execute function ────────────────────────────────────────────────────


def execute_calendar_tool(
    name: str,
    args: dict,
    extension_store: "ExtensionStore",
    active_ids: list[str] | None = None,
) -> str:
    token = _find_google_creds(extension_store, active_ids)
    if token is None:
        return (
            "Error: no connected Google extension found. "
            "Connect a Google account in Extensions settings."
        )
    try:
        if name == "calendar_list_events":
            return _tool_list_events(
                token=token,
                max_results=int(args.get("max_results") or 10),
                time_min=str(args.get("time_min") or ""),
                query=str(args.get("query") or ""),
            )
        elif name == "calendar_create_event":
            summary = str(args.get("summary", "")).strip()
            start = str(args.get("start", "")).strip()
            end = str(args.get("end", "")).strip()
            if not summary:
                return "Error: summary is required"
            if not start or not end:
                return "Error: start and end are required"
            return _tool_create_event(
                token=token,
                summary=summary,
                start=start,
                end=end,
                description=str(args.get("description") or ""),
                location=str(args.get("location") or ""),
                attendees=list(args.get("attendees") or []),
            )
        elif name == "calendar_delete_event":
            event_id = str(args.get("event_id", "")).strip()
            if not event_id:
                return "Error: event_id is required"
            return _tool_delete_event(token=token, event_id=event_id)
        else:
            return f"Error: unknown calendar tool '{name}'"
    except RuntimeError as exc:
        return f"Error: {exc}"
    except Exception as exc:
        return f"Error executing {name}: {exc}"
