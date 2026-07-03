"""entry.py — Apply Joint command for SmartFrameGenerator.

Workflow (face-selection mode)
──────────────────────────────
  1. Click a PLANAR Frame Member A **.
  2. Click a PLANAR Frame Member B **.
  3. Choose joint operation.
  4. Click OK.

Why faces instead of bodies?
  Selecting the specific face at the joint (like Fusion’s Finger Joint
  generator) removes all ambiguity about WHERE the cut should go:
    • The face’s plane gives the exact junction location.
    • The face’s outward normal tells the miter-plane direction.
    • End-face vs side-face selection drives Auto-Trim joint detection:
        – Both END faces (normal ∥ member axis) → corner → Miter.
        – One SIDE face (normal ⊥ member axis) → T-joint; that member is
          continuous and cuts the other.

Face selection tips
  • For hollow tubes (SHS/RHS): click any flat end face.
  • For round tubes (CHS): click the flat circular end cap.
  • For I-beam / C-channel: click the flat end face of the web/flange.
  • For T-joints: on the continuous (through) member, click the flat
    *side face* that the other member’s end touches.

Component scoping:
  All cut operations run inside body.parentComponent to prevent
  cross-component plane reference errors.
"""

import os
import sys
import traceback
from typing import List, Optional, Tuple

import adsk.core
import adsk.fusion

current_dir  = os.path.dirname(os.path.abspath(__file__))
commands_dir = os.path.dirname(current_dir)
root_dir     = os.path.dirname(commands_dir)

if root_dir not in sys.path:
    sys.path.append(root_dir)

import config
from utils import get_active_design

app = adsk.core.Application.get()
ui  = app.userInterface
handlers: List[adsk.core.EventHandler] = []

CMD_ID      = 'SmartFrameJointBtn'
CMD_NAME    = 'Apply Joint'
CMD_DESC    = 'Apply Miter, Butt, or Auto-Detect joints to frame members.'
ICON_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources')
_TAB_ID        = 'SmartFrameGeneratorTab'
_TAB_NAME      = 'Frame Generator'
_PANEL_ID      = 'SmartFrameGeneratorPanel'

# ── Joint operation constants ────────────────────────────────────────────────
_OP_AUTO    = 'Auto Detect (from face type)'
_OP_MITER   = 'Miter Cut (welded corner)'
_OP_BUTT_AB = 'Butt Joint (A through, B cut flush)'
_OP_BUTT_BA = 'Butt Joint (B through, A cut flush)'

# Backward-compatible aliases
_OP_TTRIM   = _OP_BUTT_AB
_OP_TTRIM_R = _OP_BUTT_BA

_PROF_SYS_STEEL = 'Steel / Structural'
_PROF_SYS_ALUM  = 'Aluminium T-slot Extrusion'

# Info text shown in the dialog for each profile system
_INFO_STEEL = (
    '<b>Select two frame members.</b> Click any face on each member.<br><br>'
    '<b>Auto Detect</b>: reads face type (end/side) and picks the right joint.<br>'
    '<b>Miter Cut</b>: both members cut at the angle bisector \u2014 for <i>welded</i> corners.<br>'
    '<b>Butt Joint A\u2192B</b>: A stays full length, B cut square flush against A.<br>'
    '&nbsp;&nbsp;&nbsp;&nbsp;Use for <i>bolted / riveted / screwed</i> connections.<br>'
    '<b>Butt Joint B\u2192A</b>: B stays full length, A cut square flush against B.<br><br>'
    'For C-channel / L-angle corners: Butt Joint gives the cleanest result.<br>'
    'For T-joints: select END face of terminating member + SIDE face of through member.'
)

_INFO_ALUM = (
    '<b>Aluminium T-slot profiles \u2014 square cut + bracket hardware.</b><br><br>'
    'T-slot extrusions use a <b>clean square cut</b> (perpendicular to the axis) '
    'on the terminating member.  The continuous member is untouched.<br><br>'
    'Physical connection uses bracket hardware that slides into the T-slots:<br>'
    '&bull; <b>Angle bracket</b> \u2014 L-bracket inside the T-slots of both members.<br>'
    '&bull; <b>Inside corner connector</b> \u2014 slides into slots from both sides.<br>'
    '&bull; <b>Gusset / joining plate</b> \u2014 for heavier loads.<br><br>'
    '<b>Auto Detect</b>: reads face type to pick the continuous member.<br>'
    '<b>Butt Joint A\u2192B</b>: A continuous, B gets a square cut at the junction.<br>'
    '<b>Butt Joint B\u2192A</b>: B continuous, A gets a square cut at the junction.<br><br>'
    '<b>\u26a0 Miter is not available for aluminium</b> \u2014 it would destroy the T-slots.'
)


def _log(message: str) -> None:
    palette = ui.palettes.itemById('TextCommands')
    if palette:
        palette.writeText(f"[ApplyJoint] {message}")  # type: ignore[attr-defined]


# ── Input-changed handler (profile system switches info text + guards Miter) ──────

class JointInputChangedHandler(adsk.core.InputChangedEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, eventArgs: adsk.core.InputChangedEventArgs) -> None:
        try:
            changed = eventArgs.input
            if changed.id != 'profile_system':
                return
            inputs   = eventArgs.inputs
            sys_drop = adsk.core.DropDownCommandInput.cast(  # type: ignore[misc]
                inputs.itemById('profile_system')
            )
            is_alum = (sys_drop.selectedItem.name == _PROF_SYS_ALUM  # type: ignore[union-attr]
                       if sys_drop else False)

            # ── Swap info text ───────────────────────────────────────────
            info = inputs.itemById('info')
            if info:
                try:
                    info.formattedText = _INFO_ALUM if is_alum else _INFO_STEEL  # type: ignore[attr-defined]
                except Exception:
                    pass

            # ── Swap operation dropdown items ────────────────────────────
            op_drop = adsk.core.DropDownCommandInput.cast(  # type: ignore[misc]
                inputs.itemById('operation')
            )
            if op_drop:
                # Remember current selection to restore if possible
                current_sel = op_drop.selectedItem.name if op_drop.selectedItem else ''
                op_drop.listItems.clear()
                if is_alum:
                    # Aluminium: square cut only, no miter
                    op_drop.listItems.add(_OP_AUTO,       current_sel == _OP_AUTO)
                    op_drop.listItems.add(_OP_BUTT_AB,    current_sel not in (_OP_AUTO, _OP_BUTT_BA))
                    op_drop.listItems.add(_OP_BUTT_BA,    current_sel == _OP_BUTT_BA)
                else:
                    # Steel: all four operations
                    op_drop.listItems.add(_OP_AUTO,       current_sel == _OP_AUTO)
                    op_drop.listItems.add(_OP_MITER,      current_sel == _OP_MITER)
                    op_drop.listItems.add(_OP_BUTT_AB,    current_sel == _OP_BUTT_AB)
                    op_drop.listItems.add(_OP_BUTT_BA,    current_sel == _OP_BUTT_BA)

        except Exception:
            pass


# ── Face-geometry helpers ───────────────────────────────────────────────────────────────

def _face_plane_normal(face: adsk.fusion.BRepFace
                       ) -> Optional[adsk.core.Vector3D]:
    """Return the outward normal of a planar face, or None if not planar."""
    try:
        plane = adsk.core.Plane.cast(face.geometry)  # type: ignore[misc]
        if plane:
            return plane.normal
    except Exception:
        pass
    return None


def _face_centroid(face: adsk.fusion.BRepFace) -> adsk.core.Point3D:
    """Bounding-box centroid of a face."""
    bb = face.boundingBox
    return adsk.core.Point3D.create(
        (bb.minPoint.x + bb.maxPoint.x) / 2.0,
        (bb.minPoint.y + bb.maxPoint.y) / 2.0,
        (bb.minPoint.z + bb.maxPoint.z) / 2.0,
    )


def _is_end_face(face: adsk.fusion.BRepFace,
                body: adsk.fusion.BRepBody) -> bool:
    """True when the face's outward normal is roughly parallel to the body's
    long axis (i.e. it is an *end* face, not a *side* face)."""
    normal = _face_plane_normal(face)
    if not normal:
        return True   # assume end face if we can’t read the normal
    axis = _get_body_long_axis(body)
    return abs(normal.dotProduct(axis)) > 0.65


# ── Body extraction helper ──────────────────────────────────────────────────

def _extract_body(entity) -> Optional[adsk.fusion.BRepBody]:
    """Extract a BRepBody from body, occurrence, or face selection."""
    body = adsk.fusion.BRepBody.cast(entity)  # type: ignore[misc]
    if body and body.isValid:
        return body
    occ = adsk.fusion.Occurrence.cast(entity)  # type: ignore[misc]
    if occ and occ.isValid:
        comp = occ.component
        if comp.bRepBodies.count > 0:
            return comp.bRepBodies.item(0)
    face = adsk.fusion.BRepFace.cast(entity)  # type: ignore[misc]
    if face and face.isValid:
        return face.body
    return None


# ── Geometry helpers ──────────────────────────────────────────────────────────

def _normalize(v: adsk.core.Vector3D) -> adsk.core.Vector3D:
    length = v.length
    if length < 1e-7:
        return v
    return adsk.core.Vector3D.create(v.x / length, v.y / length, v.z / length)


def _get_body_long_axis(body: adsk.fusion.BRepBody) -> adsk.core.Vector3D:
    """Unit vector along the body's longest bounding-box dimension.

    Works for horizontal, vertical, and diagonal frame members because
    the member length always greatly exceeds the cross-section width.
    """
    bb = body.boundingBox
    dx = abs(bb.maxPoint.x - bb.minPoint.x)
    dy = abs(bb.maxPoint.y - bb.minPoint.y)
    dz = abs(bb.maxPoint.z - bb.minPoint.z)

    if dx >= dy and dx >= dz:
        return adsk.core.Vector3D.create(1.0, 0.0, 0.0)
    elif dy >= dx and dy >= dz:
        return adsk.core.Vector3D.create(0.0, 1.0, 0.0)
    else:
        return adsk.core.Vector3D.create(0.0, 0.0, 1.0)


def _get_body_endpoints(body: adsk.fusion.BRepBody
                        ) -> Tuple[adsk.core.Point3D, adsk.core.Point3D]:
    """Returns the two endpoint centres along the body's long axis."""
    bb = body.boundingBox
    cx = (bb.minPoint.x + bb.maxPoint.x) / 2.0
    cy = (bb.minPoint.y + bb.maxPoint.y) / 2.0
    cz = (bb.minPoint.z + bb.maxPoint.z) / 2.0
    dx = abs(bb.maxPoint.x - bb.minPoint.x)
    dy = abs(bb.maxPoint.y - bb.minPoint.y)
    dz = abs(bb.maxPoint.z - bb.minPoint.z)

    if dx >= dy and dx >= dz:
        return (adsk.core.Point3D.create(bb.minPoint.x, cy, cz),
                adsk.core.Point3D.create(bb.maxPoint.x, cy, cz))
    elif dy >= dx and dy >= dz:
        return (adsk.core.Point3D.create(cx, bb.minPoint.y, cz),
                adsk.core.Point3D.create(cx, bb.maxPoint.y, cz))
    else:
        return (adsk.core.Point3D.create(cx, cy, bb.minPoint.z),
                adsk.core.Point3D.create(cx, cy, bb.maxPoint.z))


def _get_member_direction(body: adsk.fusion.BRepBody,
                          junction: adsk.core.Point3D) -> adsk.core.Vector3D:
    """Unit vector pointing FROM junction TOWARD the far end of this member.

    Strategy (in order of preference):
    1. Find the planar end face whose centroid is closest to junction.
       Use its face normal — this is the exact sweep direction Fusion used.
       Flip the normal if needed so it points AWAY from junction.
    2. Fallback: compute from bounding-box endpoint positions.

    Using the face normal is more accurate than bounding-box math, especially
    for diagonal members where the bounding-box axis snap introduces error.
    """
    best_face = None
    best_dist = float('inf')

    for face in body.faces:
        geom = face.geometry
        # Only planar faces — skip cylinders, cones, splines (side walls)
        if not isinstance(geom, adsk.core.Plane):
            continue
        try:
            centroid = face.centroid
        except Exception:
            continue
        dist = centroid.distanceTo(junction)
        if dist < best_dist:
            best_dist = dist
            best_face = face

    if best_face is not None:
        normal: adsk.core.Vector3D = best_face.geometry.normal

        # The face normal is arbitrary in sign. We want it pointing AWAY from
        # the junction (toward the body's bulk / far end). Use the body's
        # bounding-box centre as a proxy for "into the body".
        bb = body.boundingBox
        body_centre = adsk.core.Point3D.create(
            (bb.minPoint.x + bb.maxPoint.x) / 2.0,
            (bb.minPoint.y + bb.maxPoint.y) / 2.0,
            (bb.minPoint.z + bb.maxPoint.z) / 2.0,
        )
        to_centre = adsk.core.Vector3D.create(
            body_centre.x - junction.x,
            body_centre.y - junction.y,
            body_centre.z - junction.z,
        )
        # If normal points TOWARD junction (opposite to body centre), flip it
        if normal.dotProduct(to_centre) < 0:
            normal = adsk.core.Vector3D.create(-normal.x, -normal.y, -normal.z)
        return _normalize(normal)

    # ── Fallback: bounding-box endpoint ───────────────────────────────────────
    eps = _get_body_endpoints(body)
    far = eps[0] if eps[0].distanceTo(junction) >= eps[1].distanceTo(junction) else eps[1]
    return _normalize(adsk.core.Vector3D.create(
        far.x - junction.x,
        far.y - junction.y,
        far.z - junction.z,
    ))


def _auto_extend_to_junction(body: adsk.fusion.BRepBody,
                              junction: adsk.core.Point3D,
                              tolerance: float = 0.05) -> None:
    """Extend body's near end face to the junction if a gap exists.

    Works by:
    1. Finding the planar face closest to junction (the near end cap).
    2. Computing the signed gap: positive = body is SHORT; negative = past junction (overextended).
    3. If gap > tolerance: extrude the end face toward junction to close the gap
       plus a small margin so the miter cut has material to trim.
    4. If overextended: do nothing — the subsequent miter/trim cut removes the excess.
    """
    # Find the planar end face closest to junction
    best_face: Optional[adsk.fusion.BRepFace] = None
    best_dist = float('inf')
    for face in body.faces:
        if not isinstance(face.geometry, adsk.core.Plane):
            continue
        try:
            centroid = face.centroid
        except Exception:
            continue
        dist = centroid.distanceTo(junction)
        if dist < best_dist:
            best_dist = dist
            best_face = face

    if best_face is None:
        return

    try:
        centroid = best_face.centroid
    except Exception:
        return

    # dir_away: unit vector FROM junction TOWARD the body's far end
    dir_away = _get_member_direction(body, junction)

    # Signed gap: project (junction - centroid) onto dir_away.
    #   > 0  → centroid is on the far-end side → body is SHORT (gap exists)
    #   ≤ 0  → centroid is at/past junction → overextended (nothing to do)
    to_junction = adsk.core.Vector3D.create(
        junction.x - centroid.x,
        junction.y - centroid.y,
        junction.z - centroid.z,
    )
    gap = to_junction.dotProduct(dir_away)

    if gap <= tolerance:
        _log(f"  Auto-extend: already at/past junction (gap={gap:.3f} cm), skipping.")
        return

    # Extend slightly past junction so the miter cut has material to remove
    extend_dist = gap + 0.5   # 0.5 cm margin
    _log(f"  Auto-extending {extend_dist:.2f} cm (gap={gap:.2f} cm)...")

    comp: adsk.fusion.Component = body.parentComponent  # type: ignore[assignment]
    extrudes  = comp.features.extrudeFeatures
    ext_input = extrudes.createInput(
        best_face,                                                # BRepFace as profile
        adsk.fusion.FeatureOperations.JoinFeatureOperation,       # type: ignore[arg-type]
    )
    # Positive direction = along face outward normal = toward junction (fills gap)
    ext_input.setOneSideExtent(
        adsk.fusion.DistanceExtentDefinition.create(             # type: ignore[arg-type]
            adsk.core.ValueInput.createByReal(extend_dist)
        ),
        adsk.fusion.ExtentDirections.PositiveExtentDirection,    # type: ignore[attr-defined]
    )
    extrudes.add(ext_input)
    _log("  Auto-extend complete.")


def _find_junction_point(body_a: adsk.fusion.BRepBody,
                         body_b: adsk.fusion.BRepBody) -> adsk.core.Point3D:
    """Intersection of the two member centrelines (closest-approach point).

    Uses line-line intersection so the result is the original skeleton corner
    even when members are extended past it for miter overlap.
    Falls back to closest-endpoint midpoint for parallel members.
    """
    bb_a = body_a.boundingBox
    bb_b = body_b.boundingBox
    ca = adsk.core.Point3D.create(
        (bb_a.minPoint.x + bb_a.maxPoint.x) / 2.0,
        (bb_a.minPoint.y + bb_a.maxPoint.y) / 2.0,
        (bb_a.minPoint.z + bb_a.maxPoint.z) / 2.0,
    )
    cb = adsk.core.Point3D.create(
        (bb_b.minPoint.x + bb_b.maxPoint.x) / 2.0,
        (bb_b.minPoint.y + bb_b.maxPoint.y) / 2.0,
        (bb_b.minPoint.z + bb_b.maxPoint.z) / 2.0,
    )
    da = _get_body_long_axis(body_a)
    db = _get_body_long_axis(body_b)

    wx = ca.x - cb.x
    wy = ca.y - cb.y
    wz = ca.z - cb.z
    b     = da.x*db.x + da.y*db.y + da.z*db.z  # da · db
    d_    = da.x*wx   + da.y*wy   + da.z*wz    # da · (ca-cb)
    e     = db.x*wx   + db.y*wy   + db.z*wz    # db · (ca-cb)
    denom = 1.0 - b * b                         # sin²(angle between axes)

    if abs(denom) < 1e-6:
        # Parallel members — fall back to midpoint of closest endpoints
        pts_a = _get_body_endpoints(body_a)
        pts_b = _get_body_endpoints(body_b)
        best_dist = float('inf')
        best_mid: Optional[adsk.core.Point3D] = None
        for pa in pts_a:
            for pb in pts_b:
                dist = pa.distanceTo(pb)
                if dist < best_dist:
                    best_dist = dist
                    best_mid  = adsk.core.Point3D.create(
                        (pa.x + pb.x) / 2.0,
                        (pa.y + pb.y) / 2.0,
                        (pa.z + pb.z) / 2.0,
                    )
        return best_mid  # type: ignore[return-value]

    t = (b * e - d_) / denom          # parameter along da for closest point
    return adsk.core.Point3D.create(
        ca.x + t * da.x,
        ca.y + t * da.y,
        ca.z + t * da.z,
    )


def _get_root_comp(body: adsk.fusion.BRepBody) -> adsk.fusion.Component:
    """Return the root component of the design that owns this body."""
    comp = body.parentComponent
    design = comp.parentDesign
    return design.rootComponent  # type: ignore[return-value]


def _make_miter_plane_in_comp(
        comp:         adsk.fusion.Component,
        junction:     adsk.core.Point3D,
        miter_normal: adsk.core.Vector3D,
) -> adsk.fusion.ConstructionPlane:
    """Construction plane at junction with the given normal, inside comp.

    Uses setByPlane(adsk.core.Plane) — direct math-plane API, no sketch
    geometry dependency.  Must be called on the body's own sub-component
    because Fusion 360 does NOT allow adding construction planes to the root
    component from a command-plugin context ('Environment is not supported').

    The frame generator uses NewComponentFeatureOperation so each sub-component
    occurrence has an identity transform: local coords == root coords.
    No coordinate transform is therefore needed.
    """
    plane_geom  = adsk.core.Plane.create(junction, miter_normal)  # type: ignore[attr-defined]
    plane_input = comp.constructionPlanes.createInput()
    plane_input.setByPlane(plane_geom)  # type: ignore[attr-defined]
    return comp.constructionPlanes.add(plane_input)


def _cut_body_at_plane(
        body:         adsk.fusion.BRepBody,
        junction:     adsk.core.Point3D,
        miter_normal: adsk.core.Vector3D,
        far_end:      adsk.core.Point3D,
) -> None:
    """Extrude-cut one body at the miter plane, removing the wedge tip.

    Everything (plane, sketch, extrude) lives inside body.parentComponent.
    participantBodies is set to [body] so only this member is cut.

    Cut direction:
      dot(far_end - junction, miter_normal) > 0  →  body in + half  →  cut NEGATIVE
      dot(far_end - junction, miter_normal) < 0  →  body in − half  →  cut POSITIVE
    """
    comp: adsk.fusion.Component = body.parentComponent  # type: ignore[assignment]

    cut_plane = _make_miter_plane_in_comp(comp, junction, miter_normal)

    sketch: adsk.fusion.Sketch = comp.sketches.add(cut_plane)
    half = 50.0  # cm — large enough for any realistic cross-section
    sketch.sketchCurves.sketchLines.addTwoPointRectangle(
        adsk.core.Point3D.create(-half, -half, 0),
        adsk.core.Point3D.create( half,  half, 0),
    )
    cut_profile = sketch.profiles.item(sketch.profiles.count - 1)

    # Which side of the plane is the body's bulk on?
    to_far = adsk.core.Vector3D.create(
        far_end.x - junction.x,
        far_end.y - junction.y,
        far_end.z - junction.z,
    )
    dot = to_far.dotProduct(miter_normal)
    if dot > 0:
        cut_dir = adsk.fusion.ExtentDirections.NegativeExtentDirection  # type: ignore[attr-defined]
    else:
        cut_dir = adsk.fusion.ExtentDirections.PositiveExtentDirection   # type: ignore[attr-defined]

    extrudes  = comp.features.extrudeFeatures
    ext_input = extrudes.createInput(
        cut_profile,
        adsk.fusion.FeatureOperations.CutFeatureOperation,  # type: ignore[arg-type]
    )
    ext_input.setOneSideExtent(
        adsk.fusion.DistanceExtentDefinition.create(  # type: ignore[arg-type]
            adsk.core.ValueInput.createByReal(50.0)
        ),
        cut_dir,
    )
    # Scope to just this body (belt-and-suspenders — comp already isolates it)
    participant = adsk.core.ObjectCollection.create()
    participant.add(body)
    ext_input.participantBodies = participant  # type: ignore[assignment]
    extrudes.add(ext_input)
    cut_plane.isLightBulbOn = False

# ── Edge-intersection helpers for Auto Trim ──────────────────────────────────
def _bounding_boxes_overlap(body_a: adsk.fusion.BRepBody,
                            body_b: adsk.fusion.BRepBody,
                            tol: float = 0.05) -> bool:
    """Return True when the axis-aligned bounding boxes of the two bodies
    overlap in 3-D space (allowing a small tolerance for near-touch cases).

    Overlap means the two bodies physically intersect — a T-joint situation
    where one member passes through the other.  A corner joint has touching
    endpoints but no volumetric overlap.
    """
    bb_a = body_a.boundingBox
    bb_b = body_b.boundingBox
    return (
        bb_a.minPoint.x - tol <= bb_b.maxPoint.x and
        bb_a.maxPoint.x + tol >= bb_b.minPoint.x and
        bb_a.minPoint.y - tol <= bb_b.maxPoint.y and
        bb_a.maxPoint.y + tol >= bb_b.minPoint.y and
        bb_a.minPoint.z - tol <= bb_b.maxPoint.z and
        bb_a.maxPoint.z + tol >= bb_b.minPoint.z
    )


def _classify_body_orientation(body: adsk.fusion.BRepBody) -> str:
    """Return 'VERTICAL', 'HORIZONTAL', or 'DIAGONAL' for a body.

    Uses the same bounding-box-delta approach as geometry.GeometryUtils but
    works directly from the BRep body without needing a SketchLine.
    """
    bb = body.boundingBox
    dx = abs(bb.maxPoint.x - bb.minPoint.x)
    dy = abs(bb.maxPoint.y - bb.minPoint.y)
    dz = abs(bb.maxPoint.z - bb.minPoint.z)

    deltas  = sorted([dx, dy, dz], reverse=True)
    dominant = deltas[0]
    second   = deltas[1]

    if dominant < 1e-4:
        return 'HORIZONTAL'
    if second / dominant > 0.5:   # config.DIAGONAL_THRESHOLD
        return 'DIAGONAL'
    return 'VERTICAL' if dz == dominant else 'HORIZONTAL'


def _find_closest_face_centre(body: adsk.fusion.BRepBody,
                              ref_pt: adsk.core.Point3D
                              ) -> Optional[adsk.core.Point3D]:
    """Find the centre of the body face whose centroid is closest to ref_pt.

    Used to identify which end-face is nearest the junction so we know which
    side of the member to trim.
    """
    best_dist = float('inf')
    best_centre: Optional[adsk.core.Point3D] = None
    for i in range(body.faces.count):
        face = body.faces.item(i)
        try:
            bbox = face.boundingBox
            cx   = (bbox.minPoint.x + bbox.maxPoint.x) / 2.0
            cy   = (bbox.minPoint.y + bbox.maxPoint.y) / 2.0
            cz   = (bbox.minPoint.z + bbox.maxPoint.z) / 2.0
            fc   = adsk.core.Point3D.create(cx, cy, cz)
            dist = fc.distanceTo(ref_pt)
            if dist < best_dist:
                best_dist   = dist
                best_centre = fc
        except Exception:
            pass
    return best_centre


def _apply_auto_trim(body_a: adsk.fusion.BRepBody,
                     body_b: adsk.fusion.BRepBody) -> None:
    """Automatic trim: detect joint type and apply the correct operation.

    Detection logic
    ───────────────
    1.  **Bounding-box overlap test** — if the two bodies' AABBs overlap,
        the members physically intersect (T-joint).  Otherwise they meet at
        a corner (endpoint sharing).

    2.  **Orientation classification** — classify each body as VERTICAL,
        HORIZONTAL, or DIAGONAL from its longest bounding-box axis.

    3.  **Auto-orient rule** (structural convention for student projects):
        • T-joint:  the VERTICAL member (column) acts as the tool and cuts
          the HORIZONTAL member (beam).  If both are the same orientation,
          the first selected body (A) cuts the second (B).
        • Corner:   apply a Miter cut (angle-bisector plane) for any angle.
        • Both DIAGONAL or ambiguous: fall back to Miter cut.

    4.  The junction point is derived from the centreline-intersection of
        the two long-axis lines (analytical, not from face topology), which
        is robust even when members are over-extended for miter overlap.
    """
    orient_a = _classify_body_orientation(body_a)
    orient_b = _classify_body_orientation(body_b)
    overlaps  = _bounding_boxes_overlap(body_a, body_b)

    _log(f"  Auto-detect: A={orient_a}, B={orient_b}, overlap={'yes' if overlaps else 'no'}")

    if overlaps:
        # T-joint: one member passes through the other.
        # Standard rule: column (vertical) is continuous; beam (horizontal) is trimmed.
        if orient_a == 'VERTICAL' and orient_b != 'VERTICAL':
            _log("  → T-Trim: A (vertical/column) cuts B (horizontal/beam)")
            _apply_ttrim(body_a, body_b)
        elif orient_b == 'VERTICAL' and orient_a != 'VERTICAL':
            _log("  → T-Trim: B (vertical/column) cuts A (horizontal/beam)")
            _apply_ttrim(body_b, body_a)
        elif orient_a == 'HORIZONTAL' and orient_b == 'HORIZONTAL':
            # Both horizontal — use selection order (A cuts B)
            _log("  → T-Trim: both horizontal, A cuts B (selection order)")
            _apply_ttrim(body_a, body_b)
        else:
            # Diagonal or mixed — miter
            _log("  → Miter cut (diagonal / mixed orientation)")
            _apply_miter(body_a, body_b)
    else:
        # Corner joint — miter cut at the shared endpoint
        _log("  → Corner detected — applying Miter cut")
        _apply_miter(body_a, body_b)

# ── Miter cut ─────────────────────────────────────────────────────────────────

def _apply_miter(body_a: adsk.fusion.BRepBody,
                 body_b: adsk.fusion.BRepBody) -> None:
    """Miter cut at the angle-bisector plane between two members.

    Uses the same proven approach as miter.py:
      - Plane created via setByThreePoints on the ROOT component
        (no coordinate transforms, no sub-component context confusion)
      - participantBodies scopes each extrude-cut to its own body

    Miter plane normal = normalize(dir_A - dir_B)
      For 90°: (1,0,0)-(0,1,0) = (1,-1,0) → 45° plane ✓

    Cut direction:
      far_end dot miter_n > 0  →  body in + half  →  cut NEGATIVE side
      far_end dot miter_n < 0  →  body in − half  →  cut POSITIVE side
    """
    junction = _find_junction_point(body_a, body_b)
    _auto_extend_to_junction(body_a, junction)
    _auto_extend_to_junction(body_b, junction)

    # Get exact member directions from actual end-face normals.
    # This is more accurate than bounding-box endpoints, especially for
    # diagonal members where axis-snapping introduces error.
    dir_a = _get_member_direction(body_a, junction)
    dir_b = _get_member_direction(body_b, junction)

    # Miter plane normal = normalize(dir_A - dir_B) — equidistant plane
    miter_n = _normalize(adsk.core.Vector3D.create(
        dir_a.x - dir_b.x,
        dir_a.y - dir_b.y,
        dir_a.z - dir_b.z,
    ))

    if miter_n.length < 1e-6:
        raise ValueError(
            "Members run in the same direction — cannot miter parallel members.\n"
            "Use Butt Joint instead."
        )

    _log(f"  Junction: ({junction.x:.3f}, {junction.y:.3f}, {junction.z:.3f})")
    _log(f"  dir_A:    ({dir_a.x:.3f}, {dir_a.y:.3f}, {dir_a.z:.3f})")
    _log(f"  dir_B:    ({dir_b.x:.3f}, {dir_b.y:.3f}, {dir_b.z:.3f})")
    _log(f"  miter_n:  ({miter_n.x:.3f}, {miter_n.y:.3f}, {miter_n.z:.3f})")

    # Each body gets its own plane created inside its own sub-component.
    # far_a/far_b: a point one unit along each member's direction from junction,
    # used by _cut_body_at_plane to determine which side of the plane to remove.
    far_a = adsk.core.Point3D.create(
        junction.x + dir_a.x,
        junction.y + dir_a.y,
        junction.z + dir_a.z,
    )
    far_b = adsk.core.Point3D.create(
        junction.x + dir_b.x,
        junction.y + dir_b.y,
        junction.z + dir_b.z,
    )
    _cut_body_at_plane(body_a, junction, miter_n, far_a)
    _cut_body_at_plane(body_b, junction, miter_n, far_b)

    _log("  Miter cut applied.")


# ── T-Trim cut ────────────────────────────────────────────────────────────────

def _apply_ttrim(tool_body: adsk.fusion.BRepBody,
                 target_body: adsk.fusion.BRepBody) -> None:
    """Combine-Cut: tool_body shape cuts target_body. Tool is preserved.

    Uses target_body.parentComponent for the combine feature context.
    """
    junction = _find_junction_point(tool_body, target_body)
    _auto_extend_to_junction(tool_body, junction)
    _auto_extend_to_junction(target_body, junction)

    target_comp: adsk.fusion.Component = target_body.parentComponent  # type: ignore[assignment]
    tool_col = adsk.core.ObjectCollection.create()
    tool_col.add(tool_body)

    combines   = target_comp.features.combineFeatures
    combine_in = combines.createInput(target_body, tool_col)
    combine_in.operation         = adsk.fusion.FeatureOperations.CutFeatureOperation  # type: ignore[attr-defined]
    combine_in.isKeepToolBodies  = True   # Tool (continuous member) is preserved
    combine_in.isNewComponent    = False
    combines.add(combine_in)
    _log("  T-Trim applied (tool body preserved).")


# ── Square cut (aluminium T-slot) ─────────────────────────────────────────────

def _apply_square_cut(tool_body: adsk.fusion.BRepBody,
                       target_body: adsk.fusion.BRepBody) -> None:
    """Square cut for aluminium T-slot: clean perpendicular cut on the
    terminating member at the junction.  The continuous (tool) member is
    untouched.  Physical connection is via angle brackets in the T-slots.

    Unlike Combine→Cut (which sculpts the target to the tool's shape,
    creating complex geometry on T-slot profiles), this produces a flat
    square end face ready for bracket mounting.
    """
    junction = _find_junction_point(tool_body, target_body)
    _auto_extend_to_junction(tool_body, junction)
    _auto_extend_to_junction(target_body, junction)

    axis = _get_body_long_axis(target_body)

    # Determine which end of the target is closest to the junction
    eps = _get_body_endpoints(target_body)
    near_junction = eps[0] if eps[0].distanceTo(junction) < eps[1].distanceTo(junction) else eps[1]
    far_end = eps[1] if near_junction is eps[0] else eps[0]

    # Direction from junction to far end = direction to KEEP
    to_far = adsk.core.Vector3D.create(
        far_end.x - junction.x,
        far_end.y - junction.y,
        far_end.z - junction.z,
    )

    # Cut plane: perpendicular to target's long axis at the junction.
    # Cut direction: removes the junction-side tip.
    _cut_body_at_plane(target_body, junction, axis, far_end)

    _log("  Square cut applied (aluminium T-slot — add bracket hardware).")


# ── Face-based miter cut ──────────────────────────────────────────────────────

def _apply_miter_by_faces(face_a: adsk.fusion.BRepFace,
                           face_b: adsk.fusion.BRepFace) -> None:
    """Miter cut driven by face selection.

    Why not use face geometry for the cut itself?
    ──────────────────────────────────────────────
    Asymmetric profiles (C-channel, L-angle) have their bounding-box centroid
    offset 2-3 cm from the skeleton centreline.  Any junction derived from
    face centroids or body bounding-box centrelines inherits that error and
    shifts the miter plane by the same amount — producing a ramp instead of
    a clean 45° cut.

    Solution: use face selection ONLY to identify the correct bodies, then
    delegate the actual cut to _apply_miter (body-level), which was already
    working and whose junction/direction calculations are tested and stable.

    A warning is logged if a side face was selected instead of an end face,
    so the user can see in Text Commands what went wrong.
    """
    body_a = face_a.body
    body_b = face_b.body

    # Warn when a non-end face was selected (common mistake: clicking the long
    # flange or web face instead of the small cross-section face at the end)
    n_a = _face_plane_normal(face_a)
    n_b = _face_plane_normal(face_b)
    if n_a is not None and not _is_end_face(face_a, body_a):
        _log("  \u26a0 Face A appears to be a SIDE face, not an end face.")
        _log("    For Miter: click the small cross-section face at the cut END of the member.")
    if n_b is not None and not _is_end_face(face_b, body_b):
        _log("  \u26a0 Face B appears to be a SIDE face, not an end face.")
        _log("    For Miter: click the small cross-section face at the cut END of the member.")

    # Delegate to the body-level miter which handles junction + direction correctly
    # for all profile types including offset/asymmetric ones.
    _apply_miter(body_a, body_b)


# ── Face-based auto trim ──────────────────────────────────────────────────────

def _apply_auto_by_faces(face_a: adsk.fusion.BRepFace,
                          face_b: adsk.fusion.BRepFace) -> None:
    """Auto-detect joint type from the face type and apply the right operation.

    END face  (normal ≈ ∥ to member axis) = tip of the member at the joint.
    SIDE face (normal ≈ ⊥ to member axis) = the through-face of the continuous member.

    Both end faces  → corner → Miter.
    End A + Side B  → T-joint; B is continuous → T-Trim: B cuts A.
    Side A + End B  → T-joint; A is continuous → T-Trim: A cuts B.
    Both side faces → fall back to orientation-based body-level auto.
    """
    body_a = face_a.body
    body_b = face_b.body

    end_a = _is_end_face(face_a, body_a)
    end_b = _is_end_face(face_b, body_b)

    _log(f"  Face A: {'END' if end_a else 'SIDE'}  |  Face B: {'END' if end_b else 'SIDE'}")

    if end_a and end_b:
        _log("  → Corner (both end faces) — Miter cut")
        _apply_miter_by_faces(face_a, face_b)
    elif end_a and not end_b:
        _log("  → T-joint: B is continuous (side face) — B cuts A")
        _apply_ttrim(body_b, body_a)
    elif not end_a and end_b:
        _log("  → T-joint: A is continuous (side face) — A cuts B")
        _apply_ttrim(body_a, body_b)
    else:
        _log("  → Both side faces — orientation-based fallback")
        _apply_auto_trim(body_a, body_b)


# ── Execute handler ────────────────────────────────────────────────────────────

class JointExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, eventArgs: adsk.core.CommandEventArgs) -> None:
        try:
            design = get_active_design()
            if not design:
                return

            root_comp = design.rootComponent
            inputs    = eventArgs.command.commandInputs

            sel_a = inputs.itemById('body_a')
            sel_b = inputs.itemById('body_b')
            op_input = inputs.itemById('operation')

            if sel_a.selectionCount < 1 or sel_b.selectionCount < 1:
                ui.messageBox("Please select two frame member bodies.")
                return

            body_a = _extract_body(sel_a.selection(0).entity)
            body_b = _extract_body(sel_b.selection(0).entity)

            if body_a is None or body_b is None:
                ui.messageBox(
                    "Could not resolve one or both selections to a body.\n\n"
                    "Click on any face of the frame member to select its body."
                )
                return

            if body_a == body_b:
                ui.messageBox("Both selections resolve to the same body. "
                              "Please select two different members.")
                return

            operation = op_input.selectedItem.name

            # Aluminium guard: never miter, use square cut instead
            sys_input = adsk.core.DropDownCommandInput.cast(  # type: ignore[misc]
                inputs.itemById('profile_system')
            )
            is_alum = (sys_input and
                       sys_input.selectedItem.name == _PROF_SYS_ALUM)

            transaction = None
            try:
                transaction = design.beginRecordingTransaction()  # type: ignore[attr-defined]
            except Exception:
                pass

            try:
                _log(f"Applying '{operation}' ...")

                if is_alum:
                    # ── Aluminium T-slot: always square cut ──────────────
                    if operation == _OP_AUTO:
                        # Auto-detect direction from face types, then square cut
                        face_a = adsk.fusion.BRepFace.cast(sel_a.selection(0).entity)
                        face_b = adsk.fusion.BRepFace.cast(sel_b.selection(0).entity)
                        if face_a and face_b:
                            end_a = _is_end_face(face_a, face_a.body)
                            end_b = _is_end_face(face_b, face_b.body)
                            if end_a and not end_b:
                                _log("  → B continuous (side face), A square cut")
                                _apply_square_cut(body_b, body_a)
                            else:
                                # End A + End B, Side A + End B, or both side → default A through
                                _log("  → A continuous, B square cut")
                                _apply_square_cut(body_a, body_b)
                        else:
                            _log("  → Fallback: A continuous, B square cut")
                            _apply_square_cut(body_a, body_b)
                    elif operation == _OP_BUTT_BA:
                        _apply_square_cut(body_b, body_a)
                    else:
                        # _OP_BUTT_AB or fallback
                        _apply_square_cut(body_a, body_b)
                    _log("  \u26a0 Add physical bracket connectors at this joint.")

                else:
                    # ── Steel / Structural: miter, butt, or auto-detect ─
                    if operation == _OP_AUTO:
                        face_a = adsk.fusion.BRepFace.cast(sel_a.selection(0).entity)
                        face_b = adsk.fusion.BRepFace.cast(sel_b.selection(0).entity)
                        if face_a and face_b:
                            _apply_auto_by_faces(face_a, face_b)
                        else:
                            _apply_auto_trim(body_a, body_b)
                    elif operation == _OP_MITER:
                        _apply_miter(body_a, body_b)
                    elif operation == _OP_BUTT_AB:
                        _apply_ttrim(body_a, body_b)
                    elif operation == _OP_BUTT_BA:
                        _apply_ttrim(body_b, body_a)
                    else:
                        _apply_ttrim(body_a, body_b)

            except Exception:
                if transaction:
                    try:
                        transaction.abort()  # type: ignore[attr-defined]
                    except Exception:
                        pass
                raise

            if transaction:
                try:
                    transaction.commit()  # type: ignore[attr-defined]
                except Exception:
                    pass

            _log("Joint applied successfully.")

        except Exception:
            if ui:
                ui.messageBox(f"Apply Joint Error:\n{traceback.format_exc()}")


# ── Command-created handler ────────────────────────────────────────────────────

class JointCommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, eventArgs: adsk.core.CommandCreatedEventArgs) -> None:
        try:
            cmd    = eventArgs.command
            inputs = cmd.commandInputs

            try:
                cmd.setDialogMinimumSize(460, 580)  # type: ignore[attr-defined]
                cmd.setDialogInitialSize(480, 620)  # type: ignore[attr-defined]
            except Exception:
                pass
            # ── Profile system selector ─────────────────────────────────────────
            sys_drop = inputs.addDropDownCommandInput(
                'profile_system', 'Profile System',
                adsk.core.DropDownStyles.TextListDropDownStyle
            )
            sys_drop.listItems.add(_PROF_SYS_STEEL, True)
            sys_drop.listItems.add(_PROF_SYS_ALUM,  False)
            # ── Frame Member A ──────────────────────────────────────────────
            sel_a = inputs.addSelectionInput(
                'body_a', 'Frame Member A',
                'Click any face of the first frame member.'
            )
            sel_a.addSelectionFilter('SolidBodies')
            sel_a.addSelectionFilter('Occurrences')
            sel_a.setSelectionLimits(1, 1)

            # ── Frame Member B ──────────────────────────────────────────────
            sel_b = inputs.addSelectionInput(
                'body_b', 'Frame Member B',
                'Click any face of the second frame member.'
            )
            sel_b.addSelectionFilter('SolidBodies')
            sel_b.addSelectionFilter('Occurrences')
            sel_b.setSelectionLimits(1, 1)

            # ── Joint operation ───────────────────────────────────────────────
            op = inputs.addDropDownCommandInput(
                'operation', 'Joint Operation',
                adsk.core.DropDownStyles.TextListDropDownStyle
            )
            op.listItems.add(_OP_AUTO,    True)
            op.listItems.add(_OP_MITER,   False)
            op.listItems.add(_OP_BUTT_AB, False)
            op.listItems.add(_OP_BUTT_BA, False)

            # ── Info ──────────────────────────────────────────────────────────
            inputs.addTextBoxCommandInput(
                'info', '',
                _INFO_STEEL,
                9, True
            )

            on_exec = JointExecuteHandler()
            cmd.execute.add(on_exec)
            handlers.append(on_exec)

            on_changed = JointInputChangedHandler()
            cmd.inputChanged.add(on_changed)
            handlers.append(on_changed)

        except Exception:
            if ui:
                ui.messageBox(f"Apply Joint — dialog error:\n{traceback.format_exc()}")


# ── Lifecycle ──────────────────────────────────────────────────────────────────

def start():
    try:
        cmd_def = ui.commandDefinitions.itemById(CMD_ID)
        if not cmd_def:
            cmd_def = ui.commandDefinitions.addButtonDefinition(
                CMD_ID, CMD_NAME, CMD_DESC, ICON_FOLDER
            )
            on_created = JointCommandCreatedHandler()
            cmd_def.commandCreated.add(on_created)
            handlers.append(on_created)

        design_workspace = ui.workspaces.itemById('FusionSolidEnvironment')

        tab = design_workspace.toolbarTabs.itemById(_TAB_ID)
        if not tab:
            tab = design_workspace.toolbarTabs.add(_TAB_ID, _TAB_NAME)

        frame_panel = tab.toolbarPanels.itemById(_PANEL_ID)
        if not frame_panel:
            frame_panel = tab.toolbarPanels.add(_PANEL_ID, 'Frame', '', False)

        ctrl = frame_panel.controls.itemById(CMD_ID)
        if not ctrl:
            ctrl = frame_panel.controls.addCommand(cmd_def)
        if ctrl:
            cmd_ctrl = adsk.core.CommandControl.cast(ctrl)  # type: ignore[misc]
            cmd_ctrl.isPromoted          = True
            cmd_ctrl.isPromotedByDefault = True

    except Exception:
        if ui:
            ui.messageBox(f"Apply Joint — start() failed:\n{traceback.format_exc()}")


def stop():
    try:
        cmd_def = ui.commandDefinitions.itemById(CMD_ID)
        if cmd_def:
            cmd_def.deleteMe()

        design_workspace = ui.workspaces.itemById('FusionSolidEnvironment')
        tab = design_workspace.toolbarTabs.itemById(_TAB_ID)
        if tab:
            frame_panel = tab.toolbarPanels.itemById(_PANEL_ID)
            if frame_panel:
                ctrl = frame_panel.controls.itemById(CMD_ID)
                if ctrl:
                    ctrl.deleteMe()
                frame_panel.deleteMe()
            tab.deleteMe()
    except Exception:
        pass
