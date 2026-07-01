"""miter.py — Miter cut handler for CORNER joints.

For each CORNER joint (two members sharing an exact endpoint), this module
creates a miter-cutting plane at the shared vertex and trims both members so
their end faces are flush and co-planar.

Correct miter plane derivation
─────────────────────────────
A proper miter plane is the set of points equidistant from BOTH member axes:

    (P − shared_pt) · dir_A  =  (P − shared_pt) · dir_B
    ⟺  (P − shared_pt) · (dir_A − dir_B)  =  0

So the miter plane normal  =  normalize(dir_A − dir_B).

For a 90° L-corner (dir_A = +X, dir_B = +Y):
  normal = normalize(1,−1,0)  →  plane  x = y  (the classic 45° miter) ✓

Cut direction per member
────────────────────────
Both members extend AWAY from shared_pt.  For each member we determine
which side of the plane its body is on (using the dot product of its
far-end against the plane normal), then cut the OPPOSITE side — removing
the wedge where the other member's axis dominates.

  far_end on + side  →  cut NEGATIVE direction
  far_end on − side  →  cut POSITIVE direction

This guarantees the two cut faces are exactly co-planar and fill the
corner without gap or overlap for any cross-section shape.

Previous bug
────────────
The plane normal was normalize(dir_A + dir_B) — the "open-corner bisector"
pointing into empty space — and BOTH members were cut in the same direction.
This produced mismatched, asymmetric cuts instead of a proper miter.
"""

import traceback
from typing import List

import adsk.core
import adsk.fusion

import config
from joints import Joint
from geometry import GeometryUtils


def _log(message: str) -> None:
    app = adsk.core.Application.get()
    palette = app.userInterface.palettes.itemById('TextCommands')
    if palette:
        palette.writeText(f"[SmartFrameGenerator] {message}")


def _normalize(v: adsk.core.Vector3D) -> adsk.core.Vector3D:
    length = v.length
    if length < config.TOLERANCE:
        return v
    return adsk.core.Vector3D.create(v.x / length, v.y / length, v.z / length)


def _subtract_vectors(a: adsk.core.Vector3D,
                      b: adsk.core.Vector3D) -> adsk.core.Vector3D:
    return adsk.core.Vector3D.create(a.x - b.x, a.y - b.y, a.z - b.z)


def _make_miter_plane(root_comp: adsk.fusion.Component,
                      shared_pt: adsk.core.Point3D,
                      plane_normal: adsk.core.Vector3D) -> adsk.fusion.ConstructionPlane:
    """Creates a construction plane at shared_pt with the given normal.

    Uses setByThreePoints with three Point3D objects (Fusion API accepts these
    directly).  The three points are derived from two vectors perpendicular to
    plane_normal so that (pt2−pt1)×(pt3−pt1) = plane_normal (right-hand rule).
    """
    # Pick a reference vector not parallel to plane_normal
    ref = adsk.core.Vector3D.create(0.0, 0.0, 1.0)
    if abs(plane_normal.dotProduct(ref)) > 0.9:
        ref = adsk.core.Vector3D.create(1.0, 0.0, 0.0)

    perp1 = plane_normal.crossProduct(ref)
    perp1.normalize()

    perp2 = plane_normal.crossProduct(perp1)
    perp2.normalize()

    # Three points on the plane (unit offsets for numerical stability)
    pt1 = adsk.core.Point3D.create(shared_pt.x,            shared_pt.y,            shared_pt.z)
    pt2 = adsk.core.Point3D.create(shared_pt.x + perp1.x,  shared_pt.y + perp1.y,  shared_pt.z + perp1.z)
    pt3 = adsk.core.Point3D.create(shared_pt.x + perp2.x,  shared_pt.y + perp2.y,  shared_pt.z + perp2.z)

    planes      = root_comp.constructionPlanes
    plane_input = planes.createInput()
    plane_input.setByThreePoints(pt1, pt2, pt3)  # type: ignore[attr-defined]
    return planes.add(plane_input)


class MiterCutter:
    @staticmethod
    def execute(root_comp: adsk.fusion.Component, joints: List[Joint]) -> None:
        """Applies miter cuts to all CORNER joints."""
        corner_joints = [j for j in joints if j.joint_type == 'CORNER']
        if not corner_joints:
            return

        _log(f"Applying miter cuts to {len(corner_joints)} CORNER joint(s)…")
        succeeded = 0
        failed    = 0

        for joint in corner_joints:
            try:
                mA = joint.member_a
                mB = joint.member_b

                # Shared endpoint
                shared_pt = GeometryUtils.get_shared_endpoint(
                    mA.start, mA.end, mB.start, mB.end
                )
                if shared_pt is None:
                    _log(f"  ⚠ No shared endpoint for '{mA.component.name}' / "
                         f"'{mB.component.name}' — skipping.")
                    continue

                # Unit vectors pointing AWAY from shared_pt for each member
                far_a = mA.end if mA.start.distanceTo(shared_pt) < config.TOLERANCE else mA.start
                far_b = mB.end if mB.start.distanceTo(shared_pt) < config.TOLERANCE else mB.start

                dir_a = _normalize(GeometryUtils.get_vector(shared_pt, far_a))
                dir_b = _normalize(GeometryUtils.get_vector(shared_pt, far_b))

                # Guard: skip nearly-parallel members (no meaningful miter possible)
                cos_angle = dir_a.dotProduct(dir_b)
                if abs(cos_angle) > 0.99:
                    _log(f"  ⚠ Members nearly parallel (cos={cos_angle:.3f}) — "
                         f"miter skipped for '{mA.component.name}'.")
                    continue

                # ── Miter plane normal = normalize(dir_A − dir_B) ─────────────────
                # This is the normal of the plane equidistant from both member axes.
                # For 90°: (1,0,0)−(0,1,0) → normal ∝ (1,−1,0) → plane x = y  ✓
                miter_normal = _normalize(_subtract_vectors(dir_a, dir_b))

                # Build the miter plane at the shared point
                cut_plane = _make_miter_plane(root_comp, shared_pt, miter_normal)

                # Cut each member on the side belonging to the OTHER member
                for member, far_end in ((mA, far_a), (mB, far_b)):
                    MiterCutter._cut_member_at_plane(
                        root_comp, member, cut_plane,
                        shared_pt, miter_normal, far_end
                    )

                # Hide the construction plane
                cut_plane.isLightBulbOn = False
                succeeded += 1

            except Exception as ex:
                failed += 1
                _log(f"  ✗ Miter failed — '{joint.member_a.component.name}' / "
                     f"'{joint.member_b.component.name}': {ex}\n{traceback.format_exc()}")

        _log(f"Miter complete: {succeeded}/{len(corner_joints)} joints mitered."
             + (f"  ({failed} failed)" if failed else ""))

    @staticmethod
    def _cut_member_at_plane(
        root_comp:    adsk.fusion.Component,
        member,                                    # FrameMember
        cut_plane:    adsk.fusion.ConstructionPlane,
        shared_pt:    adsk.core.Point3D,
        miter_normal: adsk.core.Vector3D,
        far_end:      adsk.core.Point3D,
    ) -> None:
        """Removes the miter wedge from one member.

        The miter plane divides space into two halves:
          • The half where THIS member's axis dominates (keep this).
          • The half where the OTHER member's axis dominates (remove this).

        We determine which half the member's body is in by dotting its far_end
        direction against miter_normal, then cut the OPPOSITE half.

          far_end on + side  →  body in + half  →  cut NEGATIVE direction
          far_end on − side  →  body in − half  →  cut POSITIVE direction
        """
        # Which side is this member's body on?
        to_far = GeometryUtils.get_vector(shared_pt, far_end)
        dot = to_far.dotProduct(miter_normal)

        if dot > 0:
            # Member is on the POSITIVE side → cut the NEGATIVE side
            cut_dir = adsk.fusion.ExtentDirections.NegativeExtentDirection  # type: ignore[attr-defined]
        else:
            # Member is on the NEGATIVE side → cut the POSITIVE side
            cut_dir = adsk.fusion.ExtentDirections.PositiveExtentDirection  # type: ignore[attr-defined]

        # Create a sketch on the miter plane with an oversized rectangle
        sketch: adsk.fusion.Sketch = root_comp.sketches.add(cut_plane)
        half = 30.0  # cm — larger than any realistic cross-section
        p1   = adsk.core.Point3D.create(-half, -half, 0)
        p2   = adsk.core.Point3D.create( half,  half, 0)
        sketch.sketchCurves.sketchLines.addTwoPointRectangle(p1, p2)

        cut_profile = sketch.profiles.item(sketch.profiles.count - 1)

        extrudes  = root_comp.features.extrudeFeatures
        ext_input = extrudes.createInput(
            cut_profile,
            adsk.fusion.FeatureOperations.CutFeatureOperation  # type: ignore[arg-type]
        )

        cut_dist = adsk.core.ValueInput.createByReal(30.0)  # 30 cm depth
        ext_input.setOneSideExtent(
            adsk.fusion.DistanceExtentDefinition.create(cut_dist),  # type: ignore[arg-type]
            cut_dir
        )

        # Restrict cut to just this member's body
        bodies_to_cut = adsk.core.ObjectCollection.create()
        bodies_to_cut.add(member.body)
        ext_input.participantBodies = bodies_to_cut  # type: ignore[assignment]

        extrudes.add(ext_input)
