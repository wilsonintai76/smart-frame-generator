"""entry.py — Apply Joint command for SmartFrameGenerator.

Workflow:
  1. User selects two frame members.
     • In Assembly context: click a member body OR the component occurrence.
     • In Part Design context (single component): click a solid body directly.
  2. Chooses joint operation: Miter Cut or T-Trim.
  3. Click OK → joint is applied. Run again for each joint.

Selection note (Assembly mode):
  Fusion 360 places each generated member in its own sub-component.
  When you are at the ROOT level you may need to click a member face and
  the selection will resolve to the body inside that component.
  This command accepts BOTH 'SolidBodies' and 'Occurrences' so either
  mode works — the body is extracted from whichever is selected.

Component scoping for cuts:
  Extrude-Cut and Combine-Cut operations are performed in the BODY'S OWN
  component context (body.parentComponent) to avoid cross-component errors.
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
CMD_NAME    = 'Apply\nJoint'
CMD_DESC    = 'Applies a Miter Cut or T-Trim between two selected frame member bodies.'
ICON_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources')
_TAB_ID        = 'SmartFrameGeneratorTab'
_TAB_NAME      = 'Frame Generator'
_PANEL_ID      = 'SmartFrameGeneratorPanel'

_OP_MITER   = 'Miter Cut (angle bisector)'
_OP_TTRIM   = 'T-Trim  (A cuts through B)'
_OP_TTRIM_R = 'T-Trim  (B cuts through A)'


def _log(message: str) -> None:
    palette = ui.palettes.itemById('TextCommands')
    if palette:
        palette.writeText(f"[ApplyJoint] {message}")


# ── Selection helper ──────────────────────────────────────────────────────────

def _extract_body(entity) -> Optional[adsk.fusion.BRepBody]:
    """Extract a BRepBody from whatever the user selected.

    Accepts:
      • A direct BRepBody (Part Design / single component / activated component)
      • A component Occurrence (root-level Assembly click) → returns its first body
    """
    body = adsk.fusion.BRepBody.cast(entity)
    if body and body.isValid:
        return body

    occ = adsk.fusion.Occurrence.cast(entity)
    if occ and occ.isValid:
        comp = occ.component
        if comp.bRepBodies.count > 0:
            return comp.bRepBodies.item(0)

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


def _make_miter_plane(
        comp:         adsk.fusion.Component,
        junction:     adsk.core.Point3D,
        miter_normal: adsk.core.Vector3D,
) -> adsk.fusion.ConstructionPlane:
    """Construction plane at junction, perpendicular to miter_normal.

    Uses setByDistanceOnPath — the same technique as the frame generator's
    cross-section plane, which is known to work in component contexts.
    A temporary hidden sketch holds the path line; the plane sits at
    distance-0 on that path (= at junction, normal = miter_normal).
    """
    # Choose a sketch base-plane that is not perpendicular to miter_normal
    # so the projected line has non-zero length.
    if abs(miter_normal.z) < 0.9:
        sk_plane = comp.xYConstructionPlane
    else:
        sk_plane = comp.xZConstructionPlane

    temp_sk = comp.sketches.add(sk_plane)
    temp_sk.isVisible = False

    p2 = adsk.core.Point3D.create(
        junction.x + miter_normal.x * 2.0,
        junction.y + miter_normal.y * 2.0,
        junction.z + miter_normal.z * 2.0,
    )
    path_line = temp_sk.sketchCurves.sketchLines.addByTwoPoints(junction, p2)

    path        = comp.features.createPath(path_line)
    plane_input = comp.constructionPlanes.createInput()
    plane_input.setByDistanceOnPath(path, adsk.core.ValueInput.createByReal(0.0))
    return comp.constructionPlanes.add(plane_input)


def _extrude_cut_body(
        body:              adsk.fusion.BRepBody,
        cut_plane:         adsk.fusion.ConstructionPlane,
        use_negative_dir:  bool,
) -> None:
    """Cuts body using an extrude from cut_plane.

    Uses body.parentComponent so the extrude operates in the correct
    component context (avoids cross-component feature errors).
    """
    comp: adsk.fusion.Component = body.parentComponent  # type: ignore[assignment]

    sketch: adsk.fusion.Sketch = comp.sketches.add(cut_plane)
    half = 30.0
    sketch.sketchCurves.sketchLines.addTwoPointRectangle(
        adsk.core.Point3D.create(-half, -half, 0),
        adsk.core.Point3D.create( half,  half, 0),
    )
    cut_profile = sketch.profiles.item(sketch.profiles.count - 1)

    extrudes  = comp.features.extrudeFeatures
    ext_input = extrudes.createInput(
        cut_profile,
        adsk.fusion.FeatureOperations.CutFeatureOperation  # type: ignore[arg-type]
    )
    cut_dist = adsk.core.ValueInput.createByReal(30.0)
    ext_dir  = (adsk.fusion.ExtentDirections.NegativeExtentDirection  # type: ignore[attr-defined]
                if use_negative_dir else
                adsk.fusion.ExtentDirections.PositiveExtentDirection)  # type: ignore[attr-defined]
    ext_input.setOneSideExtent(
        adsk.fusion.DistanceExtentDefinition.create(cut_dist),  # type: ignore[arg-type]
        ext_dir
    )
    # participantBodies is intentionally omitted: the extrude is added to
    # body.parentComponent which contains exactly one body (the swept member),
    # so the cut is naturally scoped to that body without needing to specify it.
    # Passing a list or ObjectCollection here causes a TypeError in Fusion 360 2026.
    extrudes.add(ext_input)


# ── Miter cut ─────────────────────────────────────────────────────────────────

def _apply_miter(root_comp: adsk.fusion.Component,
                 body_a: adsk.fusion.BRepBody,
                 body_b: adsk.fusion.BRepBody) -> None:
    """Miter plane normal = angle bisector of the two member directions.

    Both dir_a and dir_b are computed as unit vectors FROM the junction TO
    the far endpoint of each member — i.e. pointing AWAY from the junction.
    Their sum is the bisector of the included angle, which is the correct
    miter-plane normal for any joint angle.

    Using _get_body_long_axis (axis-snapped ±1 vectors) was wrong because:
      • It ignored the actual direction relative to the junction (+ vs −).
      • dir_A − dir_B produced a perpendicular to the bisector, not the
        bisector itself, giving the wrong 45° face for many configurations.
    """
    junction = _find_junction_point(body_a, body_b)

    # Compute far endpoints once — reused for both miter_n and cut direction.
    def _far_endpoint(body: adsk.fusion.BRepBody) -> adsk.core.Point3D:
        eps = _get_body_endpoints(body)
        return eps[0] if eps[0].distanceTo(junction) >= eps[1].distanceTo(junction) else eps[1]

    far_a = _far_endpoint(body_a)
    far_b = _far_endpoint(body_b)

    # Actual unit vectors FROM junction TOWARD each member's far end.
    dir_a = _normalize(adsk.core.Vector3D.create(
        far_a.x - junction.x,
        far_a.y - junction.y,
        far_a.z - junction.z,
    ))
    dir_b = _normalize(adsk.core.Vector3D.create(
        far_b.x - junction.x,
        far_b.y - junction.y,
        far_b.z - junction.z,
    ))

    # Bisector = sum of the two away-vectors (both point from junction outward).
    miter_n = _normalize(adsk.core.Vector3D.create(
        dir_a.x + dir_b.x,
        dir_a.y + dir_b.y,
        dir_a.z + dir_b.z,
    ))

    if miter_n.length < 1e-6:
        raise ValueError(
            "Bodies appear to run in the same direction — cannot compute a miter plane.\n"
            "Use T-Trim for members running in parallel."
        )

    # Build the miter plane in root_comp so both sub-components can reference it.
    cut_plane = _make_miter_plane(root_comp, junction, miter_n)

    # Cut each body: the far end is on the + side of the bisector plane,
    # so use_negative_dir=True removes the − side (extension near the junction).
    for body, far_end in ((body_a, far_a), (body_b, far_b)):
        to_far = adsk.core.Vector3D.create(
            far_end.x - junction.x,
            far_end.y - junction.y,
            far_end.z - junction.z,
        )
        dot = to_far.dotProduct(miter_n)
        _extrude_cut_body(body, cut_plane, use_negative_dir=(dot > 0))

    cut_plane.isLightBulbOn = False
    _log("  Miter cut applied.")


# ── T-Trim cut ────────────────────────────────────────────────────────────────

def _apply_ttrim(tool_body: adsk.fusion.BRepBody,
                 target_body: adsk.fusion.BRepBody) -> None:
    """Combine-Cut: tool_body shape cuts target_body. Tool is preserved.

    Uses target_body.parentComponent for the combine feature context.
    """
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

            sel_a    = inputs.itemById('body_a')
            sel_b    = inputs.itemById('body_b')
            op_input = inputs.itemById('operation')

            if sel_a.selectionCount < 1 or sel_b.selectionCount < 1:
                ui.messageBox("Please select two frame member bodies.")
                return

            body_a = _extract_body(sel_a.selection(0).entity)
            body_b = _extract_body(sel_b.selection(0).entity)

            if body_a is None or body_b is None:
                ui.messageBox(
                    "Could not resolve one or both selections to a solid body.\n\n"
                    "Tips:\n"
                    "  • Click directly on a face of the frame member\n"
                    "  • In Assembly mode, you may need to click on the body face, "
                    "not the origin/axis of the component"
                )
                return

            if body_a == body_b:
                ui.messageBox("Both selections resolve to the same body. "
                              "Please select two different members.")
                return

            operation = op_input.selectedItem.name

            transaction = None
            try:
                transaction = design.beginRecordingTransaction()  # type: ignore[attr-defined]
            except Exception:
                pass

            try:
                _log(f"Applying '{operation}' ...")
                if operation == _OP_MITER:
                    _apply_miter(root_comp, body_a, body_b)
                elif operation == _OP_TTRIM:
                    _apply_ttrim(body_a, body_b)
                elif operation == _OP_TTRIM_R:
                    _apply_ttrim(body_b, body_a)

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
                cmd.setDialogMinimumSize(440, 460)  # type: ignore[attr-defined]
                cmd.setDialogInitialSize(460, 500)  # type: ignore[attr-defined]
            except Exception:
                pass

            # ── Frame Member A ────────────────────────────────────────────────
            sel_a = inputs.addSelectionInput(
                'body_a', 'Frame Member A',
                'Click a face of the first frame member.'
            )
            # Accept both solid bodies (Part Design / activated component)
            # AND component occurrences (root-level Assembly click)
            sel_a.addSelectionFilter('SolidBodies')
            sel_a.addSelectionFilter('Occurrences')
            sel_a.setSelectionLimits(1, 1)

            # ── Frame Member B ────────────────────────────────────────────────
            sel_b = inputs.addSelectionInput(
                'body_b', 'Frame Member B',
                'Click a face of the second frame member.'
            )
            sel_b.addSelectionFilter('SolidBodies')
            sel_b.addSelectionFilter('Occurrences')
            sel_b.setSelectionLimits(1, 1)

            # ── Joint operation ───────────────────────────────────────────────
            op = inputs.addDropDownCommandInput(
                'operation', 'Joint Operation',
                adsk.core.DropDownStyles.TextListDropDownStyle
            )
            op.listItems.add(_OP_MITER,   True)
            op.listItems.add(_OP_TTRIM,   False)
            op.listItems.add(_OP_TTRIM_R, False)

            # ── Info ──────────────────────────────────────────────────────────
            inputs.addTextBoxCommandInput(
                'info', '',
                '<b>Miter Cut</b>: Both members trimmed flush at the angle bisector.<br><br>'
                '<b>T-Trim (A cuts B)</b>: A continues unmodified; B is trimmed where A passes through.<br><br>'
                '<b>Tip</b>: In Assembly mode, click a <i>face</i> of the member to select its body.',
                5, True
            )

            on_exec = JointExecuteHandler()
            cmd.execute.add(on_exec)
            handlers.append(on_exec)

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
