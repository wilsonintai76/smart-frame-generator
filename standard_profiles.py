"""standard_profiles.py — ISO 657 metric structural profile library.

All dimensions are in centimetres (Fusion 360 internal units).
Equivalent real-world mm values are noted in comments.

Profile types:
  "solid"        → square solid bar
  "hollow"       → square/rectangular hollow section (SHS / RHS)
  "ibeam"        → I-beam (HEA / HEB series)
  "channel"      → C-channel (UPN series)
  "round_solid"  → circular solid bar
  "round_hollow" → circular hollow tube (CHS / pipe)
  "langle"       → L-angle equal/unequal bar
  "aluminum"     → T-slot aluminium extrusion (20/40 series)
"""

from typing import Any

# fmt: off
STANDARD_PROFILES: dict[str, dict[str, Any]] = {
    # ── Square Hollow Sections (SHS) ──────────────────────────────────────────
    "SHS 40×40×3":  {"type": "hollow", "w": 4.0,  "h": 4.0,  "wall": 0.30},
    "SHS 50×50×4":  {"type": "hollow", "w": 5.0,  "h": 5.0,  "wall": 0.40},
    "SHS 60×60×5":  {"type": "hollow", "w": 6.0,  "h": 6.0,  "wall": 0.50},
    "SHS 80×80×5":  {"type": "hollow", "w": 8.0,  "h": 8.0,  "wall": 0.50},
    "SHS 100×100×6":{"type": "hollow", "w": 10.0, "h": 10.0, "wall": 0.60},

    # ── Rectangular Hollow Sections (RHS) ────────────────────────────────────
    "RHS 60×40×4":  {"type": "hollow", "w": 6.0,  "h": 4.0,  "wall": 0.40},
    "RHS 80×40×4":  {"type": "hollow", "w": 8.0,  "h": 4.0,  "wall": 0.40},
    "RHS 100×50×5": {"type": "hollow", "w": 10.0, "h": 5.0,  "wall": 0.50},
    "RHS 120×60×5": {"type": "hollow", "w": 12.0, "h": 6.0,  "wall": 0.50},

    # ── I-Beams — HEA series (ISO 657-5) ────────────────────────────────────
    "HEA 100":  {"type": "ibeam", "h":  9.6, "w": 10.0, "tf": 0.80, "tw": 0.50},
    "HEA 120":  {"type": "ibeam", "h": 11.4, "w": 12.0, "tf": 0.80, "tw": 0.50},
    "HEA 140":  {"type": "ibeam", "h": 13.3, "w": 14.0, "tf": 0.85, "tw": 0.55},
    "HEA 160":  {"type": "ibeam", "h": 15.2, "w": 16.0, "tf": 0.90, "tw": 0.60},
    "HEA 180":  {"type": "ibeam", "h": 17.1, "w": 18.0, "tf": 0.95, "tw": 0.60},
    "HEA 200":  {"type": "ibeam", "h": 19.0, "w": 20.0, "tf": 1.00, "tw": 0.65},

    # ── I-Beams — HEB series (ISO 657-5) ────────────────────────────────────
    "HEB 100":  {"type": "ibeam", "h": 10.0, "w": 10.0, "tf": 1.00, "tw": 0.60},
    "HEB 120":  {"type": "ibeam", "h": 12.0, "w": 12.0, "tf": 1.10, "tw": 0.65},
    "HEB 140":  {"type": "ibeam", "h": 14.0, "w": 14.0, "tf": 1.20, "tw": 0.70},
    "HEB 160":  {"type": "ibeam", "h": 16.0, "w": 16.0, "tf": 1.30, "tw": 0.75},
    "HEB 180":  {"type": "ibeam", "h": 18.0, "w": 18.0, "tf": 1.40, "tw": 0.85},
    "HEB 200":  {"type": "ibeam", "h": 20.0, "w": 20.0, "tf": 1.50, "tw": 0.90},

    # ── C-Channels — UPN series (ISO 657-16) ────────────────────────────────
    "UPN 80":   {"type": "channel", "h":  8.0, "w": 4.50, "tf": 0.74, "tw": 0.60},
    "UPN 100":  {"type": "channel", "h": 10.0, "w": 5.00, "tf": 0.85, "tw": 0.60},
    "UPN 120":  {"type": "channel", "h": 12.0, "w": 5.50, "tf": 0.90, "tw": 0.70},
    "UPN 140":  {"type": "channel", "h": 14.0, "w": 6.00, "tf": 0.95, "tw": 0.70},
    "UPN 160":  {"type": "channel", "h": 16.0, "w": 6.50, "tf": 1.00, "tw": 0.75},
    "UPN 180":  {"type": "channel", "h": 18.0, "w": 7.00, "tf": 1.10, "tw": 0.80},
    "UPN 200":  {"type": "channel", "h": 20.0, "w": 7.50, "tf": 1.15, "tw": 0.85},

    # ── Square Solid Bars ────────────────────────────────────────────────────
    "SQ Bar 20×20": {"type": "solid", "w": 2.0, "h": 2.0},
    "SQ Bar 30×30": {"type": "solid", "w": 3.0, "h": 3.0},
    "SQ Bar 40×40": {"type": "solid", "w": 4.0, "h": 4.0},
    "SQ Bar 50×50": {"type": "solid", "w": 5.0, "h": 5.0},

    # ── Round Solid Bars ─────────────────────────────────────────────────────
    "Round Bar ⌀16": {"type": "round_solid", "d": 1.6},
    "Round Bar ⌀20": {"type": "round_solid", "d": 2.0},
    "Round Bar ⌀25": {"type": "round_solid", "d": 2.5},
    "Round Bar ⌀30": {"type": "round_solid", "d": 3.0},
    "Round Bar ⌀40": {"type": "round_solid", "d": 4.0},
    "Round Bar ⌀50": {"type": "round_solid", "d": 5.0},

    # ── Circular Hollow Sections (CHS / Pipe) ────────────────────────────────
    "CHS ⌀21.3×2.0": {"type": "round_hollow", "d": 2.13, "wall": 0.20},
    "CHS ⌀26.9×2.3": {"type": "round_hollow", "d": 2.69, "wall": 0.23},
    "CHS ⌀33.7×2.6": {"type": "round_hollow", "d": 3.37, "wall": 0.26},
    "CHS ⌀42.4×2.9": {"type": "round_hollow", "d": 4.24, "wall": 0.29},
    "CHS ⌀48.3×3.2": {"type": "round_hollow", "d": 4.83, "wall": 0.32},
    "CHS ⌀60.3×3.6": {"type": "round_hollow", "d": 6.03, "wall": 0.36},
    "CHS ⌀76.1×4.0": {"type": "round_hollow", "d": 7.61, "wall": 0.40},

    # ── Equal L-Angle Bars (ISO 657-1) ──────────────────────────────────────
    # Dimensions: h=vertical leg, w=horizontal leg, th=leg thickness
    "L 25×25×3":  {"type": "langle", "h": 2.5, "w": 2.5, "th": 0.30},
    "L 30×30×3":  {"type": "langle", "h": 3.0, "w": 3.0, "th": 0.30},
    "L 40×40×4":  {"type": "langle", "h": 4.0, "w": 4.0, "th": 0.40},
    "L 50×50×5":  {"type": "langle", "h": 5.0, "w": 5.0, "th": 0.50},
    "L 60×60×6":  {"type": "langle", "h": 6.0, "w": 6.0, "th": 0.60},
    "L 70×70×7":  {"type": "langle", "h": 7.0, "w": 7.0, "th": 0.70},
    "L 80×80×8":  {"type": "langle", "h": 8.0, "w": 8.0, "th": 0.80},
    "L 100×100×10":{"type": "langle", "h": 10.0,"w": 10.0,"th": 1.00},

    # ── Aluminium T-slot Extrusions (20-series, 40-series) ───────────────────
    # size = outer square side dimension; wall = land / wall thickness
    "AL 2020":  {"type": "aluminum", "size": 2.0,  "wall": 0.15},
    "AL 3030":  {"type": "aluminum", "size": 3.0,  "wall": 0.20},
    "AL 4040":  {"type": "aluminum", "size": 4.0,  "wall": 0.25},
    "AL 4080":  {"type": "aluminum", "size": 4.0,  "wall": 0.25},   # non-square — use width override
    "AL 6060":  {"type": "aluminum", "size": 6.0,  "wall": 0.30},
    "AL 8080":  {"type": "aluminum", "size": 8.0,  "wall": 0.35},
}
# fmt: on


def get_standard_profile_names() -> list[str]:
    """Returns the list of standard profile display names for the UI dropdown."""
    return list(STANDARD_PROFILES.keys())


def get_profile_params(name: str) -> dict[str, Any] | None:
    """Returns the parameter dict for a standard profile by display name, or None."""
    return STANDARD_PROFILES.get(name)
