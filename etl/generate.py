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
from datetime import date, timedelta

import numpy as np
from shapely.geometry import LineString, Polygon, box
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


def gen_fields(r: np.random.Generator, n: int = 900) -> list[dict]:
    crops, weights = [c[0] for c in CROPS], np.array([c[1] for c in CROPS])
    weights = weights / weights.sum()
    crop_meta = {c[0]: c for c in CROPS}

    fields = []
    for i in range(n):
        lon, lat = sample_rural_point(r, max_urbanity=0.28)

        # Dutch field parcels are long and narrow ("slagenlandschap"), aligned
        # with the drainage ditches, so the aspect ratio is deliberately extreme.
        width = float(r.uniform(60, 190))
        height = width * float(r.uniform(2.2, 6.5))
        rotation = float(r.normal(0.35, 0.45))  # broadly NE-SW
        poly = rect_polygon(lon, lat, width, height, rotation)
        area_ha = round(width * height / 10_000, 3)

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

        fields.append(
            {
                "field_code": f"NL-UT-{i + 1:05d}",
                "farm_name": f"{r.choice(FARM_PREFIX)} {r.choice(FARM_SUFFIX)}",
                "crop_type": crop,
                "crop_year": 2024,
                "area_ha": area_ha,
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
        lon, lat = sample_rural_point(r, max_urbanity=0.25)
        end = (lon + float(r.uniform(-0.010, 0.010)), lat + float(r.uniform(0.004, 0.014)))
        line = wiggly_line(r, (lon, lat), end, segments=4, amplitude_m=60)
        idx += 1
        canals.append(_canal_row(r, idx, line, str(r.choice(["tertiary", "drainage"], p=[0.6, 0.4]))))

    return canals[:n]


CANAL_NAMES = [
    "Leidsche Rijn", "Kromme Rijn", "Vaartsche Rijn", "Oude Rijn", "Merwedekanaal",
    "Enkele Wiericke", "Doorslag", "Heldam", "Bijleveld", "Haarrijn", "Zwarte Water",
]


def _canal_row(r: np.random.Generator, idx: int, line: LineString, canal_type: str) -> dict:
    length_m = _line_length_m(line)
    capacity = {
        "primary": r.uniform(8, 26),
        "secondary": r.uniform(2.5, 8),
        "tertiary": r.uniform(0.4, 2.5),
        "drainage": r.uniform(0.2, 1.6),
    }[canal_type]
    return {
        "canal_code": f"CNL-{idx:04d}",
        "name": (
            f"{r.choice(CANAL_NAMES)} {'watergang' if canal_type != 'primary' else 'kanaal'}"
            if canal_type in ("primary", "secondary")
            else None
        ),
        "canal_type": canal_type,
        "lined": bool(r.random() < (0.7 if canal_type == "primary" else 0.2)),
        "capacity_m3s": round(float(capacity), 2),
        "length_m": round(length_m, 1),
        "condition": str(r.choice(["good", "fair", "poor"], p=[0.5, 0.36, 0.14])),
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


def gen_parcels(r: np.random.Generator, zoning: list[dict], n: int = 3200) -> list[dict]:
    """Parcels laid out in blocks inside each zoning district.

    Value is driven by distance to the centre, zoning category and building
    age, which is what makes the value-distribution and price-trend panels
    show recognisable structure rather than noise.
    """
    from shapely import wkt as shapely_wkt

    parcels = []
    zones = [
        (i + 1, z, shapely_wkt.loads(z["geom"]))
        for i, z in enumerate(zoning)
        if z["zone_category"] not in ("agricultural", "open_space")
    ]
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

            uses, probs = LAND_USE_BY_ZONE[cat]
            land_use = str(r.choice(uses, p=probs))

            d_centre = dist_from_centre_m(lon, lat)
            u = urbanity(lon, lat)

            if land_use == "vacant":
                far = 0.0
                floors, year_built, bld_area, units, n_bld = 0, None, 0.0, 0, 0
            else:
                far = float(np.clip(r.normal(z["max_far"] * 0.62, z["max_far"] * 0.26), 0.05, z["max_far"] * 1.18))
                bld_area = lot_area * far
                floors = max(1, int(round(float(r.normal(max(1.0, far / 0.55), 1.1)))))
                floors = min(floors, max(1, int(z["max_height_m"] / 3.2)))
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
            land_value = lot_area * value_per_m2
            improvement = bld_area * value_per_m2 * 0.55
            assessed = land_value + improvement

            idx += 1
            sale_date = (
                (date(2015, 1, 1) + timedelta(days=int(r.integers(0, 3800)))).isoformat()
                if r.random() < 0.62 else None
            )
            parcels.append(
                {
                    "parcel_pin": f"UT-{idx:06d}",
                    "address": f"{int(r.integers(1, 320))} {r.choice(STREETS)}",
                    "district": z["zone_name"].split()[0],
                    "zone_code": z["zone_code"],
                    "zoning_district_id": zid,
                    "land_use": land_use,
                    "owner_type": str(r.choice(
                        ["private", "corporate", "municipal", "state", "ngo"],
                        p=[0.58, 0.26, 0.09, 0.04, 0.03],
                    )),
                    "lot_area_m2": round(lot_area, 1),
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
    """Tracts laid out on a jittered hex-ish grid covering the whole bbox, so
    the choropleth tiles the study area without gaps."""
    tracts = []
    cols, rows_n = 10, 6
    lon_step = (MAX_LON - MIN_LON) / cols
    lat_step = (MAX_LAT - MIN_LAT) / rows_n

    idx = 0
    for i in range(cols):
        for j in range(rows_n):
            if idx >= n:
                break
            # Offset alternate rows so cells are not a perfect lattice.
            lon = MIN_LON + (i + 0.5 + (0.25 if j % 2 else 0)) * lon_step
            lat = MIN_LAT + (j + 0.5) * lat_step
            lon = min(lon, MAX_LON - lon_step * 0.3)

            poly = irregular_polygon(
                r, lon, lat,
                radius_m=max(lon_step, lat_step) * 55_000,
                vertices=int(r.integers(6, 10)), jitter=0.16,
            )
            u = urbanity(lon, lat)
            area_km2 = round(float(r.uniform(1.4, 6.5)) * (0.55 + (1 - u)), 3)

            # Density spans three orders of magnitude between the medieval core
            # and the Lopikerwaard polder -- the real Utrecht range.
            density = float(np.clip(r.lognormal(math.log(120 + 9200 * u**2.1), 0.42), 12, 16000))
            population = int(density * area_km2)
            households = int(population / float(r.uniform(1.9, 2.7)))

            # Age structure shifts with urbanity: students in the core,
            # families in the suburbs, retirees in the villages.
            pct_under_15 = float(np.clip(r.normal(19 - 7 * u + 3 * (1 - u), 2.4), 6, 30))
            pct_15_29 = float(np.clip(r.normal(14 + 17 * u, 3.5), 8, 46))
            pct_65_plus = float(np.clip(r.normal(21 - 11 * u, 3.8), 4, 34))
            pct_30_44 = float(np.clip(r.normal(22 + 2 * u, 3.0), 12, 34))
            pct_45_64 = max(4.0, 100 - pct_under_15 - pct_15_29 - pct_30_44 - pct_65_plus)
            total = pct_under_15 + pct_15_29 + pct_30_44 + pct_45_64 + pct_65_plus
            scale = 100 / total
            pct_under_15, pct_15_29, pct_30_44, pct_45_64, pct_65_plus = (
                v * scale for v in (pct_under_15, pct_15_29, pct_30_44, pct_45_64, pct_65_plus)
            )
            median_age = 12 * pct_under_15 / 100 + 23 * pct_15_29 / 100 + 37 * pct_30_44 / 100 \
                + 54 * pct_45_64 / 100 + 73 * pct_65_plus / 100

            # Education drives income; income drives rent and deprivation.
            tertiary = float(np.clip(r.normal(30 + 34 * u, 8.5), 8, 78))
            income = float(np.clip(r.normal(24_000 + 520 * tertiary, 5200), 16_000, 82_000))
            unemployment = float(np.clip(r.normal(7.4 - 0.062 * tertiary, 1.2), 0.8, 12.5))
            owner_occ = float(np.clip(r.normal(78 - 46 * u, 10), 12, 96))
            rent = float(np.clip(r.normal(560 + 5.6 * tertiary + 260 * u, 90), 420, 1650))
            deprivation = float(np.clip(
                55 - (income - 24_000) / 700 + unemployment * 2.2 + r.normal(0, 4.5), 2, 98
            ))

            idx += 1
            tracts.append(
                {
                    "tract_code": f"BU{idx:06d}",
                    "tract_name": TRACT_NAMES[(idx - 1) % len(TRACT_NAMES)],
                    "district": DISTRICTS[int(r.integers(0, len(DISTRICTS)))] if u < 0.3
                                else DISTRICTS[int(r.integers(0, 6))],
                    "population": population,
                    "households": households,
                    "avg_household_size": round(population / max(households, 1), 2),
                    "area_km2": area_km2,
                    "density_km2": round(density, 1),
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
                    "geom": multi_wkt(poly, "polygon"),
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


def gen_roads(r: np.random.Generator) -> list[dict]:
    """A radial-plus-ring network: motorway ring, radial trunks, an urban grid
    and rural connectors. Geometry is generated, but the class hierarchy and
    the AADT/congestion relationship mirror a real Dutch city."""
    roads: list[dict] = []
    idx = 0

    def add(line: LineString, hclass: str, name: str | None, fclass: int) -> None:
        nonlocal idx
        idx += 1
        lanes, speed, aadt_mean, cong_base = HIGHWAY_PROFILE[hclass]
        length_m = _line_length_m(line)
        mid = line.interpolate(0.5, normalized=True)
        u = urbanity(mid.x, mid.y)

        aadt = int(max(0, r.normal(aadt_mean * (0.45 + 0.95 * u), aadt_mean * 0.28))) if aadt_mean else None
        # Congestion rises with urbanity and with how loaded the link is.
        load = (aadt / (aadt_mean or 1)) if aadt else 0
        congestion = float(np.clip(r.normal(cong_base * (0.55 + 0.75 * u) + 0.12 * load, 0.09), 0.01, 0.98))
        maxspeed = int(np.clip(r.normal(speed, 6), 5, 130))
        peak_speed = round(maxspeed * (1 - congestion * 0.62), 1)

        roads.append({
            "osm_id": 100_000_000 + idx,
            "name": name,
            "highway_class": hclass,
            "functional_class": fclass,
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
        lon, lat = sample_rural_point(r, max_urbanity=0.35)
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


def gen_buildings(r: np.random.Generator, n: int = 5200) -> list[dict]:
    """Footprints in perimeter blocks -- the Dutch urban form -- with heights
    that decay from the centre and a solar model driven by height and shading."""
    types = [b[0] for b in BUILDING_TYPES]
    probs = np.array([b[1] for b in BUILDING_TYPES])
    probs = probs / probs.sum()
    meta = {b[0]: b for b in BUILDING_TYPES}

    buildings = []
    idx = 0
    # Blocks on a radial lattice; buildings line the block perimeter.
    n_blocks = 300
    for b in range(n_blocks):
        if idx >= n:
            break
        a = float(r.uniform(0, 2 * math.pi))
        # Bias blocks toward the centre -- sqrt gives uniform area density.
        d = 9000 * math.sqrt(float(r.random()))
        blon = CENTRE_LON + m_to_lon(d * math.cos(a))
        blat = CENTRE_LAT + m_to_lat(d * math.sin(a))
        if not (MIN_LON < blon < MAX_LON and MIN_LAT < blat < MAX_LAT):
            continue

        u = urbanity(blon, blat)
        per_block = max(2, int(r.normal(6 + 16 * u, 4)))
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
            _, _, h_mean, h_sd = meta[btype]
            # Height decays with distance from the centre; the CBD keeps the towers.
            height = float(np.clip(r.normal(h_mean * (0.55 + 0.85 * u), h_sd), 3.0, 92.0))
            levels = max(1, int(round(height / 3.2)))

            fw = float(r.uniform(7, 16)) * (1 + 1.4 * u)
            fd = fw * float(r.uniform(1.1, 2.4))
            poly = rect_polygon(lon, lat, fw, fd, block_rot + float(r.normal(0, 0.06)))
            footprint = fw * fd
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

            idx += 1
            buildings.append({
                "osm_id": 200_000_000 + idx,
                "name": (f"{r.choice(['Huize', 'Kantoor', 'Complex', 'Gebouw'])} "
                         f"{r.choice(TRACT_NAMES)}") if r.random() < 0.10 else None,
                "building_type": btype,
                "levels": levels,
                "height_m": round(height, 2),
                "min_height_m": 0.0,
                "ground_elev_m": round(ground, 2),
                "roof_shape": str(r.choice(["flat", "gabled", "hipped", "pyramidal", "dome"],
                                           p=[0.52, 0.30, 0.13, 0.04, 0.01])),
                "roof_color": str(r.choice(["#8b5a2b", "#4a5568", "#7f1d1d", "#334155"])),
                "footprint_m2": round(footprint, 1),
                "volume_m3": round(footprint * height, 1),
                "year_built": year_built,
                "solar_potential_kwh_m2": round(solar, 1),
                "shadow_index": round(shadow, 3),
                "energy_class": "ABCDEFG"[energy_bucket],
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
def generate_all() -> dict[str, list[dict]]:
    """Build every table's rows. Returns a dict keyed by 'schema.table'."""
    r = rng()
    out: dict[str, list[dict]] = {}

    out["meta.study_area"] = [gen_study_area()]

    # --- agriculture --------------------------------------------------------
    fields = gen_fields(r)
    out["agri.fields"] = fields
    out["agri.irrigation_canals"] = gen_canals(r)
    out["agri.soil_samples"] = gen_soil_samples(r, fields)
    out["agri.field_ndvi_timeseries"] = gen_ndvi_series(r, len(fields))

    # --- parcel -------------------------------------------------------------
    zoning = gen_zoning(r)
    out["parcel.zoning_districts"] = zoning
    parcels = gen_parcels(r, zoning)
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
    roads = gen_roads(r)
    out["transport.road_segments"] = roads
    routes, stops = gen_transit(r)
    out["transport.transit_routes"] = routes
    out["transport.transit_stops"] = stops
    out["transport.isochrones"] = gen_isochrones(r, stops)
    out["transport.traffic_counts"] = gen_traffic_counts(r, roads)

    # --- terrain ------------------------------------------------------------
    buildings = gen_buildings(r)
    out["terrain.buildings"] = buildings
    out["terrain.contours"] = gen_contours(r)
    out["terrain.drainage_lines"] = gen_drainage(r)
    out["terrain.elevation_bands"] = gen_elevation_bands(r)
    out["terrain.elevation_profile"] = gen_elevation_profiles(r, buildings)

    return out
