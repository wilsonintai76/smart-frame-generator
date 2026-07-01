from typing import List
from member import FrameMember
from geometry import GeometryUtils

class Joint:
    def __init__(self, member_a: FrameMember, member_b: FrameMember, joint_type: str):
        self.member_a = member_a
        self.member_b = member_b
        self.joint_type = joint_type 

class JointDetector:
    @staticmethod
    def find_joints(members: List[FrameMember]) -> List[Joint]:
        joints: List[Joint] = []
        num_members = len(members)
        
        for i in range(num_members):
            for j in range(i + 1, num_members):
                mA = members[i]
                mB = members[j]
                
                shared = GeometryUtils.get_shared_endpoint(mA.start, mA.end, mB.start, mB.end)
                if shared:
                    joints.append(Joint(mA, mB, 'CORNER'))
                    continue
                
                t_found = (GeometryUtils.point_on_segment(mA.start, mB.start, mB.end) or 
                           GeometryUtils.point_on_segment(mA.end, mB.start, mB.end) or
                           GeometryUtils.point_on_segment(mB.start, mA.start, mA.end) or 
                           GeometryUtils.point_on_segment(mB.end, mA.start, mA.end))
                if t_found:
                    joints.append(Joint(mA, mB, 'T_JOINT'))
                    
        return joints