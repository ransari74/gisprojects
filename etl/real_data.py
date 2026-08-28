"""Real boundary geometry for the REAL_DATA_BBOX sub-area -- harvested once,
bundled as static files, loaded with zero network dependency thereafter.

    python -m etl.real_data harvest     # one-time (or refresh): hit PDOK,
                                         # write etl/real_boundaries/*.json
    python -m etl.load --real --truncate  # loads those files -- no network

Every layer comes from PDOK's OGC API Features -- paginated GeoJSON, plain
HTTP GET, no GDAL, and all backed by the same fast Dutch government
infrastructure (as opposed to the public OpenStreetMap Overpass API, which
this originally used for canals/roads/buildings but proved too slow and
unreliable -- rate limits, multi-minute timeouts on a dense bbox, occasional
outright refusal -- to depend on):

  * BRP Gewaspercelen (`brpgewas`)              -- crop parcels
  * BRK Kadastrale Kaart (`perceel`)             -- cadastral parcels
  * Waterschappen oppervlaktewateren (`oppervlaktewaterlichaam`) -- canal/
    ditch centrelines, already LineStrings with a real name and category
  * Nationaal Wegenbestand (`wegvakken`)         -- road centrelines, already
    LineStrings with a real street name and functional road class
  * BGT (`pand`)                                 -- building footprints

Fetching is a separate, explicit, resumable step (`harvest`) rather than
something the demo depends on at load time. `real_fields`/`real_canals`/
`real_parcels`/`real_roads`/`real_buildings` just read the bundled JSON in
etl/real_boundaries/ and fall back to the synthetic generator for any layer
that hasn't been harvested yet, so `--real` always works even with a fresh
clone that never ran `harvest`.

Each real_* function returns rows already run through the matching per-row
synthesis helper in etl/generate.py, so a "real" row has real geometry and
whatever real attributes the source actually publishes, with everything else
(soil/yield/NDVI, valuations, traffic, solar, canal capacity) modelled
exactly as the synthetic generator does it -- reused, not duplicated.

Harvesting caches every request to data/real_cache/ (see cache_status(), or
`python -m etl.real_data status`), so an interrupted and re-run harvest never
re-sends a request that already succeeded.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import httpx
import numpy as np
from shapely import force_2d
from shapely.geometry import shape

from etl.config import AGRI_HARVEST_BBOX, REAL_DATA_BBOX
from etl.generate import (
    building_synth_attrs,
    canal_synth_attrs,
    field_attrs_for,
    find_zone_for,
    parcel_attrs_for,
    road_synth_attrs,
    zoned_polygons,
)
from etl.geoutil import M_PER_DEG_LAT, M_PER_DEG_LON, multi_wkt

BRP_URL = "https://api.pdok.nl/rvo/gewaspercelen/ogc/v1/collections/brpgewas/items"
BRK_URL = "https://api.pdok.nl/kadaster/brk-kadastrale-kaart/ogc/v1/collections/perceel/items"
CANAL_URL = "https://api.pdok.nl/hwh/waterschappen-oppervlaktewateren-imwa/ogc/v1/collections/oppervlaktewaterlichaam/items"
ROAD_URL = "https://api.pdok.nl/rws/nationaal-wegenbestand-wegen/ogc/v1/collections/wegvakken/items"
BUILDING_URL = "https://api.pdok.nl/lv/bgt/ogc/v1/collections/pand/items"

# Degrees^2 -> m^2 at the study area's latitude -- used only as a fallback
# when a source doesn't publish its own area/length figure.
DEG2_TO_M2 = M_PER_DEG_LON * M_PER_DEG_LAT

# ---------------------------------------------------------------------------
# On-disk cache
#
# Bind-mounted into the etl container (see docker-compose.yml's `./data`
# volume), so it survives across container runs, not just within one. A
# crash partway through a harvest means a re-run skips every request that
# already succeeded instead of re-fetching the whole layer from scratch.
# Keyed by request identity, not time: this bbox's open data doesn't change
# on a scale this demo cares about, so entries never expire on their own --
# delete `data/real_cache/` to force a refetch.
# ---------------------------------------------------------------------------
CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "real_cache"


def _cache_key(*parts: object) -> str:
    raw = "|".join(str(p) for p in parts)
    return hashlib.sha1(raw.encode()).hexdigest()[:20]


def _cache_get(key: str) -> list[dict] | None:
    path = CACHE_DIR / f"{key}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None  # corrupt/partial write -- treat as a miss and refetch


def _cache_set(key: str, value: list[dict]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_DIR / f"{key}.json.part"
    tmp.write_text(json.dumps(value))
    tmp.replace(CACHE_DIR / f"{key}.json")  # atomic -- no truncated cache file on interrupt


# ---------------------------------------------------------------------------
# Bundled boundaries
#
# The final, checked-in output of a harvest: one raw feature list per layer,
# committed to the repo like everything etl/generate.py produces, so
# `--real` needs no network at all once these exist. Distinct from
# data/real_cache/ above, which is an ephemeral, resumable cache of the
# individual HTTP requests a harvest makes along the way.
# ---------------------------------------------------------------------------
BOUNDARIES_DIR = Path(__file__).resolve().parent / "real_boundaries"


def _shape2d(geojson_geometry: dict):
    """Some PDOK sources (the water-board hydrography collection in
    particular) publish a Z coordinate; the storage columns are 2D, so any
    Z dimension is dropped here rather than at every call site."""
    return force_2d(shape(geojson_geometry))


def _load_boundary(name: str) -> list[dict] | None:
    path = BOUNDARIES_DIR / f"{name}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _save_boundary(name: str, value: list[dict]) -> None:
    BOUNDARIES_DIR.mkdir(parents=True, exist_ok=True)
    (BOUNDARIES_DIR / f"{name}.json").write_text(json.dumps(value))


def _fetch_ogc_features(
    url: str, bbox: tuple[float, float, float, float], *, limit: int = 1000, max_features: int | None = None
) -> list[dict]:
    """Page through a PDOK OGC API Features collection restricted to bbox.

    `max_features` caps how many pages are fetched -- BRK parcels in
    particular are individual cadastral slivers (tens of thousands even in a
    compact bbox), far finer-grained than this demo needs, so callers that
    want a bounded row count pass a cap instead of exhausting every page.
    """
    key = _cache_key("ogc", url, bbox, limit, max_features)
    cached = _cache_get(key)
    if cached is not None:
        print(f"  cache hit: {url.rsplit('/', 2)[-2]} ({len(cached)} features)", file=sys.stderr)
        return cached

    features: list[dict] = []
    params = {"bbox": ",".join(str(v) for v in bbox), "limit": limit, "f": "json"}
    next_url, next_params = url, params
    with httpx.Client(timeout=60.0) as client:
        while next_url:
            resp = client.get(next_url, params=next_params)
            resp.raise_for_status()
            body = resp.json()
            features.extend(body.get("features", []))
            if max_features is not None and len(features) >= max_features:
                features = features[:max_features]
                break
            next_url = None
            next_params = None
            for link in body.get("links", []):
                if link.get("rel") == "next":
                    next_url = link["href"]
    _cache_set(key, features)
    return features


# ---------------------------------------------------------------------------
# Agriculture
# ---------------------------------------------------------------------------
#: BRP publishes the crop in Dutch; map to the synthetic model's crop key so
#: the yield/NDVI formulas (which are keyed by CROPS) still apply sensibly.
#: The real Dutch name is kept as the displayed crop_type regardless.
DUTCH_TO_CROP = {
    "gras": "grassland", "grasland": "grassland",
    "mais": "maize", "snijmais": "maize", "korrelmais": "maize",
    "tarwe": "wheat", "wintertarwe": "wheat", "zomertarwe": "wheat",
    "aardappelen": "potato", "pootaardappelen": "potato", "consumptieaardappelen": "potato",
    "suikerbieten": "sugarbeet",
    "gerst": "barley", "wintergerst": "barley", "zomergerst": "barley",
    "koolzaad": "rapeseed",
    "rogge": "wheat", "spelt": "wheat",  # cereals without their own model bucket
}


def _crop_model_key(gewas: str) -> str:
    lower = gewas.lower()
    for needle, key in DUTCH_TO_CROP.items():
        if needle in lower:
            return key
    return "grassland"  # dominant crop in this area; reasonable default


#: BRP also carries ditches ("Sloot") and other landscape elements sharing the
#: same collection -- those aren't crop fields, so they're excluded here (the
#: ditches are covered separately, as real geometry, by real_canals below).
CROP_CATEGORIES = {"Grasland", "Bouwland"}

#: Fields are harvested over the full study area (AGRI_HARVEST_BBOX), much
#: bigger than the other real layers' REAL_DATA_BBOX -- capped well above the
#: synthetic generator's 1,600 so real farmland still dominates the layer,
#: without pulling in every one of the province's parcels.
MAX_REAL_FIELDS = 6000


def _harvest_fields_raw(bbox: tuple[float, float, float, float]) -> list[dict]:
    # category filtering happens client-side (not a bbox/collection param PDOK
    # supports), so fetch generously past the cap before filtering down to it.
    features = _fetch_ogc_features(BRP_URL, bbox, max_features=MAX_REAL_FIELDS * 2)
    crop_features = [f for f in features if f.get("properties", {}).get("category") in CROP_CATEGORIES]
    return crop_features[:MAX_REAL_FIELDS]


def real_fields(r: np.random.Generator) -> list[dict]:
    features = _load_boundary("agri_fields")
    if features is None:
        print("  no bundled agri_fields boundary -- run `python -m etl.real_data harvest`; using synthetic fields",
              file=sys.stderr)
        from etl.generate import gen_fields

        return gen_fields(r)

    fields = []
    for i, feat in enumerate(features):
        props = feat.get("properties", {})
        geom = _shape2d(feat["geometry"])
        if geom.is_empty:
            continue
        centroid = geom.centroid
        gewas = str(props.get("gewas") or "Onbekend").strip()
        # crop_type is kept as the mapped canonical key (still genuinely
        # correct -- "maize" for "Mais, snij-") rather than the raw Dutch
        # name: the crop-rotation/embedding model downstream (gen_field_
        # embeddings) indexes its basis vectors by the canonical CROPS keys.
        attrs = field_attrs_for(r, centroid.x, centroid.y, crop_override=_crop_model_key(gewas))
        attrs["crop_year"] = props.get("jaar", attrs["crop_year"])
        area_ha = round(geom.area * DEG2_TO_M2 / 10_000, 3)
        fields.append(
            {
                "field_code": f"BRP-{props.get('gewascode', i)}-{i + 1:05d}",
                "farm_name": None,
                "area_ha": area_ha,
                **attrs,
                "geom": multi_wkt(geom, "polygon"),
            }
        )
    return fields


#: Dutch water-board "categoriewater" -> this schema's canal_type.
CATEGORIEWATER_TO_TYPE = {"primair": "primary", "secundair": "secondary", "tertiair": "tertiary"}


def _harvest_canals_raw(bbox: tuple[float, float, float, float]) -> list[dict]:
    return _fetch_ogc_features(CANAL_URL, bbox)


def real_canals(r: np.random.Generator) -> list[dict]:
    features = _load_boundary("agri_canals")
    if features is None:
        print("  no bundled agri_canals boundary -- run `python -m etl.real_data harvest`; using synthetic canals",
              file=sys.stderr)
        from etl.generate import gen_canals

        return gen_canals(r)

    canals = []
    for idx, feat in enumerate(features, start=1):
        geom = _shape2d(feat["geometry"])
        if geom.is_empty:
            continue
        props = feat.get("properties", {})
        canal_type = CATEGORIEWATER_TO_TYPE.get(props.get("categoriewater"), "tertiary")
        length_m = props.get("lengte") or geom.length * ((M_PER_DEG_LON + M_PER_DEG_LAT) / 2)
        canals.append(
            {
                "canal_code": f"WBH-{props.get('code', idx)}",
                "name": props.get("naam"),
                "canal_type": canal_type,
                "length_m": round(float(length_m), 1),
                **canal_synth_attrs(r, canal_type),
                "geom": multi_wkt(geom, "line"),
            }
        )
    return canals


# ---------------------------------------------------------------------------
# Parcel / cadastre
# ---------------------------------------------------------------------------
#: BRK parcels are individual cadastral slivers -- tens of thousands even in
#: REAL_DATA_BBOX -- so the fetch is capped to roughly the synthetic
#: generator's own scale rather than loading every one.
MAX_REAL_PARCELS = 4000


def _harvest_parcels_raw(bbox: tuple[float, float, float, float]) -> list[dict]:
    return _fetch_ogc_features(BRK_URL, bbox, max_features=MAX_REAL_PARCELS)


def real_parcels(r: np.random.Generator, zoning: list[dict]) -> list[dict]:
    features = _load_boundary("parcel_parcels")
    if features is None:
        print("  no bundled parcel_parcels boundary -- run `python -m etl.real_data harvest`; using synthetic parcels",
              file=sys.stderr)
        from etl.generate import gen_parcels

        return gen_parcels(r, zoning)

    zones = zoned_polygons(zoning)
    parcels = []
    for i, feat in enumerate(features):
        geom = _shape2d(feat["geometry"])
        if geom.is_empty:
            continue
        props = feat.get("properties", {})
        centroid = geom.centroid
        zid, z = find_zone_for(centroid.x, centroid.y, zones)
        lot_area = props.get("kadastraleGrootteWaarde") or geom.area * DEG2_TO_M2
        attrs = parcel_attrs_for(r, centroid.x, centroid.y, float(lot_area), zid, z)
        sectie = props.get("sectie", "")
        nummer = props.get("perceelnummer", i)
        parcels.append(
            {
                "parcel_pin": f"BRK-{sectie}-{nummer}",
                "lot_area_m2": round(float(lot_area), 1),
                **attrs,
                "geom": multi_wkt(geom, "polygon"),
            }
        )
    return parcels


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------
#: NWB's INSPIRE-style functional road class -> this schema's highway_class.
#: Neither lanes nor speed limit are published, same as OSM -- still
#: synthesized via road_synth_attrs, keyed off this mapped class.
FRC_TO_HIGHWAY = {
    "0": "motorway", "1": "trunk", "2": "primary", "3": "secondary",
    "4": "tertiary", "5": "unclassified",
}
#: Real road segments are split at every intersection, so even a compact
#: bbox yields far more rows than the synthetic generator's ~1,000 --
#: capped to keep row count/tile size sane.
MAX_REAL_ROADS = 4000


def _harvest_roads_raw(bbox: tuple[float, float, float, float]) -> list[dict]:
    return _fetch_ogc_features(ROAD_URL, bbox, max_features=MAX_REAL_ROADS)


def real_roads(r: np.random.Generator) -> list[dict]:
    features = _load_boundary("transport_roads")
    if features is None:
        print("  no bundled transport_roads boundary -- run `python -m etl.real_data harvest`; using synthetic roads",
              file=sys.stderr)
        from etl.generate import gen_roads

        return gen_roads(r)

    roads = []
    for feat in features:
        geom = _shape2d(feat["geometry"])
        if geom.is_empty:
            continue
        props = feat.get("properties", {})
        hclass = FRC_TO_HIGHWAY.get(str(props.get("frc")), "residential")
        # A MultiLineString's representative line (for the urbanity/midpoint
        # sample inside road_synth_attrs) -- the longest component, which is
        # what most segments already are (a single part).
        line = max(geom.geoms, key=lambda g: g.length) if geom.geom_type == "MultiLineString" else geom
        attrs = road_synth_attrs(r, hclass, line)
        length_m = props.get("st_lengthshape")
        if length_m:
            attrs["length_m"] = round(float(length_m), 1)
        rijrichtng = props.get("rijrichtng")
        if rijrichtng:
            attrs["oneway"] = rijrichtng != "B"
        wvk_id = props.get("wvk_id")
        roads.append(
            {
                "osm_id": int(wvk_id) if wvk_id else None,
                "name": props.get("stt_naam") or None,
                "highway_class": hclass,
                **attrs,
                "geom": multi_wkt(geom, "line"),
            }
        )
    return roads


# ---------------------------------------------------------------------------
# Terrain
# ---------------------------------------------------------------------------
#: A compact urban bbox has far more individual building footprints than the
#: synthetic generator's ~11,000 -- capped at fetch time via max_features
#: rather than fetching everything and discarding most of it.
MAX_REAL_BUILDINGS = 8000


def _harvest_buildings_raw(bbox: tuple[float, float, float, float]) -> list[dict]:
    return _fetch_ogc_features(BUILDING_URL, bbox, max_features=MAX_REAL_BUILDINGS)


def real_buildings(r: np.random.Generator) -> list[dict]:
    features = _load_boundary("terrain_buildings")
    if features is None:
        print("  no bundled terrain_buildings boundary -- run `python -m etl.real_data harvest`; using synthetic buildings",
              file=sys.stderr)
        from etl.generate import gen_buildings

        return gen_buildings(r)

    buildings = []
    for feat in features:
        geom = _shape2d(feat["geometry"])
        if geom.is_empty:
            continue
        props = feat.get("properties", {})
        centroid = geom.centroid
        footprint_m2 = geom.area * DEG2_TO_M2
        # BGT's `pand` collection is administrative (footprint + registration
        # metadata) and doesn't publish a use class, height or levels --
        # unlike OSM, which sometimes tags them but not reliably either, so
        # this is the same "type unknown, model the rest" starting point.
        attrs = building_synth_attrs(r, centroid.x, centroid.y, footprint_m2, "residential")
        bag_pnd = props.get("bag_pnd")
        buildings.append(
            {
                "osm_id": int(bag_pnd) if bag_pnd and bag_pnd.isdigit() else None,
                "name": None,
                "building_type": "residential",
                **attrs,
                "geom": multi_wkt(geom, "polygon"),
            }
        )
    return buildings


# ---------------------------------------------------------------------------
# Harvest orchestration + cache/status CLI
# ---------------------------------------------------------------------------
#: layer name -> (harvest function, minimum acceptable feature count). The
#: minimum is a sanity floor, not a target -- catches an empty/truncated
#: response being mistaken for a successful harvest.
HARVESTERS: dict[str, tuple] = {
    "agri_fields": (_harvest_fields_raw, 1),
    "agri_canals": (_harvest_canals_raw, 1),
    "parcel_parcels": (_harvest_parcels_raw, 1),
    "transport_roads": (_harvest_roads_raw, 1),
    "terrain_buildings": (_harvest_buildings_raw, 1),
}

#: Per-layer bbox override -- only agri_fields deviates from REAL_DATA_BBOX
#: (see AGRI_HARVEST_BBOX in etl/config.py for why).
HARVEST_BBOX_OVERRIDE: dict[str, tuple[float, float, float, float]] = {
    "agri_fields": AGRI_HARVEST_BBOX,
}


def harvest_all(bbox: tuple[float, float, float, float] = REAL_DATA_BBOX, only: set[str] | None = None) -> None:
    """Fetch every real-data layer and write it to etl/real_boundaries/.

    One layer failing doesn't stop the others -- each is independent, and a
    layer that already has a bundled file from a previous harvest is left
    alone unless `only` names it explicitly, so re-running `harvest` after a
    partial failure only (re)fetches what's still missing.
    """
    print(f"Harvesting real boundaries -> {BOUNDARIES_DIR}\n")
    results: dict[str, str] = {}
    for name, (harvest_fn, min_count) in HARVESTERS.items():
        if only is not None and name not in only:
            continue
        if only is None and (BOUNDARIES_DIR / f"{name}.json").exists():
            print(f"  {name}: already bundled, skipping (pass `only {name}` to force a refetch)")
            results[name] = "skipped (already bundled)"
            continue
        layer_bbox = HARVEST_BBOX_OVERRIDE.get(name, bbox)
        print(f"  {name}: fetching (bbox {layer_bbox})...")
        try:
            data = harvest_fn(layer_bbox)
        except httpx.HTTPError as exc:
            print(f"  {name}: FAILED -- {type(exc).__name__}: {exc}", file=sys.stderr)
            results[name] = f"failed ({type(exc).__name__})"
            continue
        if len(data) < min_count:
            print(f"  {name}: got only {len(data)} feature(s), below the sanity floor -- not saving", file=sys.stderr)
            results[name] = f"suspiciously empty ({len(data)})"
            continue
        _save_boundary(name, data)
        print(f"  {name}: saved {len(data):,} feature(s)")
        results[name] = f"ok ({len(data):,})"

    print("\nSummary:")
    for name, status in results.items():
        print(f"  {name}: {status}")
    if any(s.startswith(("failed", "suspiciously")) for s in results.values()):
        print(
            "\nSome layers failed -- `--real` will fall back to synthetic data for those. "
            "Re-run `python -m etl.real_data harvest` later to retry just the missing ones."
        )


def cache_status() -> None:
    """`python -m etl.real_data status` -- what's cached in data/real_cache/
    right now, so it's obvious whether a harvest can resume from disk or will
    hit the network again. Cache entries are keyed by request content, not
    by layer name, so this can only report counts/sizes per file, not which
    layer each belongs to -- good enough to answer "did anything get saved."
    """
    if not CACHE_DIR.exists():
        print(f"No cache directory at {CACHE_DIR} -- nothing fetched yet.")
    else:
        files = sorted(CACHE_DIR.glob("*.json"))
        if not files:
            print(f"{CACHE_DIR} exists but is empty -- nothing fetched yet.")
        else:
            total = 0
            for f in files:
                try:
                    n = len(json.loads(f.read_text()))
                except (json.JSONDecodeError, OSError):
                    n = -1
                total += max(n, 0)
                print(f"  {f.name}  {n:>7,} features  ({f.stat().st_size / 1024:.0f} KB)")
            print(f"\n{len(files)} cached request(s), {total:,} features total, in {CACHE_DIR}")
            print("Delete a file (or the whole directory) to force that request to be re-fetched.")

    print()
    if not BOUNDARIES_DIR.exists() or not any(BOUNDARIES_DIR.glob("*.json")):
        print(f"No bundled boundaries at {BOUNDARIES_DIR} yet -- run `python -m etl.real_data harvest`.")
    else:
        for name in HARVESTERS:
            path = BOUNDARIES_DIR / f"{name}.json"
            if path.exists():
                n = len(json.loads(path.read_text()))
                print(f"  {name}: bundled, {n:,} feature(s)")
            else:
                print(f"  {name}: not bundled -- falls back to synthetic")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "harvest":
        harvest_all(only=set(sys.argv[2:]) or None)
    else:
        cache_status()
