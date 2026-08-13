"""Study area definition and open-dataset registry.

Study area: Utrecht province, Netherlands. Chosen because all five project
themes have genuinely open data for the same footprint:

  * agriculture -- BRP Gewaspercelen crop parcels (CC0), real farmland sits
    inside the bbox (unlike Amsterdam or Rotterdam)
  * cadastre    -- Kadaster BRK open cadastral map
  * demographics-- CBS Wijk- en Buurtkaart, ~120 statistics per neighbourhood
  * transport   -- Geofabrik has a province-level extract (~90 MB, not the
                   1.3 GB country file) plus the national GTFS feed
  * 3D terrain  -- 3DBAG, the best open LoD2 building model in Europe

Change STUDY_AREA and every generator/loader follows.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# --- study area -------------------------------------------------------------
MIN_LON, MIN_LAT, MAX_LON, MAX_LAT = 4.95, 51.98, 5.30, 52.18

# Utrecht city centre (Domtoren)
CENTRE_LON, CENTRE_LAT = 5.1214, 52.0907

STUDY_AREA = {
    "code": "NL-UT",
    "name": "Utrecht, Netherlands",
    "country": "Netherlands",
    "epsg_local": 28992,  # Amersfoort / RD New
    "bbox": (MIN_LON, MIN_LAT, MAX_LON, MAX_LAT),
    "centre": (CENTRE_LON, CENTRE_LAT),
}

DATABASE_URL = os.environ.get(
    "ETL_DATABASE_URL",
    os.environ.get("DATABASE_URL", "postgresql://gis:gis@localhost:5432/gisportfolio"),
)


@dataclass(frozen=True)
class Dataset:
    """One open dataset, recorded in meta.dataset_source after loading."""

    project: str
    layer: str
    name: str
    provider: str
    license: str
    url: str
    fmt: str
    notes: str = ""


# ---------------------------------------------------------------------------
# Open datasets backing each project. `etl/download.py` fetches these;
# `etl/generate.py` produces a stand-in with the same schema when the network
# is unavailable so the stack is demonstrable offline.
# ---------------------------------------------------------------------------
DATASETS: list[Dataset] = [
    # --- agriculture --------------------------------------------------------
    Dataset(
        project="agriculture",
        layer="agri_fields",
        name="BRP Gewaspercelen (crop parcels)",
        provider="RVO / PDOK",
        license="CC0-1.0",
        url="https://service.pdok.nl/rvo/brpgewaspercelen/atom/v1_0/downloads/brpgewaspercelen_concept_2024.gpkg",
        fmt="GeoPackage",
        notes="Annual declared crop parcels for the whole of NL; clip to the study bbox.",
    ),
    Dataset(
        project="agriculture",
        layer="agri_fields.soil",
        name="ISRIC SoilGrids v2.0",
        provider="ISRIC World Soil Information",
        license="CC-BY-4.0",
        url="https://maps.isric.org/mapserv?map=/map/phh2o.map",
        fmt="WCS/GeoTIFF",
        notes="phh2o, soc, clay, sand, silt at 0-30 cm; sampled per field centroid.",
    ),
    Dataset(
        project="agriculture",
        layer="agri_fields.landcover",
        name="ESA WorldCover 2021 v200",
        provider="ESA",
        license="CC-BY-4.0",
        url="https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_N51E003_Map.tif",
        fmt="GeoTIFF",
        notes="10 m global land cover; majority class per field.",
    ),
    # --- parcel -------------------------------------------------------------
    Dataset(
        project="parcel",
        layer="parcel_parcels",
        name="BRK Kadastrale Kaart",
        provider="Kadaster / PDOK",
        license="CC-BY-4.0",
        url="https://service.pdok.nl/kadaster/kadastralekaart/atom/kadastralekaart.xml",
        fmt="GeoPackage",
        notes="Open cadastral map: parcel polygons + kadastralegrens boundary lines.",
    ),
    Dataset(
        project="parcel",
        layer="parcel_parcels.value",
        name="CBS WOZ property values (gem_woz)",
        provider="CBS",
        license="CC-BY-4.0",
        url="https://geodata.cbs.nl/files/Wijkenbuurtkaart/WijkBuurtkaart_2025_v1.zip",
        fmt="GeoPackage",
        notes="NL publishes no parcel-level assessed value; neighbourhood mean WOZ is the open proxy.",
    ),
    # --- demographics -------------------------------------------------------
    Dataset(
        project="demographics",
        layer="demog_tracts",
        name="CBS Wijk- en Buurtkaart 2025",
        provider="Centraal Bureau voor de Statistiek",
        license="CC-BY-4.0",
        url="https://geodata.cbs.nl/files/Wijkenbuurtkaart/WijkBuurtkaart_2025_v1.zip",
        fmt="GeoPackage",
        notes="~120 statistics per neighbourhood: population, age bands, income, housing.",
    ),
    Dataset(
        project="demographics",
        layer="demog_popgrid",
        name="Kontur Population (H3 r8)",
        provider="Kontur",
        license="CC-BY-4.0",
        url="https://data.humdata.org/dataset/kontur-population-dataset",
        fmt="GeoPackage",
        notes="Global 400 m hexagon population; alternative to GHS-POP for the grid layer.",
    ),
    # --- transport ----------------------------------------------------------
    Dataset(
        project="transport",
        layer="transport_roads",
        name="OpenStreetMap -- Utrecht province extract",
        provider="Geofabrik",
        license="ODbL-1.0",
        url="https://download.geofabrik.de/europe/netherlands/utrecht-latest.osm.pbf",
        fmt="PBF",
        notes="~90 MB. Roads, cycleways and building footprints in one extract.",
    ),
    Dataset(
        project="transport",
        layer="transport_transit_routes",
        name="GTFS Netherlands",
        provider="OpenOV / NDOV",
        license="CC0-1.0",
        url="https://gtfs.ovapi.nl/nl/gtfs-nl.zip",
        fmt="GTFS",
        notes="~200 MB, 2775 routes / 52212 stops nationally; filter to the bbox.",
    ),
    # --- terrain ------------------------------------------------------------
    Dataset(
        project="terrain",
        layer="terrain_buildings",
        name="3DBAG LoD2 building models",
        provider="TU Delft 3D geoinformation",
        license="CC-BY-4.0",
        url="https://data.3dbag.nl/v20250903/tile_index.fgb",
        fmt="FlatGeobuf index + per-tile GeoPackage",
        notes=(
            "Fetch the tile index, intersect with the bbox, then pull only matching tiles from "
            "https://data.3dbag.nl/{version}/tiles/{x}/{y}/{z}/{x}-{y}-{z}.gpkg -- the whole-NL "
            "dump is 19 GB. Heights: b3_h_dak_50p (roof), b3_h_maaiveld (ground)."
        ),
    ),
    Dataset(
        project="terrain",
        layer="terrain_contours",
        name="Copernicus DEM GLO-30",
        provider="ESA / AWS Open Data",
        license="CC-BY-4.0",
        url="https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_N52_00_E005_00_DEM/Copernicus_DSM_COG_10_N52_00_E005_00_DEM.tif",
        fmt="Cloud-Optimised GeoTIFF",
        notes="30 m DSM; gdal_contour produces the contour lines, gdaldem the elevation bands.",
    ),
    Dataset(
        project="terrain",
        layer="terrain.basemap",
        name="AWS Terrain Tiles (Terrarium)",
        provider="Mapzen / AWS Open Data",
        license="ODbL + public domain sources",
        url="https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png",
        fmt="Raster-DEM tiles",
        notes="Consumed directly by MapLibre as a raster-dem source; nothing to download.",
    ),
]


def dataset_for(layer: str) -> Dataset | None:
    return next((d for d in DATASETS if d.layer == layer), None)
