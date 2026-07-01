from typing import cast

import adsk.core
import adsk.fusion
from geometry import GeometryUtils

class FrameMember:
    """Structural body elements caching wrapper parameters class."""
    body: adsk.fusion.BRepBody
    component: adsk.fusion.Component
    line: adsk.fusion.SketchLine
    selection_index: int
    start: adsk.core.Point3D
    end: adsk.core.Point3D
    orientation: str
    direction: adsk.core.Vector3D
    length: float

    def __init__(self, body: adsk.fusion.BRepBody, component: adsk.fusion.Component, 
                 line: adsk.fusion.SketchLine, selection_index: int):
        self.body = body
        self.component = component
        self.line = line
        self.selection_index = selection_index
        
        self.start = cast(adsk.core.Point3D, line.startSketchPoint.geometry)  # type: ignore[attr-defined]
        self.end   = cast(adsk.core.Point3D, line.endSketchPoint.geometry)    # type: ignore[attr-defined]
        self.orientation = GeometryUtils.classify_orientation(self.start, self.end)
        self.direction = GeometryUtils.get_vector(self.start, self.end)
        self.length = self.direction.length