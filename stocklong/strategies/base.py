"""Common strategy contracts."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

LONG = 1    # bullish setup -> buy an ITM call (CE)
SHORT = -1  # bearish setup -> buy an ITM put (PE); still options *buying*


class SignalAction(enum.Enum):
    ENTER_LONG = "ENTER_LONG"    # buy a call on the underlying
    ENTER_SHORT = "ENTER_SHORT"  # buy a put on the underlying
    EXIT = "EXIT"                # square off the open option position
    HOLD = "HOLD"


def entry_action(direction: int) -> SignalAction:
    return SignalAction.ENTER_LONG if direction == LONG else SignalAction.ENTER_SHORT


@dataclass
class Signal:
    symbol: str
    action: SignalAction
    strategy: str
    reason: str
    direction: int = LONG
    context: dict = field(default_factory=dict)
