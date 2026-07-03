"""entry.py — Generate Frame command (sweep only, no cutting).

Workflow:
  1. User selects skeleton sketch lines.
  2. Chooses profile type, dimensions, rotation.
  3. Click OK → each line is swept into a separate frame member body.
  4. NO trimming or mitering — members are clean solids ready for
     the separate 'Apply Joint' command.

Preview:
  A live Custom Graphics overlay draws the profile cross-section in
  the viewport whenever the profile type, rotation angle, or dimensions
  change.  It is positioned at the start of the first selected skeleton
  line (or at the world origin when nothing is selected).
"""

import math
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
from analysis import generate as run_analysis
from utils import get_active_design, get_available_custom_profiles
from standard_profiles import get_standard_profile_names

app = adsk.core.Application.get()
ui  = app.userInterface
handlers: List[adsk.core.EventHandler] = []

CMD_ID      = 'SmartFrameBtn'
CMD_NAME    = 'Generate Frame'
CMD_DESC    = 'Sweeps structural frame members along skeleton sketch lines at their exact true length. ' \
              'Use "Apply Joint" to miter or trim corners.'
ICON_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources')
_TAB_ID        = 'SmartFrameGeneratorTab'
_TAB_NAME      = 'Frame Generator'
_PANEL_ID      = 'SmartFrameGeneratorPanel'

_PARAMETRIC_PROFILES = {
    config.PROFILE_SOLID,
    config.PROFILE_HOLLOW,
    config.PROFILE_IBEAM,
    config.PROFILE_CCHANNEL,
    config.PROFILE_ROUND_SOLID,
    config.PROFILE_ROUND_HOLLOW,
    config.PROFILE_LANGLE,
    config.PROFILE_ALUMINUM,
}

# Profiles that expose a wall-thickness input
_WALL_PROFILES = {
    config.PROFILE_HOLLOW,
    config.PROFILE_ROUND_HOLLOW,
    config.PROFILE_LANGLE,
    config.PROFILE_ALUMINUM,
}

# Profiles that expose a separate height input (width ≠ height / diameter only)
_HEIGHT_PROFILES = {
    config.PROFILE_IBEAM,
    config.PROFILE_CCHANNEL,
    config.PROFILE_HOLLOW,
    config.PROFILE_LANGLE,
}

# Width label remapping for diameter-based profiles
_DIAMETER_PROFILES = {
    config.PROFILE_ROUND_SOLID,
    config.PROFILE_ROUND_HOLLOW,
}


def _log(message: str) -> None:
    palette = ui.palettes.itemById('TextCommands')
    if palette:
        palette.writeText(f"[GenerateFrame] {message}")  # type: ignore[attr-defined]


# ── Profile orientation hints (shown in dialog) ────────────────────────────────

_ORIENTATION_HINTS: dict[str, str] = {
    config.PROFILE_SOLID:
        '<b>Square Solid</b> — Symmetric. Rotation tilts it diagonally.',
    config.PROFILE_HOLLOW:
        '<b>Square Hollow Tube</b> — Symmetric. Rotation changes which face is outward.',
    config.PROFILE_ROUND_SOLID:
        '<b>Round Solid Bar</b> — Circular — rotation has no visible effect.',
    config.PROFILE_ROUND_HOLLOW:
        '<b>Round Hollow Tube</b> — Circular — rotation has no visible effect.',
    config.PROFILE_LANGLE:
        '<b>L Angle Bar</b> — Corner opens toward +Y (up) and +X (right).<br>'
        'Rotate 90° → corner opens left. &nbsp;Rotate 180° → corner opens down.',
    config.PROFILE_CCHANNEL:
        '<b>C-Channel</b> — Web (back wall) at −X, flanges open toward +X.<br>'
        'Rotate 90° → web at bottom, flanges open upward.<br>'
        'Rotate −90° → web at top, flanges open downward.',
    config.PROFILE_ALUMINUM:
        '<b>Aluminium T-slot Extrusion</b> \u2014 T-slots on all 4 faces.<br>'
        'Rotation shifts which slot face aligns with the sweep path.<br><br>'
        '<span style=\"color:orange\"><b>\u26a0 No miter cuts</b></span> \u2014 '
        'T-slot profiles are always cut SQUARE (perpendicular to the axis).<br>'
        'Use <b>angle brackets</b>, <b>inside corner connectors</b>, or '
        '<b>gusset plates</b> to join members at corners.<br>'
        'Select <i>Aluminium T-slot Extrusion</i> in the Apply Joint dialog.',
    config.PROFILE_IBEAM:
        '<b>I-Beam</b> — Flanges horizontal (±X), web vertical (Y). Strong axis = Y.<br>'
        'Rotate 90° → strong axis becomes horizontal (use for columns).',
}


def _orientation_hint(profile_type: str) -> str:
    """Return the HTML orientation hint for the given profile display name."""
    return _ORIENTATION_HINTS.get(
        profile_type,
        f'<i>{profile_type}</i> — Standard library profile. '
        'Use rotation to adjust orientation.',
    )



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

            lines_input    = adsk.core.SelectionCommandInput.cast(inputs.itemById('lines'))    # type: ignore[misc]
            profile_input  = adsk.core.DropDownCommandInput.cast(inputs.itemById('profile'))    # type: ignore[misc]
            angle_input    = adsk.core.ValueCommandInput.cast(inputs.itemById('rotation'))      # type: ignore[misc]
            width_input    = adsk.core.ValueCommandInput.cast(inputs.itemById('dim_width'))     # type: ignore[misc]
            height_input   = adsk.core.ValueCommandInput.cast(inputs.itemById('dim_height'))    # type: ignore[misc]
            wall_input     = adsk.core.ValueCommandInput.cast(inputs.itemById('dim_wall'))      # type: ignore[misc]
            bom_input      = adsk.core.BoolValueCommandInput.cast(inputs.itemById('gen_bom'))   # type: ignore[misc]
            material_input = adsk.core.DropDownCommandInput.cast(inputs.itemById('material'))   # type: ignore[misc]
            analysis_input = adsk.core.BoolValueCommandInput.cast(inputs.itemById('gen_analysis'))  # type: ignore[misc]

            selected_profile = profile_input.selectedItem.name
            # ValueCommandInput.value always returns RADIANS internally —
            # convert to degrees before passing to _rotate() in profiles.py
            angle_deg = math.degrees(angle_input.value) if angle_input else 0.0

            width_val  = width_input.value  if (width_input  and width_input.isVisible)  else None
            height_val = height_input.value if (height_input and height_input.isVisible) else None
            wall_val   = wall_input.value   if (wall_input   and wall_input.isVisible)   else None
            gen_bom      = bom_input.value      if bom_input      else False
            material     = material_input.selectedItem.name if material_input else config.MATERIAL_STEEL
            gen_analysis = analysis_input.value             if analysis_input else False

            # Load inputs (from the loads group)
            udl_input       = adsk.core.ValueCommandInput.cast(inputs.itemById('udl_nm'))        # type: ignore[misc]
            pt_load_input   = adsk.core.ValueCommandInput.cast(inputs.itemById('point_load_n'))  # type: ignore[misc]
            sf_input        = adsk.core.ValueCommandInput.cast(inputs.itemById('safety_factor')) # type: ignore[misc]
            lc_input        = adsk.core.DropDownCommandInput.cast(inputs.itemById('load_case'))  # type: ignore[misc]
            udl_nm          = udl_input.value       if udl_input       else 0.0
            point_load_n    = pt_load_input.value   if pt_load_input   else 0.0
            safety_factor   = sf_input.value        if sf_input        else config.SAFETY_FACTOR
            load_case_name  = lc_input.selectedItem.name if lc_input   else "Self-weight only"  # type: ignore[union-attr]

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

                for i, line in enumerate(selected_lines):
                    member_name = f"{selected_profile.replace(' ', '_')}_{i + 1}"

                    feats = root_comp.features

                    # Generate at EXACT sketch line length — no extension.
                    # Miter cuts (miter.py) naturally trim end faces at the shared
                    # vertex; T-joint trims use the profile cross-section's natural
                    # overlap (half-width ≈ 2 cm) for Combine → Cut.
                    sweep_path = feats.createPath(line)

                    # Construction plane at start of the sketch line
                    planes   = root_comp.constructionPlanes
                    plane_in = planes.createInput()
                    plane_in.setByDistanceOnPath(sweep_path, adsk.core.ValueInput.createByReal(0.0))
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
                    BOMGenerator.generate(
                        members,
                        profile_type = selected_profile,
                        material     = material,
                        width        = width_val,
                        height       = height_val,
                        wall         = wall_val,
                    )

                # Optional structural analysis
                if gen_analysis and members:
                    run_analysis(
                        members,
                        profile_type  = selected_profile,
                        material      = material,
                        width         = width_val,
                        height        = height_val,
                        wall          = wall_val,
                        udl_nm        = udl_nm,
                        point_load_n  = point_load_n,
                        safety_factor = safety_factor,
                        load_case     = load_case_name,
                    )

                # ── Post-generation summary popup ─────────────────────
                import os as _os
                reports_dir = _os.path.join(root_dir, config.REPORTS_DIR)
                lines = [f"\u2705 {len(members)} member(s) generated."]
                if gen_bom:
                    lines.append("\n\U0001f4cb BOM report:")
                    lines.append("   \u2022 Text Commands palette")
                    lines.append(f"   \u2022 {reports_dir}\\frame_bom_*.csv")
                if gen_analysis:
                    lines.append("\n\U0001f4ca Analysis report:")
                    lines.append("   \u2022 Text Commands palette")
                    lines.append(f"   \u2022 {reports_dir}\\analysis_*.csv")
                    lines.append(f"   \u2022 Load case: {load_case_name}")
                    if udl_nm > 0 or point_load_n > 0:
                        loads_str: list[str] = []
                        if udl_nm > 0:
                            loads_str.append(f"UDL = {udl_nm:.1f} N/m")
                        if point_load_n > 0:
                            loads_str.append(f"Point Load = {point_load_n:.1f} N")
                        lines.append(f"   \u2022 Loads: {', '.join(loads_str)}")
                    lines.append(f"   \u2022 Safety Factor = {safety_factor}")
                if not gen_bom and not gen_analysis:
                    lines.append("\nTick 'Generate BOM Report' or ")
                    lines.append("'Run Structural Analysis' to get reports.")
                lines.append("\nRun 'Apply Joint' or Edit in Place to trim joints.")
                ui.messageBox("\n".join(lines), "Frame Generated")

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
            inputs        = eventArgs.inputs

            # ── Visibility / label updates on profile change ──────────────
            if changed_input.id == 'profile':
                profile_name  = inputs.itemById('profile').selectedItem.name  # type: ignore[union-attr]
                is_parametric = profile_name in _PARAMETRIC_PROFILES

                dim_group = inputs.itemById('dim_group')
                if dim_group:
                    dim_group.isVisible = is_parametric  # type: ignore[attr-defined]

                wall_input = inputs.itemById('dim_wall')
                if wall_input:
                    wall_input.isVisible = profile_name in _WALL_PROFILES
                    try:
                        wall_input.name = ('Leg Thickness'   # type: ignore[attr-defined]
                                           if profile_name == config.PROFILE_LANGLE
                                           else 'Wall Thickness')
                    except Exception:
                        pass

                height_input = inputs.itemById('dim_height')
                if height_input:
                    height_input.isVisible = profile_name in _HEIGHT_PROFILES

                width_input = inputs.itemById('dim_width')
                if width_input:
                    try:
                        width_input.name = (  # type: ignore[attr-defined]
                            'Diameter' if profile_name in _DIAMETER_PROFILES else 'Width'
                        )
                    except Exception:
                        pass

            # ── Show/hide loads group when analysis is toggled ────────────
            if changed_input.id == 'gen_analysis':
                analysis_cb = adsk.core.BoolValueCommandInput.cast(changed_input)  # type: ignore[misc]
                loads_group = inputs.itemById('loads_group')
                if loads_group and analysis_cb:
                    loads_group.isVisible = analysis_cb.value  # type: ignore[attr-defined]

            # ── Load case preset → update UDL value ───────────────────────
            if changed_input.id == 'load_case':
                case_drop = adsk.core.DropDownCommandInput.cast(changed_input)  # type: ignore[misc]
                udl_input = adsk.core.ValueCommandInput.cast(inputs.itemById('udl_nm'))  # type: ignore[misc]
                if case_drop and udl_input:
                    sel = case_drop.selectedItem.name  # type: ignore[union-attr]
                    if sel in config.LOAD_CASES:
                        udl_input.value = config.LOAD_CASES[sel]
                    # "Custom ▸" — leave UDL as-is for manual entry

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
                cmd.setDialogMinimumSize(480, 760)  # type: ignore[attr-defined]
                cmd.setDialogInitialSize(500, 800)  # type: ignore[attr-defined]
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
            prof.listItems.add(config.PROFILE_SOLID,         True)
            prof.listItems.add(config.PROFILE_HOLLOW,        False)
            prof.listItems.add(config.PROFILE_ROUND_SOLID,   False)
            prof.listItems.add(config.PROFILE_ROUND_HOLLOW,  False)
            prof.listItems.add(config.PROFILE_LANGLE,        False)
            prof.listItems.add(config.PROFILE_CCHANNEL,      False)
            prof.listItems.add(config.PROFILE_ALUMINUM,      False)
            prof.listItems.add(config.PROFILE_IBEAM,         False)
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
            # ── Orientation hint (just below rotation — updates live) ──────────
            hint = inputs.addTextBoxCommandInput(
                'orient_hint', '',
                _orientation_hint(config.PROFILE_SOLID),
                3, True
            )
            try:
                hint.isFullWidth = True  # type: ignore[attr-defined]
            except Exception:
                pass

            # ── Material selector (affects analysis weight/E) ─────────────
            mat = inputs.addDropDownCommandInput(
                'material', 'Material',
                adsk.core.DropDownStyles.TextListDropDownStyle  # type: ignore[arg-type]
            )
            mat.listItems.add(config.MATERIAL_STEEL,    True)
            mat.listItems.add(config.MATERIAL_ALUMINUM, False)

            # ── BOM report checkbox ───────────────────────────────────────
            inputs.addBoolValueInput('gen_bom', 'Generate BOM Report', True, '', False)

            # ── Structural analysis checkbox ──────────────────────────────
            inputs.addBoolValueInput(
                'gen_analysis', 'Run Structural Analysis', True, '', False
            )

            # ── Loads group (shown when analysis is checked) ──────────────
            loads_group = inputs.addGroupCommandInput('loads_group', 'Applied Loads')
            loads_group.isExpanded = True
            lch = loads_group.children

            load_case = lch.addDropDownCommandInput(
                'load_case', 'Load Case',
                adsk.core.DropDownStyles.TextListDropDownStyle  # type: ignore[arg-type]
            )
            first = True
            for name in config.LOAD_CASES:
                load_case.listItems.add(name, first)
                first = False
            load_case.listItems.add('Custom \u25B8', False)  # last item, not default

            default_udl = adsk.core.ValueInput.createByReal(config.DEFAULT_UDL_NM)
            lch.addValueInput('udl_nm', 'UDL (N/m)', 'N/m', default_udl)

            default_pt = adsk.core.ValueInput.createByReal(config.DEFAULT_POINT_LOAD_N)
            lch.addValueInput('point_load_n', 'Point Load (N)', 'N', default_pt)

            default_sf = adsk.core.ValueInput.createByReal(config.SAFETY_FACTOR)
            lch.addValueInput('safety_factor', 'Safety Factor', '', default_sf)

            # ── Output location note ──────────────────────────────────────
            out_note = inputs.addTextBoxCommandInput(
                'output_note', '',
                '📊 BOM &amp; Analysis results appear in the <b>Text Commands</b> '
                'palette (View → Text Commands) AND are saved as CSV files '
                'in the add-in <b>reports/</b> folder.',
                2, True
            )
            try:
                out_note.isFullWidth = True  # type: ignore[attr-defined]
            except Exception:
                pass

            # ── Register handlers ──────────────────────────────────────────────
            on_exec = FrameExecuteHandler()
            cmd.execute.add(on_exec)
            handlers.append(on_exec)

            on_changed = FrameInputChangedHandler()
            cmd.inputChanged.add(on_changed)
            handlers.append(on_changed)

        except Exception:
            if ui:
                ui.messageBox(f"Generate Frame — dialog error:\n{traceback.format_exc()}")