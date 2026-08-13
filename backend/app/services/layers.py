"""Registry of every vector-tile layer the API can serve.

Adding a layer means adding one LayerSpec here -- the tile endpoint, the
capabilities endpoint and the frontend layer panel are all driven off this
table, so there is exactly one place to change.

SECURITY: `schema`, `table`, `geom_column` and `columns` are interpolated into
SQL by name. They come only from this module -- never from request data -- and
`LayerSpec.__post_init__` re-validates every identifier so a future edit cannot
silently introduce an injection point.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]*$")

GeomKind = Literal["polygon", "line", "point"]


@dataclass(frozen=True, slots=True)
class LayerSpec:
    #: URL segment, e.g. /api/tiles/agri_fields/{z}/{x}/{y}.mvt
    name: str
    project: str
    title: str
    schema: str
    table: str
    geom_kind: GeomKind
    permission: str
    columns: tuple[str, ...]
    geom_column: str = "geom"
    id_column: str = "id"
    min_zoom: int = 0
    max_zoom: int = 22
    #: Below this zoom the geometry is generalised before tiling. Tolerance is
    #: expressed in web-mercator metres and halves with each zoom level.
    simplify_below_zoom: int = 12
    #: Columns exposed as `?filter_<col>=value` on the tile + feature endpoints.
    filterable: tuple[str, ...] = ()
    #: Numeric columns exposed as `?min_<col>=` / `?max_<col>=`.
    range_filterable: tuple[str, ...] = ()
    #: Default styling hint consumed by the frontend layer panel.
    style_hint: dict = field(default_factory=dict)
    description: str = ""

    def __post_init__(self) -> None:
        idents = (
            self.schema,
            self.table,
            self.geom_column,
            self.id_column,
            *self.columns,
            *self.filterable,
            *self.range_filterable,
        )
        for ident in idents:
            if not IDENT_RE.match(ident):
                raise ValueError(f"Unsafe SQL identifier in layer {self.name!r}: {ident!r}")
        unknown_filters = set(self.filterable + self.range_filterable) - set(self.columns)
        if unknown_filters:
            raise ValueError(
                f"Layer {self.name!r} filters on columns it does not select: {sorted(unknown_filters)}"
            )

    @property
    def qualified_table(self) -> str:
        return f"{self.schema}.{self.table}"


# ---------------------------------------------------------------------------
# PROJECT 1 -- AGRICULTURE
# ---------------------------------------------------------------------------
AGRICULTURE_LAYERS = [
    LayerSpec(
        name="agri_fields",
        project="agriculture",
        title="Crop fields",
        schema="agri",
        table="fields",
        geom_kind="polygon",
        permission="agriculture:read",
        columns=(
            "field_code", "farm_name", "crop_type", "crop_year", "area_ha",
            "irrigated", "organic", "soil_ph", "soil_organic_c", "soil_clay_pct",
            "soil_sand_pct", "soil_texture", "landcover_class", "ndvi_mean",
            "ndvi_max", "yield_t_ha", "yield_class", "elevation_m", "slope_deg",
        ),
        filterable=("crop_type", "crop_year", "yield_class", "soil_texture", "irrigated", "organic"),
        range_filterable=("yield_t_ha", "soil_ph", "ndvi_mean", "area_ha"),
        min_zoom=8,
        style_hint={"type": "fill", "colorBy": "yield_t_ha", "scheme": "sequential-green"},
        description="Field parcels enriched with SoilGrids chemistry and Sentinel-2 NDVI.",
    ),
    LayerSpec(
        name="agri_canals",
        project="agriculture",
        title="Irrigation network",
        schema="agri",
        table="irrigation_canals",
        geom_kind="line",
        permission="agriculture:read",
        columns=("canal_code", "name", "canal_type", "lined", "capacity_m3s", "length_m", "condition"),
        filterable=("canal_type", "condition", "lined"),
        range_filterable=("capacity_m3s",),
        min_zoom=9,
        style_hint={"type": "line", "colorBy": "canal_type", "scheme": "categorical-blue"},
        description="Primary through tertiary irrigation and drainage channels.",
    ),
    LayerSpec(
        name="agri_soil_samples",
        project="agriculture",
        title="Soil sample sites",
        schema="agri",
        table="soil_samples",
        geom_kind="point",
        permission="agriculture:read",
        columns=("sample_code", "sampled_on", "depth_cm", "ph", "organic_c", "nitrogen", "phosphorus", "potassium"),
        range_filterable=("ph", "organic_c"),
        min_zoom=11,
        style_hint={"type": "circle", "colorBy": "ph", "scheme": "diverging-ph"},
        description="Ground-truth laboratory samples backing the interpolated soil surfaces.",
    ),
]

# ---------------------------------------------------------------------------
# PROJECT 2 -- PARCEL / CADASTRE
# ---------------------------------------------------------------------------
PARCEL_LAYERS = [
    LayerSpec(
        name="parcel_zoning",
        project="parcel",
        title="Zoning districts",
        schema="parcel",
        table="zoning_districts",
        geom_kind="polygon",
        permission="parcel:read",
        columns=("zone_code", "zone_name", "zone_category", "max_far", "max_height_m", "min_lot_m2"),
        filterable=("zone_category", "zone_code"),
        range_filterable=("max_far", "max_height_m"),
        min_zoom=9,
        style_hint={"type": "fill", "colorBy": "zone_category", "scheme": "categorical-zoning"},
        description="Adopted zoning envelope: category, FAR cap and height limit.",
    ),
    LayerSpec(
        name="parcel_parcels",
        project="parcel",
        title="Cadastral parcels",
        schema="parcel",
        table="parcels",
        geom_kind="polygon",
        permission="parcel:read",
        columns=(
            "parcel_pin", "address", "district", "zone_code", "land_use", "owner_type",
            "lot_area_m2", "building_area_m2", "floor_area_ratio", "coverage_ratio",
            "num_units", "floors", "year_built", "assessed_value", "value_per_m2",
            "last_sale_price", "tax_exempt",
        ),
        filterable=("land_use", "owner_type", "zone_code", "district", "tax_exempt"),
        range_filterable=("assessed_value", "value_per_m2", "lot_area_m2", "year_built", "floors"),
        min_zoom=13,
        style_hint={"type": "fill", "colorBy": "value_per_m2", "scheme": "sequential-amber"},
        description="Parcel geometry with land use, ownership and assessed valuation.",
    ),
    LayerSpec(
        name="parcel_boundaries",
        project="parcel",
        title="Boundaries & easements",
        schema="parcel",
        table="boundary_lines",
        geom_kind="line",
        permission="parcel:read",
        columns=("parcel_pin", "boundary_type", "survey_date", "length_m", "is_disputed"),
        filterable=("boundary_type", "is_disputed"),
        min_zoom=14,
        style_hint={"type": "line", "colorBy": "boundary_type", "scheme": "categorical-cadastre"},
        description="Legal lot lines, easements, rights of way and disputed edges.",
    ),
]

# ---------------------------------------------------------------------------
# PROJECT 3 -- DEMOGRAPHICS
# ---------------------------------------------------------------------------
DEMOGRAPHIC_LAYERS = [
    LayerSpec(
        name="demog_tracts",
        project="demographics",
        title="Census tracts",
        schema="demog",
        table="census_tracts",
        geom_kind="polygon",
        permission="demographics:read",
        columns=(
            "tract_code", "tract_name", "district", "population", "households",
            "area_km2", "density_km2", "median_age", "median_income",
            "unemployment_rate", "pct_under_15", "pct_65_plus",
            "pct_tertiary_educated", "pct_owner_occupied", "median_rent",
            "deprivation_index", "census_year",
        ),
        filterable=("district", "census_year"),
        range_filterable=("population", "density_km2", "median_income", "median_age", "deprivation_index"),
        min_zoom=6,
        style_hint={"type": "fill", "colorBy": "density_km2", "scheme": "sequential-purple"},
        description="Tract-level population structure, income, housing and deprivation.",
    ),
    LayerSpec(
        name="demog_popgrid",
        project="demographics",
        title="Population grid",
        schema="demog",
        table="population_grid",
        geom_kind="polygon",
        permission="demographics:read",
        columns=("cell_id", "population", "resolution_m"),
        range_filterable=("population",),
        min_zoom=10,
        style_hint={"type": "fill", "colorBy": "population", "scheme": "sequential-heat"},
        description="500 m population raster vectorised for client-side heat rendering.",
    ),
    LayerSpec(
        name="demog_flows",
        project="demographics",
        title="Commute flows",
        schema="demog",
        table="commute_flows",
        geom_kind="line",
        permission="demographics:read",
        columns=("origin_code", "dest_code", "trips", "mode", "avg_duration_min", "distance_km"),
        filterable=("mode",),
        range_filterable=("trips", "distance_km"),
        min_zoom=8,
        style_hint={"type": "line", "colorBy": "mode", "scheme": "categorical-mode", "widthBy": "trips"},
        description="Origin-destination desire lines by travel mode.",
    ),
]

# ---------------------------------------------------------------------------
# PROJECT 4 -- TRANSPORTATION
# ---------------------------------------------------------------------------
TRANSPORT_LAYERS = [
    LayerSpec(
        name="transport_roads",
        project="transport",
        title="Road network",
        schema="transport",
        table="road_segments",
        geom_kind="line",
        permission="transport:read",
        columns=(
            "osm_id", "name", "highway_class", "functional_class", "oneway", "lanes",
            "maxspeed_kmh", "surface", "bridge", "tunnel", "length_m", "aadt",
            "peak_speed_kmh", "congestion_index", "accident_count", "has_bike_lane",
        ),
        filterable=("highway_class", "surface", "oneway", "has_bike_lane", "bridge", "tunnel"),
        range_filterable=("aadt", "congestion_index", "maxspeed_kmh", "lanes", "accident_count"),
        min_zoom=7,
        simplify_below_zoom=13,
        style_hint={"type": "line", "colorBy": "congestion_index", "scheme": "sequential-traffic", "widthBy": "functional_class"},
        description="OSM road centrelines with traffic volume and congestion metrics.",
    ),
    LayerSpec(
        name="transport_transit_routes",
        project="transport",
        title="Transit routes",
        schema="transport",
        table="transit_routes",
        geom_kind="line",
        permission="transport:read",
        columns=("route_code", "route_name", "mode", "operator", "color", "headway_min", "daily_ridership", "length_km"),
        filterable=("mode", "operator"),
        range_filterable=("daily_ridership", "headway_min"),
        min_zoom=8,
        style_hint={"type": "line", "colorBy": "mode", "scheme": "categorical-transit"},
        description="Bus, tram, metro and rail alignments with ridership.",
    ),
    LayerSpec(
        name="transport_stops",
        project="transport",
        title="Transit stops",
        schema="transport",
        table="transit_stops",
        geom_kind="point",
        permission="transport:read",
        columns=("stop_code", "stop_name", "mode", "wheelchair_accessible", "shelter", "daily_boardings", "routes_served"),
        filterable=("mode", "wheelchair_accessible"),
        range_filterable=("daily_boardings",),
        min_zoom=11,
        style_hint={"type": "circle", "colorBy": "mode", "scheme": "categorical-transit"},
        description="Stop and station points with boarding counts and accessibility.",
    ),
    LayerSpec(
        name="transport_isochrones",
        project="transport",
        title="Accessibility isochrones",
        schema="transport",
        table="isochrones",
        geom_kind="polygon",
        permission="transport:read",
        columns=("origin_code", "mode", "minutes", "population_reached", "jobs_reached", "area_km2"),
        filterable=("mode", "minutes", "origin_code"),
        range_filterable=("population_reached",),
        min_zoom=9,
        style_hint={"type": "fill", "colorBy": "minutes", "scheme": "sequential-teal"},
        description="Travel-time catchments used for the accessibility scoring.",
    ),
]

# ---------------------------------------------------------------------------
# PROJECT 5 -- 3D TERRAIN
# ---------------------------------------------------------------------------
TERRAIN_LAYERS = [
    LayerSpec(
        name="terrain_buildings",
        project="terrain",
        title="Buildings (3D)",
        schema="terrain",
        table="buildings",
        geom_kind="polygon",
        permission="terrain:read",
        columns=(
            "osm_id", "name", "building_type", "levels", "height_m", "min_height_m",
            "ground_elev_m", "roof_shape", "footprint_m2", "volume_m3", "year_built",
            "solar_potential_kwh_m2", "shadow_index", "energy_class",
        ),
        filterable=("building_type", "roof_shape", "energy_class"),
        range_filterable=("height_m", "levels", "year_built", "solar_potential_kwh_m2", "footprint_m2"),
        min_zoom=14,
        simplify_below_zoom=0,  # footprints are already small; never generalise
        style_hint={"type": "fill-extrusion", "heightBy": "height_m", "colorBy": "height_m", "scheme": "sequential-slate"},
        description="Footprints with height and level attributes for fill-extrusion.",
    ),
    LayerSpec(
        name="terrain_contours",
        project="terrain",
        title="Elevation contours",
        schema="terrain",
        table="contours",
        geom_kind="line",
        permission="terrain:read",
        columns=("elevation_m", "interval_m", "is_index"),
        filterable=("is_index", "interval_m"),
        range_filterable=("elevation_m",),
        min_zoom=11,
        style_hint={"type": "line", "colorBy": "is_index", "scheme": "contour"},
        description="Contours derived from the Copernicus GLO-30 digital elevation model.",
    ),
    LayerSpec(
        name="terrain_drainage",
        project="terrain",
        title="Hydrology & ridges",
        schema="terrain",
        table="drainage_lines",
        geom_kind="line",
        permission="terrain:read",
        columns=("name", "line_type", "stream_order", "length_m", "slope_pct"),
        filterable=("line_type",),
        range_filterable=("stream_order", "slope_pct"),
        min_zoom=10,
        style_hint={"type": "line", "colorBy": "line_type", "scheme": "categorical-hydro"},
        description="Flow-accumulation streams and ridge lines extracted from the DEM.",
    ),
    LayerSpec(
        name="terrain_elevation_bands",
        project="terrain",
        title="Elevation bands",
        schema="terrain",
        table="elevation_bands",
        geom_kind="polygon",
        permission="terrain:read",
        columns=("band_min_m", "band_max_m", "label", "color_hex", "area_km2"),
        range_filterable=("band_min_m",),
        min_zoom=8,
        style_hint={"type": "fill", "colorBy": "band_min_m", "scheme": "hypsometric"},
        description="Hypsometric tint bands for the 2D fallback view.",
    ),
]

ALL_LAYERS: list[LayerSpec] = [
    *AGRICULTURE_LAYERS,
    *PARCEL_LAYERS,
    *DEMOGRAPHIC_LAYERS,
    *TRANSPORT_LAYERS,
    *TERRAIN_LAYERS,
]

LAYER_INDEX: dict[str, LayerSpec] = {layer.name: layer for layer in ALL_LAYERS}

PROJECTS: dict[str, dict] = {
    "agriculture": {
        "title": "Agricultural Land & Soil Intelligence",
        "tagline": "Field-level soil chemistry, land cover and yield modelling",
        "permission": "agriculture:read",
        "accent": "#4d7c0f",
        "icon": "sprout",
    },
    "parcel": {
        "title": "Cadastral Parcel & Land Value Explorer",
        "tagline": "Zoning, land use and assessed value across the cadastre",
        "permission": "parcel:read",
        "accent": "#b45309",
        "icon": "map",
    },
    "demographics": {
        "title": "Population & Socio-Economic Atlas",
        "tagline": "Census structure, deprivation and commuting patterns",
        "permission": "demographics:read",
        "accent": "#7c3aed",
        "icon": "users",
    },
    "transport": {
        "title": "Multimodal Transport Network Analytics",
        "tagline": "Road congestion, transit ridership and accessibility",
        "permission": "transport:read",
        "accent": "#0e7490",
        "icon": "route",
    },
    "terrain": {
        "title": "3D Terrain & Urban Massing",
        "tagline": "Extruded city model over Copernicus DEM terrain",
        "permission": "terrain:read",
        "accent": "#475569",
        "icon": "mountain",
    },
}


def layers_for_project(project: str) -> list[LayerSpec]:
    return [layer for layer in ALL_LAYERS if layer.project == project]


def get_layer(name: str) -> LayerSpec | None:
    return LAYER_INDEX.get(name)
