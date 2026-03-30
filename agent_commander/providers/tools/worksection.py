"""Worksection integration tools — stdlib only (urllib, hashlib)."""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_commander.session.extension_store import ExtensionStore

_WS_TIMEOUT = 20


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

WORKSECTION_TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "ws_get_projects",
            "description": "List all Worksection projects in the account.",
            "parameters": {
                "type": "object",
                "properties": {
                    "connection": {
                        "type": "string",
                        "enum": ["user", "admin"],
                        "description": "Which connection to use: 'user' (OAuth) or 'admin' (API token). Default: 'user'.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ws_get_tasks",
            "description": "Get tasks from a Worksection project. Returns task IDs — use them for ws_add_comment and ws_update_task.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_page": {
                        "type": "string",
                        "description": "Project permalink path, e.g. '/project/my-project/'.",
                    },
                    "extra": {
                        "type": "boolean",
                        "description": "Include extra task fields (assignees, tags, etc.). Default: false.",
                    },
                    "connection": {
                        "type": "string",
                        "enum": ["user", "admin"],
                        "description": "Which connection to use. Default: 'user'.",
                    },
                },
                "required": ["project_page"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ws_get_task",
            "description": "Get details of a specific Worksection task.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_page": {
                        "type": "string",
                        "description": "Project permalink path, e.g. '/project/my-project/'.",
                    },
                    "task_id": {
                        "type": "integer",
                        "description": "Task numeric ID.",
                    },
                    "connection": {
                        "type": "string",
                        "enum": ["user", "admin"],
                        "description": "Which connection to use. Default: 'user'.",
                    },
                },
                "required": ["project_page", "task_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ws_create_task",
            "description": "Create a new task in a Worksection project.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_page": {
                        "type": "string",
                        "description": "Project permalink path, e.g. '/project/my-project/'.",
                    },
                    "title": {
                        "type": "string",
                        "description": "Task title.",
                    },
                    "text": {
                        "type": "string",
                        "description": "Task description text.",
                    },
                    "assignee_email": {
                        "type": "string",
                        "description": "Email of the user to assign the task to.",
                    },
                    "date_begin": {
                        "type": "string",
                        "description": "Start date in DD.MM.YYYY format.",
                    },
                    "date_end": {
                        "type": "string",
                        "description": "Due date in DD.MM.YYYY format.",
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["low", "normal", "high"],
                        "description": "Task priority. Default: 'normal'.",
                    },
                    "connection": {
                        "type": "string",
                        "enum": ["user", "admin"],
                        "description": "Which connection to use. Default: 'user'.",
                    },
                },
                "required": ["project_page", "title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ws_update_task",
            "description": "Update an existing Worksection task.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_page": {
                        "type": "string",
                        "description": "Project permalink path, e.g. '/project/my-project/'.",
                    },
                    "task_id": {
                        "type": "integer",
                        "description": "Task numeric ID.",
                    },
                    "title": {
                        "type": "string",
                        "description": "New task title.",
                    },
                    "text": {
                        "type": "string",
                        "description": "New task description.",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["active", "done", "deferred"],
                        "description": "Task status.",
                    },
                    "assignee_email": {
                        "type": "string",
                        "description": "Email of the user to assign to.",
                    },
                    "date_begin": {
                        "type": "string",
                        "description": "Start date in DD.MM.YYYY format.",
                    },
                    "date_end": {
                        "type": "string",
                        "description": "Due date in DD.MM.YYYY format.",
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["low", "normal", "high"],
                        "description": "Task priority.",
                    },
                    "connection": {
                        "type": "string",
                        "enum": ["user", "admin"],
                        "description": "Which connection to use. Default: 'user'.",
                    },
                },
                "required": ["project_page", "task_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ws_add_comment",
            "description": "Add a comment to a Worksection task. Can mention/notify specific users.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_page": {
                        "type": "string",
                        "description": "Project permalink path, e.g. '/project/my-project/'.",
                    },
                    "task_id": {
                        "type": "integer",
                        "description": "Task numeric ID.",
                    },
                    "text": {
                        "type": "string",
                        "description": "Comment text.",
                    },
                    "mention_emails": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of user emails to @mention and notify in the comment.",
                    },
                    "connection": {
                        "type": "string",
                        "enum": ["user", "admin"],
                        "description": "Which connection to use. Default: 'user'.",
                    },
                },
                "required": ["project_page", "task_id", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ws_get_users",
            "description": "List all users in the Worksection account. Requires admin connection.",
            "parameters": {
                "type": "object",
                "properties": {
                    "connection": {
                        "type": "string",
                        "enum": ["user", "admin"],
                        "description": "Which connection to use. Default: 'admin'.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ws_get_time",
            "description": "Get time entries (time tracking records) for a project or task.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_page": {
                        "type": "string",
                        "description": "Project permalink path, e.g. '/project/my-project/'.",
                    },
                    "task_id": {
                        "type": "integer",
                        "description": "Optional task ID to filter by.",
                    },
                    "connection": {
                        "type": "string",
                        "enum": ["user", "admin"],
                        "description": "Which connection to use. Default: 'admin'.",
                    },
                },
                "required": ["project_page"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ws_get_comments",
            "description": "Get comments for a Worksection project or specific task. Use to see recent activity and discussion.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_page": {
                        "type": "string",
                        "description": "Project permalink path, e.g. '/project/my-project/'.",
                    },
                    "task_id": {
                        "type": "integer",
                        "description": "Optional task ID to get comments only for that task.",
                    },
                    "connection": {
                        "type": "string",
                        "enum": ["user", "admin"],
                        "description": "Which connection to use. Default: 'user'.",
                    },
                },
                "required": ["project_page"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ws_get_notices",
            "description": "Get recent notifications/activity feed for the current user in Worksection.",
            "parameters": {
                "type": "object",
                "properties": {
                    "connection": {
                        "type": "string",
                        "enum": ["user", "admin"],
                        "description": "Which connection to use. Default: 'user'.",
                    },
                },
                "required": [],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _md5(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def _admin_hash(action: str, page: str, api_key: str) -> str:
    """Compute Worksection admin API hash: MD5(page + action + api_key)."""
    return _md5(page + action + api_key)


def _find_extension(
    extension_store: "ExtensionStore",
    active_ids: list[str] | None,
    prefer: str,
) -> "tuple[str, dict] | tuple[None, None]":
    """Find a connected Worksection extension.

    prefer: 'user' | 'admin' — which type to try first.
    Returns (provider_type, credentials) or (None, None).
    """
    candidates = active_ids or [
        e.id for e in extension_store.list_extensions()
        if e.status == "connected"
    ]
    order = (
        ["worksection_user", "worksection_admin"]
        if prefer == "user"
        else ["worksection_admin", "worksection_user"]
    )
    by_provider: dict[str, dict] = {}
    for ext_id in candidates:
        ext = extension_store.get_extension(ext_id)
        if ext and ext.status == "connected" and ext.provider in (
            "worksection_user", "worksection_admin"
        ):
            by_provider[ext.provider] = ext.credentials

    for ptype in order:
        if ptype in by_provider:
            return ptype, by_provider[ptype]
    return None, None


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _ws_admin_request(
    account: str,
    email: str,
    api_key: str,
    action: str,
    extra_params: dict | None = None,
) -> dict:
    """Make a Worksection admin API request via POST."""
    params: dict = {"action": action, "email": email}
    if extra_params:
        params.update(extra_params)

    page = params.get("page", "")
    params["hash"] = _admin_hash(action, page, api_key)

    base_url = f"https://{account}/api/admin/v2/"
    url = base_url + "?" + urllib.parse.urlencode({"action": action}, encoding="utf-8")
    post_data = urllib.parse.urlencode(
        {k: v for k, v in params.items() if k != "action"}, encoding="utf-8"
    ).encode("utf-8")

    req = urllib.request.Request(url, data=post_data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=_WS_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _ws_user_request(
    account: str,
    access_token: str,
    action: str,
    extra_params: dict | None = None,
) -> dict:
    """Make a Worksection user API request via POST with OAuth Bearer token."""
    url = f"https://{account}/api/oauth2?action={urllib.parse.quote(action)}"
    post_data = urllib.parse.urlencode(extra_params or {}, encoding="utf-8").encode("utf-8")

    req = urllib.request.Request(url, data=post_data, method="POST")
    req.add_header("Authorization", f"Bearer {access_token}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=_WS_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _normalize_domain(account: str) -> str:
    """Strip https:// prefix and trailing slash, return bare domain."""
    domain = account.strip().rstrip("/")
    if domain.startswith("https://"):
        domain = domain[8:]
    elif domain.startswith("http://"):
        domain = domain[7:]
    return domain


def _api_call(
    provider: str,
    creds: dict,
    action: str,
    extra_params: dict | None = None,
) -> dict:
    """Dispatch API call to the right auth method."""
    raw_account = creds.get("account", "")
    if not raw_account:
        return {"status": "error", "error": "account domain not set in credentials"}
    account = _normalize_domain(raw_account)

    if provider == "worksection_admin":
        email = creds.get("email", "")
        api_key = creds.get("api_key", "")
        if not api_key:
            return {"status": "error", "error": "api_key not set in admin credentials"}
        return _ws_admin_request(account, email, api_key, action, extra_params)

    # worksection_user — OAuth bearer
    access_token = creds.get("access_token", "")
    if not access_token:
        return {"status": "error", "error": "access_token not set in user credentials"}
    return _ws_user_request(account, access_token, action, extra_params)


def _format_response(data: dict) -> str:
    """Format API response as readable text."""
    if data.get("status") == "error":
        return f"Error: {data.get('error', 'unknown error')}"
    return json.dumps(data, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _ws_get_projects(provider: str, creds: dict) -> str:
    result = _api_call(provider, creds, "get_projects")
    if result.get("status") == "error":
        return f"Error: {result.get('error')}"
    projects = result.get("data", [])
    if not projects:
        return "No projects found."
    lines = [f"Found {len(projects)} project(s):"]
    for p in projects:
        status = p.get("status", "")
        name = p.get("name", "")
        page = p.get("page", "")
        lines.append(f"  - [{status}] {name}  (page: {page})")
    return "\n".join(lines)


def _ws_get_tasks(provider: str, creds: dict, project_page: str, extra: bool) -> str:
    params: dict = {"page": project_page}
    if extra:
        params["extra"] = "1"
    result = _api_call(provider, creds, "get_tasks", params)
    if result.get("status") == "error":
        return f"Error: {result.get('error')}"
    tasks = result.get("data", [])
    if not tasks:
        return f"No tasks found in project '{project_page}'."
    lines = [f"Found {len(tasks)} task(s) in '{project_page}':"]
    for t in tasks:
        tid = t.get("id", "?")
        title = t.get("name", "")
        status = t.get("status", "")
        assigned = t.get("assigned", {})
        assignee = assigned.get("name", "") if isinstance(assigned, dict) else ""
        due = t.get("date_end", "")
        parts = [f"  [{tid}] {title}"]
        if status:
            parts.append(f"status={status}")
        if assignee:
            parts.append(f"assignee={assignee}")
        if due:
            parts.append(f"due={due}")
        lines.append(" ".join(parts))
    return "\n".join(lines)


def _ws_get_task(provider: str, creds: dict, project_page: str, task_id: int) -> str:
    params = {"page": project_page, "task": task_id}
    result = _api_call(provider, creds, "get_task", params)
    if result.get("status") == "error":
        return f"Error: {result.get('error')}"
    return _format_response(result)


def _ws_create_task(
    provider: str, creds: dict, project_page: str, title: str,
    text: str, assignee_email: str, date_begin: str, date_end: str, priority: str,
) -> str:
    params: dict = {"page": project_page, "title": title}
    if text:
        params["text"] = text
    if assignee_email:
        params["email"] = assignee_email
    if date_begin:
        params["datebegin"] = date_begin
    if date_end:
        params["dateend"] = date_end
    if priority and priority != "normal":
        params["priority"] = priority
    result = _api_call(provider, creds, "add_task", params)
    if result.get("status") == "error":
        return f"Error: {result.get('error')}"
    task_id = result.get("data", {}).get("id", "?") if isinstance(result.get("data"), dict) else "?"
    return f"Task created (id={task_id}): {title}"


def _ws_update_task(
    provider: str, creds: dict, project_page: str, task_id: int,
    title: str, text: str, status: str, assignee_email: str,
    date_begin: str, date_end: str, priority: str,
) -> str:
    params: dict = {"page": project_page, "task": task_id}
    if title:
        params["title"] = title
    if text:
        params["text"] = text
    if status:
        params["status"] = status
    if assignee_email:
        params["email"] = assignee_email
    if date_begin:
        params["datebegin"] = date_begin
    if date_end:
        params["dateend"] = date_end
    if priority:
        params["priority"] = priority
    result = _api_call(provider, creds, "update_task", params)
    if result.get("status") == "error":
        return f"Error: {result.get('error')}"
    return f"Task {task_id} updated successfully."


def _ws_add_comment(
    provider: str, creds: dict, project_page: str, task_id: int,
    text: str, mention_emails: list[str] | None = None,
) -> str:
    # Prepend @mentions to text
    full_text = text
    if mention_emails:
        mentions = " ".join(f"@{e}" for e in mention_emails)
        full_text = f"{mentions} {text}"

    # user_to: comma-separated emails for server-side notifications
    params: dict = {"page": project_page, "id_task": task_id, "text": full_text}
    if mention_emails:
        params["user_to"] = ",".join(mention_emails)

    result = _api_call(provider, creds, "post_comment", params)
    if result.get("status") == "error":
        # OAuth may use 'task' instead of 'id_task' — retry with alternate param
        params2 = {k: v for k, v in params.items()}
        params2["task"] = params2.pop("id_task")
        result2 = _api_call(provider, creds, "post_comment", params2)
        if result2.get("status") != "error":
            return f"Comment added to task {task_id}."
        # Both failed — return full response for diagnosis
        err_msg = result2.get("error") or result2.get("message") or result2.get("msg")
        raw1 = json.dumps(result, ensure_ascii=False)
        raw2 = json.dumps(result2, ensure_ascii=False)
        if err_msg:
            return f"Error: {err_msg} (tried id_task: {raw1}, task: {raw2})"
        return f"Error posting comment. Response 1 (id_task): {raw1} | Response 2 (task): {raw2}"

    mentioned = f", notified: {', '.join(mention_emails)}" if mention_emails else ""
    return f"Comment added to task {task_id}{mentioned}."


def _ws_get_users(provider: str, creds: dict) -> str:
    result = _api_call(provider, creds, "get_users")
    if result.get("status") == "error":
        return f"Error: {result.get('error')}"
    users = result.get("data", [])
    if not users:
        return "No users found."
    lines = [f"Found {len(users)} user(s):"]
    for u in users:
        name = u.get("name", "")
        email = u.get("email", "")
        role = u.get("type", "")
        lines.append(f"  - {name} <{email}> [{role}]")
    return "\n".join(lines)


def _ws_get_time(provider: str, creds: dict, project_page: str, task_id: int | None) -> str:
    params: dict = {"page": project_page}
    if task_id:
        params["task"] = task_id
    result = _api_call(provider, creds, "get_time", params)
    if result.get("status") == "error":
        return f"Error: {result.get('error')}"
    entries = result.get("data", [])
    if not entries:
        return "No time entries found."
    lines = [f"Found {len(entries)} time entry(ies):"]
    for e in entries:
        user = e.get("user_name", e.get("email", "?"))
        hours = e.get("time", "?")
        date = e.get("date", "")
        comment = e.get("comment", "")
        line = f"  - {user}: {hours}h on {date}"
        if comment:
            line += f" — {comment[:60]}"
        lines.append(line)
    return "\n".join(lines)


def _ws_get_comments(
    provider: str, creds: dict, project_page: str, task_id: int | None
) -> str:
    params: dict = {"page": project_page}
    if task_id:
        params["task"] = task_id
    result = _api_call(provider, creds, "get_comments", params)
    if result.get("status") == "error":
        return f"Error: {result.get('error')}"
    comments = result.get("data", [])
    if not comments:
        return "No comments found."
    lines = [f"Found {len(comments)} comment(s):"]
    for c in comments:
        author = c.get("user_name", c.get("email", "?"))
        date = c.get("date", "")
        text = c.get("text", "").strip()[:200]
        task = c.get("task_id", "")
        task_str = f" [task #{task}]" if task else ""
        lines.append(f"  [{date}]{task_str} {author}: {text}")
    return "\n".join(lines)


def _ws_get_notices(provider: str, creds: dict) -> str:
    result = _api_call(provider, creds, "get_notices")
    if result.get("status") == "error":
        return f"Error: {result.get('error')}"
    notices = result.get("data", [])
    if not notices:
        return "No notifications found."
    lines = [f"Found {len(notices)} notification(s):"]
    for n in notices:
        date = n.get("date", "")
        text = n.get("text", n.get("message", "")).strip()[:200]
        author = n.get("user_name", "")
        lines.append(f"  [{date}] {author}: {text}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main dispatcher
# ---------------------------------------------------------------------------

def execute_worksection_tool(
    name: str,
    args: dict,
    extension_store: "ExtensionStore",
    active_ids: list[str] | None,
) -> str:
    """Route a ws_* tool call to the appropriate implementation."""
    prefer = args.get("connection", "user")
    # ws_get_users and ws_get_time default to admin
    if name in ("ws_get_users", "ws_get_time") and "connection" not in args:
        prefer = "admin"

    provider, creds = _find_extension(extension_store, active_ids, prefer)
    if provider is None or creds is None:
        return (
            "Error: no connected Worksection extension found. "
            "Please connect Worksection User or Worksection Admin in Extensions."
        )

    try:
        if name == "ws_get_projects":
            return _ws_get_projects(provider, creds)
        elif name == "ws_get_tasks":
            return _ws_get_tasks(
                provider, creds,
                args.get("project_page", ""),
                bool(args.get("extra", False)),
            )
        elif name == "ws_get_task":
            return _ws_get_task(
                provider, creds,
                args.get("project_page", ""),
                int(args.get("task_id", 0)),
            )
        elif name == "ws_create_task":
            return _ws_create_task(
                provider, creds,
                args.get("project_page", ""),
                args.get("title", ""),
                args.get("text", ""),
                args.get("assignee_email", ""),
                args.get("date_begin", ""),
                args.get("date_end", ""),
                args.get("priority", "normal"),
            )
        elif name == "ws_update_task":
            return _ws_update_task(
                provider, creds,
                args.get("project_page", ""),
                int(args.get("task_id", 0)),
                args.get("title", ""),
                args.get("text", ""),
                args.get("status", ""),
                args.get("assignee_email", ""),
                args.get("date_begin", ""),
                args.get("date_end", ""),
                args.get("priority", ""),
            )
        elif name == "ws_add_comment":
            return _ws_add_comment(
                provider, creds,
                args.get("project_page", ""),
                int(args.get("task_id", 0)),
                args.get("text", ""),
                args.get("mention_emails") or None,
            )
        elif name == "ws_get_users":
            return _ws_get_users(provider, creds)
        elif name == "ws_get_time":
            task_id = args.get("task_id")
            return _ws_get_time(
                provider, creds,
                args.get("project_page", ""),
                int(task_id) if task_id else None,
            )
        elif name == "ws_get_comments":
            task_id = args.get("task_id")
            return _ws_get_comments(
                provider, creds,
                args.get("project_page", ""),
                int(task_id) if task_id else None,
            )
        elif name == "ws_get_notices":
            return _ws_get_notices(provider, creds)
        else:
            return f"Error: unknown worksection tool: {name}"
    except urllib.error.HTTPError as exc:
        return f"Error: HTTP {exc.code} — {exc.reason}"
    except urllib.error.URLError as exc:
        return f"Error: network error — {exc.reason}"
    except Exception as exc:
        return f"Error: {exc}"
