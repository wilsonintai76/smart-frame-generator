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
PROFILE_SOLID    = "Square Solid"
PROFILE_HOLLOW   = "Square Hollow (Tube)"
PROFILE_IBEAM    = "I-Beam Standard"
PROFILE_CCHANNEL = "C-Channel Standard"

PRIORITY_VERTICAL   = "Vertical Continuous (Columns Cut Beams)"
PRIORITY_HORIZONTAL = "Horizontal Continuous (Beams Cut Columns)"
PRIORITY_SELECTION  = "Selection Order (First Selection Wins)"

# Reports output subdirectory (relative to add-in root)
REPORTS_DIR = "reports"