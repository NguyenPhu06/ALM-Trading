import pytest
from paper import InvalidPositionTransition,PositionState,PositionStateMachine
def test_closed_position_cannot_dca():
    with pytest.raises(InvalidPositionTransition):PositionStateMachine().transition(PositionState.CLOSED,PositionState.DCA_ALLOWED)
