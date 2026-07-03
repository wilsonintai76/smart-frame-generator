# Global Geometric Tolerances (Centimeters)
TOLERANCE = 0.001

# Orientation Classification
# A member is DIAGONAL when no single axis dominates by this fraction of the max delta.
# E.g. 0.5 means: if the second-largest delta is > 50% of the largest, it's DIAGONAL.
DIAGONAL_THRESHOLD = 0.5

# Predefined Basic Profile Dimensions (Centimeters)
# DEFAULT_HALF_SIZE is the half-width of the square cross-section:
#   full width = 2 × DEFAULT_HALF_SIZE = 4.0 cm (40 mm)
DEFAULT_HALF_SIZE = 2.0
DEFAULT_WALL = 0.4          # wall thickness for hollow tube (cm)

# I-Beam dimensions (cm)  — approx. HEA 60 equivalent
IBEAM_H  = 6.0    # total height
IBEAM_W  = 4.0    # flange width
IBEAM_TF = 0.6    # flange thickness
IBEAM_TW = 0.4    # web thickness

# C-Channel dimensions (cm) — approx. UPN 50 equivalent
CCHANNEL_H  = 5.0  # total height
CCHANNEL_W  = 3.0  # flange width
CCHANNEL_TF = 0.5  # flange thickness
CCHANNEL_TW = 0.4  # web thickness

# Dialogue Panel String Configuration Mapping Constants
PROFILE_SOLID         = "Square Solid"
PROFILE_HOLLOW        = "Square Hollow (Tube)"
PROFILE_IBEAM         = "I-Beam Standard"
PROFILE_CCHANNEL      = "C-Channel Standard"
PROFILE_ROUND_SOLID   = "Round Solid Bar"
PROFILE_ROUND_HOLLOW  = "Round Hollow Tube"
PROFILE_LANGLE        = "L Angle Bar"
PROFILE_ALUMINUM      = "Aluminium Extrusion (T-slot)"

PRIORITY_VERTICAL   = "Vertical Continuous (Columns Cut Beams)"
PRIORITY_HORIZONTAL = "Horizontal Continuous (Beams Cut Columns)"
PRIORITY_SELECTION  = "Selection Order (First Selection Wins)"

# Round bar / tube defaults (cm)
DEFAULT_ROUND_DIAMETER = 3.0   # 30 mm
DEFAULT_ROUND_WALL     = 0.3   # 3 mm wall

# L-Angle bar defaults (cm)
LANGLE_H  = 4.0   # vertical leg height
LANGLE_W  = 4.0   # horizontal leg width
LANGLE_TH = 0.4   # leg thickness

# Aluminium T-slot extrusion defaults (cm)
ALUMINUM_SIZE = 4.0   # overall side (40×40 mm)
ALUMINUM_WALL = 0.25  # wall / land thickness

# Material identifiers
MATERIAL_STEEL    = "Steel"
MATERIAL_ALUMINUM = "Aluminium"

# Material densities (g/cm³)
DENSITY_STEEL    = 7.85
DENSITY_ALUMINUM = 2.70

# Young's modulus (N/cm²) — used by simple beam analysis
E_STEEL    = 21_000_000.0   # 210 GPa
E_ALUMINUM =  7_000_000.0   #  70 GPa

# Yield strength (N/cm²) — for stress checks
# Structural steel S275 ≈ 27,500 N/cm²  (275 MPa)
# Aluminium 6061-T6  ≈ 27,600 N/cm²    (276 MPa)
YIELD_STEEL    = 27_500.0
YIELD_ALUMINUM = 27_600.0

# Design safety factor (applied to yield strength)
SAFETY_FACTOR = 1.5

# Deflection limits (span/limit ratio)
DEFL_LIMIT_PRIMARY   = 180.0   # L/180 — primary structural members
DEFL_LIMIT_SECONDARY = 240.0   # L/240 — floors / secondary members

# Default applied loads
DEFAULT_UDL_NM       = 0.0     # N/m  (uniform distributed load on horizontals)
DEFAULT_POINT_LOAD_N = 0.0     # N    (point load at mid-span of longest horizontal)

# ── Load case presets (N/m line load) ────────────────────────────────────────
# Students pick from a dropdown; "Custom" uses the manual UDL input.
LOAD_CASES: dict[str, float] = {
    "Self-weight only":               0.0,
    "Light Roof (0.5 kN/m)":        500.0,
    "Residential Floor (2.0 kN/m)": 2000.0,
    "Office Floor (3.0 kN/m)":      3000.0,
    "Walkway / Balcony (5.0 kN/m)": 5000.0,
}

# ── Material cost (RM per kg) ─────────────────────────────────────────────────
COST_PER_KG_STEEL    = 5.0     # RM/kg — typical mild steel (S275)
COST_PER_KG_ALUMINUM = 22.0    # RM/kg — typical 6061-T6 aluminium

# Gravitational acceleration (cm/s²)
GRAVITY = 981.0   # 9.81 m/s²

# Reports output subdirectory (relative to add-in root)
REPORTS_DIR = "reports"