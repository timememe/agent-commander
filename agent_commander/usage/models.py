"""Usage data models for agent rate limit monitoring."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class RateWindow:
    """A single rate-limit window (e.g. 5h or Weekly).

    If ``label`` is set, ``format_status()`` returns it directly – use this
    when quota % is not available but we still have useful info (e.g. plan
    type, model name).
    """

    name: str               # "5h" | "Weekly" | "Plan" | …
    used_percent: float = 0.0   # 0.0–100.0  (ignored when label is set)
    reset_info: str | None = None
    label: str | None = None    # Override display string, e.g. "Pro · Sonnet 4.6"

    @property
    def remaining_percent(self) -> float:
        return max(0.0, 100.0 - self.used_percent)

    @property
    def has_quota(self) -> bool:
        """True when this window carries real percentage data."""
        return self.label is None

    def format_status(self) -> str:
        """Return the human-readable status string."""
        if self.label is not None:
            return self.label
        rem = self.remaining_percent
        # Show one decimal place only when there is a fractional part (e.g. 99.9%)
        pct = f"{rem:.1f}".rstrip("0").rstrip(".")
        base = f"{pct}% left"
        if self.reset_info:
            return f"{base} · {self.reset_info}"
        return base


@dataclass
class AgentUsageSnapshot:
    """Rate-limit snapshot for one agent."""

    agent: str
    windows: list[RateWindow] = field(default_factory=list)
    updated_at: float = field(default_factory=time.time)
    error: str | None = None

    @property
    def primary(self) -> RateWindow | None:
        """Return the most-constrained window (lowest remaining %)."""
        quota_windows = [w for w in self.windows if w.has_quota]
        if not quota_windows:
            return self.windows[0] if self.windows else None
        return min(quota_windows, key=lambda w: w.remaining_percent)

    @property
    def is_depleted(self) -> bool:
        """True if the primary window is near-empty (< 2% remaining)."""
        p = self.primary
        return p is not None and p.remaining_percent < 2.0
