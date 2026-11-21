"""
Notification de-duplication / cooldown state.

Without this the app would re-send the same alert on every poll. State is keyed
by symbol+rule and records the last status sent and when. A signal is worth
sending when:
  - it has never been sent, or
  - its status escalated (approaching -> met), or
  - the cooldown window has elapsed since it was last sent.

State is persisted to a small JSON file so cooldowns survive restarts.
"""

from __future__ import annotations

import json
import os
import time
from typing import Optional

import rules as R

# A "met" alert is more important than "approaching", so escalation always sends.
_STATUS_RANK = {R.APPROACHING: 1, R.MET: 2}


class AlertState:
    def __init__(self, path: str, cooldown_minutes: float = 60.0):
        self.path = path
        self.cooldown = cooldown_minutes * 60.0
        self._data: dict = {}
        self._load()

    def _load(self) -> None:
        if self.path and os.path.exists(self.path):
            try:
                with open(self.path) as fh:
                    self._data = json.load(fh)
            except (OSError, json.JSONDecodeError):
                self._data = {}

    def save(self) -> None:
        if not self.path:
            return
        tmp = f"{self.path}.tmp"
        try:
            with open(tmp, "w") as fh:
                json.dump(self._data, fh, indent=2)
            os.replace(tmp, self.path)
        except OSError as exc:
            print(f"[warn] could not persist state: {exc}")

    def should_send(self, sig, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else now
        prev = self._data.get(sig.key())
        if prev is None:
            return True
        # Escalation to a higher-severity status always notifies.
        if _STATUS_RANK.get(sig.status, 0) > _STATUS_RANK.get(prev.get("status"), 0):
            return True
        # Same or lower status: respect the cooldown window.
        if sig.status != prev.get("status"):
            return True
        return (now - float(prev.get("ts", 0))) >= self.cooldown

    def record(self, sig, now: Optional[float] = None) -> None:
        now = time.time() if now is None else now
        self._data[sig.key()] = {"status": sig.status, "ts": now, "value": sig.value}
