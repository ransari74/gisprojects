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

# --- real-data sub-area -------------------------------------------------
# Nested inside STUDY_AREA. Parcels, irrigation canals, roads and buildings
# are loaded from real open PDOK sources scoped to this smaller Utrecht
# city-centre bbox -- see etl/real_data.py and `python -m etl.load --real`.
# Everything else keeps generating synthetically across the full STUDY_AREA
# above.
REAL_DATA_BBOX = (5.05, 52.06, 5.15, 52.12)
REAL_DATA_CENTRE = (
    (REAL_DATA_BBOX[0] + REAL_DATA_BBOX[2]) / 2,
    (REAL_DATA_BBOX[1] + REAL_DATA_BBOX[3]) / 2,
)

# Crop fields are the one real layer harvested over the *full* study area
# rather than REAL_DATA_BBOX: that bbox is centred on the city, where real
# farmland is scarce, while BRP crop parcels are large enough (typically
# several hectares) that covering the whole province doesn't blow up the row
# count the way BRK's tiny cadastral slivers would.
AGRI_HARVEST_BBOX = (MIN_LON, MIN_LAT, MAX_LON, MAX_LAT)

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
        layer="agri_canals",
        name="Irrigation/drainage canals",
        provider="OpenStreetMap contributors",
        license="ODbL-1.0",
        url="https://overpass-api.de/api/interpreter",
        fmt="Overpass API (JSON)",
        notes="waterway=canal/ditch/drain ways; clipped to REAL_DATA_BBOX.",
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
    Dataset(
        project="agriculture",
        layer="agri_field_embeddings",
        name="AlphaEarth Foundations Satellite Embedding V1",
        provider="Google / Google DeepMind",
        license="CC-BY-4.0",
        url="https://source.coop/tge-labs/aef",
        fmt="Cloud-Optimised GeoTIFF, 64 bands, 10 m, annual",
        notes=(
            "64 floats per 10 m pixel per year distilled from Sentinel-1/2 and Landsat. Published "
            "in Earth Engine as GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL, and since Nov 2025 as public "
            "COGs on Source Cooperative, AWS Open Data and gs://alphaearth_foundations -- which is "
            "what this project reads, so nothing credentialed sits in the serving path. Zonal-mean "
            "the pixels per parcel and re-normalise: the vectors are unit length, so a dot product "
            "is the cosine similarity. Attribution required."
        ),
    ),
    # --- remote sensing -----------------------------------------------------
    Dataset(
        project="remote_sensing",
        layer="rs_scenes",
        name="Sentinel-2 MSI L2A scene catalogue",
        provider="ESA Copernicus / Element 84 Earth Search",
        license="CC-BY-SA-3.0-IGO",
        url="https://earth-search.aws.element84.com/v1/collections/sentinel-2-l2a/items",
        fmt="STAC API (GeoJSON items)",
        notes=(
            "A STAC search bounded by the study-area bbox returns footprints, acquisition times "
            "and eo:cloud_cover directly -- the catalogue layer needs no pixels downloaded at all."
        ),
    ),
    Dataset(
        project="remote_sensing",
        layer="rs_index_cells",
        name="Sentinel-2 L2A surface reflectance",
        provider="ESA Copernicus / AWS Open Data",
        license="CC-BY-SA-3.0-IGO",
        url="https://registry.opendata.aws/sentinel-2-l2a-cogs/",
        fmt="Cloud-Optimised GeoTIFF (per band)",
        notes=(
            "NDVI (B08,B04), NDWI (B03,B08), NDBI (B11,B08) and NBR (B08,B12) computed per pixel, "
            "then zonal-summarised onto the 500 m grid with rasterstats. Only the bands used are "
            "read, and COG range requests keep it to the bbox."
        ),
    ),
    Dataset(
        project="remote_sensing",
        layer="rs_index_cells.lst",
        name="Landsat Collection 2 Level-2 surface temperature",
        provider="USGS / AWS Open Data",
        license="Public domain (US Government work)",
        url="https://registry.opendata.aws/usgs-landsat/",
        fmt="Cloud-Optimised GeoTIFF (ST_B10)",
        notes=(
            "Landsat rather than Sentinel-2 because only Landsat carries a thermal band. "
            "ST_B10 is already atmospherically corrected: scale by 0.00341802, add 149.0, "
            "subtract 273.15 for degrees Celsius."
        ),
    ),
    Dataset(
        project="remote_sensing",
        layer="rs_change",
        name="ESA WorldCover 10 m land cover, v100 (2020) and v200 (2021)",
        provider="ESA / VITO",
        license="CC-BY-4.0",
        url="https://registry.opendata.aws/esa-worldcover-vito/",
        fmt="Cloud-Optimised GeoTIFF",
        notes=(
            "Two epochs of the same product give the from/to transition matrix directly. "
            "ESA warns the two versions are not designed for change detection -- a real study "
            "would classify both epochs itself from Sentinel-2 rather than diff the products."
        ),
    ),
    Dataset(
        project="remote_sensing",
        layer="rs_subsidence",
        name="European Ground Motion Service, ortho (vertical) product",
        provider="Copernicus Land Monitoring Service / EEA",
        license="CC-BY-4.0",
        url="https://egms.land.copernicus.eu/",
        fmt="CSV per 100 km tile (persistent scatterers with velocity + time series)",
        notes=(
            "EGMS publishes InSAR ground motion for the whole EU from Sentinel-1, already "
            "unwrapped and calibrated. Tiles 32ULC/32UMC cover Utrecht. Negative velocity is "
            "subsidence."
        ),
    ),
    Dataset(
        project="remote_sensing",
        layer="rs_profiles",
        name="European Ground Motion Service, aggregated to infrastructure corridors",
        provider="Copernicus Land Monitoring Service / EEA",
        license="CC-BY-4.0",
        url="https://egms.land.copernicus.eu/",
        fmt="CSV persistent scatterers, buffered against an OSM corridor geometry",
        notes=(
            "Not a separate download: the EGMS scatterers are buffered against canal, dike and "
            "rail alignments from OSM and summarised per corridor. The reported differential is "
            "the spread of the *fitted* profile along the line, not of the raw scatterers -- "
            "PS scatter alone is several mm and would swamp the real gradient."
        ),
    ),
    Dataset(
        project="remote_sensing",
        layer="rs_water",
        name="Sentinel-1 GRD backscatter",
        provider="ESA Copernicus / AWS Open Data",
        license="CC-BY-SA-3.0-IGO",
        url="https://registry.opendata.aws/sentinel-1/",
        fmt="Cloud-Optimised GeoTIFF (VV/VH, GRD IW)",
        notes=(
            "Open water is specular at C-band, so a threshold near -18 dB on VV separates it "
            "cleanly. Radar sees through cloud, which is the whole reason flood mapping uses "
            "SAR rather than an optical water index."
        ),
    ),
]


def dataset_for(layer: str) -> Dataset | None:
    return next((d for d in DATASETS if d.layer == layer), None)
