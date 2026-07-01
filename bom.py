"""bom.py — Bill of Materials generator for SmartFrameGenerator.

After frame generation, produces a BOM table listing each member's:
  - Index number
  - Profile type
  - Component name
  - Length in mm (rounded to 1 decimal place)

Output:
  1. Printed to Fusion 360's Text Commands palette for instant visibility.
  2. Saved as a CSV file to <addin_root>/reports/frame_bom_<timestamp>.csv
"""

import csv
import os
import datetime
from typing import List

import adsk.core

import config
from member import FrameMember


def _log(message: str) -> None:
    """Writes a message to Fusion 360's Text Commands palette."""
    app = adsk.core.Application.get()
    palette = app.userInterface.palettes.itemById('TextCommands')
    if palette:
        palette.writeText(f"[SmartFrameGenerator] {message}")


def _get_reports_dir() -> str:
    """Returns the absolute path to the reports directory, creating it if needed."""
    addon_dir = os.path.dirname(os.path.abspath(__file__))
    reports_dir = os.path.join(addon_dir, config.REPORTS_DIR)
    os.makedirs(reports_dir, exist_ok=True)
    return reports_dir


class BOMGenerator:
    @staticmethod
    def generate(members: List[FrameMember], profile_type: str) -> None:
        """Generates a BOM from the list of FrameMembers and outputs it.

        Args:
            members:      List of all generated FrameMember objects.
            profile_type: The profile type string selected by the user.
        """
        if not members:
            _log("BOM: No members to report.")
            return

        rows = []
        for idx, m in enumerate(members, start=1):
            length_mm = round(m.length * 10.0, 1)  # cm → mm
            comp_name = m.component.name if m.component else f"Member_{idx}"
            rows.append({
                "No.":          idx,
                "Profile":      profile_type,
                "Component":    comp_name,
                "Orientation":  m.orientation,
                "Length (mm)":  length_mm,
            })

        # ── Text Commands Output ──────────────────────────────────────────────
        _log("─" * 72)
        _log("  BILL OF MATERIALS")
        _log(f"  {'No.':<5} {'Profile':<25} {'Component':<25} {'Orient.':<12} {'Length (mm)':>12}")
        _log("  " + "─" * 70)
        for row in rows:
            _log(f"  {row['No.']:<5} {row['Profile']:<25} {row['Component']:<25} "
                 f"{row['Orientation']:<12} {row['Length (mm)']:>12.1f}")
        _log("─" * 72)
        _log(f"  Total members: {len(rows)}")
        _log("─" * 72)

        # ── CSV Output ────────────────────────────────────────────────────────
        try:
            timestamp  = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            csv_name   = f"frame_bom_{timestamp}.csv"
            csv_path   = os.path.join(_get_reports_dir(), csv_name)
            fieldnames = ["No.", "Profile", "Component", "Orientation", "Length (mm)"]

            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

            _log(f"  BOM saved → {csv_path}")
        except Exception as ex:
            _log(f"  ⚠ BOM CSV save failed: {ex}")
