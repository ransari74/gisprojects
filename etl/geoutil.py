"""Small geometry helpers shared by the generator.

Everything works in EPSG:4326 degrees but takes metre arguments, converting
with the local scale factor at the study area's latitude. Over a 25 km study
area that approximation is accurate to well under a metre, which is far below
the precision the synthetic data claims anyway.
"""

from __future__ import annotations

import math

import numpy as np
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry

from etl.config import CENTRE_LAT, CENTRE_LON, MAX_LAT, MAX_LON, MIN_LAT, MIN_LON

M_PER_DEG_LAT = 111_320.0
M_PER_DEG_LON = 111_320.0 * math.cos(math.radians(CENTRE_LAT))  # ~68,500 m at 52N


def m_to_lon(metres: float) -> float:
    return metres / M_PER_DEG_LON


def m_to_lat(metres: float) -> float:
    return metres / M_PER_DEG_LAT


def lon_to_m(deg: float) -> float:
    return deg * M_PER_DEG_LON


def lat_to_m(deg: float) -> float:
    return deg * M_PER_DEG_LAT


def dist_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    return math.hypot(lon_to_m(lon2 - lon1), lat_to_m(lat2 - lat1))


def dist_from_centre_m(lon: float, lat: float) -> float:
    return dist_m(CENTRE_LON, CENTRE_LAT, lon, lat)


# ---------------------------------------------------------------------------
# Terrain model
#
# Utrecht's real relief: reclaimed polder in the west sitting at or just below
# NAP (0 m), rising eastward onto the Utrechtse Heuvelrug -- an ice-pushed
# ridge that reaches roughly 45-50 m around Doorn/Zeist. Modelled as a smooth
# eastward ramp plus a few ridge crests and low-frequency noise.
# ---------------------------------------------------------------------------
RIDGE_START_LON = 5.16
RIDGE_END_LON = 5.30
RIDGE_MAX_M = 48.0


def elevation_at(lon: float | np.ndarray, lat: float | np.ndarray) -> float | np.ndarray:
    lon = np.asarray(lon, dtype=float)
    lat = np.asarray(lat, dtype=float)

    # Eastward ramp onto the ice-pushed ridge
    t = np.clip((lon - RIDGE_START_LON) / (RIDGE_END_LON - RIDGE_START_LON), 0.0, 1.0)
    ramp = RIDGE_MAX_M * t**1.7

    # Two ridge crests running roughly NNE-SSW
    crest1 = 9.0 * np.exp(-(((lon - 5.245) / 0.020) ** 2) - (((lat - 52.06) / 0.16) ** 2))
    crest2 = 6.0 * np.exp(-(((lon - 5.285) / 0.016) ** 2) - (((lat - 52.12) / 0.14) ** 2))

    # Polder depressions in the west, some genuinely below sea level
    polder = -2.2 * np.exp(-(((lon - 5.00) / 0.055) ** 2) - (((lat - 52.06) / 0.10) ** 2))

    # River corridors (Kromme Rijn / Amsterdam-Rijnkanaal) cut a shallow trough
    trough = -1.4 * np.exp(-(((lat - 52.075) / 0.012) ** 2))

    # Gentle undulation so contours are not perfectly parallel
    noise = (
        1.1 * np.sin(lon * 145.0) * np.cos(lat * 165.0)
        + 0.6 * np.sin(lon * 310.0 + 1.3) * np.cos(lat * 275.0 - 0.7)
    )

    return np.round(ramp + crest1 + crest2 + polder + trough + noise + 1.0, 2)


def elevation_scalar(lon: float, lat: float) -> float:
    return float(elevation_at(lon, lat))


# ---------------------------------------------------------------------------
# Urban structure
# ---------------------------------------------------------------------------
URBAN_RADIUS_M = 6_200.0     # dense core
SUBURB_RADIUS_M = 11_000.0   # built-up edge


def urbanity(lon: float, lat: float) -> float:
    """0 (open countryside) .. 1 (city centre).

    Distance decay from the Domtoren plus two satellite centres standing in for
    Nieuwegein and Zeist, so the built-up area is not a single perfect disc.
    """
    d = dist_from_centre_m(lon, lat)
    core = math.exp(-((d / SUBURB_RADIUS_M) ** 2))
    sat1 = 0.55 * math.exp(-((dist_m(5.085, 52.030, lon, lat) / 3500.0) ** 2))  # Nieuwegein
    sat2 = 0.50 * math.exp(-((dist_m(5.235, 52.090, lon, lat) / 3200.0) ** 2))  # Zeist
    return min(1.0, core + sat1 + sat2)


def in_bbox(lon: float, lat: float) -> bool:
    return MIN_LON <= lon <= MAX_LON and MIN_LAT <= lat <= MAX_LAT


def clamp_to_bbox(lon: float, lat: float) -> tuple[float, float]:
    return (min(max(lon, MIN_LON), MAX_LON), min(max(lat, MIN_LAT), MAX_LAT))


# ---------------------------------------------------------------------------
# Shape builders
# ---------------------------------------------------------------------------
def rect_polygon(
    lon: float, lat: float, width_m: float, height_m: float, rotation_rad: float = 0.0
) -> Polygon:
    """Axis-relative rectangle centred on (lon, lat), rotated in the plane."""
    hw, hh = width_m / 2, height_m / 2
    corners = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
    cos_r, sin_r = math.cos(rotation_rad), math.sin(rotation_rad)
    pts = []
    for dx, dy in corners:
        rx = dx * cos_r - dy * sin_r
        ry = dx * sin_r + dy * cos_r
        pts.append((lon + m_to_lon(rx), lat + m_to_lat(ry)))
    return Polygon(pts)


def irregular_polygon(
    rng: np.random.Generator,
    lon: float,
    lat: float,
    radius_m: float,
    vertices: int = 7,
    jitter: float = 0.30,
) -> Polygon:
    """Convex-ish blob -- used for census tracts and zoning districts."""
    angles = np.sort(rng.uniform(0, 2 * math.pi, vertices))
    radii = radius_m * (1 + rng.uniform(-jitter, jitter, vertices))
    pts = [
        (lon + m_to_lon(r * math.cos(a)), lat + m_to_lat(r * math.sin(a)))
        for a, r in zip(angles, radii, strict=True)
    ]
    poly = Polygon(pts)
    return poly if poly.is_valid else poly.buffer(0)


def wiggly_line(
    rng: np.random.Generator,
    start: tuple[float, float],
    end: tuple[float, float],
    segments: int = 8,
    amplitude_m: float = 120.0,
) -> LineString:
    """Straight line perturbed perpendicular to its axis."""
    lon0, lat0 = start
    lon1, lat1 = end
    dx_m, dy_m = lon_to_m(lon1 - lon0), lat_to_m(lat1 - lat0)
    length = math.hypot(dx_m, dy_m) or 1.0
    nx, ny = -dy_m / length, dx_m / length  # unit normal

    pts = []
    for i in range(segments + 1):
        t = i / segments
        # Taper the perturbation to zero at both ends so endpoints stay put --
        # otherwise connected networks pull apart at the joins.
        taper = math.sin(math.pi * t)
        offset = rng.normal(0, amplitude_m) * taper
        lon = lon0 + (lon1 - lon0) * t + m_to_lon(nx * offset)
        lat = lat0 + (lat1 - lat0) * t + m_to_lat(ny * offset)
        pts.append((lon, lat))
    return LineString(pts)


def to_wkt(geom: BaseGeometry) -> str:
    return geom.wkt


def multi_wkt(geom: BaseGeometry, kind: str) -> str:
    """Force a geometry into its Multi* form so it matches the column type."""
    gtype = geom.geom_type
    if kind == "polygon":
        return geom.wkt if gtype == "MultiPolygon" else f"MULTIPOLYGON ({geom.wkt[8:]})"
    if kind == "line":
        return geom.wkt if gtype == "MultiLineString" else f"MULTILINESTRING ({geom.wkt[11:]})"
    return geom.wkt


def sample_point(rng: np.random.Generator) -> tuple[float, float]:
    return (
        float(rng.uniform(MIN_LON, MAX_LON)),
        float(rng.uniform(MIN_LAT, MAX_LAT)),
    )


def sample_urban_point(
    rng: np.random.Generator, sigma_m: float = 4200.0
) -> tuple[float, float]:
    """Gaussian around the city centre, rejected back into the bbox."""
    for _ in range(40):
        lon = CENTRE_LON + m_to_lon(rng.normal(0, sigma_m))
        lat = CENTRE_LAT + m_to_lat(rng.normal(0, sigma_m))
        if in_bbox(lon, lat):
            return lon, lat
    return CENTRE_LON, CENTRE_LAT


def sample_rural_point(rng: np.random.Generator, max_urbanity: float = 0.30) -> tuple[float, float]:
    """Uniform in the bbox but rejecting built-up land."""
    for _ in range(60):
        lon, lat = sample_point(rng)
        if urbanity(lon, lat) < max_urbanity:
            return lon, lat
    return float(rng.uniform(MIN_LON, MIN_LON + 0.08)), float(rng.uniform(MIN_LAT, MAX_LAT))


def point_wkt(lon: float, lat: float) -> str:
    return Point(lon, lat).wkt
