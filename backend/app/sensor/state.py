from dataclasses import dataclass
from datetime import datetime


@dataclass
class NodeState:
    roll: float = 0.0
    pitch: float = 0.0
    timestamp: datetime | None = None