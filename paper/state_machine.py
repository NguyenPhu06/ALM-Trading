from paper.models import PositionState
class InvalidPositionTransition(ValueError):pass
class PositionStateMachine:
    ALLOWED={PositionState.WATCHING:{PositionState.ENTRY_READY,PositionState.INVALIDATED},PositionState.ENTRY_READY:{PositionState.OPEN,PositionState.INVALIDATED},PositionState.OPEN:{PositionState.DCA_ALLOWED,PositionState.DCA_BLOCKED,PositionState.REDUCE,PositionState.EXIT_PENDING,PositionState.INVALIDATED},PositionState.DCA_ALLOWED:{PositionState.OPEN,PositionState.DCA_BLOCKED,PositionState.EXIT_PENDING},PositionState.DCA_BLOCKED:{PositionState.OPEN,PositionState.REDUCE,PositionState.EXIT_PENDING},PositionState.REDUCE:{PositionState.OPEN,PositionState.EXIT_PENDING},PositionState.EXIT_PENDING:{PositionState.CLOSED},PositionState.INVALIDATED:{PositionState.EXIT_PENDING,PositionState.CLOSED},PositionState.CLOSED:set()}
    def transition(self,current,target):
        if target not in self.ALLOWED[current]:raise InvalidPositionTransition(f"invalid paper position transition: {current}->{target}")
        return target
