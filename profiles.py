"""profiles.py — Cross-section profile sketch factory for SmartFrameGenerator.

ProfileFactory.draw() draws the structural cross-section into a Fusion sketch
so it can be used as the profile for a sweep feature.

Enhancements over the original:
  • Rotation support — all profiles honour a rotation_angle (degrees) parameter.
    Points are rotated around the sketch origin before being added.
  • Parametric dimensions — width, height, wall overrides allow per-member sizing
    without touching config.py.
  • Standard library routing — when profile_type matches a key in
    standard_profiles.STANDARD_PROFILES, the correct built-in drawing method is
    called with the standard dimensions, avoiding the .f3d import path.
"""

import math
import os
from typing import List, Optional, cast

import adsk.core
import adsk.fusion

import config
from utils import get_resource_path, get_active_design
from typing import Any
from standard_profiles import get_profile_params


def _fget(d: dict[str, Any], key: str, default: float) -> float:
    """Extract a float value from a profile parameter dict with a typed default."""
    return float(d.get(key, default))


# ── Rotation helper ───────────────────────────────────────────────────────────

def _rotate(points: List[adsk.core.Point3D], angle_deg: float) -> List[adsk.core.Point3D]:
    """Rotates a list of 2-D sketch points around the origin by angle_deg degrees."""
    if abs(angle_deg) < 1e-6:
        return points
    rad = math.radians(angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    rotated: List[adsk.core.Point3D] = []
    for p in points:
        rx = p.x * cos_a - p.y * sin_a
        ry = p.x * sin_a + p.y * cos_a
        rotated.append(adsk.core.Point3D.create(rx, ry, 0.0))  # type: ignore[arg-type]
    return rotated


def _draw_closed_polygon(sketch: adsk.fusion.Sketch,
                         points: List[adsk.core.Point3D]) -> None:
    """Draws a closed polygon from a list of Point3D vertices."""
    lines = sketch.sketchCurves.sketchLines
    n = len(points)
    for i in range(n):
        lines.addByTwoPoints(points[i], points[(i + 1) % n])


def _find_hollow_profile(sketch: adsk.fusion.Sketch) -> adsk.fusion.Profile:
    """Return the annular (hollow) profile from a sketch with nested loops.

    When two nested closed shapes are drawn (outer + inner), Fusion creates
    multiple profiles.  The correct hollow cross-section is the one with
    exactly 2 profile loops (outer boundary + inner island).  If no 2-loop
    profile is found, falls back to the largest-area profile.
    """
    profiles = sketch.profiles
    best: Optional[adsk.fusion.Profile] = None
    best_area = -1.0

    for i in range(profiles.count):
        p = profiles.item(i)
        if p.profileLoops.count == 2:
            # Annular profile found — has outer boundary + inner hole
            try:
                a = p.areaProperties().area  # type: ignore[attr-defined]
            except Exception:
                a = 0.0
            if a > best_area:
                best_area = a
                best = p

    if best is not None:
        return best

    # Fallback: pick the profile with the largest area (likely the outer solid)
    for i in range(profiles.count):
        p = profiles.item(i)
        try:
            a = p.areaProperties().area  # type: ignore[attr-defined]
        except Exception:
            a = 0.0
        if a > best_area:
            best_area = a
            best = p

    return best if best is not None else profiles.item(profiles.count - 1)


# ── Profile drawing helpers ───────────────────────────────────────────────────

def _draw_solid(sketch: adsk.fusion.Sketch,
                w: float, h: float,
                angle_deg: float) -> adsk.fusion.Profile:
    """Square / rectangular solid bar."""
    hw, hh = w / 2.0, h / 2.0
    raw = [
        adsk.core.Point3D.create(-hw, -hh, 0),
        adsk.core.Point3D.create( hw, -hh, 0),
        adsk.core.Point3D.create( hw,  hh, 0),
        adsk.core.Point3D.create(-hw,  hh, 0),
    ]
    pts = _rotate(raw, angle_deg)
    _draw_closed_polygon(sketch, pts)
    return sketch.profiles.item(sketch.profiles.count - 1)


def _draw_round_solid(sketch: adsk.fusion.Sketch,
                      diameter: float,
                      angle_deg: float) -> adsk.fusion.Profile:
    """Circular solid bar (round bar / rod).

    angle_deg is ignored for circles (rotationally symmetric) but accepted
    for API consistency.
    """
    radius = diameter / 2.0
    origin = adsk.core.Point3D.create(0.0, 0.0, 0.0)
    sketch.sketchCurves.sketchCircles.addByCenterRadius(origin, radius)
    return sketch.profiles.item(sketch.profiles.count - 1)


def _draw_round_hollow(sketch: adsk.fusion.Sketch,
                       diameter: float, wall: float,
                       angle_deg: float) -> adsk.fusion.Profile:
    """Circular hollow tube (CHS — Circular Hollow Section / pipe)."""
    r_outer = diameter / 2.0
    r_inner = max(r_outer - wall, 1e-4)
    origin  = adsk.core.Point3D.create(0.0, 0.0, 0.0)
    sketch.sketchCurves.sketchCircles.addByCenterRadius(origin, r_outer)
    sketch.sketchCurves.sketchCircles.addByCenterRadius(origin, r_inner)
    return _find_hollow_profile(sketch)


def _draw_langle(sketch: adsk.fusion.Sketch,
                 h: float, w: float, th: float,
                 angle_deg: float) -> adsk.fusion.Profile:
    """L-angle bar — two-leg equal or unequal angle section.

    Origin at the outer corner.  Centred so the outer corner is near
    the sketch origin (matches sweep axis direction).
    """
    raw = [
        adsk.core.Point3D.create(-w / 2.0,        -h / 2.0,       0),
        adsk.core.Point3D.create( w / 2.0,        -h / 2.0,       0),
        adsk.core.Point3D.create( w / 2.0,        -h / 2.0 + th,  0),
        adsk.core.Point3D.create(-w / 2.0 + th,   -h / 2.0 + th,  0),
        adsk.core.Point3D.create(-w / 2.0 + th,    h / 2.0,       0),
        adsk.core.Point3D.create(-w / 2.0,         h / 2.0,       0),
    ]
    pts = _rotate(raw, angle_deg)
    _draw_closed_polygon(sketch, pts)
    return sketch.profiles.item(sketch.profiles.count - 1)


def _draw_aluminum_tslot(sketch: adsk.fusion.Sketch,
                         size: float, wall: float,
                         angle_deg: float) -> adsk.fusion.Profile:
    """Simplified T-slot aluminium extrusion outer contour.

    Draws the characteristic outer silhouette of a 20-/40-series
    T-slot extrusion (square with 4 face notches).  The interior is
    solid for sweep compatibility — material properties are computed
    analytically in analysis.py using the real hollow cross-section.

    Slot proportions (relative to half-size ``s``):
      slot opening half-width  = 0.15 × size
      slot depth               = 0.12 × size
    """
    s  = size / 2.0
    sw = size * 0.15   # slot opening half-width
    sd = size * 0.12   # slot depth from outer face

    raw = [
        # Top face  (left corner → left of slot → slot bottom → right of slot → right corner)
        adsk.core.Point3D.create(-s,         s,        0),
        adsk.core.Point3D.create(-sw,        s,        0),
        adsk.core.Point3D.create(-sw,        s - sd,   0),
        adsk.core.Point3D.create( sw,        s - sd,   0),
        adsk.core.Point3D.create( sw,        s,        0),
        # Right face
        adsk.core.Point3D.create( s,         s,        0),
        adsk.core.Point3D.create( s,         sw,       0),
        adsk.core.Point3D.create( s - sd,    sw,       0),
        adsk.core.Point3D.create( s - sd,   -sw,       0),
        adsk.core.Point3D.create( s,        -sw,       0),
        # Bottom face
        adsk.core.Point3D.create( s,        -s,        0),
        adsk.core.Point3D.create( sw,       -s,        0),
        adsk.core.Point3D.create( sw,      -(s - sd),  0),
        adsk.core.Point3D.create(-sw,      -(s - sd),  0),
        adsk.core.Point3D.create(-sw,       -s,        0),
        # Left face
        adsk.core.Point3D.create(-s,        -s,        0),
        adsk.core.Point3D.create(-s,        -sw,       0),
        adsk.core.Point3D.create(-(s - sd), -sw,       0),
        adsk.core.Point3D.create(-(s - sd),  sw,       0),
        adsk.core.Point3D.create(-s,         sw,       0),
    ]
    pts = _rotate(raw, angle_deg)
    _draw_closed_polygon(sketch, pts)
    return sketch.profiles.item(sketch.profiles.count - 1)


def _draw_hollow(sketch: adsk.fusion.Sketch,
                 w: float, h: float, wall: float,
                 angle_deg: float) -> adsk.fusion.Profile:
    """Square / rectangular hollow section (tube).  Outer then inner rectangle."""
    hw, hh = w / 2.0, h / 2.0
    iw, ih = (w - 2 * wall) / 2.0, (h - 2 * wall) / 2.0

    outer_raw = [
        adsk.core.Point3D.create(-hw, -hh, 0),
        adsk.core.Point3D.create( hw, -hh, 0),
        adsk.core.Point3D.create( hw,  hh, 0),
        adsk.core.Point3D.create(-hw,  hh, 0),
    ]
    inner_raw = [
        adsk.core.Point3D.create(-iw, -ih, 0),
        adsk.core.Point3D.create( iw, -ih, 0),
        adsk.core.Point3D.create( iw,  ih, 0),
        adsk.core.Point3D.create(-iw,  ih, 0),
    ]
    _draw_closed_polygon(sketch, _rotate(outer_raw, angle_deg))
    _draw_closed_polygon(sketch, _rotate(inner_raw, angle_deg))
    return _find_hollow_profile(sketch)


def _draw_ibeam(sketch: adsk.fusion.Sketch,
                h: float, w: float, tf: float, tw: float,
                angle_deg: float) -> adsk.fusion.Profile:
    """I-beam / H-section (HEA/HEB style) — 12-vertex closed polygon."""
    raw = [
        adsk.core.Point3D.create(-w/2,   h/2,       0),
        adsk.core.Point3D.create( w/2,   h/2,       0),
        adsk.core.Point3D.create( w/2,   h/2 - tf,  0),
        adsk.core.Point3D.create( tw/2,  h/2 - tf,  0),
        adsk.core.Point3D.create( tw/2, -h/2 + tf,  0),
        adsk.core.Point3D.create( w/2,  -h/2 + tf,  0),
        adsk.core.Point3D.create( w/2,  -h/2,       0),
        adsk.core.Point3D.create(-w/2,  -h/2,       0),
        adsk.core.Point3D.create(-w/2,  -h/2 + tf,  0),
        adsk.core.Point3D.create(-tw/2, -h/2 + tf,  0),
        adsk.core.Point3D.create(-tw/2,  h/2 - tf,  0),
        adsk.core.Point3D.create(-w/2,   h/2 - tf,  0),
    ]
    _draw_closed_polygon(sketch, _rotate(raw, angle_deg))
    return sketch.profiles.item(sketch.profiles.count - 1)


def _draw_channel(sketch: adsk.fusion.Sketch,
                  h: float, w: float, tf: float, tw: float,
                  angle_deg: float) -> adsk.fusion.Profile:
    """C-channel / UPN — 8-vertex closed polygon."""
    raw = [
        adsk.core.Point3D.create(-tw/2,      h/2,       0),
        adsk.core.Point3D.create(w - tw/2,   h/2,       0),
        adsk.core.Point3D.create(w - tw/2,   h/2 - tf,  0),
        adsk.core.Point3D.create( tw/2,      h/2 - tf,  0),
        adsk.core.Point3D.create( tw/2,     -h/2 + tf,  0),
        adsk.core.Point3D.create(w - tw/2,  -h/2 + tf,  0),
        adsk.core.Point3D.create(w - tw/2,  -h/2,       0),
        adsk.core.Point3D.create(-tw/2,     -h/2,       0),
    ]
    _draw_closed_polygon(sketch, _rotate(raw, angle_deg))
    return sketch.profiles.item(sketch.profiles.count - 1)


# ── Public factory ────────────────────────────────────────────────────────────

class ProfileFactory:
    @staticmethod
    def draw(sketch: adsk.fusion.Sketch,
             profile_type: str,
             angle_deg: float = 0.0,
             width:  Optional[float] = None,
             height: Optional[float] = None,
             wall:   Optional[float] = None) -> adsk.fusion.Profile:
        """Draws the cross-section profile into sketch and returns the Fusion Profile.

        Args:
            sketch:       The target Fusion sketch (on a perpendicular construction plane).
            profile_type: Display name from the UI dropdown.
            angle_deg:    Rotation around the sweep axis in degrees (default 0).
            width:        Override for cross-section width (cm). Uses config default if None.
            height:       Override for cross-section height (cm). Uses config default if None.
            wall:         Override for wall thickness (cm) — hollow/tube only.

        The method first checks the standard profile library, then falls back to the
        four built-in parametric types, and finally tries the .f3d custom import path.
        """

        # ── 1. Standard library lookup ────────────────────────────────────────
        std_params = get_profile_params(profile_type)
        if std_params:
            ptype = str(std_params["type"])
            if ptype == "solid":
                w = width  or _fget(std_params, "w", config.DEFAULT_HALF_SIZE * 2)
                h = height or _fget(std_params, "h", w)
                return _draw_solid(sketch, w, h, angle_deg)

            elif ptype == "hollow":
                w  = width  or _fget(std_params, "w",    config.DEFAULT_HALF_SIZE * 2)
                h  = height or _fget(std_params, "h",    w)
                wl = wall   or _fget(std_params, "wall", config.DEFAULT_WALL)
                return _draw_hollow(sketch, w, h, wl, angle_deg)

            elif ptype == "ibeam":
                return _draw_ibeam(
                    sketch,
                    h  = height or _fget(std_params, "h",  config.IBEAM_H),
                    w  = width  or _fget(std_params, "w",  config.IBEAM_W),
                    tf = _fget(std_params, "tf", config.IBEAM_TF),
                    tw = _fget(std_params, "tw", config.IBEAM_TW),
                    angle_deg=angle_deg,
                )
            elif ptype == "channel":
                return _draw_channel(
                    sketch,
                    h  = height or _fget(std_params, "h",  config.CCHANNEL_H),
                    w  = width  or _fget(std_params, "w",  config.CCHANNEL_W),
                    tf = _fget(std_params, "tf", config.CCHANNEL_TF),
                    tw = _fget(std_params, "tw", config.CCHANNEL_TW),
                    angle_deg=angle_deg,
                )
            elif ptype == "round_solid":
                d = width or _fget(std_params, "d", config.DEFAULT_ROUND_DIAMETER)
                return _draw_round_solid(sketch, d, angle_deg)

            elif ptype == "round_hollow":
                d  = width or _fget(std_params, "d",    config.DEFAULT_ROUND_DIAMETER)
                wl = wall  or _fget(std_params, "wall", config.DEFAULT_ROUND_WALL)
                return _draw_round_hollow(sketch, d, wl, angle_deg)

            elif ptype == "langle":
                return _draw_langle(
                    sketch,
                    h  = height or _fget(std_params, "h",  config.LANGLE_H),
                    w  = width  or _fget(std_params, "w",  config.LANGLE_W),
                    th = wall   or _fget(std_params, "th", config.LANGLE_TH),
                    angle_deg=angle_deg,
                )
            elif ptype == "aluminum":
                sz = width or _fget(std_params, "size", config.ALUMINUM_SIZE)
                wl = wall  or _fget(std_params, "wall", config.ALUMINUM_WALL)
                return _draw_aluminum_tslot(sketch, sz, wl, angle_deg)

        # ── 2. Built-in parametric types ──────────────────────────────────────
        if profile_type == config.PROFILE_SOLID:
            w = width  or config.DEFAULT_HALF_SIZE * 2
            h = height or w
            return _draw_solid(sketch, w, h, angle_deg)

        elif profile_type == config.PROFILE_HOLLOW:
            w  = width  or config.DEFAULT_HALF_SIZE * 2
            h  = height or w
            wl = wall   or config.DEFAULT_WALL
            return _draw_hollow(sketch, w, h, wl, angle_deg)

        elif profile_type == config.PROFILE_IBEAM:
            return _draw_ibeam(
                sketch,
                h  = height or config.IBEAM_H,
                w  = width  or config.IBEAM_W,
                tf = config.IBEAM_TF,
                tw = config.IBEAM_TW,
                angle_deg=angle_deg,
            )

        elif profile_type == config.PROFILE_CCHANNEL:
            return _draw_channel(
                sketch,
                h  = height or config.CCHANNEL_H,
                w  = width  or config.CCHANNEL_W,
                tf = config.CCHANNEL_TF,
                tw = config.CCHANNEL_TW,
                angle_deg=angle_deg,
            )

        elif profile_type == config.PROFILE_ROUND_SOLID:
            d = width or config.DEFAULT_ROUND_DIAMETER
            return _draw_round_solid(sketch, d, angle_deg)

        elif profile_type == config.PROFILE_ROUND_HOLLOW:
            d  = width or config.DEFAULT_ROUND_DIAMETER
            wl = wall  or config.DEFAULT_ROUND_WALL
            return _draw_round_hollow(sketch, d, wl, angle_deg)

        elif profile_type == config.PROFILE_LANGLE:
            return _draw_langle(
                sketch,
                h  = height or config.LANGLE_H,
                w  = width  or config.LANGLE_W,
                th = wall   or config.LANGLE_TH,
                angle_deg=angle_deg,
            )

        elif profile_type == config.PROFILE_ALUMINUM:
            sz = width or config.ALUMINUM_SIZE
            wl = wall  or config.ALUMINUM_WALL
            return _draw_aluminum_tslot(sketch, sz, wl, angle_deg)

        # ── 3. Custom .f3d import fallback ────────────────────────────────────
        app    = adsk.core.Application.get()
        design = get_active_design()
        if not design:
            raise RuntimeError("No active design.")
        root_comp: adsk.fusion.Component = design.rootComponent

        file_path = get_resource_path(os.path.join('profiles', f"{profile_type}.f3d"))
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Unknown profile '{profile_type}' — "
                                    f"no matching standard, built-in type, or .f3d archive found.")

        import_mgr: adsk.core.ImportManager = app.importManager
        import_options = (  # type: ignore[assignment]
            import_mgr.createFusionImportOptions(file_path)  # type: ignore[attr-defined]
        )
        temp_occurrence = cast(
            adsk.fusion.Occurrence,
            root_comp.occurrences.addByImportedComponent(  # type: ignore[attr-defined]
                import_options, adsk.core.Matrix3D.create()
            )
        )

        template_sketch = cast(
            adsk.fusion.Sketch,
            temp_occurrence.component.sketches.itemByName("Profile")  # type: ignore[union-attr]
        )
        if not template_sketch or template_sketch.profiles.count == 0:
            temp_occurrence.deleteMe()
            raise ValueError("Custom .f3d archive has no sketch named 'Profile'.")

        entities: adsk.core.ObjectCollection = adsk.core.ObjectCollection.create()
        for curve in template_sketch.sketchCurves:
            entities.add(curve)

        sketch.project(entities)  # type: ignore[attr-defined]
        temp_occurrence.deleteMe()
        return sketch.profiles.item(sketch.profiles.count - 1)