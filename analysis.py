"""analysis.py — Structural analysis for SmartFrameGenerator.

Designed for student projects.  Computes per-member:
  • Cross-section area, moment of inertia (Ix, Iy)
  • Mass, weight
  • Max deflection under self-weight + UDL + point load (simply-supported)
  • Bending stress, axial stress, combined stress vs yield
  • Euler buckling check for columns (pinned-pinned)
  • Frame-level column load accumulation from supported beams
  • Pass / Fail summary against yield strength and L/180 deflection limit

All inputs are in Fusion 360 internal units (cm).  Outputs are in
human-friendly SI units (mm, kg, N, MPa where applicable).

DISCLAIMER shown in output:
  This is a simplified first-order analysis for educational purposes.
  It does not account for connection fixity, lateral-torsional buckling,
  combined load factors, dynamic effects, or code safety factors.
  Always consult a qualified engineer for load-bearing structures.
"""

import math
import csv
import os
import datetime
from typing import List, Optional

import adsk.core

import config
from member import FrameMember


# ── Logging helper ─────────────────────────────────────────────────────────────

def _log(message: str) -> None:
    app = adsk.core.Application.get()
    palette = app.userInterface.palettes.itemById('TextCommands')
    if palette:
        palette.writeText(f"[Analysis] {message}")


# ── Section properties (all units: cm) ────────────────────────────────────────

def _section_props(profile_type: str,
                   width:  Optional[float],
                   height: Optional[float],
                   wall:   Optional[float]) -> dict:
    """Return cross-section geometric properties for a given profile.

    Returns a dict with:
      area  (cm²)   — cross-section area
      Ix    (cm⁴)   — second moment of area about the strong axis
      Iy    (cm⁴)   — second moment of area about the weak axis
      y_max (cm)    — distance from neutral axis to extreme fibre
      label (str)   — human-readable description
    """
    # ── resolve defaults ──────────────────────────────────────────────────────
    w  = width  or config.DEFAULT_HALF_SIZE * 2
    h  = height or w
    wl = wall   or config.DEFAULT_WALL

    pt = profile_type

    # ── Square / rectangular solid ────────────────────────────────────────────
    if pt == config.PROFILE_SOLID:
        area = w * h
        Ix   = w * h**3 / 12.0
        Iy   = h * w**3 / 12.0
        return {"area": area, "Ix": Ix, "Iy": Iy, "y_max": h / 2.0,
                "label": f"Solid {w*10:.0f}\u00d7{h*10:.0f} mm"}

    # ── Square / rectangular hollow ──────────────────────────────────────────
    if pt == config.PROFILE_HOLLOW:
        wi, hi = w - 2*wl, h - 2*wl
        wi, hi = max(wi, 0.0), max(hi, 0.0)
        area = w * h - wi * hi
        Ix   = (w * h**3 - wi * hi**3) / 12.0
        Iy   = (h * w**3 - hi * wi**3) / 12.0
        return {"area": area, "Ix": Ix, "Iy": Iy, "y_max": h / 2.0,
                "label": f"SHS {w*10:.0f}\u00d7{h*10:.0f}\u00d7{wl*10:.0f} mm"}

    # ── Round solid bar ──────────────────────────────────────────────────────
    if pt == config.PROFILE_ROUND_SOLID:
        r    = w / 2.0
        area = math.pi * r**2
        I    = math.pi * r**4 / 4.0
        return {"area": area, "Ix": I, "Iy": I, "y_max": r,
                "label": f"Round Bar \u2300{w*10:.0f} mm"}

    # ── Round hollow tube (CHS) ──────────────────────────────────────────────
    if pt == config.PROFILE_ROUND_HOLLOW:
        r_o  = w / 2.0
        r_i  = max(r_o - wl, 0.0)
        area = math.pi * (r_o**2 - r_i**2)
        I    = math.pi * (r_o**4 - r_i**4) / 4.0
        return {"area": area, "Ix": I, "Iy": I, "y_max": r_o,
                "label": f"CHS \u2300{w*10:.0f}\u00d7{wl*10:.0f} mm"}

    # ── L-angle bar ──────────────────────────────────────────────────────────
    if pt == config.PROFILE_LANGLE:
        th = wl   # wall parameter used as leg thickness
        # Two rectangles: vertical leg h×th, horizontal leg th×(w-th)
        a1 = h * th
        a2 = (w - th) * th
        area = a1 + a2
        # Ix about centroid (parallel axis theorem)
        y1 = h / 2.0
        y2 = th / 2.0
        y_c = (a1 * y1 + a2 * y2) / area if area > 0 else 0.0
        I1  = th * h**3 / 12.0 + a1 * (y1 - y_c)**2
        I2  = (w - th) * th**3 / 12.0 + a2 * (y2 - y_c)**2
        Ix  = I1 + I2
        Iy  = Ix  # approximate for equal-leg angle
        y_max = max(abs(y_c), abs(h - y_c))
        return {"area": area, "Ix": Ix, "Iy": Iy, "y_max": y_max,
                "label": f"L {h*10:.0f}\u00d7{w*10:.0f}\u00d7{th*10:.0f} mm"}

    # ── Aluminium T-slot extrusion (approximated as SHS with t=wall) ─────────
    if pt == config.PROFILE_ALUMINUM:
        # Use the declared wall as structural wall thickness.
        # T-slot voids reduce area ≈ 20 % — apply correction factor.
        wi  = w - 2 * wl
        hi  = w - 2 * wl  # square extrusion
        area_shs = w * w - wi * hi
        area = area_shs * 0.80   # ~20 % void correction for T-slots
        Ix   = (w * w**3 - wi * hi**3) / 12.0 * 0.80
        Iy   = Ix
        return {"area": area, "Ix": Ix, "Iy": Iy, "y_max": w / 2.0,
                "label": f"AL {w*10:.0f}\u00d7{w*10:.0f} mm (T-slot)"}

    # ── I-beam ────────────────────────────────────────────────────────────────
    if pt == config.PROFILE_IBEAM:
        tf = config.IBEAM_TF
        tw = config.IBEAM_TW
        h_use = height or config.IBEAM_H
        w_use = width  or config.IBEAM_W
        web_h = h_use - 2 * tf
        area  = 2 * (w_use * tf) + web_h * tw
        Ix    = (w_use * h_use**3 - (w_use - tw) * web_h**3) / 12.0
        Iy    = (2 * tf * w_use**3 + web_h * tw**3) / 12.0
        return {"area": area, "Ix": Ix, "Iy": Iy, "y_max": h_use / 2.0,
                "label": f"I-Beam {h_use*10:.0f}\u00d7{w_use*10:.0f} mm"}

    # ── C-channel ────────────────────────────────────────────────────────────
    if pt == config.PROFILE_CCHANNEL:
        tf   = config.CCHANNEL_TF
        tw   = config.CCHANNEL_TW
        h_use = height or config.CCHANNEL_H
        w_use = width  or config.CCHANNEL_W
        web_h = h_use - 2 * tf
        area  = 2 * (w_use * tf) + web_h * tw
        Ix    = (w_use * h_use**3 - (w_use - tw) * web_h**3) / 12.0
        Iy    = (tf * w_use**3 / 12.0) * 2 + (web_h * tw**3 / 12.0)
        return {"area": area, "Ix": Ix, "Iy": Iy, "y_max": h_use / 2.0,
                "label": f"C-Channel {h_use*10:.0f}\u00d7{w_use*10:.0f} mm"}

    # ── Fallback: treat as solid bar ──────────────────────────────────────────
    area = w * h
    Ix   = w * h**3 / 12.0
    Iy   = h * w**3 / 12.0
    return {"area": area, "Ix": Ix, "Iy": Iy, "y_max": h / 2.0, "label": profile_type}


# ═══════════════════════════════════════════════════════════════════════════════
#  LOAD & STRESS CALCULATIONS
# ═══════════════════════════════════════════════════════════════════════════════

def _self_weight_per_cm(area_cm2: float, density_gcm3: float) -> float:
    """Self-weight line load in N/cm."""
    return density_gcm3 * area_cm2 * config.GRAVITY / 1000.0


def _total_udl_per_cm(area_cm2: float, density_gcm3: float,
                       udl_nm: float) -> float:
    """Total uniform distributed line load (self-weight + applied UDL) in N/cm."""
    sw = _self_weight_per_cm(area_cm2, density_gcm3)
    return sw + udl_nm / 100.0


def _deflection_udl(w_ncm: float, L_cm: float, E_Ncm2: float, I_cm4: float) -> float:
    """Max mid-span deflection (cm) from UDL on simply-supported beam.
    \u03b4 = 5 w L\u2074 / (384 E I)
    """
    if I_cm4 < 1e-10 or E_Ncm2 < 1e-6 or L_cm < 1e-6:
        return 0.0
    return 5.0 * w_ncm * L_cm**4 / (384.0 * E_Ncm2 * I_cm4)


def _deflection_point_load(P_N: float, L_cm: float, a_frac: float,
                            E_Ncm2: float, I_cm4: float) -> float:
    """Max deflection (cm) from point load at fraction a_frac of span.

    For simply-supported beam, max deflection under the load:
      \u03b4 = P \u00b7 a \u00b7 b \u00b7 (L\u00b2 - a\u00b2 - b\u00b2) / (6 E I L)
    If at mid-span (a_frac \u2248 0.5): \u03b4 = P L\u00b3 / (48 E I)
    """
    if I_cm4 < 1e-10 or E_Ncm2 < 1e-6 or L_cm < 1e-6 or P_N < 1e-6:
        return 0.0
    a = a_frac * L_cm
    b = L_cm - a
    if a < 1e-6 or b < 1e-6:
        return 0.0
    return P_N * a * b * (L_cm**2 - a**2 - b**2) / (6.0 * E_Ncm2 * I_cm4 * L_cm)


def _max_moment_udl(w_ncm: float, L_cm: float) -> float:
    """Max bending moment (N\u00b7cm) from UDL on simply-supported beam. M = wL\u00b2/8"""
    return w_ncm * L_cm**2 / 8.0


def _max_moment_point_load(P_N: float, L_cm: float, a_frac: float) -> float:
    """Max bending moment (N\u00b7cm) from point load at a_frac of span. M = Pab/L"""
    a = a_frac * L_cm
    b = L_cm - a
    return P_N * a * b / L_cm


def _bending_stress(M_Ncm: float, y_max_cm: float, I_cm4: float) -> float:
    """Bending stress (N/cm\u00b2). \u03c3 = M\u00b7y/I"""
    if I_cm4 < 1e-10:
        return 0.0
    return M_Ncm * y_max_cm / I_cm4


def _euler_buckling_load(E_Ncm2: float, I_min_cm4: float,
                          L_cm: float, K: float = 1.0) -> float:
    """Euler critical buckling load (N). P_cr = \u03c0\u00b2EI/(KL)\u00b2. K=1.0 for pinned-pinned."""
    if L_cm < 1e-6 or I_min_cm4 < 1e-10:
        return float('inf')
    return math.pi**2 * E_Ncm2 * I_min_cm4 / (K * L_cm)**2


# ═══════════════════════════════════════════════════════════════════════════════
#  FRAME-LEVEL ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════════

def _accumulate_column_loads(members: List[FrameMember],
                              area_cm2: float, density_gcm3: float,
                              udl_nm: float,
                              point_load_N: float,
                              point_member_idx: int) -> dict:
    """Estimate axial loads on columns from supported beams.

    For each joint where a beam connects to a column, half the beam's
    total load (self-weight + UDL + point load) is transferred as an
    axial reaction to the column.

    Returns dict: {member_index: total_axial_load_N}
    """
    from joints import JointDetector
    joints = JointDetector.find_joints(members)

    column_loads: dict = {}
    member_load: dict = {}
    w_sw = _self_weight_per_cm(area_cm2, density_gcm3)
    w_total = w_sw + udl_nm / 100.0

    for idx, m in enumerate(members):
        total = w_total * m.length
        if idx == point_member_idx and point_load_N > 0:
            total += point_load_N
        member_load[idx] = total

    for joint in joints:
        mA_idx = joint.member_a.selection_index
        mB_idx = joint.member_b.selection_index
        mA = joint.member_a
        mB = joint.member_b

        if mA.orientation == "VERTICAL" and mB.orientation != "VERTICAL":
            column_loads[mA_idx] = column_loads.get(mA_idx, 0.0) + member_load.get(mB_idx, 0.0) / 2.0
        elif mB.orientation == "VERTICAL" and mA.orientation != "VERTICAL":
            column_loads[mB_idx] = column_loads.get(mB_idx, 0.0) + member_load.get(mA_idx, 0.0) / 2.0

    return column_loads


# ═══════════════════════════════════════════════════════════════════════════════
#  PUBLIC ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def generate(members: List[FrameMember],
             profile_type:  str,
             material:      str,
             width:         Optional[float] = None,
             height:        Optional[float] = None,
             wall:          Optional[float] = None,
             udl_nm:        float = 0.0,
             point_load_n:  float = 0.0,
             safety_factor: float = 1.5,
             load_case:     str = "Self-weight only") -> None:
    """Run structural analysis and print/save results.

    Args:
        members:       Frame members created by the generate command.
        profile_type:  Display name of the cross-section profile.
        material:      "Steel" or "Aluminium".
        width/height/wall: Parametric dimensions (cm).
        udl_nm:        Uniform distributed load in N/m (applied to horizontals).
        point_load_n:  Point load in N (at mid-span of longest horizontal).
        safety_factor: Design safety factor applied to yield strength.
        load_case:     Name of the selected load case (for reporting).
    """
    if not members:
        _log("Analysis: no members to analyse.")
        return

    density   = (config.DENSITY_ALUMINUM if material == config.MATERIAL_ALUMINUM
                 else config.DENSITY_STEEL)
    E_mod     = (config.E_ALUMINUM if material == config.MATERIAL_ALUMINUM
                 else config.E_STEEL)
    yield_str = (config.YIELD_ALUMINUM if material == config.MATERIAL_ALUMINUM
                 else config.YIELD_STEEL)
    allowable = yield_str / safety_factor
    cost_per_kg = (config.COST_PER_KG_ALUMINUM if material == config.MATERIAL_ALUMINUM
                   else config.COST_PER_KG_STEEL)

    props    = _section_props(profile_type, width, height, wall)
    area_cm2 = props["area"]
    Ix_cm4   = props["Ix"]
    Iy_cm4   = props["Iy"]
    y_max    = props["y_max"]
    label    = props["label"]

    # ── Determine point load target: longest horizontal/diagonal at mid-span ──
    point_member_idx = -1
    longest_L = 0.0
    for idx, m in enumerate(members):
        if m.orientation in ("HORIZONTAL", "DIAGONAL") and m.length > longest_L:
            longest_L = m.length
            point_member_idx = idx

    # ── Frame-level column loads ────────────────────────────────────────────
    column_axial = _accumulate_column_loads(
        members, area_cm2, density, udl_nm, point_load_n, point_member_idx
    )

    rows: list = []
    total_weight_N = 0.0
    passes = 0
    fails  = 0

    for idx, m in enumerate(members, start=1):
        L_cm     = m.length
        vol_cm3  = area_cm2 * L_cm
        mass_kg  = vol_cm3 * density / 1000.0
        weight_N = mass_kg * 9.81
        total_weight_N += weight_N

        # ── Loads ──────────────────────────────────────────────────────────
        w_total_ncm = _total_udl_per_cm(area_cm2, density, udl_nm)
        has_point = (idx - 1 == point_member_idx and point_load_n > 0)
        P_N = point_load_n if has_point else 0.0
        a_frac = 0.5

        # ── Deflection ─────────────────────────────────────────────────────
        if m.orientation in ("HORIZONTAL", "DIAGONAL"):
            delta_total_cm = (_deflection_udl(w_total_ncm, L_cm, E_mod, Ix_cm4) +
                              _deflection_point_load(P_N, L_cm, a_frac, E_mod, Ix_cm4))
            delta_mm = delta_total_cm * 10.0
            span_defl = (L_cm / delta_total_cm) if delta_total_cm > 1e-9 else float('inf')
            defl_ok = span_defl >= config.DEFL_LIMIT_PRIMARY
        else:
            delta_mm = 0.0
            span_defl = float('inf')
            defl_ok = True

        # ── Bending moment & stress ────────────────────────────────────────
        if m.orientation in ("HORIZONTAL", "DIAGONAL"):
            M_udl = _max_moment_udl(w_total_ncm, L_cm)
            M_pt  = _max_moment_point_load(P_N, L_cm, a_frac) if has_point else 0.0
            M_max = M_udl + M_pt
            sigma_bend = _bending_stress(M_max, y_max, Ix_cm4)
        else:
            M_max = 0.0
            sigma_bend = 0.0

        # ── Axial stress (columns get beam reactions) ──────────────────────
        axial_N = column_axial.get(idx - 1, 0.0) + weight_N
        sigma_axial = axial_N / area_cm2 if area_cm2 > 1e-10 else 0.0

        # ── Combined stress ────────────────────────────────────────────────
        sigma_combined = sigma_axial + sigma_bend
        stress_ok = sigma_combined <= allowable

        # ── Buckling (columns only) ────────────────────────────────────────
        if m.orientation == "VERTICAL":
            I_min = min(Ix_cm4, Iy_cm4)
            P_cr  = _euler_buckling_load(E_mod, I_min, L_cm, K=1.0)
            buckling_ratio = axial_N / P_cr if P_cr > 1e-6 else 0.0
            buckling_ok = buckling_ratio < 1.0
        else:
            P_cr = float('inf')
            buckling_ratio = 0.0
            buckling_ok = True

        # ── Utilization % ─────────────────────────────────────────────────
        stress_util  = (sigma_combined / allowable * 100.0) if allowable > 0 else 0.0
        defl_limit_cm = L_cm / config.DEFL_LIMIT_PRIMARY if m.orientation in ("HORIZONTAL", "DIAGONAL") else float('inf')
        defl_util     = (delta_total_cm / defl_limit_cm * 100.0) if defl_limit_cm > 1e-9 and delta_total_cm > 0 else 0.0
        buckl_util    = buckling_ratio * 100.0 if m.orientation == "VERTICAL" else 0.0

        governing_util = max(stress_util, defl_util, buckl_util)
        util_bar = (
            "\U0001f7e2" if governing_util < 70 else   # green
            "\U0001f7e1" if governing_util < 90 else   # yellow
            "\U0001f534"                                 # red
        )

        # ── Cost ──────────────────────────────────────────────────────────
        cost_rm = round(mass_kg * cost_per_kg, 2)

        # ── Pass / Fail ────────────────────────────────────────────────────
        member_ok = defl_ok and stress_ok and buckling_ok
        if member_ok:
            passes += 1
        else:
            fails += 1

        comp_name = m.component.name if m.component else f"Member_{idx}"

        failures = []
        if not defl_ok:
            failures.append(f"Defl L/{span_defl:.0f} < L/{config.DEFL_LIMIT_PRIMARY:.0f}")
        if not stress_ok:
            fail_mpa = sigma_combined / 100.0
            allow_mpa = allowable / 100.0
            failures.append(f"Stress {fail_mpa:.1f} > {allow_mpa:.1f} MPa")
        if not buckling_ok:
            failures.append(f"Buckling {buckling_ratio:.2f} > 1.0")

        rows.append({
            "No.":              idx,
            "Component":        comp_name,
            "Profile":          label,
            "Material":         material,
            "Orientation":      m.orientation,
            "Length (mm)":      round(L_cm * 10.0, 1),
            "Area (cm\u00b2)":   round(area_cm2, 3),
            "Ix (cm\u2074)":     round(Ix_cm4, 4),
            "Mass (kg)":        round(mass_kg, 3),
            "Cost (RM)":        cost_rm,
            "Axial Load (N)":   round(axial_N, 1),
            "Max Moment (N\u00b7m)": round(M_max / 100.0, 2),
            "Bend Stress (MPa)": round(sigma_bend / 100.0, 2),
            "Comb Stress (MPa)": round(sigma_combined / 100.0, 2),
            "Allow Stress (MPa)": round(allowable / 100.0, 1),
            "Util %":           f"{governing_util:.0f}% {util_bar}",
            "Max Defl (mm)":    round(delta_mm, 2) if delta_mm > 0 else "\u2014",
            "L/\u03b4":         f"L/{span_defl:.0f}" if span_defl < 1e6 else "\u2014",
            "Buckling Ratio":   f"{buckling_ratio:.3f}" if m.orientation == "VERTICAL" else "\u2014",
            "Status":           "\u2705 PASS" if member_ok else f"\u274c FAIL: {'; '.join(failures)}",
        })

    # ── Totals ────────────────────────────────────────────────────────────────
    total_mass = sum(r["Mass (kg)"] for r in rows)
    total_cost = round(sum(r["Cost (RM)"] for r in rows), 2)

    # ═══════════════════════════════════════════════════════════════════════════
    #  TEXT COMMANDS OUTPUT
    # ═══════════════════════════════════════════════════════════════════════════
    _log("=" * 88)
    _log("  STRUCTURAL ANALYSIS REPORT")
    _log(f"  Profile   : {label}")
    _log(f"  Material  : {material}  |  \u03c1 = {density} g/cm\u00b3"
         f"  |  E = {E_mod/1e6:.0f} GPa"
         f"  |  \u03c3_y = {yield_str/100:.0f} MPa")
    _log(f"  Section   : A = {area_cm2:.3f} cm\u00b2"
         f"  Ix = {Ix_cm4:.4f} cm\u2074"
         f"  Iy = {Iy_cm4:.4f} cm\u2074"
         f"  y_max = {y_max:.2f} cm")
    _log(f"  Load Case : {load_case}")
    _log(f"  Cost/kg   : RM {cost_per_kg:.2f}")
    _log(f"  Safety Factor : {safety_factor}")
    if udl_nm > 0:
        _log(f"  Applied UDL    : {udl_nm:.1f} N/m  ({udl_nm/9.81:.2f} kg/m)")
    if point_load_n > 0 and point_member_idx >= 0:
        _log(f"  Point Load     : {point_load_n:.1f} N  at mid-span of "
             f"'{members[point_member_idx].component.name}'")
    if column_axial:
        _log(f"  Frame columns  : {len(column_axial)} column(s) with accumulated beam loads")
    _log("-" * 88)

    _log(f"  {'#':<3} {'Component':<18} {'Orient':<7} {'L mm':>7}"
         f" {'Mass kg':>7} {'Cost RM':>8} {'Util':>7}"
         f" {'\u03c3 MPa':>7} {'Defl mm':>8} {'L/\u03b4':>7}"
         f" {'Buckl':>6} {'Status'}")
    _log("  " + "-" * 86)

    for r in rows:
        _log(
            f"  {r['No.']:<3} {r['Component']:<18} {r['Orientation']:<7}"
            f" {r['Length (mm)']:>7.0f} {r['Mass (kg)']:>7.3f}"
            f" {r['Cost (RM)']:>8.2f} {str(r['Util %']):>7}"
            f" {str(r['Comb Stress (MPa)']):>7} {str(r['Max Defl (mm)']):>8}"
            f" {str(r['L/\u03b4']):>7} {str(r['Buckling Ratio']):>6} {r['Status']}"
        )

    _log("-" * 88)
    _log(f"  Total members   : {len(rows)}")
    _log(f"  Total mass      : {total_mass:.3f} kg")
    _log(f"  Total cost      : RM {total_cost:.2f}")
    _log(f"  Total weight    : {total_weight_N:.2f} N  ({total_weight_N/9.81:.2f} kg)")
    _log(f"  Allowable stress: {allowable/100:.1f} MPa  "
         f"(\u03c3_y/SF = {yield_str/100:.0f}/{safety_factor})")
    _log(f"  Utilization     : \U0001f7e2 <70%  \U0001f7e1 70-90%  \U0001f534 >90%")
    _log(f"  Result          : {passes} PASS  /  {fails} FAIL")
    if fails > 0:
        _log("")
        _log("  \u26a0  SOME MEMBERS FAILED \u2014 consider:")
        _log("     \u2022 Larger profile or thicker wall")
        _log("     \u2022 Shorter spans / additional columns")
        _log("     \u2022 Higher-grade material")
    _log("")
    _log("  \u26a0  EDUCATIONAL USE ONLY \u2014 simply-supported, first-order elastic.")
    _log("     Does not include: connection fixity, lateral-torsional buckling,")
    _log("     combined load factors, dynamic effects, or code safety factors.")
    _log("     Consult a qualified structural engineer for load-bearing design.")
    _log("=" * 88)

    # ── CSV output ────────────────────────────────────────────────────────────
    try:
        addon_dir   = os.path.dirname(os.path.abspath(__file__))
        reports_dir = os.path.join(addon_dir, config.REPORTS_DIR)
        os.makedirs(reports_dir, exist_ok=True)
        ts       = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path = os.path.join(reports_dir, f"analysis_{ts}.csv")
        fields   = list(rows[0].keys())
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        _log(f"  Report saved \u2192 {csv_path}")
    except Exception as ex:
        _log(f"  (CSV save failed: {ex})")
