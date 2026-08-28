"""Registry of basemaps and raster overlays the frontend can pick from.

Deliberately not Google's tile API. Google Maps Platform tiles need an API key
tied to a billing account (the $200/month credit often covers a low-traffic
portfolio's usage, but it is not key-free), and the unofficial
`mt0-mt3.google.com/vt` endpoint some hobby projects use needs no key but is
not a documented product -- Google can rate-limit or block it without notice,
which is a bad foundation for something meant to stay up.

Everything registered here is a public, key-free, documented tile service:

  - OpenStreetMap standard tiles (roads)
  - Esri World Imagery (satellite) -- the same free community basemap used
    throughout the Leaflet/Mapbox ecosystem
  - Esri World Imagery + Esri's reference/labels layer stacked (hybrid)
  - PDOK Luchtfoto -- Dutch national aerial imagery, higher resolution than
    global satellite providers over the study area specifically

All are raster tile sources, so no MapLibre vector-style API key is needed
either (Mapbox/MapTiler/Stadia vector styles all require one).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True, slots=True)
class BasemapLayer:
    """One raster layer in a basemap stack. `hybrid` composes two of these
    (imagery, then a transparent labels/boundaries layer) into one basemap."""

    tiles: tuple[str, ...]
    tile_size: int = 256
    max_zoom: int = 19


@dataclass(frozen=True, slots=True)
class BasemapSpec:
    id: str
    name: str
    description: str
    attribution: str
    #: "roads" gets the muted/desaturated treatment so the app's own data reads
    #: clearly on top; "imagery" is shown at full colour since the imagery
    #: itself is usually the point of selecting it.
    kind: Literal["roads", "imagery"]
    layers: tuple[BasemapLayer, ...]


BASEMAPS: tuple[BasemapSpec, ...] = (
    BasemapSpec(
        id="osm",
        name="Roads",
        description="OpenStreetMap standard tiles",
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        kind="roads",
        layers=(BasemapLayer(tiles=("https://tile.openstreetmap.org/{z}/{x}/{y}.png",)),),
    ),
    BasemapSpec(
        id="esri_satellite",
        name="Satellite",
        description="Esri World Imagery",
        attribution="Esri, Maxar, Earthstar Geographics",
        kind="imagery",
        layers=(
            BasemapLayer(
                tiles=(
                    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
                ),
            ),
        ),
    ),
    BasemapSpec(
        id="esri_hybrid",
        name="Hybrid",
        description="Esri World Imagery with roads, boundaries and place labels",
        attribution="Esri, Maxar, Earthstar Geographics",
        kind="imagery",
        layers=(
            BasemapLayer(
                tiles=(
                    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
                ),
            ),
            BasemapLayer(
                tiles=(
                    "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
                ),
            ),
        ),
    ),
    BasemapSpec(
        id="pdok_aerial",
        name="NL Aerial",
        description="PDOK Luchtfoto -- Dutch national aerial imagery, higher resolution than global providers over Utrecht",
        attribution="Beeldmateriaal.nl, PDOK",
        kind="imagery",
        layers=(
            BasemapLayer(
                tiles=(
                    "https://service.pdok.nl/hwh/luchtfotorgb/wmts/v1_0/Actueel_ortho25/EPSG:3857/{z}/{x}/{y}.jpeg",
                ),
                max_zoom=20,
            ),
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class LandCoverClass:
    code: int
    label: str
    color_hex: str


# The official ESA WorldCover 2021 (v200) 11-class legend, in product order.
WORLDCOVER_LEGEND: tuple[LandCoverClass, ...] = (
    LandCoverClass(10, "Tree cover", "#006400"),
    LandCoverClass(20, "Shrubland", "#ffbb22"),
    LandCoverClass(30, "Grassland", "#ffff4c"),
    LandCoverClass(40, "Cropland", "#f096ff"),
    LandCoverClass(50, "Built-up", "#fa0000"),
    LandCoverClass(60, "Bare / sparse vegetation", "#b4b4b4"),
    LandCoverClass(70, "Snow and ice", "#f0f0f0"),
    LandCoverClass(80, "Permanent water bodies", "#0064c8"),
    LandCoverClass(90, "Herbaceous wetland", "#0096a0"),
    LandCoverClass(95, "Mangroves", "#00cf75"),
    LandCoverClass(100, "Moss and lichen", "#fae6a0"),
)


@dataclass(frozen=True, slots=True)
class OverlaySpec:
    id: str
    name: str
    description: str
    attribution: str
    #: Which project pages offer this overlay. Purely a hint the frontend acts
    #: on by choosing what to pass in `overlayIds` -- the API itself serves the
    #: whole registry to everyone, the same as /meta/basemaps.
    projects: tuple[str, ...]
    #: Either a WMS GetMap URL using MapLibre's `{bbox-epsg-3857}` substitution
    #: (no WMTS proxy needed, MapLibre fills it in per-tile) or a plain
    #: `{z}/{x}/{y}` XYZ template -- both are just raster tile sources to
    #: MapLibre, so one field covers both.
    tiles: tuple[str, ...]
    tile_size: int = 256
    max_zoom: int = 18
    default_opacity: float = 0.7
    #: Discrete class legend (WorldCover's 11 classes, a single-class
    #: boundary tint). Leave empty for a continuous property map.
    legend: tuple[LandCoverClass, ...] = field(default_factory=tuple)
    #: Short explanation shown instead of a legend when the overlay is a
    #: continuous surface (SoilGrids) or a pre-styled cartographic reference
    #: layer (the hydro overlay) rather than a fixed set of classes.
    legend_note: str = ""


OVERLAYS: tuple[OverlaySpec, ...] = (
    OverlaySpec(
        id="esa_worldcover",
        name="ESA WorldCover",
        description="Global 10 m land cover, 2021 (v200) -- 11 classes",
        attribution="ESA WorldCover project 2021 / VITO",
        projects=("agriculture",),
        tiles=(
            "https://services.terrascope.be/wms/v2?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap"
            "&FORMAT=image/png&TRANSPARENT=TRUE&LAYERS=WORLDCOVER_2021_MAP"
            "&SRS=EPSG:3857&WIDTH=256&HEIGHT=256&BBOX={bbox-epsg-3857}",
        ),
        default_opacity=0.7,
        legend=WORLDCOVER_LEGEND,
    ),
    # ISRIC's SoilGrids WMS renders each property through its own mapfile at
    # maps.isric.org, one endpoint per property (phh2o, soc, clay, ...), with
    # ISRIC's own colour ramp baked into the WMS response server-side -- the
    # same reason WorldCover needs no client-side classification either.
    # There is no fixed class list for a continuous property, so this carries
    # a legend_note instead of a swatch list.
    OverlaySpec(
        id="soilgrids_ph",
        name="SoilGrids pH",
        description="ISRIC SoilGrids v2.0 -- soil pH in H2O, 0-5 cm depth, 250 m",
        attribution="ISRIC -- World Soil Information, SoilGrids 2.0",
        projects=("agriculture",),
        tiles=(
            "https://maps.isric.org/mapserv?map=/map/phh2o.map&SERVICE=WMS&VERSION=1.1.1"
            "&REQUEST=GetMap&FORMAT=image/png&TRANSPARENT=TRUE&LAYERS=phh2o_0-5cm_mean&STYLES="
            "&SRS=EPSG:3857&WIDTH=256&HEIGHT=256&BBOX={bbox-epsg-3857}",
        ),
        default_opacity=0.75,
        legend_note="Continuous property map; ISRIC's own colour ramp -- lighter is more acidic, darker more alkaline.",
    ),
    OverlaySpec(
        id="soilgrids_soc",
        name="SoilGrids organic carbon",
        description="ISRIC SoilGrids v2.0 -- soil organic carbon, 0-5 cm depth, 250 m",
        attribution="ISRIC -- World Soil Information, SoilGrids 2.0",
        projects=("agriculture",),
        tiles=(
            "https://maps.isric.org/mapserv?map=/map/soc.map&SERVICE=WMS&VERSION=1.1.1"
            "&REQUEST=GetMap&FORMAT=image/png&TRANSPARENT=TRUE&LAYERS=soc_0-5cm_mean&STYLES="
            "&SRS=EPSG:3857&WIDTH=256&HEIGHT=256&BBOX={bbox-epsg-3857}",
        ),
        default_opacity=0.75,
        legend_note="Continuous property map; ISRIC's own colour ramp -- darker means more organic carbon.",
    ),
    # EEA's Natura 2000 WMS is the authoritative EU-wide protected-area
    # boundary service (Dutch sites published nationally via PDOK are the
    # same underlying data, republished) -- one endpoint covers the whole
    # study area with no country-specific swap needed.
    OverlaySpec(
        id="protected_areas",
        name="Protected areas (Natura 2000)",
        description="EU-wide protected habitat and bird-directive site boundaries",
        attribution="European Environment Agency, Natura 2000",
        projects=("agriculture", "parcel", "terrain", "transport"),
        tiles=(
            "https://bio.discomap.eea.europa.eu/arcgis/services/ProtectedSites/"
            "Natura2000_Dyna_WM/MapServer/WmsServer?SERVICE=WMS&VERSION=1.1.1"
            "&REQUEST=GetMap&FORMAT=image/png&TRANSPARENT=TRUE&LAYERS=0&STYLES="
            "&SRS=EPSG:3857&WIDTH=256&HEIGHT=256&BBOX={bbox-epsg-3857}",
        ),
        default_opacity=0.55,
        legend=(LandCoverClass(1, "Natura 2000 site", "#2e7d32"),),
    ),
    # A "waterways" overlay (Esri Reference/World_Hydro_Reference_Overlay)
    # used to live here -- Esri retired that service (confirmed 404 on its
    # MapServer endpoint) with no equivalent replacement in the same
    # collection, so it's removed rather than left pointing at a dead URL.
    # The agriculture project's own agri_canals layer already covers real
    # canal geometry for the study area; a general-purpose water reference
    # overlay would need its own real PDOK-sourced vector layer (harvest +
    # migration + LayerSpec) if it's wanted back.
)


def basemaps_payload() -> list[dict]:
    return [
        {
            "id": b.id,
            "name": b.name,
            "description": b.description,
            "attribution": b.attribution,
            "kind": b.kind,
            "layers": [
                {"tiles": list(layer.tiles), "tileSize": layer.tile_size, "maxZoom": layer.max_zoom}
                for layer in b.layers
            ],
        }
        for b in BASEMAPS
    ]


def overlays_payload() -> list[dict]:
    return [
        {
            "id": o.id,
            "name": o.name,
            "description": o.description,
            "attribution": o.attribution,
            "projects": list(o.projects),
            "tiles": list(o.tiles),
            "tileSize": o.tile_size,
            "maxZoom": o.max_zoom,
            "defaultOpacity": o.default_opacity,
            "legend": [
                {"code": c.code, "label": c.label, "colorHex": c.color_hex} for c in o.legend
            ],
            "legendNote": o.legend_note,
        }
        for o in OVERLAYS
    ]
