from typing import List, Tuple
from joints import Joint
from member import FrameMember
import config


class PrioritySolver:
    @staticmethod
    def solve(joints: List[Joint], mode: str) -> List[Tuple[FrameMember, FrameMember]]:
        """Converts a list of joints into an ordered trim queue.

        Each entry is (tool_member, target_member): the tool member's body is used
        to cut material from the target member at their shared T-joint.

        Bug #4 fix: same-orientation pairs no longer silently drop out. When the
        chosen priority mode cannot determine a winner (both members have the same
        orientation), the solver falls back to selection-order as a tiebreaker.
        DIAGONAL members are treated as neither vertical nor horizontal, so they
        always fall through to the selection-order fallback.
        """
        trim_queue: List[Tuple[FrameMember, FrameMember]] = []

        for joint in joints:
            if joint.joint_type != 'T_JOINT':
                continue

            mA = joint.member_a
            mB = joint.member_b
            tool, target = None, None

            if mode == config.PRIORITY_VERTICAL:
                if mA.orientation == "VERTICAL" and mB.orientation != "VERTICAL":
                    tool, target = mA, mB
                elif mB.orientation == "VERTICAL" and mA.orientation != "VERTICAL":
                    tool, target = mB, mA
                # Same orientation or both DIAGONAL → fall back to selection order

            elif mode == config.PRIORITY_HORIZONTAL:
                if mA.orientation == "HORIZONTAL" and mB.orientation != "HORIZONTAL":
                    tool, target = mA, mB
                elif mB.orientation == "HORIZONTAL" and mA.orientation != "HORIZONTAL":
                    tool, target = mB, mA
                # Same orientation or both DIAGONAL → fall back to selection order

            elif mode == config.PRIORITY_SELECTION:
                # Always resolved by selection order
                if mA.selection_index < mB.selection_index:
                    tool, target = mA, mB
                else:
                    tool, target = mB, mA

            # Bug #4 fix: if mode-based rule couldn't decide, use selection order as tiebreaker
            if tool is None or target is None:
                if mA.selection_index < mB.selection_index:
                    tool, target = mA, mB
                else:
                    tool, target = mB, mA

            trim_queue.append((tool, target))

        return trim_queue