"""Declarative models for the five project schemas.

The API still queries these tables through hand-written SQL -- ST_AsMVT and the
aggregate endpoints express far better that way than through the ORM. The
models exist so that Alembic's autogenerate has a target to diff against, which
makes the schema a single, reviewable, version-controlled artefact rather than
a pile of loose DDL.

Geometry columns use GeoAlchemy2, which also emits the GiST index for each one
(spatial_index defaults to True); the tile query depends on those indexes
existing, so they are part of the schema definition rather than an afterthought.
"""

from datetime import date, datetime
from decimal import Decimal

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

SRID = 4326


def _multipolygon() -> Geometry:
    return Geometry("MULTIPOLYGON", srid=SRID, spatial_index=True)


def _multiline() -> Geometry:
    return Geometry("MULTILINESTRING", srid=SRID, spatial_index=True)


def _polygon() -> Geometry:
    return Geometry("POLYGON", srid=SRID, spatial_index=True)


def _line() -> Geometry:
    return Geometry("LINESTRING", srid=SRID, spatial_index=True)


def _point() -> Geometry:
    return Geometry("POINT", srid=SRID, spatial_index=True)


# ===========================================================================
# meta -- shared study area and dataset provenance
# ===========================================================================
class StudyArea(Base):
    __tablename__ = "study_area"
    __table_args__ = {"schema": "meta"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    country: Mapped[str | None] = mapped_column(Text)
    #: Projected SRID for area/length maths in the study area's own region.
    epsg_local: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3857")
    geom: Mapped[object] = mapped_column(_multipolygon(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DatasetSource(Base):
    """Provenance written by the ETL, read by the frontend's sources panel."""

    __tablename__ = "dataset_source"
    __table_args__ = (
        UniqueConstraint("project", "layer", "dataset_name", name="dataset_source_key"),
        {"schema": "meta"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project: Mapped[str] = mapped_column(Text, nullable=False)
    layer: Mapped[str] = mapped_column(Text, nullable=False)
    dataset_name: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str | None] = mapped_column(Text)
    license: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    feature_count: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)


# ===========================================================================
# PROJECT 1 -- agriculture
# ===========================================================================
class Field(Base):
    __tablename__ = "fields"
    __table_args__ = {"schema": "agri"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    field_code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    farm_name: Mapped[str | None] = mapped_column(Text)
    crop_type: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    crop_year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    area_ha: Mapped[float] = mapped_column(Float, nullable=False)
    irrigated: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    organic: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    # ISRIC SoilGrids, 0-30 cm depth-weighted means
    soil_ph: Mapped[float | None] = mapped_column(Float)
    soil_organic_c: Mapped[float | None] = mapped_column(Float)
    soil_nitrogen: Mapped[float | None] = mapped_column(Float)
    soil_clay_pct: Mapped[float | None] = mapped_column(Float)
    soil_sand_pct: Mapped[float | None] = mapped_column(Float)
    soil_silt_pct: Mapped[float | None] = mapped_column(Float)
    soil_texture: Mapped[str | None] = mapped_column(Text)

    # ESA WorldCover majority class within the parcel
    landcover_class: Mapped[str | None] = mapped_column(Text)
    landcover_code: Mapped[int | None] = mapped_column(Integer)

    ndvi_mean: Mapped[float | None] = mapped_column(Float)
    ndvi_max: Mapped[float | None] = mapped_column(Float)
    ndvi_stddev: Mapped[float | None] = mapped_column(Float)

    elevation_m: Mapped[float | None] = mapped_column(Float)
    slope_deg: Mapped[float | None] = mapped_column(Float)
    yield_t_ha: Mapped[float | None] = mapped_column(Float, index=True)
    yield_class: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    geom: Mapped[object] = mapped_column(_multipolygon(), nullable=False)


class IrrigationCanal(Base):
    """The agriculture project's LINESTRING layer."""

    __tablename__ = "irrigation_canals"
    __table_args__ = {"schema": "agri"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canal_code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    canal_type: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    lined: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    capacity_m3s: Mapped[float | None] = mapped_column(Float)
    length_m: Mapped[float | None] = mapped_column(Float)
    condition: Mapped[str | None] = mapped_column(Text)
    geom: Mapped[object] = mapped_column(_multiline(), nullable=False)


class SoilSample(Base):
    __tablename__ = "soil_samples"
    __table_args__ = {"schema": "agri"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sample_code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    sampled_on: Mapped[date | None] = mapped_column(Date)
    depth_cm: Mapped[int | None] = mapped_column(Integer)
    ph: Mapped[float | None] = mapped_column(Float)
    organic_c: Mapped[float | None] = mapped_column(Float)
    nitrogen: Mapped[float | None] = mapped_column(Float)
    phosphorus: Mapped[float | None] = mapped_column(Float)
    potassium: Mapped[float | None] = mapped_column(Float)
    geom: Mapped[object] = mapped_column(_point(), nullable=False)


class FieldNdviTimeseries(Base):
    __tablename__ = "field_ndvi_timeseries"
    __table_args__ = (
        UniqueConstraint("field_id", "obs_date", name="ndvi_ts_field_date_key"),
        {"schema": "agri"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    field_id: Mapped[int] = mapped_column(
        ForeignKey("agri.fields.id", ondelete="CASCADE"), nullable=False, index=True
    )
    obs_date: Mapped[date] = mapped_column(Date, nullable=False)
    ndvi: Mapped[float] = mapped_column(Float, nullable=False)
    cloud_pct: Mapped[float | None] = mapped_column(Float)


# ===========================================================================
# PROJECT 2 -- parcel / cadastre
# ===========================================================================
class ZoningDistrict(Base):
    __tablename__ = "zoning_districts"
    __table_args__ = {"schema": "parcel"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    zone_code: Mapped[str] = mapped_column(Text, nullable=False)
    zone_name: Mapped[str] = mapped_column(Text, nullable=False)
    zone_category: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    max_far: Mapped[float | None] = mapped_column(Float)
    max_height_m: Mapped[float | None] = mapped_column(Float)
    min_lot_m2: Mapped[float | None] = mapped_column(Float)
    adopted_on: Mapped[date | None] = mapped_column(Date)
    geom: Mapped[object] = mapped_column(_multipolygon(), nullable=False)


class Parcel(Base):
    __tablename__ = "parcels"
    __table_args__ = {"schema": "parcel"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    parcel_pin: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    address: Mapped[str | None] = mapped_column(Text)
    district: Mapped[str | None] = mapped_column(Text)
    zone_code: Mapped[str | None] = mapped_column(Text, index=True)
    zoning_district_id: Mapped[int | None] = mapped_column(
        ForeignKey("parcel.zoning_districts.id", ondelete="SET NULL")
    )

    land_use: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    owner_type: Mapped[str | None] = mapped_column(Text)
    lot_area_m2: Mapped[float] = mapped_column(Float, nullable=False)
    building_area_m2: Mapped[float | None] = mapped_column(Float)
    floor_area_ratio: Mapped[float | None] = mapped_column(Float)
    coverage_ratio: Mapped[float | None] = mapped_column(Float)
    num_buildings: Mapped[int | None] = mapped_column(Integer, server_default="0")
    num_units: Mapped[int | None] = mapped_column(Integer, server_default="0")
    floors: Mapped[int | None] = mapped_column(Integer)
    year_built: Mapped[int | None] = mapped_column(Integer, index=True)

    assessed_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), index=True)
    land_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    improvement_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    value_per_m2: Mapped[float | None] = mapped_column(Float)
    last_sale_date: Mapped[date | None] = mapped_column(Date)
    last_sale_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    tax_exempt: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    geom: Mapped[object] = mapped_column(_multipolygon(), nullable=False)


class BoundaryLine(Base):
    """The cadastre project's LINESTRING layer."""

    __tablename__ = "boundary_lines"
    __table_args__ = {"schema": "parcel"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    parcel_pin: Mapped[str | None] = mapped_column(Text)
    boundary_type: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    survey_date: Mapped[date | None] = mapped_column(Date)
    length_m: Mapped[float | None] = mapped_column(Float)
    is_disputed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    geom: Mapped[object] = mapped_column(_multiline(), nullable=False)


class SalesHistory(Base):
    __tablename__ = "sales_history"
    __table_args__ = {"schema": "parcel"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    parcel_id: Mapped[int] = mapped_column(
        ForeignKey("parcel.parcels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sale_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    sale_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    price_per_m2: Mapped[float | None] = mapped_column(Float)
    buyer_type: Mapped[str | None] = mapped_column(Text)


# ===========================================================================
# PROJECT 3 -- demographics
# ===========================================================================
class CensusTract(Base):
    __tablename__ = "census_tracts"
    __table_args__ = {"schema": "demog"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tract_code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    tract_name: Mapped[str | None] = mapped_column(Text)
    district: Mapped[str | None] = mapped_column(Text)

    population: Mapped[int] = mapped_column(Integer, nullable=False)
    households: Mapped[int | None] = mapped_column(Integer)
    avg_household_size: Mapped[float | None] = mapped_column(Float)
    area_km2: Mapped[float] = mapped_column(Float, nullable=False)
    density_km2: Mapped[float | None] = mapped_column(Float, index=True)

    pct_under_15: Mapped[float | None] = mapped_column(Float)
    pct_15_29: Mapped[float | None] = mapped_column(Float)
    pct_30_44: Mapped[float | None] = mapped_column(Float)
    pct_45_64: Mapped[float | None] = mapped_column(Float)
    pct_65_plus: Mapped[float | None] = mapped_column(Float)
    median_age: Mapped[float | None] = mapped_column(Float)

    median_income: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), index=True)
    unemployment_rate: Mapped[float | None] = mapped_column(Float)
    pct_tertiary_educated: Mapped[float | None] = mapped_column(Float)
    pct_foreign_born: Mapped[float | None] = mapped_column(Float)

    dwellings: Mapped[int | None] = mapped_column(Integer)
    pct_owner_occupied: Mapped[float | None] = mapped_column(Float)
    pct_vacant: Mapped[float | None] = mapped_column(Float)
    median_rent: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))

    #: Composite 0-100 index; the choropleth's default colour column.
    deprivation_index: Mapped[float | None] = mapped_column(Float)

    census_year: Mapped[int] = mapped_column(Integer, nullable=False, server_default="2021")
    geom: Mapped[object] = mapped_column(_multipolygon(), nullable=False)


class PopulationGrid(Base):
    __tablename__ = "population_grid"
    __table_args__ = {"schema": "demog"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cell_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    population: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    resolution_m: Mapped[int] = mapped_column(Integer, nullable=False, server_default="500")
    geom: Mapped[object] = mapped_column(_polygon(), nullable=False)


class CommuteFlow(Base):
    """The demographics project's LINESTRING layer -- OD desire lines."""

    __tablename__ = "commute_flows"
    __table_args__ = (
        UniqueConstraint("origin_code", "dest_code", "mode", name="commute_flows_od_mode_key"),
        {"schema": "demog"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    origin_code: Mapped[str] = mapped_column(Text, nullable=False)
    dest_code: Mapped[str] = mapped_column(Text, nullable=False)
    trips: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    avg_duration_min: Mapped[float | None] = mapped_column(Float)
    distance_km: Mapped[float | None] = mapped_column(Float)
    geom: Mapped[object] = mapped_column(_line(), nullable=False)


class AgeStructure(Base):
    __tablename__ = "age_structure"
    __table_args__ = (
        UniqueConstraint("tract_id", "age_band", name="age_structure_tract_band_key"),
        {"schema": "demog"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tract_id: Mapped[int] = mapped_column(
        ForeignKey("demog.census_tracts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    age_band: Mapped[str] = mapped_column(Text, nullable=False)
    band_order: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    male: Mapped[int] = mapped_column(Integer, nullable=False)
    female: Mapped[int] = mapped_column(Integer, nullable=False)


# ===========================================================================
# PROJECT 4 -- transport
# ===========================================================================
class RoadSegment(Base):
    """The transport project's primary LINESTRING layer."""

    __tablename__ = "road_segments"
    __table_args__ = {"schema": "transport"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    osm_id: Mapped[int | None] = mapped_column(BigInteger)
    name: Mapped[str | None] = mapped_column(Text)
    highway_class: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    functional_class: Mapped[int | None] = mapped_column(SmallInteger)
    oneway: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    lanes: Mapped[int | None] = mapped_column(SmallInteger)
    maxspeed_kmh: Mapped[int | None] = mapped_column(SmallInteger)
    surface: Mapped[str | None] = mapped_column(Text)
    bridge: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    tunnel: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    length_m: Mapped[float] = mapped_column(Float, nullable=False)

    aadt: Mapped[int | None] = mapped_column(Integer, index=True)
    peak_speed_kmh: Mapped[float | None] = mapped_column(Float)
    congestion_index: Mapped[float | None] = mapped_column(Float, index=True)
    accident_count: Mapped[int | None] = mapped_column(Integer, server_default="0")
    has_bike_lane: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    geom: Mapped[object] = mapped_column(_multiline(), nullable=False)


class TransitRoute(Base):
    __tablename__ = "transit_routes"
    __table_args__ = {"schema": "transport"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    route_code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    route_name: Mapped[str | None] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    operator: Mapped[str | None] = mapped_column(Text)
    color: Mapped[str | None] = mapped_column(Text)
    headway_min: Mapped[float | None] = mapped_column(Float)
    daily_ridership: Mapped[int | None] = mapped_column(Integer)
    length_km: Mapped[float | None] = mapped_column(Float)
    geom: Mapped[object] = mapped_column(_multiline(), nullable=False)


class TransitStop(Base):
    __tablename__ = "transit_stops"
    __table_args__ = {"schema": "transport"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stop_code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    stop_name: Mapped[str | None] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    wheelchair_accessible: Mapped[bool | None] = mapped_column(Boolean)
    shelter: Mapped[bool | None] = mapped_column(Boolean)
    daily_boardings: Mapped[int | None] = mapped_column(Integer)
    routes_served: Mapped[int | None] = mapped_column(SmallInteger)
    geom: Mapped[object] = mapped_column(_point(), nullable=False)


class Isochrone(Base):
    """The transport project's POLYGON layer -- travel-time catchments."""

    __tablename__ = "isochrones"
    __table_args__ = (
        UniqueConstraint("origin_code", "mode", "minutes", name="isochrones_origin_mode_min_key"),
        {"schema": "transport"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    origin_code: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    minutes: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    population_reached: Mapped[int | None] = mapped_column(Integer)
    jobs_reached: Mapped[int | None] = mapped_column(Integer)
    area_km2: Mapped[float | None] = mapped_column(Float)
    geom: Mapped[object] = mapped_column(_multipolygon(), nullable=False)


class TrafficCount(Base):
    __tablename__ = "traffic_counts"
    __table_args__ = (
        UniqueConstraint("segment_id", "count_date", "hour", name="traffic_counts_seg_date_hour_key"),
        CheckConstraint("hour BETWEEN 0 AND 23", name="traffic_counts_hour_range"),
        {"schema": "transport"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    segment_id: Mapped[int] = mapped_column(
        ForeignKey("transport.road_segments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    count_date: Mapped[date] = mapped_column(Date, nullable=False)
    hour: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    vehicles: Mapped[int] = mapped_column(Integer, nullable=False)
    avg_speed_kmh: Mapped[float | None] = mapped_column(Float)


# ===========================================================================
# PROJECT 5 -- 3D terrain
# ===========================================================================
class Building(Base):
    __tablename__ = "buildings"
    __table_args__ = {"schema": "terrain"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    osm_id: Mapped[int | None] = mapped_column(BigInteger)
    name: Mapped[str | None] = mapped_column(Text)
    building_type: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    levels: Mapped[int | None] = mapped_column(SmallInteger)
    height_m: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    min_height_m: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    #: Terrain elevation at the footprint centroid. MapLibre needs the
    #: extrusion base offset by this when the model is draped over 3D terrain.
    ground_elev_m: Mapped[float | None] = mapped_column(Float)
    roof_shape: Mapped[str | None] = mapped_column(Text)
    roof_color: Mapped[str | None] = mapped_column(Text)
    footprint_m2: Mapped[float | None] = mapped_column(Float)
    volume_m3: Mapped[float | None] = mapped_column(Float)
    year_built: Mapped[int | None] = mapped_column(Integer)
    solar_potential_kwh_m2: Mapped[float | None] = mapped_column(Float)
    shadow_index: Mapped[float | None] = mapped_column(Float)
    energy_class: Mapped[str | None] = mapped_column(String(1))
    geom: Mapped[object] = mapped_column(_multipolygon(), nullable=False)


class Contour(Base):
    """The terrain project's LINESTRING layer, from the Copernicus DEM."""

    __tablename__ = "contours"
    __table_args__ = {"schema": "terrain"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    elevation_m: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    interval_m: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="10")
    #: Every fifth contour, drawn heavier on the map.
    is_index: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    geom: Mapped[object] = mapped_column(_multiline(), nullable=False)


class DrainageLine(Base):
    __tablename__ = "drainage_lines"
    __table_args__ = {"schema": "terrain"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str | None] = mapped_column(Text)
    line_type: Mapped[str] = mapped_column(Text, nullable=False)
    stream_order: Mapped[int | None] = mapped_column(SmallInteger)
    length_m: Mapped[float | None] = mapped_column(Float)
    slope_pct: Mapped[float | None] = mapped_column(Float)
    geom: Mapped[object] = mapped_column(_multiline(), nullable=False)


class ElevationBand(Base):
    __tablename__ = "elevation_bands"
    __table_args__ = {"schema": "terrain"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    band_min_m: Mapped[float] = mapped_column(Float, nullable=False)
    band_max_m: Mapped[float] = mapped_column(Float, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    color_hex: Mapped[str] = mapped_column(Text, nullable=False)
    area_km2: Mapped[float | None] = mapped_column(Float)
    geom: Mapped[object] = mapped_column(_multipolygon(), nullable=False)


class ElevationProfile(Base):
    __tablename__ = "elevation_profile"
    __table_args__ = (
        UniqueConstraint("transect_id", "seq", name="elevation_profile_transect_seq_key"),
        {"schema": "terrain"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    transect_id: Mapped[str] = mapped_column(Text, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    distance_m: Mapped[float] = mapped_column(Float, nullable=False)
    elevation_m: Mapped[float] = mapped_column(Float, nullable=False)
    #: Terrain plus whatever building the transect passes through.
    surface_elev_m: Mapped[float | None] = mapped_column(Float)
    geom: Mapped[object] = mapped_column(_point(), nullable=False)
