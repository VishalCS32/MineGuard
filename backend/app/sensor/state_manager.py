from .state import NodeState


class SensorStateManager:

    def __init__(self):
        self._states: dict[str, NodeState] = {}

    def get(self, node_id: str) -> NodeState:
        """
        Get the current state for a node.
        Creates a new state if this is the first reading.
        """

        if node_id not in self._states:
            self._states[node_id] = NodeState()

        return self._states[node_id]

    def update(
        self,
        node_id: str,
        state: NodeState,
    ) -> None:
        """
        Store the latest state for a node.
        """

        self._states[node_id] = state