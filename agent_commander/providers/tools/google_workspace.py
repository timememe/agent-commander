"""Google Workspace tools — Drive, Docs, Sheets.

Requires: pip install google-api-python-client google-auth
Credentials are read from the active Google extension in ExtensionStore.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_commander.session.extension_store import ExtensionStore

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

GOOGLE_WORKSPACE_TOOL_DEFINITIONS: list[dict] = [
    # ── Drive ────────────────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "gdrive_list_files",
            "description": (
                "List files in Google Drive. Can search by name, MIME type, or parent folder. "
                "Returns file id, name, mimeType, modifiedTime for each item."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Drive search query, e.g. \"name contains 'report'\" or "
                            "\"mimeType='application/vnd.google-apps.spreadsheet'\". "
                            "Leave empty to list recent files."
                        ),
                    },
                    "folder_id": {
                        "type": "string",
                        "description": "ID of parent folder to list. Defaults to 'root'.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max number of results (default 20, max 100).",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gdrive_get_file_info",
            "description": "Get metadata for a specific Drive file by its ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_id": {"type": "string", "description": "Drive file ID."},
                },
                "required": ["file_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gdrive_create_folder",
            "description": "Create a folder in Google Drive.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Folder name."},
                    "parent_id": {
                        "type": "string",
                        "description": "ID of parent folder. Defaults to root.",
                    },
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gdrive_delete_file",
            "description": "Delete a file or folder from Google Drive by its ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_id": {"type": "string", "description": "Drive file ID to delete."},
                },
                "required": ["file_id"],
            },
        },
    },
    # ── Docs ─────────────────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "gdocs_create",
            "description": "Create a new Google Docs document.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Document title."},
                    "content": {
                        "type": "string",
                        "description": "Initial text content to insert (optional).",
                    },
                    "folder_id": {
                        "type": "string",
                        "description": "Move document to this Drive folder after creation (optional).",
                    },
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gdocs_get",
            "description": "Read a Google Docs document. Returns plain text content and document ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "document_id": {
                        "type": "string",
                        "description": "Google Docs document ID (from the URL).",
                    },
                },
                "required": ["document_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gdocs_append",
            "description": "Append text to the end of a Google Docs document.",
            "parameters": {
                "type": "object",
                "properties": {
                    "document_id": {"type": "string", "description": "Document ID."},
                    "text": {"type": "string", "description": "Text to append."},
                },
                "required": ["document_id", "text"],
            },
        },
    },
    # ── Sheets ───────────────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "gsheets_create",
            "description": "Create a new Google Sheets spreadsheet.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Spreadsheet title."},
                    "folder_id": {
                        "type": "string",
                        "description": "Move to this Drive folder after creation (optional).",
                    },
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gsheets_read",
            "description": "Read a range of cells from a Google Sheets spreadsheet.",
            "parameters": {
                "type": "object",
                "properties": {
                    "spreadsheet_id": {
                        "type": "string",
                        "description": "Spreadsheet ID (from the URL).",
                    },
                    "range": {
                        "type": "string",
                        "description": "A1 notation range, e.g. 'Sheet1!A1:D10' or 'A1:Z100'.",
                    },
                },
                "required": ["spreadsheet_id", "range"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gsheets_write",
            "description": "Write data to a range of cells in a Google Sheets spreadsheet.",
            "parameters": {
                "type": "object",
                "properties": {
                    "spreadsheet_id": {"type": "string", "description": "Spreadsheet ID."},
                    "range": {
                        "type": "string",
                        "description": "A1 notation range, e.g. 'Sheet1!A1'.",
                    },
                    "values": {
                        "type": "array",
                        "description": "2D array of values (rows of columns), e.g. [[1, 'hello'], [2, 'world']].",
                        "items": {"type": "array", "items": {}},
                    },
                },
                "required": ["spreadsheet_id", "range", "values"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gsheets_append",
            "description": "Append rows of data to a Google Sheets spreadsheet.",
            "parameters": {
                "type": "object",
                "properties": {
                    "spreadsheet_id": {"type": "string", "description": "Spreadsheet ID."},
                    "range": {
                        "type": "string",
                        "description": "A1 notation range indicating the table, e.g. 'Sheet1!A1'.",
                    },
                    "values": {
                        "type": "array",
                        "description": "2D array of rows to append, e.g. [['Alice', 30], ['Bob', 25]].",
                        "items": {"type": "array", "items": {}},
                    },
                },
                "required": ["spreadsheet_id", "range", "values"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Credential helper
# ---------------------------------------------------------------------------

def _get_google_creds(extension_store: "ExtensionStore"):
    """Build and return refreshed google.oauth2.credentials.Credentials."""
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
    except ImportError as exc:
        raise RuntimeError(
            "google-api-python-client not installed. "
            "Run: pip install google-api-python-client google-auth"
        ) from exc

    ext = extension_store.get_extension("google")
    if ext is None or ext.status != "connected":
        raise RuntimeError(
            "Google extension not connected. "
            "Go to Extensions → Google Workspace → Connect."
        )

    c = ext.credentials

    # gws auth method: get access token via `gws auth token` command
    if c.get("auth_method") == "gws":
        gws_bin = c.get("gws_bin", "")
        gws_cfg = c.get("gws_config_dir", "")
        if not gws_bin or not gws_cfg:
            raise RuntimeError(
                "gws binary or config dir not configured. Reconnect Google extension."
            )
        import subprocess, os
        env = {
            **os.environ,
            "GOOGLE_WORKSPACE_CLI_CONFIG_DIR": gws_cfg,
            "GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND": "file",
        }
        # Try `gws auth token` to get current access token
        r = subprocess.run(
            [gws_bin, "auth", "token"],
            capture_output=True, text=True, timeout=10, env=env,
        )
        token = r.stdout.strip().splitlines()[0] if r.stdout.strip() else ""
        if not token:
            raise RuntimeError(
                f"Could not get access token from gws (exit {r.returncode}).\n"
                f"Re-authorize: gws auth login -s drive,docs,sheets,calendar,gmail"
            )
        return Credentials(token=token)

    # Standard OAuth2 credentials (refresh_token stored in extension)
    creds = Credentials(
        token=c.get("token") or None,
        refresh_token=c.get("refresh_token") or None,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=c.get("client_id") or None,
        client_secret=c.get("client_secret") or None,
    )
    if creds.expired or not creds.token:
        creds.refresh(Request())
        ext.credentials["token"] = creds.token or ""
        extension_store.upsert_extension(ext)
    return creds


def _build(service: str, version: str, extension_store: "ExtensionStore"):
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError(
            "google-api-python-client not installed. "
            "Run: pip install google-api-python-client google-auth"
        ) from exc
    creds = _get_google_creds(extension_store)
    return build(service, version, credentials=creds)


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------

def execute_google_workspace_tool(
    name: str,
    args: dict,
    extension_store: "ExtensionStore",
) -> str:
    import json as _json

    try:
        if name == "gdrive_list_files":
            return _gdrive_list_files(args, extension_store)
        if name == "gdrive_get_file_info":
            return _gdrive_get_file_info(args, extension_store)
        if name == "gdrive_create_folder":
            return _gdrive_create_folder(args, extension_store)
        if name == "gdrive_delete_file":
            return _gdrive_delete_file(args, extension_store)
        if name == "gdocs_create":
            return _gdocs_create(args, extension_store)
        if name == "gdocs_get":
            return _gdocs_get(args, extension_store)
        if name == "gdocs_append":
            return _gdocs_append(args, extension_store)
        if name == "gsheets_create":
            return _gsheets_create(args, extension_store)
        if name == "gsheets_read":
            return _gsheets_read(args, extension_store)
        if name == "gsheets_write":
            return _gsheets_write(args, extension_store)
        if name == "gsheets_append":
            return _gsheets_append(args, extension_store)
        return _json.dumps({"error": f"Unknown tool: {name}"})
    except Exception as exc:
        return _json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# Drive
# ---------------------------------------------------------------------------

def _gdrive_list_files(args: dict, es: "ExtensionStore") -> str:
    import json as _json
    drive = _build("drive", "v3", es)
    limit = min(int(args.get("limit", 20)), 100)
    folder_id = args.get("folder_id", "")
    query = args.get("query", "")

    q_parts = ["trashed = false"]
    if folder_id:
        q_parts.append(f"'{folder_id}' in parents")
    if query:
        q_parts.append(query)

    result = drive.files().list(
        q=" and ".join(q_parts),
        pageSize=limit,
        fields="files(id,name,mimeType,modifiedTime,size,webViewLink)",
        orderBy="modifiedTime desc",
    ).execute()

    files = result.get("files", [])
    return _json.dumps({"files": files, "count": len(files)}, ensure_ascii=False)


def _gdrive_get_file_info(args: dict, es: "ExtensionStore") -> str:
    import json as _json
    drive = _build("drive", "v3", es)
    file_id = args["file_id"]
    meta = drive.files().get(
        fileId=file_id,
        fields="id,name,mimeType,modifiedTime,size,webViewLink,parents",
    ).execute()
    return _json.dumps(meta, ensure_ascii=False)


def _gdrive_create_folder(args: dict, es: "ExtensionStore") -> str:
    import json as _json
    drive = _build("drive", "v3", es)
    metadata = {
        "name": args["name"],
        "mimeType": "application/vnd.google-apps.folder",
    }
    parent_id = args.get("parent_id", "")
    if parent_id:
        metadata["parents"] = [parent_id]
    folder = drive.files().create(body=metadata, fields="id,name,webViewLink").execute()
    return _json.dumps(folder, ensure_ascii=False)


def _gdrive_delete_file(args: dict, es: "ExtensionStore") -> str:
    import json as _json
    drive = _build("drive", "v3", es)
    drive.files().delete(fileId=args["file_id"]).execute()
    return _json.dumps({"deleted": args["file_id"]})


# ---------------------------------------------------------------------------
# Docs
# ---------------------------------------------------------------------------

def _gdocs_create(args: dict, es: "ExtensionStore") -> str:
    import json as _json
    docs = _build("docs", "v1", es)
    drive = _build("drive", "v3", es)

    doc = docs.documents().create(body={"title": args["title"]}).execute()
    doc_id = doc["documentId"]

    content = args.get("content", "")
    if content:
        docs.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": [{"insertText": {"location": {"index": 1}, "text": content}}]},
        ).execute()

    folder_id = args.get("folder_id", "")
    if folder_id:
        # Move to folder: add new parent, remove old
        file_meta = drive.files().get(fileId=doc_id, fields="parents").execute()
        old_parents = ",".join(file_meta.get("parents", []))
        drive.files().update(
            fileId=doc_id,
            addParents=folder_id,
            removeParents=old_parents,
            fields="id,parents",
        ).execute()

    url = f"https://docs.google.com/document/d/{doc_id}/edit"
    return _json.dumps({"document_id": doc_id, "title": args["title"], "url": url}, ensure_ascii=False)


def _gdocs_get(args: dict, es: "ExtensionStore") -> str:
    import json as _json
    docs = _build("docs", "v1", es)
    doc = docs.documents().get(documentId=args["document_id"]).execute()
    title = doc.get("title", "")

    # Extract plain text from document body
    text_parts: list[str] = []
    for element in doc.get("body", {}).get("content", []):
        para = element.get("paragraph")
        if not para:
            continue
        for pe in para.get("elements", []):
            tr = pe.get("textRun")
            if tr:
                text_parts.append(tr.get("content", ""))

    plain_text = "".join(text_parts)
    return _json.dumps({
        "document_id": args["document_id"],
        "title": title,
        "text": plain_text,
        "char_count": len(plain_text),
    }, ensure_ascii=False)


def _gdocs_append(args: dict, es: "ExtensionStore") -> str:
    import json as _json
    docs = _build("docs", "v1", es)
    doc_id = args["document_id"]
    text = args["text"]

    # Get current end index
    doc = docs.documents().get(documentId=doc_id, fields="body").execute()
    content = doc.get("body", {}).get("content", [])
    end_index = content[-1].get("endIndex", 1) - 1 if content else 1

    docs.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": [{"insertText": {"location": {"index": end_index}, "text": text}}]},
    ).execute()

    return _json.dumps({"document_id": doc_id, "appended_chars": len(text)})


# ---------------------------------------------------------------------------
# Sheets
# ---------------------------------------------------------------------------

def _gsheets_create(args: dict, es: "ExtensionStore") -> str:
    import json as _json
    sheets = _build("sheets", "v4", es)
    drive = _build("drive", "v3", es)

    spreadsheet = sheets.spreadsheets().create(
        body={"properties": {"title": args["title"]}},
        fields="spreadsheetId,spreadsheetUrl",
    ).execute()
    sid = spreadsheet["spreadsheetId"]

    folder_id = args.get("folder_id", "")
    if folder_id:
        file_meta = drive.files().get(fileId=sid, fields="parents").execute()
        old_parents = ",".join(file_meta.get("parents", []))
        drive.files().update(
            fileId=sid, addParents=folder_id,
            removeParents=old_parents, fields="id,parents",
        ).execute()

    return _json.dumps({
        "spreadsheet_id": sid,
        "title": args["title"],
        "url": spreadsheet.get("spreadsheetUrl", f"https://docs.google.com/spreadsheets/d/{sid}/edit"),
    }, ensure_ascii=False)


def _gsheets_read(args: dict, es: "ExtensionStore") -> str:
    import json as _json
    sheets = _build("sheets", "v4", es)
    result = sheets.spreadsheets().values().get(
        spreadsheetId=args["spreadsheet_id"],
        range=args["range"],
    ).execute()
    values = result.get("values", [])
    return _json.dumps({
        "spreadsheet_id": args["spreadsheet_id"],
        "range": result.get("range", args["range"]),
        "rows": len(values),
        "values": values,
    }, ensure_ascii=False)


def _gsheets_write(args: dict, es: "ExtensionStore") -> str:
    import json as _json
    sheets = _build("sheets", "v4", es)
    result = sheets.spreadsheets().values().update(
        spreadsheetId=args["spreadsheet_id"],
        range=args["range"],
        valueInputOption="USER_ENTERED",
        body={"values": args["values"]},
    ).execute()
    return _json.dumps({
        "updated_range": result.get("updatedRange"),
        "updated_rows": result.get("updatedRows"),
        "updated_cells": result.get("updatedCells"),
    })


def _gsheets_append(args: dict, es: "ExtensionStore") -> str:
    import json as _json
    sheets = _build("sheets", "v4", es)
    result = sheets.spreadsheets().values().append(
        spreadsheetId=args["spreadsheet_id"],
        range=args["range"],
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": args["values"]},
    ).execute()
    updates = result.get("updates", {})
    return _json.dumps({
        "updated_range": updates.get("updatedRange"),
        "updated_rows": updates.get("updatedRows"),
        "updated_cells": updates.get("updatedCells"),
    })
