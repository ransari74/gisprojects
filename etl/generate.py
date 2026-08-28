"""Deterministic synthetic data generator for the Utrecht study area.

Why this exists: the real open datasets in etl/config.py total ~660 MB and need
GDAL, an OSM PBF reader and network access. That is the right pipeline for the
production load (etl/download.py), but it makes "clone and see it work" a
30-minute exercise. This module writes the same schema with the same attribute
distributions in about ten seconds and no network, so the API, the tiles and
every chart are exercisable immediately.

The data is synthetic but not arbitrary -- the terrain model, the urban decay
function, the crop mix, the modal split and the building-height distribution
are all shaped to match the real Utrecht values, so the charts show the
patterns a reviewer would expect to see.

Everything is seeded, so two runs produce byte-identical output.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta

import numpy as np
from shapely.geometry import LineString, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from etl.config import CENTRE_LAT, CENTRE_LON, MAX_LAT, MAX_LON, MIN_LAT, MIN_LON
from etl.geoutil import (
    dist_from_centre_m,
    elevation_at,
    elevation_scalar,
    irregular_polygon,
    m_to_lat,
    m_to_lon,
    multi_wkt,
    point_wkt,
    rect_polygon,
    sample_point,
    sample_rural_point,
    urbanity,
    wiggly_line,
)

SEED = 20260813


def rng() -> np.random.Generator:
    return np.random.default_rng(SEED)


# ===========================================================================
# STUDY AREA
# ===========================================================================
def gen_study_area() -> dict:
    poly = box(MIN_LON, MIN_LAT, MAX_LON, MAX_LAT)
    return {
        "code": "NL-UT",
        "name": "Utrecht, Netherlands",
        "country": "Netherlands",
        "epsg_local": 28992,
        "geom": multi_wkt(poly, "polygon"),
    }


# ===========================================================================
# PROJECT 1 -- AGRICULTURE
# ===========================================================================

# Crop mix reflecting the real Utrecht/Kromme Rijn area: overwhelmingly
# grassland (dairy), then maize, with arable rotation crops behind.
CROPS = [
    # name, share, yield mean t/ha, yield sd, prefers wet soil
    ("grassland", 0.42, 11.5, 2.2, True),
    ("maize", 0.20, 44.0, 7.5, True),
    ("wheat", 0.13, 8.9, 1.4, False),
    ("potato", 0.09, 47.0, 8.0, False),
    ("sugarbeet", 0.07, 82.0, 12.0, False),
    ("barley", 0.05, 6.8, 1.1, False),
    ("rapeseed", 0.04, 3.9, 0.7, False),
]

SOIL_TEXTURES = [
    # USDA class, clay range, sand range
    ("clay", (35, 55), (10, 30)),
    ("clay loam", (27, 38), (20, 42)),
    ("loam", (10, 26), (30, 50)),
    ("sandy loam", (5, 18), (52, 72)),
    ("sand", (2, 8), (78, 92)),
    ("peat", (12, 25), (12, 28)),
]


def _texture_for(lon: float) -> tuple[str, tuple, tuple]:
    """West Utrecht is river clay and peat polder; the eastern Heuvelrug is
    glacial sand. Texture therefore correlates with longitude."""
    t = (lon - MIN_LON) / (MAX_LON - MIN_LON)
    if t < 0.22:
        return SOIL_TEXTURES[5]  # peat polder
    if t < 0.42:
        return SOIL_TEXTURES[0]  # river clay
    if t < 0.60:
        return SOIL_TEXTURES[1]
    if t < 0.78:
        return SOIL_TEXTURES[2]
    if t < 0.90:
        return SOIL_TEXTURES[3]
    return SOIL_TEXTURES[4]  # Heuvelrug sand


def field_attrs_for(r: np.random.Generator, lon: float, lat: float, crop_override: str | None = None) -> dict:
    """Everything about a field except geometry, code and farm name -- shared
    by the synthetic generator and the real-data mapper in etl/real_data.py,
    which supplies real geometry/crop and wants the rest (soil, yield, NDVI)
    computed the same plausible way."""
    crops, weights = [c[0] for c in CROPS], np.array([c[1] for c in CROPS])
    weights = weights / weights.sum()
    crop_meta = {c[0]: c for c in CROPS}

    texture, clay_rng, sand_rng = _texture_for(lon)
    clay = float(r.uniform(*clay_rng))
    sand = float(r.uniform(*sand_rng))
    silt = max(1.0, 100 - clay - sand)

    # Peat and clay hold water and organic carbon; sand does not.
    if texture == "peat":
        soc, ph = float(r.normal(180, 35)), float(r.normal(5.2, 0.35))
    elif texture in ("clay", "clay loam"):
        soc, ph = float(r.normal(38, 9)), float(r.normal(7.1, 0.4))
    elif texture == "loam":
        soc, ph = float(r.normal(28, 7)), float(r.normal(6.6, 0.4))
    else:
        soc, ph = float(r.normal(19, 6)), float(r.normal(5.6, 0.45))
    soc, ph = max(4.0, soc), min(8.4, max(3.9, ph))

    if crop_override is not None and crop_override in crop_meta:
        crop = crop_override
    else:
        crop = str(r.choice(crops, p=weights))
    _, _, y_mean, y_sd, wet_pref = crop_meta[crop]

    elev = elevation_scalar(lon, lat)
    slope = max(0.0, float(r.gamma(1.6, 0.55)) + max(0.0, (elev - 12) * 0.05))

    # Yield responds to pH optimum, organic carbon and slope -- this is what
    # makes the soil/yield scatter panel show a real relationship.
    ph_penalty = 1.0 - min(0.35, abs(ph - 6.6) * 0.11)
    soc_bonus = 1.0 + min(0.18, (soc - 25) * 0.0035)
    slope_penalty = 1.0 - min(0.20, slope * 0.022)
    wet_bonus = 1.06 if (wet_pref and texture in ("peat", "clay", "clay loam")) else 1.0
    irrigated = bool(r.random() < (0.30 if texture in ("sand", "sandy loam") else 0.08))
    organic = bool(r.random() < 0.11)

    yield_t = y_mean * ph_penalty * soc_bonus * slope_penalty * wet_bonus
    yield_t *= 0.88 if organic else 1.0
    yield_t *= 1.05 if irrigated else 1.0
    yield_t = max(0.4, float(r.normal(yield_t, y_sd * 0.55)))

    # NDVI tracks canopy vigour, so it tracks the same drivers as yield.
    ndvi_mean = float(np.clip(r.normal(0.62 + (yield_t / y_mean - 1) * 0.13, 0.055), 0.12, 0.93))
    ndvi_max = float(np.clip(ndvi_mean + abs(r.normal(0.16, 0.04)), 0.2, 0.98))

    ratio = yield_t / y_mean
    yield_class = "high" if ratio > 1.12 else ("low" if ratio < 0.88 else "medium")

    landcover = (
        ("Grassland", 30) if crop == "grassland" else ("Cropland", 40)
    )

    return {
        "crop_type": crop,
        "crop_year": 2024,
        "irrigated": irrigated,
        "organic": organic,
        "soil_ph": round(ph, 2),
        "soil_organic_c": round(soc, 1),
        "soil_nitrogen": round(soc * float(r.uniform(0.07, 0.11)) * 10, 1),
        "soil_clay_pct": round(clay, 1),
        "soil_sand_pct": round(sand, 1),
        "soil_silt_pct": round(silt, 1),
        "soil_texture": texture,
        "landcover_class": landcover[0],
        "landcover_code": landcover[1],
        "ndvi_mean": round(ndvi_mean, 4),
        "ndvi_max": round(ndvi_max, 4),
        "ndvi_stddev": round(float(abs(r.normal(0.09, 0.025))), 4),
        "elevation_m": round(elev, 2),
        "slope_deg": round(slope, 2),
        "yield_t_ha": round(yield_t, 2),
        "yield_class": yield_class,
    }


def gen_fields(r: np.random.Generator, n: int = 1600) -> list[dict]:
    fields = []
    for i in range(n):
        lon, lat = sample_rural_point(r, max_urbanity=0.68)

        # Dutch field parcels are long and narrow ("slagenlandschap"), aligned
        # with the drainage ditches, so the aspect ratio is deliberately extreme.
        width = float(r.uniform(60, 190))
        height = width * float(r.uniform(2.2, 6.5))
        rotation = float(r.normal(0.35, 0.45))  # broadly NE-SW
        poly = rect_polygon(lon, lat, width, height, rotation)
        area_ha = round(width * height / 10_000, 3)

        attrs = field_attrs_for(r, lon, lat)
        fields.append(
            {
                "field_code": f"NL-UT-{i + 1:05d}",
                "farm_name": f"{r.choice(FARM_PREFIX)} {r.choice(FARM_SUFFIX)}",
                "area_ha": area_ha,
                **attrs,
                "geom": multi_wkt(poly, "polygon"),
            }
        )
    return fields


FARM_PREFIX = ["Hoeve", "Boerderij", "Erf", "Landgoed", "Polderhoeve", "Weidehof"]
FARM_SUFFIX = [
    "De Meern", "Rijnzicht", "Vechtoever", "Kromme Rijn", "Nieuwland", "Groenekan",
    "Haarzuilens", "Lopikerwaard", "Vleuten", "Bunnik", "Houten", "Maarssen",
]


def gen_canals(r: np.random.Generator, n: int = 130) -> list[dict]:
    """Irrigation/drainage network -- the agriculture project's LINESTRING layer.

    Dutch polder ditches run in dense parallel sets, so primaries are laid out
    as long spines with secondaries branching off perpendicular.
    """
    canals = []
    idx = 0

    # Primary spines: long, roughly N-S, in the western polder
    for p in range(8):
        lon = MIN_LON + 0.012 + p * 0.020
        start = (lon, MIN_LAT + 0.01)
        end = (lon + float(r.uniform(-0.012, 0.012)), MAX_LAT - 0.01)
        line = wiggly_line(r, start, end, segments=14, amplitude_m=340)
        idx += 1
        canals.append(_canal_row(r, idx, line, "primary"))

        # Secondaries branching east off each spine
        for s in range(int(r.integers(2, 5))):
            t = float(r.uniform(0.15, 0.85))
            pt = line.interpolate(t, normalized=True)
            length_deg = float(r.uniform(0.012, 0.030))
            end_s = (pt.x + length_deg, pt.y + float(r.uniform(-0.006, 0.006)))
            if end_s[0] > MAX_LON:
                continue
            sline = wiggly_line(r, (pt.x, pt.y), end_s, segments=6, amplitude_m=110)
            idx += 1
            canals.append(_canal_row(r, idx, sline, "secondary"))

    # Tertiary field ditches scattered through the rural south-west
    while len(canals) < n:
        lon, lat = sample_rural_point(r, max_urbanity=0.62)
        end = (lon + float(r.uniform(-0.010, 0.010)), lat + float(r.uniform(0.004, 0.014)))
        line = wiggly_line(r, (lon, lat), end, segments=4, amplitude_m=60)
        idx += 1
        canals.append(_canal_row(r, idx, line, str(r.choice(["tertiary", "drainage"], p=[0.6, 0.4]))))

    return canals[:n]


CANAL_NAMES = [
    "Leidsche Rijn", "Kromme Rijn", "Vaartsche Rijn", "Oude Rijn", "Merwedekanaal",
    "Enkele Wiericke", "Doorslag", "Heldam", "Bijleveld", "Haarrijn", "Zwarte Water",
]


def canal_synth_attrs(r: np.random.Generator, canal_type: str) -> dict:
    """Everything about a canal except identity/geometry -- shared by the
    synthetic generator and the real-data mapper, which supplies the real
    line/name/category and wants capacity/lining/condition modelled the same
    way (neither OSM nor the Dutch water-board register publishes those)."""
    capacity = {
        "primary": r.uniform(8, 26),
        "secondary": r.uniform(2.5, 8),
        "tertiary": r.uniform(0.4, 2.5),
        "drainage": r.uniform(0.2, 1.6),
    }[canal_type]
    return {
        "lined": bool(r.random() < (0.7 if canal_type == "primary" else 0.2)),
        "capacity_m3s": round(float(capacity), 2),
        "condition": str(r.choice(["good", "fair", "poor"], p=[0.5, 0.36, 0.14])),
    }


def _canal_row(r: np.random.Generator, idx: int, line: LineString, canal_type: str) -> dict:
    length_m = _line_length_m(line)
    return {
        "canal_code": f"CNL-{idx:04d}",
        "name": (
            f"{r.choice(CANAL_NAMES)} {'watergang' if canal_type != 'primary' else 'kanaal'}"
            if canal_type in ("primary", "secondary")
            else None
        ),
        "canal_type": canal_type,
        "length_m": round(length_m, 1),
        **canal_synth_attrs(r, canal_type),
        "geom": multi_wkt(line, "line"),
    }


def _line_length_m(line: LineString) -> float:
    from etl.geoutil import lat_to_m, lon_to_m

    coords = list(line.coords)
    total = 0.0
    for (x1, y1), (x2, y2) in zip(coords, coords[1:]):  # noqa: B905 - offset pairs
        total += math.hypot(lon_to_m(x2 - x1), lat_to_m(y2 - y1))
    return total


def gen_soil_samples(r: np.random.Generator, fields: list[dict], n: int = 320) -> list[dict]:
    """Lab samples placed inside real fields so they agree with the field row."""
    samples = []
    picks = r.choice(len(fields), size=min(n, len(fields)), replace=False)
    for i, fi in enumerate(picks):
        f = fields[int(fi)]
        # Take the field's own centroid, nudged, so sample ~ field attributes.
        wkt = f["geom"]
        lon, lat = _centroid_of_multipolygon_wkt(wkt)
        lon += m_to_lon(float(r.normal(0, 40)))
        lat += m_to_lat(float(r.normal(0, 40)))
        samples.append(
            {
                "sample_code": f"SMP-{i + 1:05d}",
                "sampled_on": (date(2024, 3, 1) + timedelta(days=int(r.integers(0, 210)))).isoformat(),
                "depth_cm": int(r.choice([15, 30, 30, 60])),
                "ph": round(float(np.clip(r.normal(f["soil_ph"], 0.18), 3.8, 8.6)), 2),
                "organic_c": round(max(2.0, float(r.normal(f["soil_organic_c"], 4.5))), 1),
                "nitrogen": round(max(1.0, float(r.normal(f["soil_nitrogen"], 8))), 1),
                "phosphorus": round(float(abs(r.normal(38, 14))), 1),
                "potassium": round(float(abs(r.normal(155, 55))), 1),
                "geom": point_wkt(lon, lat),
            }
        )
    return samples


def _centroid_of_multipolygon_wkt(wkt: str) -> tuple[float, float]:
    from shapely import wkt as shapely_wkt

    c = shapely_wkt.loads(wkt).centroid
    return c.x, c.y


def gen_ndvi_series(r: np.random.Generator, n_fields: int, sample: int = 260) -> list[dict]:
    """Sentinel-2 style revisit: one observation every ~10 days through 2024.

    Only a sample of fields gets a series -- the chart aggregates by crop, so a
    few hundred fields already give tight confidence bands, and the table stays
    small enough to ship in a free-tier database.
    """
    rows = []
    field_ids = r.choice(np.arange(1, n_fields + 1), size=min(sample, n_fields), replace=False)
    dates = [date(2024, 3, 1) + timedelta(days=10 * k) for k in range(24)]

    for fid in field_ids:
        # Each field gets its own phenology: emergence, peak and senescence.
        peak_day = float(r.normal(115, 16))     # days after 1 March
        amplitude = float(r.uniform(0.42, 0.62))
        baseline = float(r.uniform(0.14, 0.24))
        width = float(r.uniform(42, 62))
        for d in dates:
            doy = (d - date(2024, 3, 1)).days
            ndvi = baseline + amplitude * math.exp(-(((doy - peak_day) / width) ** 2))
            ndvi = float(np.clip(r.normal(ndvi, 0.028), 0.03, 0.97))
            rows.append(
                {
                    "field_id": int(fid),
                    "obs_date": d.isoformat(),
                    "ndvi": round(ndvi, 4),
                    "cloud_pct": round(float(abs(r.normal(12, 14))), 1),
                }
            )
    return rows


# ===========================================================================
# PROJECT 2 -- PARCEL / CADASTRE
# ===========================================================================
ZONE_TYPES = [
    # code, name, category, max FAR, max height, min lot
    ("R-1", "Low-density residential", "residential", 0.6, 10.0, 250),
    ("R-2", "Medium-density residential", "residential", 1.4, 18.0, 150),
    ("R-3", "High-density residential", "residential", 2.6, 34.0, 90),
    ("C-1", "Neighbourhood commercial", "commercial", 1.8, 20.0, 200),
    ("C-2", "Central business district", "commercial", 4.5, 62.0, 300),
    ("M-1", "Mixed use", "mixed", 2.8, 28.0, 180),
    ("I-1", "Light industrial", "industrial", 1.2, 16.0, 800),
    ("I-2", "Heavy industrial", "industrial", 1.0, 24.0, 2000),
    ("A-1", "Agricultural", "agricultural", 0.1, 12.0, 10000),
    ("OS", "Open space & recreation", "open_space", 0.05, 8.0, 5000),
]


def gen_zoning(r: np.random.Generator) -> list[dict]:
    """Concentric zoning: CBD at the Domtoren, density falling outward, with
    industrial estates by the canal and agriculture beyond the ring."""
    districts = []
    idx = 0

    def add(zone, lon, lat, radius, jitter=0.28):
        nonlocal idx
        idx += 1
        code, name, cat, far, height, min_lot = zone
        poly = irregular_polygon(r, lon, lat, radius, vertices=int(r.integers(7, 12)), jitter=jitter)
        districts.append(
            {
                "zone_code": f"{code}-{idx:02d}",
                "zone_name": name,
                "zone_category": cat,
                "max_far": far,
                "max_height_m": height,
                "min_lot_m2": min_lot,
                "adopted_on": (date(2004, 1, 1) + timedelta(days=int(r.integers(0, 7000)))).isoformat(),
                "geom": multi_wkt(poly, "polygon"),
            }
        )

    add(ZONE_TYPES[4], CENTRE_LON, CENTRE_LAT, 900)                      # CBD
    for k in range(4):                                                    # inner ring
        a = k * math.pi / 2 + 0.4
        add(ZONE_TYPES[5], CENTRE_LON + m_to_lon(1500 * math.cos(a)),
            CENTRE_LAT + m_to_lat(1500 * math.sin(a)), 950)
    for k in range(6):                                                    # R-3 belt
        a = k * math.pi / 3
        add(ZONE_TYPES[2], CENTRE_LON + m_to_lon(2900 * math.cos(a)),
            CENTRE_LAT + m_to_lat(2900 * math.sin(a)), 1250)
    for k in range(8):                                                    # R-2 belt
        a = k * math.pi / 4 + 0.2
        add(ZONE_TYPES[1], CENTRE_LON + m_to_lon(5000 * math.cos(a)),
            CENTRE_LAT + m_to_lat(5000 * math.sin(a)), 1700)
    for k in range(8):                                                    # R-1 outer
        a = k * math.pi / 4 + 0.5
        add(ZONE_TYPES[0], CENTRE_LON + m_to_lon(8200 * math.cos(a)),
            CENTRE_LAT + m_to_lat(8200 * math.sin(a)), 2100)
    for lon, lat in [(5.055, 52.115), (5.185, 52.045), (5.09, 52.145)]:   # industry
        add(ZONE_TYPES[6], lon, lat, 1300)
    add(ZONE_TYPES[7], 5.045, 52.060, 1100)
    for k in range(3):                                                    # commercial nodes
        add(ZONE_TYPES[3], CENTRE_LON + m_to_lon(3800 * math.cos(k * 2.1)),
            CENTRE_LAT + m_to_lat(3800 * math.sin(k * 2.1)), 700)
    for lon, lat in [(5.02, 52.03), (5.00, 52.14), (5.26, 52.15), (5.24, 52.01)]:
        add(ZONE_TYPES[8], lon, lat, 3400, jitter=0.35)                   # agriculture
    for lon, lat in [(5.16, 52.13), (5.07, 52.06)]:
        add(ZONE_TYPES[9], lon, lat, 1000)                                # parks

    return districts


LAND_USE_BY_ZONE = {
    "residential": (["residential", "mixed", "vacant"], [0.86, 0.09, 0.05]),
    "commercial": (["retail", "office", "mixed", "vacant"], [0.34, 0.40, 0.20, 0.06]),
    "mixed": (["mixed", "residential", "retail", "office"], [0.40, 0.30, 0.18, 0.12]),
    "industrial": (["industrial", "office", "vacant"], [0.78, 0.12, 0.10]),
    "agricultural": (["residential", "vacant", "industrial"], [0.42, 0.50, 0.08]),
    "open_space": (["civic", "vacant"], [0.55, 0.45]),
}

STREETS = [
    "Oudegracht", "Biltstraat", "Amsterdamsestraatweg", "Vleutenseweg", "Croeselaan",
    "Nachtegaalstraat", "Voorstraat", "Maliebaan", "Kanaalstraat", "Weerdsingel",
    "Lange Nieuwstraat", "Wittevrouwenstraat", "Burgemeester Reigerstraat", "Rijnlaan",
    "Adriaen van Ostadelaan", "Vaartsche Rijn", "Europalaan", "Cartesiusweg",
]


def zoned_polygons(zoning: list[dict]) -> list[tuple[int, dict, BaseGeometry]]:
    """Zoning districts as (id, row, shapely geometry), skipping the two
    categories parcels are never placed in. Shared by the synthetic generator
    and the real-data mapper, which point-in-polygon tests real parcel
    centroids against the same zoning to fill zone_code/zoning_district_id."""
    from shapely import wkt as shapely_wkt

    return [
        (i + 1, z, shapely_wkt.loads(z["geom"]))
        for i, z in enumerate(zoning)
        if z["zone_category"] not in ("agricultural", "open_space")
    ]


def find_zone_for(lon: float, lat: float, zones: list[tuple[int, dict, BaseGeometry]]):
    """First zone containing (lon, lat), or None if the point falls outside
    every zoning district (real parcels can land outside the synthetic zoning
    coverage, unlike synthetically-placed ones)."""
    from shapely.geometry import Point

    pt = Point(lon, lat)
    for zid, z, geom in zones:
        if geom.contains(pt):
            return zid, z
    return None, None


def parcel_attrs_for(
    r: np.random.Generator, lon: float, lat: float, lot_area_m2: float, zid: int | None, z: dict | None
) -> dict:
    """Everything about a parcel except geometry and pin -- shared by the
    synthetic generator and the real-data mapper, which supplies real
    geometry/area/zoning match and wants the value model computed the same
    plausible way (NL doesn't publish parcel-level assessed value)."""
    cat = z["zone_category"] if z else "residential"

    uses, probs = LAND_USE_BY_ZONE[cat]
    land_use = str(r.choice(uses, p=probs))

    d_centre = dist_from_centre_m(lon, lat)
    max_far = z["max_far"] if z else 1.0
    max_height_m = z["max_height_m"] if z else 12.0

    if land_use == "vacant":
        far = 0.0
        floors, year_built, bld_area, units, n_bld = 0, None, 0.0, 0, 0
    else:
        far = float(np.clip(r.normal(max_far * 0.62, max_far * 0.26), 0.05, max_far * 1.18))
        bld_area = lot_area_m2 * far
        floors = max(1, int(round(float(r.normal(max(1.0, far / 0.55), 1.1)))))
        floors = min(floors, max(1, int(max_height_m / 3.2)))
        # Utrecht's building stock: a medieval core, 1900s belts,
        # post-war expansion and the Leidsche Rijn new town after 1997.
        year_built = int(np.clip(
            r.choice(
                [r.integers(1600, 1900), r.integers(1900, 1945),
                 r.integers(1945, 1980), r.integers(1980, 2000),
                 r.integers(2000, 2025)],
                p=[0.06, 0.22, 0.30, 0.18, 0.24],
            ),
            1600, 2025,
        ))
        units = (
            max(1, int(bld_area / float(r.uniform(70, 130))))
            if land_use in ("residential", "mixed") else 0
        )
        n_bld = max(1, int(r.integers(1, 3)))

    # Value model: centrality dominates, then use class, then age.
    base = 2600 * math.exp(-d_centre / 5200) + 380
    use_mult = {
        "office": 1.45, "retail": 1.55, "mixed": 1.25, "residential": 1.0,
        "industrial": 0.52, "civic": 0.7, "vacant": 0.38,
    }[land_use]
    age_mult = 1.0 if year_built is None else (
        1.22 if year_built > 2010 else (1.12 if year_built > 1990 else
        (1.18 if year_built < 1900 else 0.94))
    )
    value_per_m2 = float(max(60, r.normal(base * use_mult * age_mult, base * 0.18)))
    land_value = lot_area_m2 * value_per_m2
    improvement = bld_area * value_per_m2 * 0.55
    assessed = land_value + improvement

    sale_date = (
        (date(2015, 1, 1) + timedelta(days=int(r.integers(0, 3800)))).isoformat()
        if r.random() < 0.62 else None
    )
    return {
        "address": f"{int(r.integers(1, 320))} {r.choice(STREETS)}",
        "district": z["zone_name"].split()[0] if z else "Buitengebied",
        "zone_code": z["zone_code"] if z else None,
        "zoning_district_id": zid,
        "land_use": land_use,
        "owner_type": str(r.choice(
            ["private", "corporate", "municipal", "state", "ngo"],
            p=[0.58, 0.26, 0.09, 0.04, 0.03],
        )),
        "building_area_m2": round(bld_area, 1),
        "floor_area_ratio": round(far, 3),
        "coverage_ratio": round(min(0.95, far / max(floors, 1)), 3),
        "num_buildings": n_bld,
        "num_units": units,
        "floors": floors or None,
        "year_built": year_built,
        "assessed_value": round(assessed, 2),
        "land_value": round(land_value, 2),
        "improvement_value": round(improvement, 2),
        "value_per_m2": round(value_per_m2, 2),
        "last_sale_date": sale_date,
        "last_sale_price": round(assessed * float(r.uniform(0.82, 1.16)), 2) if sale_date else None,
        "tax_exempt": bool(land_use == "civic" or r.random() < 0.035),
    }


def gen_parcels(r: np.random.Generator, zoning: list[dict], n: int = 3200) -> list[dict]:
    """Parcels laid out in blocks inside each zoning district.

    Value is driven by distance to the centre, zoning category and building
    age, which is what makes the value-distribution and price-trend panels
    show recognisable structure rather than noise.
    """
    from shapely import wkt as shapely_wkt

    parcels = []
    zones = zoned_polygons(zoning)
    # Allocate parcels to zones by area so dense districts get more of them.
    areas = np.array([g.area for _, _, g in zones])
    shares = (areas / areas.sum() * n).astype(int)

    idx = 0
    for (zid, z, geom), count in zip(zones, shares, strict=True):
        minx, miny, maxx, maxy = geom.bounds
        placed = 0
        attempts = 0
        while placed < count and attempts < count * 12:
            attempts += 1
            lon = float(r.uniform(minx, maxx))
            lat = float(r.uniform(miny, maxy))
            if not geom.contains(shapely_wkt.loads(f"POINT ({lon} {lat})")):
                continue

            cat = z["zone_category"]
            # Lot size by zone category, log-normal so the tail is realistic.
            lot_mean = {
                "commercial": 1100, "mixed": 620, "residential": 340,
                "industrial": 4200,
            }.get(cat, 500)
            lot_area = float(r.lognormal(math.log(lot_mean), 0.55))
            lot_area = float(np.clip(lot_area, z["min_lot_m2"] * 0.7, lot_mean * 9))

            side = math.sqrt(lot_area)
            depth_ratio = float(r.uniform(1.3, 2.6))
            width = side / math.sqrt(depth_ratio)
            depth = side * math.sqrt(depth_ratio)
            rotation = float(r.normal(0.6, 0.9))
            poly = rect_polygon(lon, lat, width, depth, rotation)

            idx += 1
            attrs = parcel_attrs_for(r, lon, lat, lot_area, zid, z)
            parcels.append(
                {
                    "parcel_pin": f"UT-{idx:06d}",
                    "lot_area_m2": round(lot_area, 1),
                    **attrs,
                    "geom": multi_wkt(poly, "polygon"),
                }
            )
            placed += 1

    return parcels


def gen_boundary_lines(r: np.random.Generator, parcels: list[dict], n: int = 1400) -> list[dict]:
    """Lot lines, easements and rights of way -- the parcel LINESTRING layer."""
    from shapely import wkt as shapely_wkt

    rows = []
    picks = r.choice(len(parcels), size=min(n, len(parcels)), replace=False)
    for i, pi in enumerate(picks):
        p = parcels[int(pi)]
        poly = shapely_wkt.loads(p["geom"])
        ring = list(poly.geoms[0].exterior.coords)

        btype = str(r.choice(
            ["lot_line", "easement", "right_of_way", "setback", "disputed"],
            p=[0.54, 0.18, 0.14, 0.10, 0.04],
        ))
        if btype == "lot_line":
            # The full parcel outline as a line.
            line = LineString(ring)
        elif btype == "setback":
            shrunk = poly.buffer(-m_to_lon(3.0))
            line = LineString(shrunk.exterior.coords) if not shrunk.is_empty and shrunk.geom_type == "Polygon" else LineString(ring)
        else:
            # A single edge stands in for the easement / ROW corridor.
            j = int(r.integers(0, max(1, len(ring) - 1)))
            line = LineString([ring[j], ring[(j + 1) % len(ring)]])

        rows.append(
            {
                "parcel_pin": p["parcel_pin"],
                "boundary_type": btype,
                "survey_date": (date(1998, 1, 1) + timedelta(days=int(r.integers(0, 9800)))).isoformat(),
                "length_m": round(_line_length_m(line), 2),
                "is_disputed": btype == "disputed",
                "geom": multi_wkt(line, "line"),
            }
        )
    return rows


def gen_sales_history(r: np.random.Generator, parcels: list[dict]) -> list[dict]:
    """Transaction history with a realistic Dutch housing-market trajectory:
    recovery from 2015, a sharp 2021-22 run-up, then a 2023 correction."""
    index = {
        2015: 0.72, 2016: 0.78, 2017: 0.85, 2018: 0.92, 2019: 0.98,
        2020: 1.05, 2021: 1.22, 2022: 1.35, 2023: 1.28, 2024: 1.31, 2025: 1.36,
    }
    rows = []
    for pid, p in enumerate(parcels, start=1):
        if p["value_per_m2"] is None or r.random() > 0.45:
            continue
        for _ in range(int(r.integers(1, 4))):
            year = int(r.choice(list(index.keys())))
            d = date(year, int(r.integers(1, 13)), int(r.integers(1, 28)))
            ppm2 = p["value_per_m2"] * index[year] * float(r.normal(1.0, 0.09))
            price = ppm2 * p["lot_area_m2"]
            rows.append(
                {
                    "parcel_id": pid,
                    "sale_date": d.isoformat(),
                    "sale_price": round(max(1000.0, price), 2),
                    "price_per_m2": round(max(30.0, ppm2), 2),
                    "buyer_type": str(r.choice(
                        ["private", "corporate", "investor", "municipal"],
                        p=[0.61, 0.21, 0.14, 0.04],
                    )),
                }
            )
    return rows


# ===========================================================================
# PROJECT 3 -- DEMOGRAPHICS
# ===========================================================================
TRACT_NAMES = [
    "Binnenstad", "Wittevrouwen", "Oudwijk", "Lombok", "Pijlsweerd", "Ondiep",
    "Zuilen", "Overvecht", "Tuindorp", "Voordorp", "Tuinwijk", "Vogelenbuurt",
    "Wilhelminapark", "Rivierenwijk", "Dichterswijk", "Transwijk", "Kanaleneiland",
    "Hoograven", "Lunetten", "Leidsche Rijn", "Vleuten", "De Meern", "Terwijde",
    "Parkwijk", "Langerak", "Papendorp", "Hoge Weide", "Maximapark", "Haarzuilens",
    "Bunnik", "Odijk", "Werkhoven", "Houten Noord", "Houten Zuid", "Nieuwegein Centrum",
    "Vreeswijk", "Jutphaas", "Galecop", "Zeist West", "Zeist Centrum", "Den Dolder",
    "Bilthoven", "De Bilt", "Groenekan", "Maartensdijk", "Westbroek", "Maarssen",
    "Breukelen", "Loenen", "Vinkeveen", "Abcoude", "Wilnis", "Kockengen", "Harmelen",
    "Woerden Oost", "Linschoten", "Montfoort", "IJsselstein", "Lopik", "Benschop",
]

DISTRICTS = ["Centrum", "Noord", "Oost", "Zuid", "West", "Leidsche Rijn", "Buitengebied"]

AGE_BANDS = [
    "0-4", "5-9", "10-14", "15-19", "20-24", "25-29", "30-34", "35-39", "40-44",
    "45-49", "50-54", "55-59", "60-64", "65-69", "70-74", "75-79", "80-84", "85+",
]


def gen_tracts(r: np.random.Generator, n: int = 60) -> list[dict]:
    """Census tracts as a Voronoi tessellation of jittered seed points.

    Real census geography partitions its area exactly -- neighbourhoods share
    borders and leave no gaps. Independent blobs on a grid read as generated at
    a glance, and worse, they make the choropleth lie: the white space between
    them is not "no population", it is missing polygons. Voronoi cells clipped
    to the study area tile it completely, which is both honest and what a
    neighbourhood map looks like.

    Seeds are denser toward the centre, so tracts are small in the city and
    large in the countryside -- the same relationship real census areas have,
    since they are drawn to hold comparable populations.
    """
    from shapely import voronoi_polygons
    from shapely.geometry import MultiPoint

    envelope = box(MIN_LON, MIN_LAT, MAX_LON, MAX_LAT)

    # Half the seeds cluster on the city, half spread over the whole area.
    seeds: list[tuple[float, float]] = []
    while len(seeds) < n:
        if len(seeds) % 2 == 0:
            lon = CENTRE_LON + m_to_lon(float(r.normal(0, 4200)))
            lat = CENTRE_LAT + m_to_lat(float(r.normal(0, 4200)))
        else:
            lon = float(r.uniform(MIN_LON, MAX_LON))
            lat = float(r.uniform(MIN_LAT, MAX_LAT))
        if MIN_LON < lon < MAX_LON and MIN_LAT < lat < MAX_LAT:
            seeds.append((lon, lat))

    cells = [
        cell.intersection(envelope)
        for cell in voronoi_polygons(MultiPoint(seeds), extend_to=envelope).geoms
    ]
    cells = [c for c in cells if not c.is_empty and c.geom_type in ("Polygon", "MultiPolygon")]
    # Voronoi returns cells in its own order; sorting by centroid keeps the
    # output stable run to run, which the fixed seed alone does not guarantee.
    cells.sort(key=lambda c: (round(c.centroid.y, 6), round(c.centroid.x, 6)))

    tracts = []
    for idx, cell in enumerate(cells, start=1):
        centroid = cell.centroid
        lon, lat = centroid.x, centroid.y
        u = urbanity(lon, lat)

        # Real area of the cell, in km2 at this latitude.
        area_km2 = round(cell.area * (68.5 * 111.3), 3)

        # Density spans two orders of magnitude between the medieval core and
        # the Lopikerwaard polder. Calibrated so the study area totals roughly
        # 800k residents over its 534 km2 -- Utrecht city plus Nieuwegein,
        # Zeist, Houten, IJsselstein and the countryside between them.
        density = float(np.clip(r.lognormal(math.log(55 + 3600 * u**2.1), 0.45), 12, 12000))
        population = max(50, int(density * area_km2))
        households = max(20, int(population / float(r.uniform(1.9, 2.7))))

        # Age structure shifts with urbanity: students in the core, families in
        # the suburbs, retirees in the villages.
        pct_under_15 = float(np.clip(r.normal(19 - 7 * u + 3 * (1 - u), 2.4), 6, 30))
        pct_15_29 = float(np.clip(r.normal(14 + 17 * u, 3.5), 8, 46))
        pct_65_plus = float(np.clip(r.normal(21 - 11 * u, 3.8), 4, 34))
        pct_30_44 = float(np.clip(r.normal(22 + 2 * u, 3.0), 12, 34))
        pct_45_64 = max(4.0, 100 - pct_under_15 - pct_15_29 - pct_30_44 - pct_65_plus)
        scale = 100 / (pct_under_15 + pct_15_29 + pct_30_44 + pct_45_64 + pct_65_plus)
        pct_under_15, pct_15_29, pct_30_44, pct_45_64, pct_65_plus = (
            v * scale for v in (pct_under_15, pct_15_29, pct_30_44, pct_45_64, pct_65_plus)
        )
        median_age = (
            12 * pct_under_15 / 100 + 23 * pct_15_29 / 100 + 37 * pct_30_44 / 100
            + 54 * pct_45_64 / 100 + 73 * pct_65_plus / 100
        )

        # Education drives income; income drives rent and deprivation.
        tertiary = float(np.clip(r.normal(30 + 34 * u, 8.5), 8, 78))
        income = float(np.clip(r.normal(24_000 + 520 * tertiary, 5200), 16_000, 82_000))
        unemployment = float(np.clip(r.normal(7.4 - 0.062 * tertiary, 1.2), 0.8, 12.5))
        owner_occ = float(np.clip(r.normal(78 - 46 * u, 10), 12, 96))
        rent = float(np.clip(r.normal(560 + 5.6 * tertiary + 260 * u, 90), 420, 1650))
        deprivation = float(np.clip(
            55 - (income - 24_000) / 700 + unemployment * 2.2 + r.normal(0, 4.5), 2, 98
        ))

        tracts.append(
            {
                "tract_code": f"BU{idx:06d}",
                "tract_name": TRACT_NAMES[(idx - 1) % len(TRACT_NAMES)],
                "district": DISTRICTS[min(int(u * len(DISTRICTS)), len(DISTRICTS) - 1)],
                "population": population,
                "households": households,
                "avg_household_size": round(population / max(households, 1), 2),
                "area_km2": area_km2,
                "density_km2": round(population / max(area_km2, 0.01), 1),
                "pct_under_15": round(pct_under_15, 1),
                "pct_15_29": round(pct_15_29, 1),
                "pct_30_44": round(pct_30_44, 1),
                "pct_45_64": round(pct_45_64, 1),
                "pct_65_plus": round(pct_65_plus, 1),
                "median_age": round(median_age, 1),
                "median_income": round(income, 2),
                "unemployment_rate": round(unemployment, 2),
                "pct_tertiary_educated": round(tertiary, 1),
                "pct_foreign_born": round(float(np.clip(r.normal(12 + 22 * u, 6), 2, 62)), 1),
                "dwellings": int(households * float(r.uniform(1.01, 1.09))),
                "pct_owner_occupied": round(owner_occ, 1),
                "pct_vacant": round(float(np.clip(r.normal(3.4, 1.5), 0.3, 12)), 1),
                "median_rent": round(rent, 2),
                "deprivation_index": round(deprivation, 1),
                "census_year": 2021,
                "geom": multi_wkt(cell, "polygon"),
            }
        )
    return tracts


def gen_age_structure(r: np.random.Generator, tracts: list[dict]) -> list[dict]:
    """Expand each tract's five broad bands into 18 five-year bands."""
    # Weight within each broad band, so the pyramid has smooth internal shape.
    band_group = {
        "0-4": ("u15", 0.34), "5-9": ("u15", 0.33), "10-14": ("u15", 0.33),
        "15-19": ("a1529", 0.30), "20-24": ("a1529", 0.37), "25-29": ("a1529", 0.33),
        "30-34": ("a3044", 0.36), "35-39": ("a3044", 0.33), "40-44": ("a3044", 0.31),
        "45-49": ("a4564", 0.28), "50-54": ("a4564", 0.27),
        "55-59": ("a4564", 0.24), "60-64": ("a4564", 0.21),
        "65-69": ("a65", 0.29), "70-74": ("a65", 0.25), "75-79": ("a65", 0.20),
        "80-84": ("a65", 0.15), "85+": ("a65", 0.11),
    }
    rows = []
    for tid, t in enumerate(tracts, start=1):
        shares = {
            "u15": t["pct_under_15"], "a1529": t["pct_15_29"], "a3044": t["pct_30_44"],
            "a4564": t["pct_45_64"], "a65": t["pct_65_plus"],
        }
        for order, band in enumerate(AGE_BANDS, start=1):
            group, weight = band_group[band]
            count = t["population"] * shares[group] / 100 * weight
            # Sex ratio starts slightly male-heavy and inverts with age.
            male_share = 0.512 - 0.0125 * order
            male = int(count * max(0.30, male_share))
            female = int(count) - male
            rows.append(
                {
                    "tract_id": tid,
                    "age_band": band,
                    "band_order": order,
                    "male": max(0, male),
                    "female": max(0, female),
                }
            )
    return rows


def gen_commute_flows(r: np.random.Generator, tracts: list[dict], n: int = 320) -> list[dict]:
    """Gravity-model OD flows: trips ~ (Pi * Pj) / d^2, with a modal split that
    shifts to bike at short range -- the Dutch signature."""
    from shapely import wkt as shapely_wkt

    centroids = []
    for t in tracts:
        c = shapely_wkt.loads(t["geom"]).centroid
        centroids.append((t["tract_code"], c.x, c.y, t["population"]))

    # Rank all pairs by gravity, keep the strongest.
    pairs = []
    for i, (code_i, lon_i, lat_i, pop_i) in enumerate(centroids):
        for j, (code_j, lon_j, lat_j, pop_j) in enumerate(centroids):
            if i >= j:
                continue
            d_km = math.hypot(
                (lon_j - lon_i) * 68.5, (lat_j - lat_i) * 111.3
            )
            if d_km < 0.4:
                continue
            gravity = (pop_i * pop_j) / (d_km**2)
            pairs.append((gravity, code_i, lon_i, lat_i, code_j, lon_j, lat_j, d_km))

    pairs.sort(reverse=True, key=lambda p: p[0])
    rows = []
    seen: set[tuple[str, str, str]] = set()

    for gravity, code_i, lon_i, lat_i, code_j, lon_j, lat_j, d_km in pairs:
        if len(rows) >= n:
            break
        # Distance-dependent modal split: bike dominates under 5 km, car beyond.
        bike_p = max(0.04, 0.62 * math.exp(-d_km / 4.5))
        walk_p = max(0.01, 0.22 * math.exp(-d_km / 1.8))
        transit_p = min(0.42, 0.10 + 0.030 * d_km)
        car_p = max(0.05, 1 - bike_p - walk_p - transit_p)
        probs = np.array([car_p, transit_p, bike_p, walk_p])
        probs = probs / probs.sum()

        for mode, p in zip(["car", "transit", "bike", "walk"], probs, strict=True):
            key = (code_i, code_j, mode)
            if key in seen or p < 0.04:
                continue
            seen.add(key)
            trips = int(max(5, gravity * 1e-5 * p * float(r.uniform(0.6, 1.5))))
            speed = {"car": 34.0, "transit": 21.0, "bike": 15.5, "walk": 4.8}[mode]
            rows.append(
                {
                    "origin_code": code_i,
                    "dest_code": code_j,
                    "trips": trips,
                    "mode": mode,
                    "avg_duration_min": round(d_km / speed * 60 * float(r.uniform(0.9, 1.3)), 1),
                    "distance_km": round(d_km * float(r.uniform(1.15, 1.45)), 2),  # network detour
                    "geom": LineString([(lon_i, lat_i), (lon_j, lat_j)]).wkt,
                }
            )
            if len(rows) >= n:
                break
    return rows


def gen_population_grid(r: np.random.Generator, cell_m: int = 500) -> list[dict]:
    """500 m grid whose values follow the same urbanity surface as the tracts,
    so the heat layer and the choropleth agree."""
    rows = []
    lon_step = m_to_lon(cell_m)
    lat_step = m_to_lat(cell_m)
    n_lon = int((MAX_LON - MIN_LON) / lon_step)
    n_lat = int((MAX_LAT - MIN_LAT) / lat_step)

    idx = 0
    for i in range(n_lon):
        for j in range(n_lat):
            lon = MIN_LON + i * lon_step
            lat = MIN_LAT + j * lat_step
            u = urbanity(lon + lon_step / 2, lat + lat_step / 2)
            pop = float(max(0.0, r.normal(9200 * u**2.4 + 18, 60 + 700 * u)))
            if pop < 1:
                continue
            idx += 1
            rows.append(
                {
                    "cell_id": f"G{i:03d}{j:03d}",
                    "population": round(pop * (cell_m / 1000) ** 2, 2),
                    "resolution_m": cell_m,
                    "geom": Polygon([
                        (lon, lat), (lon + lon_step, lat),
                        (lon + lon_step, lat + lat_step), (lon, lat + lat_step), (lon, lat),
                    ]).wkt,
                }
            )
    return rows


# ===========================================================================
# PROJECT 4 -- TRANSPORT
# ===========================================================================
ROAD_NAMES = [
    "A2", "A12", "A27", "A28", "N230", "N198", "N409", "Waterlinieweg",
    "Europalaan", "Cartesiusweg", "Biltsestraatweg", "Amsterdamsestraatweg",
    "Vleutenseweg", "Koningsweg", "Weg der Verenigde Naties", "Socratesstraat",
    "Marnixlaan", "Talmalaan", "Venuslaan", "Archimedeslaan", "Burgemeester Fockema Andreaelaan",
]

HIGHWAY_PROFILE = {
    #                 lanes   speed  aadt mean   congestion base
    "motorway":      (4, 100, 78_000, 0.62),
    "trunk":         (3, 80,  38_000, 0.55),
    "primary":       (2, 50,  19_000, 0.48),
    "secondary":     (2, 50,  11_000, 0.38),
    "tertiary":      (2, 50,  5_600,  0.28),
    "residential":   (1, 30,  1_400,  0.14),
    "service":       (1, 20,  350,    0.06),
    "cycleway":      (1, 20,  0,      0.04),
    "footway":       (1, 5,   0,      0.02),
}


#: Fallback profile for OSM highway values not in HIGHWAY_PROFILE (e.g.
#: unclassified, living_street, path, track, pedestrian, *_link).
DEFAULT_HIGHWAY_PROFILE = (1, 30, 800, 0.16)


def road_synth_attrs(r: np.random.Generator, hclass: str, line: LineString) -> dict:
    """Everything about a road segment except identity/geometry -- shared by
    the synthetic generator and the real-data mapper, which supplies the real
    line/highway_class/name and wants traffic/condition modelled the same way
    (OSM doesn't publish AADT or congestion)."""
    lanes, speed, aadt_mean, cong_base = HIGHWAY_PROFILE.get(hclass, DEFAULT_HIGHWAY_PROFILE)
    length_m = _line_length_m(line)
    mid = line.interpolate(0.5, normalized=True)
    u = urbanity(mid.x, mid.y)

    aadt = int(max(0, r.normal(aadt_mean * (0.45 + 0.95 * u), aadt_mean * 0.28))) if aadt_mean else None
    # Congestion rises with urbanity and with how loaded the link is.
    load = (aadt / (aadt_mean or 1)) if aadt else 0
    congestion = float(np.clip(r.normal(cong_base * (0.55 + 0.75 * u) + 0.12 * load, 0.09), 0.01, 0.98))
    maxspeed = int(np.clip(r.normal(speed, 6), 5, 130))
    peak_speed = round(maxspeed * (1 - congestion * 0.62), 1)

    return {
        "functional_class": None,
        "oneway": bool(r.random() < (0.55 if hclass in ("motorway", "trunk") else 0.14)),
        "lanes": int(np.clip(r.normal(lanes, 0.6), 1, 6)),
        "maxspeed_kmh": maxspeed,
        "surface": str(r.choice(["asphalt", "concrete", "paving_stones", "gravel"],
                                p=[0.80, 0.09, 0.09, 0.02])),
        "bridge": bool(r.random() < 0.05),
        "tunnel": bool(r.random() < 0.02),
        "length_m": round(length_m, 1),
        "aadt": aadt,
        "peak_speed_kmh": peak_speed,
        "congestion_index": round(congestion, 3),
        "accident_count": int(r.poisson(max(0.05, (aadt or 0) / 22_000 * (length_m / 1000) * 2.4))),
        "has_bike_lane": bool(hclass == "cycleway" or (hclass in ("secondary", "tertiary", "residential") and r.random() < 0.66)),
    }


def gen_roads(r: np.random.Generator) -> list[dict]:
    """A radial-plus-ring network: motorway ring, radial trunks, an urban grid
    and rural connectors. Geometry is generated, but the class hierarchy and
    the AADT/congestion relationship mirror a real Dutch city."""
    roads: list[dict] = []
    idx = 0

    def add(line: LineString, hclass: str, name: str | None, fclass: int) -> None:
        nonlocal idx
        idx += 1
        attrs = road_synth_attrs(r, hclass, line)
        attrs["functional_class"] = fclass
        roads.append({
            "osm_id": 100_000_000 + idx,
            "name": name,
            "highway_class": hclass,
            **attrs,
            "geom": multi_wkt(line, "line"),
        })

    # --- motorway ring (A27/A12/A2 form a real ring around Utrecht) ---------
    ring_r = 7600.0
    ring_pts = []
    for k in range(37):
        a = 2 * math.pi * k / 36
        rr = ring_r * (1 + 0.10 * math.sin(3 * a) + 0.05 * math.cos(5 * a))
        ring_pts.append((CENTRE_LON + m_to_lon(rr * math.cos(a)), CENTRE_LAT + m_to_lat(rr * math.sin(a))))
    for k in range(36):
        add(LineString([ring_pts[k], ring_pts[k + 1]]), "motorway",
            ROAD_NAMES[k % 4], 1)

    # --- radial trunks from the ring into the centre -------------------------
    for k in range(8):
        a = 2 * math.pi * k / 8
        outer = (CENTRE_LON + m_to_lon(11_500 * math.cos(a)), CENTRE_LAT + m_to_lat(11_500 * math.sin(a)))
        inner = (CENTRE_LON + m_to_lon(1_100 * math.cos(a)), CENTRE_LAT + m_to_lat(1_100 * math.sin(a)))
        line = wiggly_line(r, outer, inner, segments=9, amplitude_m=180)
        coords = list(line.coords)
        for s in range(len(coords) - 1):
            seg = LineString([coords[s], coords[s + 1]])
            hclass = "trunk" if s < 4 else "primary"
            add(seg, hclass, ROAD_NAMES[4 + (k % 12)], 2 if hclass == "trunk" else 3)

    # --- inner ring roads (secondary) ---------------------------------------
    for radius, hclass, fclass in ((2400, "secondary", 4), (4300, "secondary", 4)):
        pts = []
        for k in range(25):
            a = 2 * math.pi * k / 24
            rr = radius * (1 + 0.09 * math.sin(4 * a))
            pts.append((CENTRE_LON + m_to_lon(rr * math.cos(a)), CENTRE_LAT + m_to_lat(rr * math.sin(a))))
        for k in range(24):
            add(LineString([pts[k], pts[k + 1]]), hclass, ROAD_NAMES[8 + (k % 13)], fclass)

    # --- urban street grid ---------------------------------------------------
    grid_extent_m = 5200
    spacing_m = 260
    steps = int(grid_extent_m * 2 / spacing_m)
    for i in range(steps + 1):
        off = -grid_extent_m + i * spacing_m
        # E-W street
        p1 = (CENTRE_LON - m_to_lon(grid_extent_m), CENTRE_LAT + m_to_lat(off))
        p2 = (CENTRE_LON + m_to_lon(grid_extent_m), CENTRE_LAT + m_to_lat(off))
        # N-S street
        p3 = (CENTRE_LON + m_to_lon(off), CENTRE_LAT - m_to_lat(grid_extent_m))
        p4 = (CENTRE_LON + m_to_lon(off), CENTRE_LAT + m_to_lat(grid_extent_m))
        for a, b in ((p1, p2), (p3, p4)):
            # Split into a few segments so each carries its own attributes.
            for s in range(4):
                t0, t1 = s / 4, (s + 1) / 4
                seg = LineString([
                    (a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0),
                    (a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1),
                ])
                mid = seg.interpolate(0.5, normalized=True)
                if dist_from_centre_m(mid.x, mid.y) > grid_extent_m:
                    continue
                hclass = str(r.choice(["residential", "tertiary", "service"], p=[0.66, 0.24, 0.10]))
                add(seg, hclass, str(r.choice(ROAD_NAMES[8:])) if r.random() < 0.6 else None,
                    5 if hclass == "tertiary" else 6)

    # --- cycle network (the Netherlands' defining mode) ----------------------
    for k in range(170):
        a = float(r.uniform(0, 2 * math.pi))
        d0 = float(r.uniform(500, 9000))
        start = (CENTRE_LON + m_to_lon(d0 * math.cos(a)), CENTRE_LAT + m_to_lat(d0 * math.sin(a)))
        d1 = d0 + float(r.uniform(600, 2600))
        end = (CENTRE_LON + m_to_lon(d1 * math.cos(a + r.normal(0, 0.25))),
               CENTRE_LAT + m_to_lat(d1 * math.sin(a + r.normal(0, 0.25))))
        add(wiggly_line(r, start, end, segments=4, amplitude_m=70), "cycleway",
            f"Doorfietsroute {k + 1}" if r.random() < 0.3 else None, 7)

    # --- rural connectors ----------------------------------------------------
    for k in range(260):
        lon, lat = sample_rural_point(r, max_urbanity=0.72)
        end = (lon + float(r.uniform(-0.022, 0.022)), lat + float(r.uniform(-0.016, 0.016)))
        add(wiggly_line(r, (lon, lat), end, segments=5, amplitude_m=130),
            str(r.choice(["tertiary", "residential", "service"], p=[0.45, 0.35, 0.20])),
            None, 6)

    return roads


TRANSIT_MODES = [
    # mode, count, headway range, ridership range, colour
    ("bus", 26, (7, 30), (900, 9_500), "#0ea5e9"),
    ("tram", 3, (6, 12), (12_000, 34_000), "#f59e0b"),
    ("rail", 6, (10, 30), (18_000, 62_000), "#dc2626"),
]


def gen_transit(r: np.random.Generator) -> tuple[list[dict], list[dict]]:
    routes, stops = [], []
    route_idx, stop_idx = 0, 0

    for mode, count, headway_rng, ridership_rng, colour in TRANSIT_MODES:
        for k in range(count):
            route_idx += 1
            # Routes run through the centre, entering and leaving on different bearings.
            a_in = float(r.uniform(0, 2 * math.pi))
            a_out = a_in + math.pi + float(r.normal(0, 0.7))
            reach = {"bus": 7000, "tram": 6000, "rail": 13_000}[mode]
            p_in = (CENTRE_LON + m_to_lon(reach * math.cos(a_in)),
                    CENTRE_LAT + m_to_lat(reach * math.sin(a_in)))
            p_out = (CENTRE_LON + m_to_lon(reach * math.cos(a_out)),
                     CENTRE_LAT + m_to_lat(reach * math.sin(a_out)))
            leg1 = wiggly_line(r, p_in, (CENTRE_LON, CENTRE_LAT), segments=6,
                               amplitude_m=140 if mode != "rail" else 60)
            leg2 = wiggly_line(r, (CENTRE_LON, CENTRE_LAT), p_out, segments=6,
                               amplitude_m=140 if mode != "rail" else 60)
            line = LineString(list(leg1.coords) + list(leg2.coords)[1:])
            length_km = _line_length_m(line) / 1000

            code = {"bus": f"{k + 1}", "tram": f"{20 + k}", "rail": f"IC{k + 1}"}[mode]
            routes.append({
                "route_code": f"{mode[:1].upper()}{code}",
                "route_name": f"{mode.title()} {code} -- Utrecht Centraal",
                "mode": mode,
                "operator": str(r.choice(["Qbuzz", "U-OV", "NS", "Syntus"], p=[0.3, 0.35, 0.25, 0.1])),
                "color": colour,
                "headway_min": round(float(r.uniform(*headway_rng)), 1),
                "daily_ridership": int(r.uniform(*ridership_rng)),
                "length_km": round(length_km, 2),
                "geom": multi_wkt(line, "line"),
            })

            # Stops spaced along the route: dense for bus, sparse for rail.
            spacing_m = {"bus": 420, "tram": 600, "rail": 2600}[mode]
            n_stops = max(2, int(length_km * 1000 / spacing_m))
            for s in range(n_stops):
                pt = line.interpolate(s / max(n_stops - 1, 1), normalized=True)
                stop_idx += 1
                u = urbanity(pt.x, pt.y)
                stops.append({
                    "stop_code": f"ST{stop_idx:05d}",
                    "stop_name": f"{r.choice(TRACT_NAMES)} {r.choice(['', 'Noord', 'Zuid', 'Centrum', 'Station'])}".strip(),
                    "mode": mode,
                    "wheelchair_accessible": bool(r.random() < (0.95 if mode == "rail" else 0.72)),
                    "shelter": bool(r.random() < 0.68),
                    "daily_boardings": int(max(8, r.normal(
                        {"bus": 220, "tram": 900, "rail": 6500}[mode] * (0.35 + 1.4 * u),
                        {"bus": 130, "tram": 400, "rail": 3000}[mode],
                    ))),
                    "routes_served": int(r.integers(1, 6)),
                    "geom": point_wkt(pt.x, pt.y),
                })

    return routes, stops


def gen_isochrones(r: np.random.Generator, stops: list[dict], n_origins: int = 55) -> list[dict]:
    """Travel-time catchments around a sample of the busiest stops.

    Real isochrones follow the network; these are irregular blobs whose radius
    matches the mode's speed. The area/population relationship they produce is
    what the accessibility panel actually charts.
    """
    from shapely import wkt as shapely_wkt

    busiest = sorted(stops, key=lambda s: -s["daily_boardings"])[:n_origins]
    speeds_kmh = {"walk": 4.8, "bike": 15.0, "car": 27.0, "transit": 19.0}

    rows = []
    for s in busiest:
        pt = shapely_wkt.loads(s["geom"])
        for mode, speed in speeds_kmh.items():
            for minutes in (5, 10, 15, 30):
                # Detour factor: street networks never let you travel radially.
                radius_m = speed * 1000 / 60 * minutes * 0.62
                poly = irregular_polygon(r, pt.x, pt.y, radius_m,
                                         vertices=int(r.integers(9, 15)), jitter=0.22)
                area_km2 = radius_m**2 * math.pi / 1e6 * 0.92
                u = urbanity(pt.x, pt.y)
                pop = int(area_km2 * (9200 * u**2.2 + 60) * float(r.uniform(0.85, 1.15)))
                rows.append({
                    "origin_code": s["stop_code"],
                    "mode": mode,
                    "minutes": minutes,
                    "population_reached": pop,
                    "jobs_reached": int(pop * float(r.uniform(0.35, 0.95))),
                    "area_km2": round(area_km2, 3),
                    "geom": multi_wkt(poly, "polygon"),
                })
    return rows


def gen_traffic_counts(r: np.random.Generator, roads: list[dict], n_sites: int = 90) -> list[dict]:
    """Hourly counts with the classic twin-peak commuter profile."""
    # Fraction of daily traffic in each hour -- sums to ~1.
    profile = np.array([
        0.006, 0.004, 0.003, 0.004, 0.010, 0.028, 0.062, 0.094, 0.081, 0.055,
        0.044, 0.043, 0.046, 0.047, 0.051, 0.064, 0.088, 0.097, 0.073, 0.049,
        0.033, 0.023, 0.016, 0.010,
    ])
    profile = profile / profile.sum()

    # Only segments that actually carry traffic and have a name are counted.
    candidates = [
        (i + 1, road) for i, road in enumerate(roads)
        if road["aadt"] and road["aadt"] > 2000
    ]
    if not candidates:
        return []
    picks = r.choice(len(candidates), size=min(n_sites, len(candidates)), replace=False)

    rows = []
    count_dates = [date(2024, 5, 13) + timedelta(days=k) for k in range(5)]  # one work week
    for pi in picks:
        seg_id, road = candidates[int(pi)]
        for d in count_dates:
            for hour in range(24):
                vehicles = int(max(0, r.normal(road["aadt"] * profile[hour], road["aadt"] * 0.012)))
                # Speed collapses where hourly flow approaches capacity.
                load = vehicles / (road["aadt"] * profile.max())
                speed = road["maxspeed_kmh"] * (1 - 0.55 * min(1.0, load) * road["congestion_index"])
                rows.append({
                    "segment_id": seg_id,
                    "count_date": d.isoformat(),
                    "hour": hour,
                    "vehicles": vehicles,
                    "avg_speed_kmh": round(float(max(5.0, r.normal(speed, 2.5))), 1),
                })
    return rows


# ===========================================================================
# PROJECT 5 -- 3D TERRAIN
# ===========================================================================
BUILDING_TYPES = [
    # type, share, height mean, height sd
    ("residential", 0.56, 9.5, 3.4),
    ("commercial", 0.11, 14.0, 6.5),
    ("office", 0.09, 22.0, 11.0),
    ("retail", 0.09, 8.0, 3.0),
    ("industrial", 0.07, 11.0, 4.0),
    ("civic", 0.03, 15.0, 7.0),
    ("school", 0.03, 10.0, 3.0),
    ("hospital", 0.02, 24.0, 9.0),
]


def building_synth_attrs(
    r: np.random.Generator,
    lon: float,
    lat: float,
    footprint_m2: float,
    btype: str,
    levels_hint: int | None = None,
    height_hint: float | None = None,
) -> dict:
    """Everything about a building except identity/geometry -- shared by the
    synthetic generator and the real-data mapper, which supplies the real
    footprint/type and (when OSM has it tagged) a real height/level count,
    and wants the rest (roof, solar, energy label) modelled the same way."""
    u = urbanity(lon, lat)
    meta = {b[0]: b for b in BUILDING_TYPES}
    _, _, h_mean, h_sd = meta.get(btype, meta["residential"])

    if height_hint is not None:
        height = float(np.clip(height_hint, 3.0, 200.0))
    else:
        # Height decays with distance from the centre; the CBD keeps the towers.
        height = float(np.clip(r.normal(h_mean * (0.55 + 0.85 * u), h_sd), 3.0, 92.0))
    levels = int(levels_hint) if levels_hint else max(1, int(round(height / 3.2)))
    ground = elevation_scalar(lon, lat)

    # Taller buildings and open surroundings get more sun; the dense
    # core self-shades, which is exactly what the solar panel shows.
    shadow = float(np.clip(r.normal(0.16 + 0.42 * u - height / 320, 0.09), 0.02, 0.88))
    solar = float(np.clip(r.normal(1010 * (1 - shadow * 0.72), 70), 250, 1180))

    year_built = int(np.clip(r.choice(
        [r.integers(1400, 1900), r.integers(1900, 1945),
         r.integers(1945, 1980), r.integers(1980, 2005), r.integers(2005, 2026)],
        p=[0.05, 0.20, 0.31, 0.20, 0.24],
    ), 1400, 2026))
    # Newer stock is better insulated, so the energy label correlates with age.
    energy_bucket = int(np.clip((2026 - year_built) / 22 + r.normal(0, 1.1), 0, 6))

    return {
        "levels": levels,
        "height_m": round(height, 2),
        "min_height_m": 0.0,
        "ground_elev_m": round(ground, 2),
        "roof_shape": str(r.choice(["flat", "gabled", "hipped", "pyramidal", "dome"],
                                   p=[0.52, 0.30, 0.13, 0.04, 0.01])),
        "roof_color": str(r.choice(["#8b5a2b", "#4a5568", "#7f1d1d", "#334155"])),
        "footprint_m2": round(footprint_m2, 1),
        "volume_m3": round(footprint_m2 * height, 1),
        "year_built": year_built,
        "solar_potential_kwh_m2": round(solar, 1),
        "shadow_index": round(shadow, 3),
        "energy_class": "ABCDEFG"[energy_bucket],
    }


def gen_buildings(r: np.random.Generator, n: int = 11000) -> list[dict]:
    """Footprints in perimeter blocks -- the Dutch urban form -- with heights
    that decay from the centre and a solar model driven by height and shading."""
    types = [b[0] for b in BUILDING_TYPES]
    probs = np.array([b[1] for b in BUILDING_TYPES])
    probs = probs / probs.sum()

    buildings = []
    idx = 0
    # Perimeter blocks on a radial lattice. The count is set so the core reads
    # as a continuous urban fabric at z15 rather than scattered islands.
    n_blocks = 1100
    for b in range(n_blocks):
        if idx >= n:
            break
        a = float(r.uniform(0, 2 * math.pi))
        # sqrt(u) would spread blocks evenly by area; the exponent below biases
        # them toward the centre instead, which is how a real city is built.
        d = 9500 * float(r.random()) ** 1.35
        blon = CENTRE_LON + m_to_lon(d * math.cos(a))
        blat = CENTRE_LAT + m_to_lat(d * math.sin(a))
        if not (MIN_LON < blon < MAX_LON and MIN_LAT < blat < MAX_LAT):
            continue

        u = urbanity(blon, blat)
        per_block = max(3, int(r.normal(8 + 14 * u, 4)))
        block_rot = float(r.uniform(0, math.pi))
        block_w, block_h = float(r.uniform(60, 140)), float(r.uniform(60, 140))

        for k in range(per_block):
            if idx >= n:
                break
            # Position along the block perimeter.
            t = k / per_block
            side = int(t * 4)
            frac = (t * 4) - side
            hx, hy = block_w / 2, block_h / 2
            if side == 0:
                ox, oy = -hx + frac * block_w, -hy
            elif side == 1:
                ox, oy = hx, -hy + frac * block_h
            elif side == 2:
                ox, oy = hx - frac * block_w, hy
            else:
                ox, oy = -hx, hy - frac * block_h
            cos_r, sin_r = math.cos(block_rot), math.sin(block_rot)
            rx, ry = ox * cos_r - oy * sin_r, ox * sin_r + oy * cos_r
            lon = blon + m_to_lon(rx)
            lat = blat + m_to_lat(ry)
            if not (MIN_LON < lon < MAX_LON and MIN_LAT < lat < MAX_LAT):
                continue

            btype = str(r.choice(types, p=probs))
            fw = float(r.uniform(7, 16)) * (1 + 1.4 * u)
            fd = fw * float(r.uniform(1.1, 2.4))
            poly = rect_polygon(lon, lat, fw, fd, block_rot + float(r.normal(0, 0.06)))
            footprint = fw * fd

            idx += 1
            attrs = building_synth_attrs(r, lon, lat, footprint, btype)
            buildings.append({
                "osm_id": 200_000_000 + idx,
                "name": (f"{r.choice(['Huize', 'Kantoor', 'Complex', 'Gebouw'])} "
                         f"{r.choice(TRACT_NAMES)}") if r.random() < 0.10 else None,
                "building_type": btype,
                **attrs,
                "geom": multi_wkt(poly, "polygon"),
            })

    return buildings


def gen_contours(r: np.random.Generator, interval_m: int = 5) -> list[dict]:
    """Contours traced from the analytic elevation surface with marching
    squares, so they are genuinely consistent with the terrain model that
    buildings and fields sample their ground elevation from."""
    grid_n = 260
    lons = np.linspace(MIN_LON, MAX_LON, grid_n)
    lats = np.linspace(MIN_LAT, MAX_LAT, grid_n)
    lon_grid, lat_grid = np.meshgrid(lons, lats)
    z = np.asarray(elevation_at(lon_grid, lat_grid), dtype=float)

    rows = []
    z_min, z_max = float(z.min()), float(z.max())
    levels = np.arange(
        math.ceil(z_min / interval_m) * interval_m,
        math.floor(z_max / interval_m) * interval_m + 1,
        interval_m,
    )

    for level in levels:
        segments = _marching_squares(lons, lats, z, float(level))
        if not segments:
            continue
        merged = _merge_segments(segments)
        for line in merged:
            if len(line) < 3:
                continue
            rows.append({
                "elevation_m": float(level),
                "interval_m": interval_m,
                "is_index": bool(int(level) % (interval_m * 5) == 0),
                "geom": multi_wkt(LineString(line), "line"),
            })
    return rows


def _marching_squares(lons, lats, z, level: float) -> list[tuple]:
    """Minimal marching-squares contour extraction.

    Written out rather than pulled from matplotlib/scikit-image so the ETL
    dependency set stays at numpy + shapely.
    """
    segs = []
    ny, nx = z.shape
    for j in range(ny - 1):
        for i in range(nx - 1):
            # Cell corners, counter-clockwise from bottom-left
            z00, z10 = z[j, i], z[j, i + 1]
            z11, z01 = z[j + 1, i + 1], z[j + 1, i]
            corners = ((z00, lons[i], lats[j]), (z10, lons[i + 1], lats[j]),
                       (z11, lons[i + 1], lats[j + 1]), (z01, lons[i], lats[j + 1]))

            crossings = []
            for k in range(4):
                za, xa, ya = corners[k]
                zb, xb, yb = corners[(k + 1) % 4]
                if (za < level) != (zb < level):
                    t = (level - za) / (zb - za) if zb != za else 0.5
                    crossings.append((xa + (xb - xa) * t, ya + (yb - ya) * t))
            # A cell is crossed twice in the ordinary case; the ambiguous
            # four-crossing saddle is rare at this grid resolution, and joining
            # the first pair keeps the contour continuous either way.
            if len(crossings) >= 2:
                segs.append((crossings[0], crossings[1]))
    return segs


def _merge_segments(segments: list[tuple], tol: float = 1e-9) -> list[list]:
    """Chain marching-squares segments into polylines by endpoint matching."""
    from collections import defaultdict

    def key(pt):
        return (round(pt[0] / tol) if tol else pt[0], round(pt[1] / tol) if tol else pt[1])

    adjacency = defaultdict(list)
    for a, b in segments:
        adjacency[key(a)].append((a, b))
        adjacency[key(b)].append((b, a))

    used = set()
    lines = []
    for i, (a, b) in enumerate(segments):
        if i in used:
            continue
        used.add(i)
        line = [a, b]
        # Walk forward from the tail.
        changed = True
        while changed:
            changed = False
            tail = line[-1]
            for j, (c, d) in enumerate(segments):
                if j in used:
                    continue
                if key(c) == key(tail):
                    line.append(d)
                    used.add(j)
                    changed = True
                    break
                if key(d) == key(tail):
                    line.append(c)
                    used.add(j)
                    changed = True
                    break
        if len(line) >= 3:
            lines.append(line)
    return lines


def gen_elevation_bands(r: np.random.Generator) -> list[dict]:
    """Hypsometric bands: a coarse raster classified and dissolved per band."""
    grid_n = 150
    lons = np.linspace(MIN_LON, MAX_LON, grid_n)
    lats = np.linspace(MIN_LAT, MAX_LAT, grid_n)
    lon_step = lons[1] - lons[0]
    lat_step = lats[1] - lats[0]
    lon_grid, lat_grid = np.meshgrid(lons, lats)
    z = np.asarray(elevation_at(lon_grid, lat_grid), dtype=float)

    bands = [
        (-10, 0, "Below NAP", "#08519c"),
        (0, 5, "0-5 m", "#4292c6"),
        (5, 10, "5-10 m", "#9ecae1"),
        (10, 20, "10-20 m", "#c7e9c0"),
        (20, 30, "20-30 m", "#fdd0a2"),
        (30, 40, "30-40 m", "#e6550d"),
        (40, 100, "Above 40 m", "#a63603"),
    ]

    rows = []
    for lo, hi, label, colour in bands:
        mask = (z >= lo) & (z < hi)
        if not mask.any():
            continue
        cells = []
        jj, ii = np.nonzero(mask)
        for j, i in zip(jj, ii, strict=True):
            cells.append(box(lons[i], lats[j], lons[i] + lon_step, lats[j] + lat_step))
        merged = unary_union(cells)
        # Round the blocky raster edge into something map-like.
        merged = merged.buffer(lon_step * 0.28).buffer(-lon_step * 0.24)
        if merged.is_empty:
            continue
        area_km2 = int(mask.sum()) * (lon_step * 68.5) * (lat_step * 111.3)
        rows.append({
            "band_min_m": float(lo),
            "band_max_m": float(hi),
            "label": label,
            "color_hex": colour,
            "area_km2": round(area_km2, 3),
            "geom": multi_wkt(merged, "polygon"),
        })
    return rows


def gen_drainage(r: np.random.Generator, n: int = 90) -> list[dict]:
    """Streams flow downhill (westward here); ridges follow the crests."""
    rows = []
    for k in range(n):
        is_ridge = r.random() < 0.28
        if is_ridge:
            # Ridges run N-S along the Heuvelrug crest.
            lon = float(r.normal(5.25, 0.018))
            lat0 = float(r.uniform(MIN_LAT, MAX_LAT - 0.03))
            line = wiggly_line(r, (lon, lat0), (lon + float(r.normal(0, 0.006)), lat0 + 0.03),
                               segments=6, amplitude_m=90)
            ltype = str(r.choice(["ridge", "valley"], p=[0.7, 0.3]))
            order = None
        else:
            # Streams start on the slope and run west toward the polder.
            lon0 = float(r.uniform(5.14, 5.29))
            lat0 = float(r.uniform(MIN_LAT + 0.01, MAX_LAT - 0.01))
            lon1 = max(MIN_LON + 0.005, lon0 - float(r.uniform(0.03, 0.12)))
            line = wiggly_line(r, (lon0, lat0), (lon1, lat0 + float(r.normal(0, 0.012))),
                               segments=8, amplitude_m=160)
            ltype = str(r.choice(["stream", "river"], p=[0.82, 0.18]))
            order = int(r.integers(1, 5))

        mid = line.interpolate(0.5, normalized=True)
        start_z = elevation_scalar(*line.coords[0])
        end_z = elevation_scalar(*line.coords[-1])
        length_m = _line_length_m(line)
        rows.append({
            "name": f"{r.choice(['Kromme', 'Oude', 'Nieuwe', 'Zwarte', 'Hoge'])} "
                    f"{r.choice(['Rijn', 'Wetering', 'Beek', 'Grift', 'Vaart', 'Rug'])}"
                    if r.random() < 0.45 else None,
            "line_type": ltype,
            "stream_order": order,
            "length_m": round(length_m, 1),
            "slope_pct": round(abs(start_z - end_z) / max(length_m, 1) * 100, 3),
            "geom": multi_wkt(line, "line"),
        })
    return rows


def gen_elevation_profiles(r: np.random.Generator, buildings: list[dict]) -> list[dict]:
    """Three W-E transects sampling terrain and the building skyline above it."""
    from shapely import wkt as shapely_wkt
    from shapely.strtree import STRtree

    geoms = [shapely_wkt.loads(b["geom"]) for b in buildings]
    tree = STRtree(geoms)
    heights = [b["height_m"] for b in buildings]

    rows = []
    transects = [
        ("W-E through the centre", MIN_LAT + (MAX_LAT - MIN_LAT) * 0.55),
        ("W-E northern", MIN_LAT + (MAX_LAT - MIN_LAT) * 0.78),
        ("W-E southern", MIN_LAT + (MAX_LAT - MIN_LAT) * 0.28),
    ]
    for tid, (label, lat) in enumerate(transects, start=1):
        n_samples = 240
        for s in range(n_samples):
            t = s / (n_samples - 1)
            lon = MIN_LON + (MAX_LON - MIN_LON) * t
            terrain = elevation_scalar(lon, lat)
            # Surface = terrain + whatever building the ray passes through.
            pt = shapely_wkt.loads(f"POINT ({lon} {lat})")
            hits = tree.query(pt.buffer(m_to_lon(25)))
            extra = max((heights[int(h)] for h in hits), default=0.0)
            distance_m = t * (MAX_LON - MIN_LON) * 68_500
            rows.append({
                "transect_id": f"T{tid}-{label.replace(' ', '_')}",
                "seq": s,
                "distance_m": round(distance_m, 1),
                "elevation_m": round(terrain, 2),
                "surface_elev_m": round(terrain + extra, 2),
                "geom": point_wkt(lon, lat),
            })
    return rows


# ===========================================================================
# ORCHESTRATION
# ===========================================================================
def generate_all(real: bool = False) -> dict[str, list[dict]]:
    """Build every table's rows. Returns a dict keyed by 'schema.table'.

    When `real=True`, agri.fields, agri.irrigation_canals, parcel.parcels,
    transport.road_segments and terrain.buildings are fetched from real open
    sources (PDOK OGC API Features, OSM Overpass) scoped to REAL_DATA_BBOX
    instead of generated -- see etl/real_data.py. Everything else is
    unchanged and still synthetic across the full study area.
    """
    r = rng()
    out: dict[str, list[dict]] = {}

    if real:
        from etl.real_data import real_buildings, real_canals, real_fields, real_parcels, real_roads

    out["meta.study_area"] = [gen_study_area()]

    # --- agriculture --------------------------------------------------------
    fields = real_fields(r) if real else gen_fields(r)
    out["agri.fields"] = fields
    out["agri.irrigation_canals"] = real_canals(r) if real else gen_canals(r)
    out["agri.soil_samples"] = gen_soil_samples(r, fields)
    out["agri.field_ndvi_timeseries"] = gen_ndvi_series(r, len(fields))
    out["agri.field_embeddings"] = gen_field_embeddings(r, fields)

    # --- parcel -------------------------------------------------------------
    zoning = gen_zoning(r)
    out["parcel.zoning_districts"] = zoning
    parcels = real_parcels(r, zoning) if real else gen_parcels(r, zoning)
    out["parcel.parcels"] = parcels
    out["parcel.boundary_lines"] = gen_boundary_lines(r, parcels)
    out["parcel.sales_history"] = gen_sales_history(r, parcels)

    # --- demographics -------------------------------------------------------
    tracts = gen_tracts(r)
    out["demog.census_tracts"] = tracts
    out["demog.age_structure"] = gen_age_structure(r, tracts)
    out["demog.commute_flows"] = gen_commute_flows(r, tracts)
    out["demog.population_grid"] = gen_population_grid(r)

    # --- transport ----------------------------------------------------------
    roads = real_roads(r) if real else gen_roads(r)
    out["transport.road_segments"] = roads
    routes, stops = gen_transit(r)
    out["transport.transit_routes"] = routes
    out["transport.transit_stops"] = stops
    out["transport.isochrones"] = gen_isochrones(r, stops)
    out["transport.traffic_counts"] = gen_traffic_counts(r, roads)

    # --- terrain ------------------------------------------------------------
    buildings = real_buildings(r) if real else gen_buildings(r)
    out["terrain.buildings"] = buildings
    out["terrain.contours"] = gen_contours(r)
    out["terrain.drainage_lines"] = gen_drainage(r)
    out["terrain.elevation_bands"] = gen_elevation_bands(r)
    out["terrain.elevation_profile"] = gen_elevation_profiles(r, buildings)

    # --- remote sensing -----------------------------------------------------
    out["rs.scenes"] = gen_scenes(r)
    cells = gen_index_cells(r)
    out["rs.index_cells"] = cells
    out["rs.change_polygons"] = gen_change_polygons(r, cells)
    out["rs.subsidence_points"] = gen_subsidence_points(r)
    out["rs.deformation_profiles"] = gen_deformation_profiles(r)
    out["rs.water_extent"] = gen_water_extent(r)
    out["rs.index_timeseries"] = gen_index_timeseries(r)

    return out


# ===========================================================================
# PROJECT 6 -- REMOTE SENSING
# ===========================================================================
# Class names follow ESA WorldCover's vocabulary so the project's own
# classification and the WorldCover WMS overlay describe the same ground in
# the same words.
LANDCOVER_CLASSES = ("built_up", "cropland", "grassland", "tree_cover", "water", "bare")

#: (platform, sensor, resolution_m, revisit_days, level, optical?)
PLATFORMS = [
    ("Sentinel-2A", "MSI", 10.0, 10, "L2A", True),
    ("Sentinel-2B", "MSI", 10.0, 10, "L2A", True),
    ("Landsat-8", "OLI-TIRS", 30.0, 16, "L2SP", True),
    ("Landsat-9", "OLI-TIRS", 30.0, 16, "L2SP", True),
    ("Sentinel-1A", "C-SAR", 10.0, 12, "GRD-IW", False),
]

#: Monthly mean cloud fraction over the central Netherlands. High and
#: seasonal -- this is the number that makes an all-optical study of this
#: region unworkable and puts the SAR layers in the project.
CLOUD_BY_MONTH = [0.78, 0.72, 0.66, 0.58, 0.52, 0.50, 0.51, 0.52, 0.58, 0.68, 0.78, 0.81]

#: Beta concentration for the per-scene cloud draw. Deliberately below 2, which
#: makes the distribution U-shaped rather than peaked: skies are usually either
#: broken-clear or solidly overcast, and rarely sit at the monthly mean. That
#: shape is what puts the usable-scene rate at the ~18 % Sentinel-2 actually
#: achieves over the Netherlands; a peaked draw with the same mean yields under
#: 10 %, because it almost never produces a genuinely clear day.
CLOUD_BETA_K = 1.8
#: The threshold an optical analyst screens on. Over the Netherlands this
#: rejects most of the archive, which is the argument for the SAR layers.
USABLE_CLOUD_PCT = 30.0


# Thresholds on the shared `urbanity` surface. That surface decays slowly --
# it is still ~0.37 at the far corner of the bbox -- so "rural" sits well above
# 0.5 on it, the same calibration `sample_rural_point` already assumes. Picking
# these off the 0..1 range naively lands two thirds of the study area in
# built_up, which is not what the province looks like.
URBAN_CORE_U = 0.88
URBAN_FRINGE_U = 0.74

#: Height above which the eastern Heuvelrug reads as woodland rather than farm.
WOODED_RIDGE_M = 8.0


def _landcover_for(lon: float, lat: float, u: float, elev: float, r: np.random.Generator) -> str:
    """Assign a class from the same urbanity and elevation surfaces the other
    projects use, so the six datasets describe one coherent landscape.

    The mix these thresholds produce -- roughly a quarter built, a third
    grassland, a fifth arable, an eighth woodland -- is what ESA WorldCover
    actually reports for a Utrecht-sized window centred on the city.
    """
    if u > URBAN_CORE_U:
        return "built_up"
    if u > URBAN_FRINGE_U:
        # The fringe is mostly the parks, allotments and sports grounds that
        # separate Utrecht's neighbourhoods, not solid building.
        return "built_up" if r.random() < 0.25 else "grassland"
    # The Heuvelrug ridge in the east is the wooded part of the study area;
    # the western polder is grass and arable on drained peat.
    if elev > WOODED_RIDGE_M:
        return "tree_cover" if r.random() < 0.70 else "grassland"
    if elev < -0.5 and r.random() < 0.22:
        return "water"
    if r.random() < 0.03:
        return "bare"
    return "cropland" if r.random() < 0.48 else "grassland"


#: (ndvi, ndwi, ndbi, albedo) means per class, and the standard deviation used
#: for all four. Values are the ranges these indices actually occupy for
#: temperate European cover types.
CLASS_SPECTRA = {
    "built_up":   (0.19, -0.28,  0.14, 0.16),
    "cropland":   (0.66, -0.24, -0.19, 0.19),
    "grassland":  (0.71, -0.21, -0.22, 0.18),
    "tree_cover": (0.82, -0.18, -0.30, 0.11),
    "water":      (-0.06, 0.42, -0.12, 0.06),
    "bare":       (0.14, -0.30,  0.05, 0.24),
}

#: Land surface temperature offset per class, relative to the study-area mean.
#: Built-up runs hot, water and woodland run cool -- the urban heat island in
#: its simplest form, and the effect /heat-island regresses against NDVI.
CLASS_LST_OFFSET = {
    "built_up": 1.0, "bare": 2.1, "cropland": -0.4,
    "grassland": -0.8, "tree_cover": -2.4, "water": -3.6,
}

# Clear-sky summer daytime land surface temperature, the condition a Landsat
# thermal scene over the Netherlands is usable in. Calibrated so built-up land
# lands near 25 °C against roughly 19-20 °C over grass: a ~6 °C daytime surface
# UHI, which is the middle of the range published for mid-sized European
# cities. Note this is *surface* temperature from the thermal band, which runs
# several degrees above the 2 m air temperature a weather station reports.
LST_BASELINE_C = 22.0
#: Impervious cover stores heat; vegetation sheds it through evapotranspiration.
LST_PER_IMPERVIOUS_PCT = 0.030
LST_PER_NDVI = -2.6
#: Residual scatter. Without it the NDVI/LST correlation comes out near -0.95,
#: which no real scene produces -- published studies land around -0.5 to -0.75.
LST_NOISE_C = 1.35

#: Transitions the change detector is allowed to find, and how likely each is.
#: Every one is a process actually visible around Utrecht over a three-year
#: window. Weights are relative *within a destination class*, so what comes out
#: is dominated by grass/arable rotation rather than by urbanisation -- which
#: is the honest result: rotation is the largest gross signal any two-epoch
#: land-cover diff picks up, even though urbanisation is the larger *net* one.
#: Separating those two is exactly what the from/to matrix is for.
TRANSITIONS: list[tuple[str, str, str, float]] = [
    ("cropland", "built_up", "urbanisation", 0.34),
    ("grassland", "built_up", "urbanisation", 0.22),
    ("cropland", "grassland", "agricultural_shift", 0.13),
    ("grassland", "cropland", "agricultural_shift", 0.11),
    ("grassland", "tree_cover", "afforestation", 0.08),
    ("tree_cover", "grassland", "vegetation_loss", 0.05),
    ("bare", "built_up", "urbanisation", 0.04),
    ("grassland", "water", "water_gain", 0.03),
]

BASELINE_YEAR, DETECTED_YEAR = 2021, 2024

#: Share of cells whose class differs between the two epochs. Around 6 % over
#: three years is brisk but not absurd for a fast-growing urban region; the
#: point is to leave the transition matrix and the change layer enough to say
#: something with.
CHANGE_RATE = 0.06

#: Transitions indexed by destination class. Built this way rather than drawn
#: flat and rejected: a cell's present class is already fixed by the time the
#: change is assigned, so only transitions that *end* at that class are
#: coherent, and rejection sampling on the full table throws away ~90 % of
#: draws -- which quietly starves the change layer.
TRANSITIONS_BY_TO: dict[str, list[tuple[str, str, float]]] = {}
for _from, _to, _kind, _weight in TRANSITIONS:
    TRANSITIONS_BY_TO.setdefault(_to, []).append((_from, _kind, _weight))


def gen_index_cells(r: np.random.Generator, cell_m: int = 500) -> list[dict]:
    """The analysis grid: one row per cell carrying the zonal summary of every
    band the project uses.

    Deriving LST from imperviousness and NDVI rather than drawing it
    independently is the whole point -- it is what gives /heat-island a real
    correlation to find instead of noise.
    """
    rows: list[dict] = []
    lon_step, lat_step = m_to_lon(cell_m), m_to_lat(cell_m)
    n_lon = int((MAX_LON - MIN_LON) / lon_step)
    n_lat = int((MAX_LAT - MIN_LAT) / lat_step)
    cell_ha = (cell_m / 100.0) ** 2

    for i in range(n_lon):
        for j in range(n_lat):
            lon = MIN_LON + i * lon_step
            lat = MIN_LAT + j * lat_step
            clon, clat = lon + lon_step / 2, lat + lat_step / 2
            u = urbanity(clon, clat)
            elev = elevation_scalar(clon, clat)

            cls = _landcover_for(clon, clat, u, elev, r)
            ndvi_mu, ndwi_mu, ndbi_mu, albedo_mu = CLASS_SPECTRA[cls]

            ndvi = float(np.clip(r.normal(ndvi_mu, 0.07), -0.2, 0.95))
            ndwi = float(np.clip(r.normal(ndwi_mu, 0.06), -0.6, 0.8))
            ndbi = float(np.clip(r.normal(ndbi_mu, 0.06), -0.6, 0.5))
            # NBR separates healthy vegetation from bare and burnt ground; with
            # no fire history here it tracks NDVI with a wider spread.
            nbr = float(np.clip(ndvi * 0.82 + r.normal(0, 0.09), -0.5, 0.95))
            albedo = float(np.clip(r.normal(albedo_mu, 0.03), 0.02, 0.45))

            impervious = float(np.clip(100 * (0.93 * u**1.35 + r.normal(0, 0.05)), 0, 100))
            tree_cover = float(np.clip(
                100 * (0.85 if cls == "tree_cover" else 0.22 * max(0.0, ndvi)) + r.normal(0, 4),
                0, 100,
            ))

            lst = (
                LST_BASELINE_C
                + CLASS_LST_OFFSET[cls]
                + LST_PER_IMPERVIOUS_PCT * impervious
                + LST_PER_NDVI * ndvi
                + float(r.normal(0, LST_NOISE_C))
            )

            # Most ground does not change. Where it does, pick a transition
            # that ends at this cell's present class, so both epochs stay
            # coherent with the classification already assigned.
            prev, changed, ndvi_delta = cls, False, float(r.normal(0.0, 0.02))
            inbound = TRANSITIONS_BY_TO.get(cls)
            if inbound and r.random() < CHANGE_RATE:
                weights = np.array([w for _, _, w in inbound], dtype=float)
                pick = inbound[int(r.choice(len(inbound), p=weights / weights.sum()))]
                prev, changed = pick[0], True
                ndvi_delta = round(ndvi - CLASS_SPECTRA[prev][0], 3)

            rows.append({
                "cell_code": f"C{i:03d}{j:03d}",
                "ndvi": round(ndvi, 4),
                "ndwi": round(ndwi, 4),
                "ndbi": round(ndbi, 4),
                "nbr": round(nbr, 4),
                "lst_c": round(lst, 2),
                "lst_anomaly_c": 0.0,  # filled in below, once the mean is known
                "albedo": round(albedo, 4),
                "landcover_class": cls,
                "landcover_prev": prev,
                "changed": changed,
                "imperviousness_pct": round(impervious, 1),
                "tree_cover_pct": round(tree_cover, 1),
                "ndvi_delta": round(ndvi_delta, 4),
                "area_ha": round(cell_ha, 2),
                "geom": multi_wkt(Polygon([
                    (lon, lat), (lon + lon_step, lat),
                    (lon + lon_step, lat + lat_step), (lon, lat + lat_step), (lon, lat),
                ]), "polygon"),
            })

    # The anomaly is what the heat-island map actually reads, and it can only
    # be computed once every cell exists.
    mean_lst = sum(row["lst_c"] for row in rows) / max(1, len(rows))
    for row in rows:
        row["lst_anomaly_c"] = round(row["lst_c"] - mean_lst, 2)
    return rows


def gen_change_polygons(r: np.random.Generator, cells: list[dict], n: int = 140) -> list[dict]:
    """Dissolved change regions, the form a change-detection product reports.

    Seeded on cells the grid already flagged as changed, so the polygon layer
    and the transition matrix tell the same story rather than two unrelated
    ones.
    """
    changed = [c for c in cells if c["changed"]]
    if not changed:
        return []

    rows = []
    picks = r.choice(len(changed), size=min(n, len(changed)), replace=False)
    for k, pick in enumerate(picks, start=1):
        cell = changed[int(pick)]
        lon, lat = _centroid_of_multipolygon_wkt(cell["geom"])
        change_type = next(
            (t[2] for t in TRANSITIONS
             if t[0] == cell["landcover_prev"] and t[1] == cell["landcover_class"]),
            "other",
        )
        poly = irregular_polygon(r, lon, lat, float(r.uniform(180, 620)), jitter=0.3)
        area_ha = float(r.uniform(2.5, 46.0))
        rows.append({
            "change_code": f"CH{k:04d}",
            "from_class": cell["landcover_prev"],
            "to_class": cell["landcover_class"],
            "change_type": change_type,
            "detected_year": DETECTED_YEAR,
            "baseline_year": BASELINE_YEAR,
            "area_ha": round(area_ha, 2),
            # A bigger, more spectrally distinct patch is easier to call, so
            # confidence rises with area rather than being drawn flat.
            "confidence": round(float(np.clip(0.58 + area_ha / 130 + r.normal(0, 0.06), 0.4, 0.99)), 3),
            "ndvi_delta": cell["ndvi_delta"],
            "geom": multi_wkt(poly, "polygon"),
        })
    return rows


def gen_subsidence_points(r: np.random.Generator, n: int = 2400) -> list[dict]:
    """InSAR persistent scatterers.

    Soil follows elevation, which is what makes the by-soil chart meaningful:
    the western polder is drained peat, the Heuvelrug ridge in the east is
    glacial sand, and peat subsides roughly an order of magnitude faster
    because draining it lets the organic matter oxidise away.
    """
    rows = []
    for k in range(1, n + 1):
        lon, lat = sample_point(r)
        elev = elevation_scalar(lon, lat)
        u = urbanity(lon, lat)

        # Cut-offs chosen against the elevation surface so the mix lands near
        # the province's real soil map -- roughly a third peat in the western
        # polder, a third sand on the Heuvelrug, clay in between. Taking peat
        # as "everything below 1.5 m" instead puts 59 % of the study area on
        # peat, which would overstate the headline subsidence badly.
        if elev > 8:
            soil, vel_mu, vel_sd = "sand", -0.4, 0.5
        elif elev > 0.5:
            soil, vel_mu, vel_sd = "clay", -3.1, 1.4
        else:
            soil, vel_mu, vel_sd = "peat", -8.4, 2.9

        velocity = float(r.normal(vel_mu, vel_sd))
        # Persistent scatterers need a stable reflector, so coherence is high
        # on buildings and poor over vegetation and open water -- which is why
        # a PS dataset is dense over towns and sparse over farmland.
        coherence = float(np.clip(r.normal(0.55 + 0.34 * u, 0.11), 0.30, 0.99))

        if velocity <= -8:
            risk = "high"
        elif velocity <= -4:
            risk = "moderate"
        elif velocity <= -1.5:
            risk = "low"
        else:
            risk = "stable"

        rows.append({
            "ps_id": f"PS{k:05d}",
            "velocity_mm_yr": round(velocity, 2),
            # Six years of Sentinel-1, with a little non-linearity so the
            # cumulative figure is not just velocity times a constant.
            "cumulative_mm": round(velocity * 6.0 * float(r.uniform(0.92, 1.08)), 1),
            "coherence": round(coherence, 3),
            "std_mm_yr": round(float(np.clip(r.normal(0.9, 0.35), 0.15, 2.6)), 2),
            "height_m": round(elev + float(r.normal(0, 1.2)), 1),
            "soil_type": soil,
            "land_use": "urban" if u > 0.55 else ("suburban" if u > 0.28 else "rural"),
            "risk_class": risk,
            "geom": point_wkt(lon, lat),
        })
    return rows


def gen_water_extent(r: np.random.Generator, n_dates: int = 8) -> list[dict]:
    """SAR-delineated open water on eight dates through the year.

    Permanent water is the same footprint every pass; the seasonal and flood
    classes are the departure from it. February carries a real inundation
    event, which is when the Dutch river system actually peaks.
    """
    rows = []
    dates = [date(2024, 1, 18), date(2024, 2, 11), date(2024, 3, 16), date(2024, 5, 9),
             date(2024, 7, 2), date(2024, 9, 14), date(2024, 11, 8), date(2024, 12, 20)][:n_dates]

    for observed in dates:
        flood_event = observed.month == 2
        for kind, count in (("permanent", 14), ("seasonal", 9 if observed.month in (1, 2, 3, 11, 12) else 4),
                            ("flood", 11 if flood_event else 0)):
            for _ in range(count):
                if kind == "permanent":
                    lon, lat = sample_point(r)
                else:
                    # Seasonal and flood water sits in the low-lying polder,
                    # not on the ridge.
                    lon, lat = sample_rural_point(r, max_urbanity=0.5)
                    if elevation_scalar(lon, lat) > 4:
                        continue
                radius = float(r.uniform(150, 900)) * (1.6 if kind == "flood" else 1.0)
                poly = irregular_polygon(r, lon, lat, radius, jitter=0.4)
                rows.append({
                    "observed_on": observed,
                    "source": "Sentinel-1 GRD",
                    "water_type": kind,
                    "area_ha": round(float(r.uniform(4, 120)) * (2.2 if kind == "flood" else 1.0), 2),
                    # Open water is a specular reflector: it scatters the radar
                    # pulse away from the sensor, so it returns a very low
                    # backscatter, which is exactly how SAR finds it.
                    "backscatter_db": round(float(r.normal(-19.5, 1.8)), 1),
                    "confidence": round(float(np.clip(r.normal(0.86 if kind == "permanent" else 0.72, 0.08), 0.4, 0.99)), 3),
                    "geom": multi_wkt(poly, "polygon"),
                })
    return rows


def gen_scenes(r: np.random.Generator) -> list[dict]:
    """A year of acquisitions over the study area.

    Cloud is drawn from the real monthly climatology, and `usable` applies the
    30 % threshold an optical analyst would. Over the Netherlands that throws
    away most of the optical archive, which is the case for the SAR half of
    this project stated in data.
    """
    rows = []
    start = date(2024, 1, 1)
    k = 0
    for platform, sensor, res_m, revisit, level, optical in PLATFORMS:
        # Stagger the constellations so two satellites in a pair do not land
        # on the same day.
        offset = int(r.integers(0, revisit))
        day = offset
        while day < 365:
            acquired = start + timedelta(days=day)
            month = acquired.month
            if optical:
                # Beta shaped to the month's mean cloud fraction rather than
                # scaled off a symmetric draw: the tail matters more than the
                # mean here, because "how often is it clear enough to use" is
                # the question, and a symmetric draw answers it far too
                # optimistically.
                p = CLOUD_BY_MONTH[month - 1]
                cloud = float(np.clip(r.beta(CLOUD_BETA_K * p, CLOUD_BETA_K * (1 - p)) * 100, 0, 100))
                usable = cloud < USABLE_CLOUD_PCT
                orbit = "descending"
                sun_elev = round(14 + 44 * math.sin(math.pi * (day - 80) / 365) ** 2, 1)
            else:
                # SAR does not care about cloud; the column stays 0 rather than
                # NULL so "mean cloud by platform" is still answerable.
                cloud, usable, sun_elev = 0.0, True, None
                orbit = "ascending" if (day // revisit) % 2 == 0 else "descending"

            k += 1
            # Footprints are wider than the study area and drift with the
            # orbit track, the way a real tile grid overlaps its neighbours.
            pad_lon, pad_lat = m_to_lon(9000), m_to_lat(9000)
            drift = m_to_lon(float(r.normal(0, 2600)))
            poly = box(
                MIN_LON - pad_lon + drift, MIN_LAT - pad_lat,
                MAX_LON + pad_lon + drift, MAX_LAT + pad_lat,
            )
            rows.append({
                "scene_id": f"{platform.replace('-', '')}_{acquired:%Y%m%d}_{k:04d}",
                "platform": platform,
                "sensor": sensor,
                "acquired_at": datetime(acquired.year, acquired.month, acquired.day, 10, 42, tzinfo=UTC),
                "cloud_pct": round(cloud, 1),
                "sun_elevation_deg": sun_elev,
                "orbit_direction": orbit,
                "processing_level": level,
                "resolution_m": res_m,
                "usable": usable,
                "geom": multi_wkt(poly, "polygon"),
            })
            day += revisit
    return rows


def gen_index_timeseries(r: np.random.Generator) -> list[dict]:
    """Ten-day composites of NDVI, NDWI and NDBI per land-cover class.

    The phenology is the signal worth showing: cropland swings from bare soil
    to closed canopy and back inside one season, woodland barely moves, and
    built-up land is flat all year. That contrast is what makes a single-date
    classification unreliable and a time series worth building.
    """
    rows = []
    for step in range(37):
        observed = date(2024, 1, 5) + timedelta(days=10 * step)
        doy = observed.timetuple().tm_yday
        # Peaks near day 190 (early July) for the northern hemisphere.
        season = math.sin(math.pi * max(0.0, min(1.0, (doy - 40) / 250)))

        for cls in LANDCOVER_CLASSES:
            base_ndvi, base_ndwi, base_ndbi, _ = CLASS_SPECTRA[cls]
            amplitude = {
                "cropland": 0.46, "grassland": 0.24, "tree_cover": 0.20,
                "built_up": 0.05, "bare": 0.06, "water": 0.02,
            }[cls]
            winter_floor = base_ndvi - amplitude * 0.65

            for index_name, value in (
                ("ndvi", winter_floor + amplitude * season + float(r.normal(0, 0.015))),
                # Wetter in winter, drier at the peak of the growing season.
                ("ndwi", base_ndwi + 0.07 * (1 - season) + float(r.normal(0, 0.012))),
                # Built-up land is a fixed surface; NDBI barely moves.
                ("ndbi", base_ndbi - 0.04 * season + float(r.normal(0, 0.010))),
            ):
                spread = 0.05 + 0.06 * amplitude
                rows.append({
                    "observed_on": observed,
                    "landcover_class": cls,
                    "index_name": index_name,
                    "value": round(float(np.clip(value, -0.6, 0.95)), 4),
                    "p10": round(float(np.clip(value - spread, -0.7, 0.95)), 4),
                    "p90": round(float(np.clip(value + spread, -0.6, 0.99)), 4),
                    "sample_n": int(r.integers(120, 620)),
                    "cloud_pct": round(CLOUD_BY_MONTH[observed.month - 1] * 100, 1),
                })
    return rows


#: Corridors the deformation profiles run along. Chosen to cross the soil
#: gradient rather than sit inside one band: a line wholly on sand says nothing,
#: and the interesting engineering case is the asset that spans a boundary.
PROFILE_ASSETS: list[tuple[str, str, tuple[float, float], tuple[float, float]]] = [
    ("canal", "Amsterdam-Rijnkanaal", (5.075, 52.170), (5.115, 51.995)),
    ("canal", "Merwedekanaal", (5.100, 52.115), (5.085, 52.010)),
    ("canal", "Vecht corridor", (5.010, 52.175), (5.045, 52.070)),
    ("dike", "Lekdijk west", (4.975, 52.005), (5.180, 51.990)),
    ("dike", "Kromme Rijn embankment", (5.140, 52.055), (5.290, 52.020)),
    ("rail", "Utrecht - Amsterdam line", (5.110, 52.090), (5.060, 52.178)),
    ("rail", "Utrecht - Arnhem line", (5.115, 52.089), (5.298, 52.055)),
    ("road", "A2 corridor", (5.055, 52.175), (5.090, 51.985)),
    ("road", "A12 corridor", (4.960, 52.070), (5.298, 52.048)),
    ("road", "N230 north ring", (5.040, 52.140), (5.200, 52.135)),
    # Short corridors that stay inside one soil band. Without these every
    # profile spans the gradient and the low/stable risk classes never appear,
    # which would make the risk breakdown look like a threshold problem rather
    # than the real distribution.
    ("dike", "Heuvelrug ridge road", (5.252, 52.105), (5.288, 52.092)),
    ("rail", "Zeist branch", (5.238, 52.088), (5.272, 52.070)),
    ("canal", "Polder drainage main", (4.966, 52.108), (4.998, 52.132)),
    ("dike", "Westbroek polder dike", (4.972, 52.145), (5.006, 52.160)),
]


def gen_deformation_profiles(r: np.random.Generator) -> list[dict]:
    """Ground motion aggregated along each corridor.

    Velocities are sampled from the same elevation-driven soil model the
    persistent scatterers use, so a profile crossing the polder reports the
    peat signal the point cloud shows underneath it -- the two layers cannot
    disagree.
    """
    rows = []
    for idx, (asset_type, name, start, end) in enumerate(PROFILE_ASSETS, start=1):
        line = wiggly_line(r, start, end, segments=14, amplitude_m=260)

        # Two quantities per sample, and keeping them apart is the whole point.
        # `expected` is the soil-driven settlement rate at that spot; `measured`
        # adds the scatter a real PS solution carries.
        expected, measured, soils = [], [], []
        for t in np.linspace(0, 1, 24):
            pt = line.interpolate(float(t), normalized=True)
            elev = elevation_scalar(pt.x, pt.y)
            if elev > 8:
                soil, mu, sd = "sand", -0.4, 0.5
            elif elev > 0.5:
                soil, mu, sd = "clay", -3.1, 1.4
            else:
                soil, mu, sd = "peat", -8.4, 2.9
            # A little within-band variation, so a corridor sitting wholly on
            # one soil still differs slightly end to end, as ground does.
            mu_here = mu + float(r.normal(0, 0.35))
            expected.append(mu_here)
            measured.append(mu_here + float(r.normal(0, sd)))
            soils.append(soil)

        mean_v = float(np.mean(measured))
        min_v = float(np.min(measured))
        # Differential comes off the expected profile, not the measured one.
        # Taking max-minus-min of the noisy samples measures the scatter of the
        # InSAR solution -- with peat's sigma near 3 mm that alone spans ~11 mm
        # and rates every corridor "high", burying the real signal. The
        # engineering question is whether the asset crosses a soil boundary,
        # and that lives in the expected profile.
        differential = float(np.max(expected) - np.min(expected))

        if differential >= 7:
            risk = "high"
        elif differential >= 4:
            risk = "moderate"
        elif differential >= 1.5:
            risk = "low"
        else:
            risk = "stable"

        rows.append({
            "profile_code": f"DP{idx:03d}",
            "name": name,
            "asset_type": asset_type,
            "length_m": round(_line_length_m(line), 1),
            "mean_velocity_mm_yr": round(mean_v, 2),
            "min_velocity_mm_yr": round(min_v, 2),
            "differential_mm_yr": round(differential, 2),
            "ps_count": int(r.integers(120, 900)),
            "dominant_soil": max(set(soils), key=soils.count),
            "risk_class": risk,
            "geom": multi_wkt(line, "line"),
        })
    return rows


# ===========================================================================
# ALPHAEARTH SATELLITE EMBEDDINGS (agriculture)
# ===========================================================================
# Google's AlphaEarth Foundations model reduces a year of Sentinel-1,
# Sentinel-2 and Landsat observations over a 10 m pixel to 64 numbers on the
# unit sphere. The real pipeline reads the published COGs and takes a
# per-parcel mean; this stands in for that step.
#
# The whole point of an embedding is that *distance means something*, so
# drawing 64 random numbers per parcel would be worse than useless -- it would
# produce a similarity search that returns noise while looking like it works.
# Instead each parcel's vector is built as a weighted sum of latent "concept"
# directions, then normalised. Two parcels growing the same crop on the same
# soil therefore end up genuinely close, and every downstream result -- the
# similarity ranking, the few-shot classifier, the rotation detector -- is
# measuring structure that is really in the data.

EMBEDDING_DIM = 64

#: How much each attribute contributes before normalisation. Crop dominates,
#: because an annual embedding is mostly a phenology curve and phenology is
#: mostly what crop is growing. Soil is next -- it drives the whole season's
#: vigour. Management is a smaller, real signal.
CONCEPT_WEIGHTS = {
    "crop": 1.00,
    "soil": 0.55,
    "wetness": 0.30,
    "vigour": 0.28,
    "irrigated": 0.18,
    "organic": 0.16,
    "parcel_size": 0.10,
}

# Residual variation splits in two, and keeping them apart is what makes both
# the similarity search and the rotation detector behave like the real thing.
#
#: Persistent: drainage, field history, cultivar preference, the farmer's own
#: habits. Drawn once per parcel and reused every year, so it separates two
#: otherwise-identical parcels without making the same parcel look different
#: from one year to the next.
FIELD_NOISE = 1.55
#: Year-specific: weather, sowing date, sensor and atmospheric residue. Redrawn
#: annually. Folding this into one undifferentiated noise term would force a
#: choice between "fields are hard to tell apart" and "a parcel resembles
#: itself across years", when real embeddings do both at once.
YEAR_NOISE = 0.62

#: Years the embedding dataset covers here. AlphaEarth itself runs 2017 to
#: present; six years is enough to show rotation without inflating the table.
EMBEDDING_YEARS = (2019, 2020, 2021, 2022, 2023, 2024)

#: Crops that rotate, and how likely a parcel is to change crop year to year.
#: Dutch grassland is semi-permanent -- dairy pasture stays put for years --
#: while arable land rotates hard, which is exactly the contrast the rotation
#: analysis is meant to surface.
ROTATION_PROBABILITY = {
    "grassland": 0.06,
    "maize": 0.42,
    "wheat": 0.66,
    "potato": 0.85,
    "sugarbeet": 0.80,
    "barley": 0.68,
    "rapeseed": 0.72,
}

#: Realistic Dutch arable sequences: potato and sugarbeet are demanding and are
#: separated by cereals, which is what a rotation is for.
ROTATION_SUCCESSORS = {
    "grassland": ["grassland", "maize"],
    "maize": ["maize", "grassland", "wheat"],
    "wheat": ["potato", "sugarbeet", "barley", "maize"],
    "potato": ["wheat", "barley", "sugarbeet"],
    "sugarbeet": ["wheat", "barley", "potato"],
    "barley": ["potato", "sugarbeet", "rapeseed", "wheat"],
    "rapeseed": ["wheat", "barley"],
}


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


#: Crops that look alike from orbit, because they *are* alike: same sowing
#: window, same canopy development, same harvest. A real embedding places them
#: close together, and a real classifier confuses them -- winter cereals with
#: each other far more often than with a root crop.
CROP_GROUPS = {
    "fodder": ["grassland", "maize"],
    "winter_cereal": ["wheat", "barley", "rapeseed"],
    "root": ["potato", "sugarbeet"],
}

#: How much of a crop's direction is its group rather than itself. Sets the
#: within-group cosine to share^2 / (share^2 + (1-share)^2) -- about 0.6 here.
#: Drawing every crop independently instead makes the classes mutually
#: orthogonal, and a classifier then scores ~100 %: not a good result, just an
#: artefact of pretending potatoes and barley are unrelated.
CROP_GROUP_SHARE = 0.72


def _concept_basis(r: np.random.Generator, names: list[str]) -> dict[str, np.ndarray]:
    """One unit direction per concept.

    Random directions in 64 dimensions are very nearly orthogonal -- the
    expected cosine between two of them is 0 with a standard deviation of
    1/sqrt(64) = 0.125 -- so unrelated concepts stay separable without the cost
    and the false tidiness of forcing an exact orthonormal basis. Crop
    directions are the exception and are built correlated, below.
    """
    return {name: _unit(r.normal(0, 1, EMBEDDING_DIM)) for name in names}


def _crop_basis(r: np.random.Generator, crops: list[str]) -> dict[str, np.ndarray]:
    """Crop directions that share a common component within an agronomic group."""
    group_of = {c: g for g, members in CROP_GROUPS.items() for c in members}
    group_dirs = {g: _unit(r.normal(0, 1, EMBEDDING_DIM)) for g in CROP_GROUPS}
    out = {}
    for crop in crops:
        own = _unit(r.normal(0, 1, EMBEDDING_DIM))
        group = group_dirs.get(group_of.get(crop, ""), own)
        out[crop] = _unit(CROP_GROUP_SHARE * group + (1 - CROP_GROUP_SHARE) * own)
    return out


def gen_field_embeddings(r: np.random.Generator, fields: list[dict]) -> list[dict]:
    """A 64-dim unit vector per parcel per year, plus that year's declared crop."""
    crops = [c[0] for c in CROPS]
    textures = [t[0] for t in SOIL_TEXTURES]
    basis = _concept_basis(
        r,
        [f"soil:{t}" for t in textures]
        + ["wetness", "vigour", "irrigated", "organic", "parcel_size"],
    )
    basis |= {f"crop:{c}": v for c, v in _crop_basis(r, crops).items()}

    rows: list[dict] = []
    for field_id, field in enumerate(fields, start=1):
        # Walk the rotation backwards from the 2024 declaration, so the crop
        # recorded on agri.fields stays the final year's truth.
        crop_by_year: dict[int, str] = {EMBEDDING_YEARS[-1]: field["crop_type"]}
        crop = field["crop_type"]
        for year in reversed(EMBEDDING_YEARS[:-1]):
            if r.random() < ROTATION_PROBABILITY.get(crop, 0.5):
                crop = str(r.choice(ROTATION_SUCCESSORS.get(crop, crops)))
            crop_by_year[year] = crop

        # One draw per parcel, shared by every year.
        field_residual = r.normal(0, FIELD_NOISE / math.sqrt(EMBEDDING_DIM), EMBEDDING_DIM)

        texture = field["soil_texture"]
        # Normalise the continuous attributes to roughly [-1, 1] so one of them
        # cannot dominate the sum through its units alone.
        wetness = (field["soil_clay_pct"] - 25.0) / 25.0
        vigour = (field["ndvi_mean"] - 0.62) / 0.25
        size = min(1.0, field["area_ha"] / 8.0) - 0.5

        for year in EMBEDDING_YEARS:
            year_crop = crop_by_year[year]
            vec = CONCEPT_WEIGHTS["crop"] * basis[f"crop:{year_crop}"]
            vec = vec + CONCEPT_WEIGHTS["soil"] * basis[f"soil:{texture}"]
            vec = vec + CONCEPT_WEIGHTS["wetness"] * wetness * basis["wetness"]
            # Season-to-season weather moves vigour around even on an
            # unchanged parcel; without it, an unrotated field would be
            # bit-identical across years and the rotation detector would have a
            # perfectly separable problem, which is not the real one.
            year_vigour = vigour + float(r.normal(0, 0.35))
            vec = vec + CONCEPT_WEIGHTS["vigour"] * year_vigour * basis["vigour"]
            if field["irrigated"]:
                vec = vec + CONCEPT_WEIGHTS["irrigated"] * basis["irrigated"]
            if field["organic"]:
                vec = vec + CONCEPT_WEIGHTS["organic"] * basis["organic"]
            vec = vec + CONCEPT_WEIGHTS["parcel_size"] * size * basis["parcel_size"]
            vec = vec + field_residual
            vec = vec + r.normal(0, YEAR_NOISE / math.sqrt(EMBEDDING_DIM), EMBEDDING_DIM)

            rows.append({
                "field_id": field_id,
                "year": year,
                # Stored at full precision deliberately. Rounding saves nothing
                # -- a float8 is eight bytes whatever its decimal places -- and
                # costs enough accuracy to trip the unit-length check
                # constraint, since the error accumulates over all 64 terms of
                # the self-dot-product.
                "embedding": [float(x) for x in _unit(vec)],
                "declared_crop": year_crop,
                # A 10 m grid over a parcel of this size, minus the edge pixels
                # a real zonal mean would drop for mixed-pixel contamination.
                "pixel_count": max(4, int(field["area_ha"] * 10_000 / 100 * 0.82)),
                "source": "AlphaEarth Foundations V1",
            })
    return rows
