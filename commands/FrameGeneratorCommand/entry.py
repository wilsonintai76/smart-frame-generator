"""entry.py — Generate Frame command (sweep only, no cutting).

Workflow:
  1. User selects skeleton sketch lines.
  2. Chooses profile type, dimensions, rotation.
  3. Click OK → each line is swept into a separate frame member body.
  4. NO trimming or mitering — members are clean solids ready for
     the separate 'Apply Joint' command.
"""

import os
import sys
import traceback
from typing import List

import adsk.core
import adsk.fusion

current_dir  = os.path.dirname(os.path.abspath(__file__))
commands_dir = os.path.dirname(current_dir)
root_dir     = os.path.dirname(commands_dir)

if root_dir not in sys.path:
    sys.path.append(root_dir)

import config
from member import FrameMember
from profiles import ProfileFactory
from bom import BOMGenerator
from utils import get_active_design, get_available_custom_profiles
from standard_profiles import get_standard_profile_names

app = adsk.core.Application.get()
ui  = app.userInterface
handlers: List[adsk.core.EventHandler] = []

CMD_ID      = 'SmartFrameBtn'
CMD_NAME    = 'Generate\nFrame'
CMD_DESC    = 'Sweeps structural frame members along skeleton sketch lines. ' \
              'Each member is created as a separate body. Use "Apply Joint" to trim or miter.'
ICON_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources')
_TAB_ID        = 'SmartFrameGeneratorTab'
_TAB_NAME      = 'Frame Generator'
_PANEL_ID      = 'SmartFrameGeneratorPanel'

_PARAMETRIC_PROFILES = {
    config.PROFILE_SOLID,
    config.PROFILE_HOLLOW,
    config.PROFILE_IBEAM,
    config.PROFILE_CCHANNEL,
}


def _log(message: str) -> None:
    palette = ui.palettes.itemById('TextCommands')
    if palette:
        palette.writeText(f"[GenerateFrame] {message}")  # type: ignore[attr-defined]


# ── Lifecycle ──────────────────────────────────────────────────────────────────

def start():
    try:
        cmd_def = ui.commandDefinitions.itemById(CMD_ID)
        if not cmd_def:
            cmd_def = ui.commandDefinitions.addButtonDefinition(
                CMD_ID, CMD_NAME, CMD_DESC, ICON_FOLDER
            )
            on_created = FrameCommandCreatedHandler()
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
            ui.messageBox(f"Generate Frame — start() failed:\n{traceback.format_exc()}")


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
                # Don't delete the panel or tab — Apply Joint also uses them
    except Exception:
        pass


# ── Execute handler ────────────────────────────────────────────────────────────

class FrameExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, eventArgs: adsk.core.CommandEventArgs) -> None:
        try:
            design = get_active_design()
            if not design:
                return

            root_comp = design.rootComponent
            cmd       = eventArgs.command
            inputs    = cmd.commandInputs

            lines_input   = adsk.core.SelectionCommandInput.cast(inputs.itemById('lines'))   # type: ignore[misc]
            profile_input = adsk.core.DropDownCommandInput.cast(inputs.itemById('profile'))   # type: ignore[misc]
            angle_input   = adsk.core.ValueCommandInput.cast(inputs.itemById('rotation'))     # type: ignore[misc]
            width_input   = adsk.core.ValueCommandInput.cast(inputs.itemById('dim_width'))    # type: ignore[misc]
            height_input  = adsk.core.ValueCommandInput.cast(inputs.itemById('dim_height'))   # type: ignore[misc]
            wall_input    = adsk.core.ValueCommandInput.cast(inputs.itemById('dim_wall'))     # type: ignore[misc]
            bom_input     = adsk.core.BoolValueCommandInput.cast(inputs.itemById('gen_bom'))  # type: ignore[misc]

            selected_profile = profile_input.selectedItem.name
            angle_deg        = angle_input.value if angle_input else 0.0

            width_val  = width_input.value  if (width_input  and width_input.isVisible)  else None
            height_val = height_input.value if (height_input and height_input.isVisible) else None
            wall_val   = wall_input.value   if (wall_input   and wall_input.isVisible)   else None
            gen_bom    = bom_input.value    if bom_input else False

            # Single undo transaction
            transaction = None
            try:
                transaction = design.beginRecordingTransaction()  # type: ignore[attr-defined]
            except Exception:
                pass

            members: List[FrameMember] = []

            try:
                # Snapshot all line references BEFORE any model operations.
                # Fusion 360 invalidates SelectionCommandInput entries as soon as
                # the model is modified, so selection(i) raises "invalid argument
                # index" on the second iteration if read inside the sweep loop.
                selected_lines: List[adsk.fusion.SketchLine] = []
                for i in range(lines_input.selectionCount):
                    line = adsk.fusion.SketchLine.cast(  # type: ignore[misc]
                        lines_input.selection(i).entity  # type: ignore[arg-type]
                    )
                    if line:
                        selected_lines.append(line)

                # Extension = profile_size / 2 (exact minimum for 90° miter)
                # + 1 mm tolerance for floating-point stability.
                # Only use the actual profile dimensions — no I-beam fallback
                # that would over-extend smaller profiles.
                ext_size = max(
                    width_val  if width_val  is not None else 1.0,
                    height_val if height_val is not None else 1.0,
                ) / 2.0 + 0.1

                for i, line in enumerate(selected_lines):
                    member_name = f"{selected_profile.replace(' ', '_')}_{i + 1}"

                    # ── Detect shared endpoints ───────────────────────────────
                    # Check ALL non-construction lines in the same sketch, not
                    # just the current selection.  This means a single-line run
                    # still detects that its endpoint touches other skeleton lines
                    # drawn in the sketch, so the extension is added even when the
                    # user generates members one batch at a time.
                    sp_geom = line.startSketchPoint.geometry
                    ep_geom = line.endSketchPoint.geometry

                    _sk_lines_col = line.parentSketch.sketchCurves.sketchLines
                    _all_sk_lines = [
                        _sk_lines_col.item(j)
                        for j in range(_sk_lines_col.count)
                        if not _sk_lines_col.item(j).isConstruction
                    ]

                    start_shared = any(
                        other is not line and (
                            sp_geom.distanceTo(other.startSketchPoint.geometry) < config.TOLERANCE or
                            sp_geom.distanceTo(other.endSketchPoint.geometry)   < config.TOLERANCE
                        )
                        for other in _all_sk_lines
                    )
                    end_shared = any(
                        other is not line and (
                            ep_geom.distanceTo(other.startSketchPoint.geometry) < config.TOLERANCE or
                            ep_geom.distanceTo(other.endSketchPoint.geometry)   < config.TOLERANCE
                        )
                        for other in _all_sk_lines
                    )

                    # ── Build sweep path (extend past shared endpoints) ───────
                    feats      = root_comp.features
                    sweep_path_curve: adsk.fusion.SketchLine = line  # type: ignore[assignment]

                    if start_shared or end_shared:
                        dx = ep_geom.x - sp_geom.x
                        dy = ep_geom.y - sp_geom.y
                        dz = ep_geom.z - sp_geom.z
                        d_vec = adsk.core.Vector3D.create(dx, dy, dz)
                        d_len = d_vec.length
                        if d_len > config.TOLERANCE:
                            d_vec.normalize()
                            ext_sp = adsk.core.Point3D.create(
                                sp_geom.x - d_vec.x * (ext_size if start_shared else 0.0),
                                sp_geom.y - d_vec.y * (ext_size if start_shared else 0.0),
                                sp_geom.z - d_vec.z * (ext_size if start_shared else 0.0),
                            )
                            ext_ep = adsk.core.Point3D.create(
                                ep_geom.x + d_vec.x * (ext_size if end_shared else 0.0),
                                ep_geom.y + d_vec.y * (ext_size if end_shared else 0.0),
                                ep_geom.z + d_vec.z * (ext_size if end_shared else 0.0),
                            )
                            temp_sk = root_comp.sketches.add(line.parentSketch.referencePlane)
                            temp_sk.isVisible = False
                            sweep_path_curve = temp_sk.sketchCurves.sketchLines.addByTwoPoints(ext_sp, ext_ep)

                    # Use the ORIGINAL line for the construction plane so Fusion 360
                    # preserves the same rotational frame as the skeleton sketch.
                    # Asymmetric profiles (C-channel) must not be rotated by the
                    # different natural frame that a temp-sketch path would produce.
                    orig_path  = feats.createPath(line)
                    sweep_path = feats.createPath(sweep_path_curve)

                    # Construction plane at start of ORIGINAL line (correct orientation)
                    planes   = root_comp.constructionPlanes
                    plane_in = planes.createInput()
                    plane_in.setByDistanceOnPath(orig_path, adsk.core.ValueInput.createByReal(0.0))
                    plane = planes.add(plane_in)

                    # Cross-section sketch
                    sketch  = root_comp.sketches.add(plane)
                    profile = ProfileFactory.draw(
                        sketch,
                        selected_profile,
                        angle_deg = angle_deg,
                        width     = width_val,
                        height    = height_val,
                        wall      = wall_val,
                    )

                    # ── Sweep: always use NewComponentFeatureOperation ─────────
                    # Each member MUST live in its own sub-component.
                    # If NewBodyFeatureOperation were used instead, Fusion 360 would
                    # automatically join touching/overlapping bodies into one solid,
                    # making it impossible to select individual members in Apply Joint.
                    sweeps = feats.sweepFeatures
                    occ_before = root_comp.occurrences.count
                    try:
                        sweep_in = sweeps.createInput(
                            profile, sweep_path,
                            adsk.fusion.FeatureOperations.NewComponentFeatureOperation  # type: ignore[arg-type]
                        )
                        sweep_in.orientation = adsk.fusion.SweepOrientationTypes.PerpendicularOrientationType  # type: ignore[assignment]
                        sweeps.add(sweep_in)
                    except RuntimeError as rte:
                        err = str(rte)
                        if 'one component' in err or 'Part Design' in err or '\x03' in err or '3 :' in err:
                            raise RuntimeError(
                                "Generate Frame requires an ASSEMBLY document.\n\n"
                                "In a Part Design document, Fusion 360 only allows one component, "
                                "so all swept members join into a single body — making it "
                                "impossible to select them individually for Apply Joint.\n\n"
                                "How to fix:\n"
                                "  1. File → New Design  (creates an Assembly by default)\n"
                                "  2. Draw your skeleton sketch in the new design\n"
                                "  3. Run Generate Frame again"
                            ) from rte
                        raise

                    # Verify a new occurrence was actually created
                    if root_comp.occurrences.count != occ_before + 1:
                        raise RuntimeError(
                            f"Member {i+1}: Expected a new component occurrence but none was created. "
                            "The sweep may have merged with an existing body."
                        )

                    new_occ   = root_comp.occurrences.item(root_comp.occurrences.count - 1)
                    comp      = new_occ.component
                    comp.name = member_name
                    body      = comp.bRepBodies.item(0)

                    members.append(FrameMember(body, comp, line, i))
                    _log(f"  ✓ Member {i+1}: '{member_name}'  "
                         f"length = {round(members[-1].length * 10, 1)} mm")

                # Optional BOM
                if gen_bom and members:
                    BOMGenerator.generate(members, selected_profile)

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

            _log(f"✅ Frame generation complete — {len(members)} member(s) created. "
                 f"Select members and run 'Apply Joint' to trim/miter corners.")

        except Exception:
            if ui:
                ui.messageBox(f"Generate Frame Error:\n{traceback.format_exc()}")


# ── Input-changed handler (show/hide dimension inputs) ─────────────────────────

class FrameInputChangedHandler(adsk.core.InputChangedEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, eventArgs: adsk.core.InputChangedEventArgs) -> None:
        try:
            changed_input = eventArgs.input
            if changed_input.id != 'profile':
                return

            inputs       = eventArgs.inputs
            profile_name = inputs.itemById('profile').selectedItem.name  # type: ignore[union-attr]
            is_parametric = profile_name in _PARAMETRIC_PROFILES

            dim_group = inputs.itemById('dim_group')
            if dim_group:
                dim_group.isVisible = is_parametric  # type: ignore[attr-defined]

            wall_input = inputs.itemById('dim_wall')
            if wall_input:
                wall_input.isVisible = (profile_name == config.PROFILE_HOLLOW)

            height_input = inputs.itemById('dim_height')
            if height_input:
                height_input.isVisible = profile_name in (
                    config.PROFILE_IBEAM, config.PROFILE_CCHANNEL, config.PROFILE_HOLLOW
                )
        except Exception:
            pass


# ── Command-created handler ────────────────────────────────────────────────────

class FrameCommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, eventArgs: adsk.core.CommandCreatedEventArgs) -> None:
        try:
            cmd    = eventArgs.command
            inputs = cmd.commandInputs

            # Dialog size
            try:
                cmd.setDialogMinimumSize(480, 620)  # type: ignore[attr-defined]
                cmd.setDialogInitialSize(500, 660)  # type: ignore[attr-defined]
            except Exception:
                pass

            # ── Skeleton line selection ───────────────────────────────────────
            sel = inputs.addSelectionInput(
                'lines', 'Skeleton Lines',
                'Select sketch lines for the frame skeleton.'
            )
            sel.addSelectionFilter('SketchLines')
            sel.setSelectionLimits(1, 0)

            # ── Profile cross-section dropdown ────────────────────────────────
            prof = inputs.addDropDownCommandInput(
                'profile', 'Cross-Section Profile',
                adsk.core.DropDownStyles.TextListDropDownStyle  # type: ignore[arg-type]
            )
            prof.listItems.add(config.PROFILE_SOLID,    True)
            prof.listItems.add(config.PROFILE_HOLLOW,   False)
            prof.listItems.add(config.PROFILE_IBEAM,    False)
            prof.listItems.add(config.PROFILE_CCHANNEL, False)
            for std_name in get_standard_profile_names():
                prof.listItems.add(std_name, False)
            for p_name in get_available_custom_profiles():
                prof.listItems.add(p_name, False)

            # ── Parametric dimension overrides ────────────────────────────────
            dim_group = inputs.addGroupCommandInput('dim_group', 'Cross-Section Dimensions')
            dim_group.isExpanded = True
            dim_group.isVisible  = True
            dim_ch = dim_group.children

            default_w = adsk.core.ValueInput.createByReal(config.DEFAULT_HALF_SIZE * 2)
            dim_ch.addValueInput('dim_width', 'Width', 'cm', default_w)

            default_h = adsk.core.ValueInput.createByReal(config.DEFAULT_HALF_SIZE * 2)
            h_vi = dim_ch.addValueInput('dim_height', 'Height', 'cm', default_h)
            h_vi.isVisible = False

            default_wall = adsk.core.ValueInput.createByReal(config.DEFAULT_WALL)
            w_vi = dim_ch.addValueInput('dim_wall', 'Wall Thickness', 'cm', default_wall)
            w_vi.isVisible = False

            # ── Profile rotation angle ────────────────────────────────────────
            inputs.addValueInput(
                'rotation', 'Profile Rotation', 'deg',
                adsk.core.ValueInput.createByReal(0.0)
            )

            # ── BOM report checkbox ───────────────────────────────────────────
            inputs.addBoolValueInput('gen_bom', 'Generate BOM Report', True, '', False)

            # ── Register handlers ─────────────────────────────────────────────
            on_exec = FrameExecuteHandler()
            cmd.execute.add(on_exec)
            handlers.append(on_exec)

            on_changed = FrameInputChangedHandler()
            cmd.inputChanged.add(on_changed)
            handlers.append(on_changed)

        except Exception:
            if ui:
                ui.messageBox(f"Generate Frame — dialog error:\n{traceback.format_exc()}")