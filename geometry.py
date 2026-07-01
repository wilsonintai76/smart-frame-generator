import adsk.core
import math
import config


class GeometryUtils:
    @staticmethod
    def get_vector(start: adsk.core.Point3D, end: adsk.core.Point3D) -> adsk.core.Vector3D:
        return adsk.core.Vector3D.create(end.x - start.x, end.y - start.y, end.z - start.z)

    @staticmethod
    def classify_orientation(start: adsk.core.Point3D, end: adsk.core.Point3D) -> str:
        """Classifies a member as VERTICAL, HORIZONTAL, or DIAGONAL.

        VERTICAL  — Z-delta is the dominant axis.
        HORIZONTAL — X or Y delta dominates and Z delta is small.
        DIAGONAL  — No single axis dominates; the member is at a compound angle.
        The DIAGONAL_THRESHOLD in config controls how dominant the leading axis must be:
        if the second-largest delta is > DIAGONAL_THRESHOLD × the largest delta, it's DIAGONAL.
        """
        delta_x = abs(end.x - start.x)
        delta_y = abs(end.y - start.y)
        delta_z = abs(end.z - start.z)

        deltas = sorted([delta_x, delta_y, delta_z], reverse=True)
        dominant = deltas[0]
        second   = deltas[1]

        # Guard against zero-length lines
        if dominant < config.TOLERANCE:
            return "HORIZONTAL"

        # If the second-largest axis is more than DIAGONAL_THRESHOLD of the dominant,
        # the member is considered diagonal (no clear single-axis orientation).
        if second / dominant > config.DIAGONAL_THRESHOLD:
            return "DIAGONAL"

        return "VERTICAL" if (delta_z == dominant) else "HORIZONTAL"

    @staticmethod
    def get_shared_endpoint(s1: adsk.core.Point3D, e1: adsk.core.Point3D,
                            s2: adsk.core.Point3D, e2: adsk.core.Point3D) -> adsk.core.Point3D | None:
        if s1.distanceTo(s2) < config.TOLERANCE or s1.distanceTo(e2) < config.TOLERANCE:
            return s1
        if e1.distanceTo(s2) < config.TOLERANCE or e1.distanceTo(e2) < config.TOLERANCE:
            return e1
        return None

    @staticmethod
    def point_on_segment(pt: adsk.core.Point3D, start: adsk.core.Point3D, end: adsk.core.Point3D) -> bool:
        """Tests whether pt lies on the line segment [start, end].

        Bug #5 fix: cross-product magnitude is normalized by the segment length so that
        the collinearity tolerance is consistent regardless of member length.
        """
        line_vec = GeometryUtils.get_vector(start, end)
        pt_vec   = GeometryUtils.get_vector(start, pt)

        line_len = line_vec.length
        if line_len < config.TOLERANCE:
            return False

        cross_x = line_vec.y * pt_vec.z - line_vec.z * pt_vec.y
        cross_y = line_vec.z * pt_vec.x - line_vec.x * pt_vec.z
        cross_z = line_vec.x * pt_vec.y - line_vec.y * pt_vec.x

        # Normalize by line length so tolerance is in absolute distance units (cm)
        cross_magnitude_normalized = math.sqrt(cross_x**2 + cross_y**2 + cross_z**2) / line_len

        if cross_magnitude_normalized > config.TOLERANCE:
            return False

        dot_product = pt_vec.dotProduct(line_vec)
        return 0 <= dot_product <= (line_len * line_len)