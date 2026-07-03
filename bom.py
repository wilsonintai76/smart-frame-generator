"""bom.py — Bill of Materials generator for SmartFrameGenerator.

After frame generation, produces a BOM table listing each member with:
  - Cut-list quantity grouping  (members with the same length are merged)
  - Profile type and material
  - Orientation
  - Length in mm
  - Cross-section area (cm²)
  - Mass per piece (kg) and total mass for that row (kg)

Output:
  1. Printed to Fusion 360's Text Commands palette for instant visibility.
  2. Saved as a CSV file to <addin_root>/reports/frame_bom_<timestamp>.csv
"""

import csv
import math
import os
import datetime
from typing import Any, List, Optional

import adsk.core

import config
from member import FrameMember


def _log(message: str) -> None:
    """Writes a message to Fusion 360's Text Commands palette."""
    app = adsk.core.Application.get()
    palette = app.userInterface.palettes.itemById('TextCommands')
    if palette:
        palette.writeText(f"[BOM] {message}")  # type: ignore[attr-defined]


def _get_reports_dir() -> str:
    """Returns the absolute path to the reports directory, creating it if needed."""
    addon_dir = os.path.dirname(os.path.abspath(__file__))
    reports_dir = os.path.join(addon_dir, config.REPORTS_DIR)
    os.makedirs(reports_dir, exist_ok=True)
    return reports_dir


def _section_area(profile_type: str,
                  width:  Optional[float],
                  height: Optional[float],
                  wall:   Optional[float]) -> float:
    """Approximate cross-section area (cm²) for mass calculation."""
    w  = width  or config.DEFAULT_HALF_SIZE * 2
    h  = height or w
    wl = wall   or config.DEFAULT_WALL

    if profile_type == config.PROFILE_SOLID:
        return w * h

    if profile_type == config.PROFILE_HOLLOW:
        wi, hi = max(w - 2*wl, 0.0), max(h - 2*wl, 0.0)
        return w * h - wi * hi

    if profile_type == config.PROFILE_ROUND_SOLID:
        return math.pi * (w / 2.0) ** 2

    if profile_type == config.PROFILE_ROUND_HOLLOW:
        r_o = w / 2.0
        r_i = max(r_o - wl, 0.0)
        return math.pi * (r_o**2 - r_i**2)

    if profile_type == config.PROFILE_LANGLE:
        th = wl
        return h * th + (w - th) * th

    if profile_type == config.PROFILE_ALUMINUM:
        wi = max(w - 2*wl, 0.0)
        return (w * w - wi * wi) * 0.80   # ~20 % void correction

    if profile_type == config.PROFILE_IBEAM:
        tf = config.IBEAM_TF; tw = config.IBEAM_TW
        h_use = height or config.IBEAM_H
        w_use = width  or config.IBEAM_W
        return 2 * (w_use * tf) + (h_use - 2*tf) * tw

    if profile_type == config.PROFILE_CCHANNEL:
        tf = config.CCHANNEL_TF; tw = config.CCHANNEL_TW
        h_use = height or config.CCHANNEL_H
        w_use = width  or config.CCHANNEL_W
        return 2 * (w_use * tf) + (h_use - 2*tf) * tw

    # Standard library / unknown: rough outer-area approximation
    return w * h


class BOMGenerator:
    @staticmethod
    def generate(members:      List[FrameMember],
                 profile_type: str,
                 material:     str              = config.MATERIAL_STEEL,
                 width:        Optional[float]  = None,
                 height:       Optional[float]  = None,
                 wall:         Optional[float]  = None) -> None:
        """Generates a cut-list BOM from the list of FrameMembers.

        Args:
            members:      Frame members created by the generate command.
            profile_type: Display name of the cross-section profile.
            material:     "Steel" or "Aluminium" — controls density.
            width / height / wall: Parametric dimensions (cm).
        """
        if not members:
            _log("No members to report.")
            return

        density  = (config.DENSITY_ALUMINUM if material == config.MATERIAL_ALUMINUM
                    else config.DENSITY_STEEL)
        cost_per_kg = (config.COST_PER_KG_ALUMINUM if material == config.MATERIAL_ALUMINUM
                       else config.COST_PER_KG_STEEL)
        area_cm2 = _section_area(profile_type, width, height, wall)

        # ── Build per-member rows ─────────────────────────────────────────────
        detail_rows: list[dict[str, Any]] = []
        for idx, m in enumerate(members, start=1):
            length_mm = round(m.length * 10.0, 1)
            mass_kg   = round(area_cm2 * m.length * density / 1000.0, 3)
            cost_rm   = round(mass_kg * cost_per_kg, 2)
            comp_name = m.component.name if m.component else f"Member_{idx}"
            detail_rows.append({
                "No.":          idx,
                "Component":    comp_name,
                "Profile":      profile_type,
                "Material":     material,
                "Orientation":  m.orientation,
                "Length (mm)":  length_mm,
                "Area (cm\u00b2)": round(area_cm2, 3),
                "Mass (kg)":    mass_kg,
                "Cost (RM)":    cost_rm,
            })

        # ── Cut-list: group by (profile, length) ─────────────────────────────
        cut_groups: dict[tuple[str, float], dict[str, Any]] = {}
        for r in detail_rows:
            key = (r["Profile"], r["Length (mm)"])
            if key in cut_groups:
                cut_groups[key]["Qty"]           += 1
                cut_groups[key]["Total Mass (kg)"] = round(
                    cut_groups[key]["Total Mass (kg)"] + r["Mass (kg)"], 3)
                cut_groups[key]["Total Cost (RM)"] = round(
                    cut_groups[key]["Total Cost (RM)"] + r["Cost (RM)"], 2)
            else:
                cut_groups[key] = {
                    "Qty":            1,
                    "Profile":        r["Profile"],
                    "Material":       r["Material"],
                    "Length (mm)":    r["Length (mm)"],
                    "Area (cm\u00b2)": r["Area (cm\u00b2)"],
                    "Mass/pc (kg)":   r["Mass (kg)"],
                    "Total Mass (kg)":r["Mass (kg)"],
                    "Cost/pc (RM)":   r["Cost (RM)"],
                    "Total Cost (RM)":r["Cost (RM)"],
                }
        cut_list = sorted(cut_groups.values(),
                          key=lambda x: (x["Profile"], x["Length (mm)"]))

        total_mass = round(sum(r["Total Mass (kg)"] for r in cut_list), 3)
        total_cost = round(sum(r["Total Cost (RM)"] for r in cut_list), 2)
        total_qty  = sum(r["Qty"] for r in cut_list)

        # ── Text Commands: cut list ───────────────────────────────────────────
        _log("\u2550" * 78)
        _log("  BILL OF MATERIALS \u2014 CUT LIST")
        _log(f"  Profile : {profile_type}   Material : {material}   "
             f"Section area : {area_cm2:.3f} cm\u00b2"
             f"   Cost : RM {cost_per_kg:.2f}/kg")
        _log("\u2500" * 78)
        hdr = (f"  {'Qty':>4}  {'Profile':<22} {'Material':<9} "
               f"{'L (mm)':>8} {'kg/pc':>7} {'RM/pc':>7} {'Total kg':>9} {'Total RM':>9}")
        _log(hdr)
        _log("  " + "\u2500" * 76)
        for r in cut_list:
            _log(
                f"  {r['Qty']:>4}  {r['Profile']:<22} {r['Material']:<9} "
                f"{r['Length (mm)']:>8.0f} {r['Mass/pc (kg)']:>7.3f} "
                f"{r['Cost/pc (RM)']:>7.2f} {r['Total Mass (kg)']:>9.3f} "
                f"{r['Total Cost (RM)']:>9.2f}"
            )
        _log("\u2500" * 78)
        _log(f"  Total pieces : {total_qty}     Total mass : {total_mass:.3f} kg  "
             f"({total_mass * 9.81:.1f} N)")
        _log(f"  Total cost   : RM {total_cost:.2f}")
        _log("\u2550" * 78)

        # ── CSV: two sheets in one file — cut list, then detail ───────────────
        try:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            csv_path  = os.path.join(_get_reports_dir(), f"frame_bom_{timestamp}.csv")

            cut_fields    = ["Qty", "Profile", "Material", "Length (mm)",
                             "Area (cm\u00b2)", "Mass/pc (kg)", "Cost/pc (RM)",
                             "Total Mass (kg)", "Total Cost (RM)"]
            detail_fields = ["No.", "Component", "Profile", "Material",
                             "Orientation", "Length (mm)", "Area (cm\u00b2)",
                             "Mass (kg)", "Cost (RM)"]

            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                # Section 1 — cut list
                writer.writerow(["CUT LIST"])
                writer.writerow(cut_fields)
                for r in cut_list:
                    writer.writerow([r[k] for k in cut_fields])
                writer.writerow([])
                writer.writerow([f"Total pieces: {total_qty}",
                                 f"Total mass: {total_mass:.3f} kg",
                                 f"Total cost: RM {total_cost:.2f}"])
                writer.writerow([])
                # Section 2 — per-member detail
                writer.writerow(["MEMBER DETAIL"])
                writer.writerow(detail_fields)
                for r in detail_rows:
                    writer.writerow([r[k] for k in detail_fields])

            _log(f"  BOM saved → {csv_path}")
        except Exception as ex:
            _log(f"  ⚠ BOM CSV save failed: {ex}")
