import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from orchestrator_store import EventRecord

SIGNAL_USER_MESSAGE = "user_message"
SIGNAL_ASSISTANT_MESSAGE = "assistant_message"
SIGNAL_CHOICE_REQUEST = "choice_request"
SIGNAL_CHOICE_SELECTED = "choice_selected"
SIGNAL_SYSTEM_EVENT = "system_event"
SIGNAL_IGNORED = "ignored"

_OPTION_RE = re.compile(r"(?:^|\s)(\d{1,2})\s*[\)\.\:\-]\s+(.+)$")


@dataclass(frozen=True)
class NormalizedSignal:
    id: int
    pane_id: str
    task_id: int
    created_at: str
    agent: str
    event_type: str
    kind: str
    text: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    source_event_id: int = 0
    question: str = ""
    options: list[dict[str, Any]] = field(default_factory=list)
    choice_number: int = 0
    choice_title: str = ""


def parse_payload_json(payload_json: str) -> dict[str, Any]:
    try:
        data = json.loads(payload_json)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def extract_choice_payload(text: str) -> Optional[dict[str, Any]]:
    option_rows: list[dict[str, Any]] = []
    option_start_index: Optional[int] = None
    seen_numbers: set[int] = set()
    lines = text.splitlines()
    for idx, raw_line in enumerate(lines):
        line = raw_line.rstrip()
        if not line.strip():
            continue
        match = _OPTION_RE.search(line)
        if not match:
            continue
        number = int(match.group(1))
        title = match.group(2).strip()
        if not title or number in seen_numbers:
            continue
        if option_start_index is None:
            option_start_index = idx
        seen_numbers.add(number)
        option_rows.append({"number": number, "title": title})
    if not option_rows:
        return None
    option_rows.sort(key=lambda item: int(item["number"]))
    question_lines = lines[:option_start_index] if option_start_index is not None else []
    question = "\n".join(line.rstrip() for line in question_lines).strip()
    if not question:
        question = "Choose one option."
    return {"question": question, "options": option_rows}


def normalize_choice_payload(payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    source_event_id = int(payload.get("source_event_id", 0) or 0)
    if source_event_id <= 0:
        return None
    options = payload.get("options")
    if not isinstance(options, list) or not options:
        return None
    normalized_options: list[dict[str, Any]] = []
    seen_numbers: set[int] = set()
    for raw in options:
        if not isinstance(raw, dict):
            continue
        try:
            number = int(raw.get("number", 0) or 0)
        except Exception:
            number = 0
        title = str(raw.get("title", "")).strip()
        if number <= 0 or not title or number in seen_numbers:
            continue
        seen_numbers.add(number)
        normalized_options.append({"number": number, "title": title})
    if not normalized_options:
        return None
    normalized_options.sort(key=lambda item: int(item["number"]))
    question = str(payload.get("question", "")).strip() or "Choose one option."
    return {
        "source_event_id": source_event_id,
        "question": question,
        "options": normalized_options,
    }


class DefaultSignalAdapter:
    """Normalize low-level stored events into a chat-safe signal contract."""

    def normalize(self, event: EventRecord) -> NormalizedSignal:
        payload = parse_payload_json(event.payload_json)
        event_type = event.event_type

        if event_type == "terminal_input_submitted":
            text = str(payload.get("text", "")).strip()
            return NormalizedSignal(
                id=event.id,
                pane_id=event.pane_id,
                task_id=event.task_id,
                created_at=event.created_at,
                agent=event.agent,
                event_type=event_type,
                kind=SIGNAL_USER_MESSAGE if text else SIGNAL_IGNORED,
                text=text,
                payload=payload,
            )

        if event_type == "terminal_output":
            text = str(payload.get("text", ""))
            return NormalizedSignal(
                id=event.id,
                pane_id=event.pane_id,
                task_id=event.task_id,
                created_at=event.created_at,
                agent=event.agent,
                event_type=event_type,
                kind=SIGNAL_ASSISTANT_MESSAGE if text.strip() else SIGNAL_IGNORED,
                text=text,
                payload=payload,
            )

        if event_type == "assistant_choice_request_detected":
            normalized = normalize_choice_payload(payload)
            if not normalized:
                return NormalizedSignal(
                    id=event.id,
                    pane_id=event.pane_id,
                    task_id=event.task_id,
                    created_at=event.created_at,
                    agent=event.agent,
                    event_type=event_type,
                    kind=SIGNAL_IGNORED,
                    payload=payload,
                )
            return NormalizedSignal(
                id=event.id,
                pane_id=event.pane_id,
                task_id=event.task_id,
                created_at=event.created_at,
                agent=event.agent,
                event_type=event_type,
                kind=SIGNAL_CHOICE_REQUEST,
                payload=payload,
                source_event_id=int(normalized["source_event_id"]),
                question=str(normalized["question"]),
                options=list(normalized["options"]),
            )

        if event_type == "assistant_choice_selected":
            source_event_id = int(payload.get("source_event_id", 0) or 0)
            number = int(payload.get("choice_number", 0) or 0)
            title = str(payload.get("choice_title", "")).strip()
            return NormalizedSignal(
                id=event.id,
                pane_id=event.pane_id,
                task_id=event.task_id,
                created_at=event.created_at,
                agent=event.agent,
                event_type=event_type,
                kind=SIGNAL_CHOICE_SELECTED,
                payload=payload,
                source_event_id=source_event_id,
                choice_number=number,
                choice_title=title,
            )

        return NormalizedSignal(
            id=event.id,
            pane_id=event.pane_id,
            task_id=event.task_id,
            created_at=event.created_at,
            agent=event.agent,
            event_type=event_type,
            kind=SIGNAL_SYSTEM_EVENT,
            payload=payload,
        )
