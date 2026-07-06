"""Common strategy contracts."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class SignalAction(enum.Enum):
    ENTER_LONG = "ENTER_LONG"   # buy a call on the underlying
    EXIT = "EXIT"               # square off the open option position
    HOLD = "HOLD"


@dataclass
class Signal:
    symbol: str
    action: SignalAction
    strategy: str
    reason: str
    context: dict = field(default_factory=dict)
