"""standard_profiles.py — ISO 657 metric structural steel profile library.

All dimensions are in centimetres (Fusion 360 internal units).
Equivalent real-world mm values are noted in comments.

Profile types:
  "solid"   → square solid bar (half-size + optional width/height override)
  "hollow"  → square/rectangular hollow section (SHS / RHS)
  "ibeam"   → I-beam (HEA / HEB series)
  "channel" → C-channel (UPN series)

The STANDARD_PROFILES dict is keyed by the display name shown in the UI dropdown.
Each entry carries enough parameters for ProfileFactory to draw the cross-section
without referencing config.py constants.
"""

# fmt: off
STANDARD_PROFILES: dict = {
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
    # Dimensions: h=total height, w=flange width, tf=flange thickness, tw=web thickness
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
    # Dimensions: h=total height, w=flange width, tf=flange thickness, tw=web thickness
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
}
# fmt: on


def get_standard_profile_names() -> list[str]:
    """Returns the list of standard profile display names for the UI dropdown."""
    return list(STANDARD_PROFILES.keys())


def get_profile_params(name: str) -> dict | None:
    """Returns the parameter dict for a standard profile by display name, or None."""
    return STANDARD_PROFILES.get(name)
