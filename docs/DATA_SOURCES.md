# Open Geospatial Data Sources — 5-Theme Portfolio

Research date: **2026-08-13**

---

## 0. Verification status legend

This session ran behind a restrictive egress proxy: `curl` and direct page fetches were
blocked for almost every data host (only `raw.githubusercontent.com` was reachable).
Verification was therefore done via live web search that reads page contents, plus two
authoritative machine-readable files fetched directly from GitHub. Every entry below is
tagged:

| Tag | Meaning |
|-----|---------|
| **[V]** | Verified this session — the URL string, file size or schema was read from live page content or a fetched file |
| **[P]** | Pattern — constructed from the provider's officially documented naming convention; the base path is verified, the specific tile/date component is not |
| **[U]** | Unverified — from provider documentation/prior knowledge; `curl -sI` it before you build on it |

**Do this first**, once you have unrestricted network:

```bash
# smoke-test every URL in this doc
while read -r u; do printf '%-110s ' "$u"; curl -sI -o /dev/null -w '%{http_code} %{size_download}\n' -L "$u"; done <<'EOF'
https://download.geofabrik.de/europe/netherlands/utrecht-latest.osm.pbf
https://geodata.cbs.nl/files/Wijkenbuurtkaart/WijkBuurtkaart_2025_v1.zip
https://service.pdok.nl/rvo/brpgewaspercelen/atom/v1_0/downloads/brpgewaspercelen_definitief_2024.gpkg
https://service.pdok.nl/rvo/referentiepercelen/atom/downloads/referentiepercelen.gpkg
https://data.3dbag.nl/v20250903/tile_index.fgb
https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_N52_00_E005_00_DEM/Copernicus_DSM_COG_10_N52_00_E005_00_DEM.tif
https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_N51E003_Map.tif
http://gtfs.ovapi.nl/gtfs-nl.zip
https://cdn.knmi.nl/knmi/map/page/klimatologie/gegevens/daggegevens/etmgeg_260.zip
EOF
```

---

## 1. Recommended study area: **Utrecht, Netherlands**

### Recommendation

> **Use the City of Utrecht plus its surrounding green belt / Province of Utrecht.**
> Bounding box (WGS84 / EPSG:4326): **`4.95 51.98 5.30 52.18`**
> Same box in RD New (EPSG:28992): **`127000 443500 151500 466000`**
> Everything in this document overlays on that box.

### Why Utrecht beats the alternatives

The only two themes that are genuinely *region-specific* are **crop-field boundaries**
(theme 1) and **cadastral parcels** (theme 2). Soil, land cover, population grids, DEM,
OSM and Overture are all global. So the study area should be chosen on those two — and
on whether a high-quality 3D building dataset exists.

| Candidate | Crop parcels | Cadastre | 3D buildings w/ height | Verdict |
|---|---|---|---|---|
| **Netherlands (Utrecht)** | **BRP Gewaspercelen — CC0, per-year GeoPackage, crop name + crop code + category, 2009→2025** | BRK Kadastrale Kaart parcels via OGC API Features, + BAG buildings with year/use/area | **3DBAG — LoD1.2/1.3/2.2, measured roof heights from lidar, CC BY 4.0, small per-tile GPKG/CityJSON** | **Winner** |
| France (a département) | RPG crop parcels — excellent | Etalab cadastre GeoJSON + **DVF real transaction prices** (best "value" attribute anywhere) | BD TOPO `HAUTEUR`, but per-dépt archives are `.7z` and ~1 GB | Strong runner-up; only loses on 3D download ergonomics |
| Denmark | Yes (Markblokke) | Yes (Matriklen) | DHM/Denmark 3D, heavier | Fine, but smaller ecosystem, more Danish-only docs |
| US county (King Co., Travis Co.) | Weak — CDL is raster only, no field polygons | **Best in class**: parcel polygons *with zoning + assessed value* | Overture/Microsoft footprints, height coverage patchy | Wins theme 2, loses theme 1 badly |

Utrecht specifically (rather than Amsterdam or Rotterdam):

- It is **compact** — the whole city fits in a ~25 × 22 km box, so extracts stay small.
- The box contains **real farmland** (Groene Hart polder, Vleuten-De Meern, Haarzuilens),
  so the agriculture theme is not empty — which is not true of an Amsterdam or Rotterdam box.
- Geofabrik ships a **province-level OSM extract** (`utrecht-latest.osm.pbf`, ~90 MB) — one
  clean download, no country-wide 1.3 GB file.
- **KNMI station 260 (De Bilt)** — the Dutch national reference weather station, with a
  100-year daily record — sits *inside* the box. Free precipitation time series with a
  real point geometry.
- Dense mixed land use: historic centre, Utrecht Science Park, Leidsche Rijn new-build
  district (great for `bouwjaar` / building-age charts), industry at Lage Weide.

### The one gap, and how to fill it

Dutch cadastral parcels are open but carry **no zoning and no assessed value** (WOZ values
are only queryable per address, not in bulk). Two clean substitutes:

1. **CBS Wijk- en Buurtkaart** carries `g_wozbag` / average dwelling value per neighbourhood —
   join parcels → neighbourhood to get a value surface.
2. **BAG `gebruiksdoel`** (residential / industrial / office / retail / healthcare /
   education / sport / lodging / meeting / cell) on every unit gives a de-facto land-use
   classification per building, which you can aggregate to the parcel.

If you *must* have parcel-level zoning + assessed value, add **NYC MapPLUTO** as a
secondary study area (see §3.5).

---

## 2. Theme 1 — AGRICULTURE

### 2.1 BRP Gewaspercelen (Dutch crop-field parcels) ★ core dataset

| | |
|---|---|
| **Name** | Basisregistratie Gewaspercelen (BRP), RVO / PDOK |
| **License** | **CC0-1.0** (public domain) **[V]** |
| **Format** | GeoPackage (2021–2025), zipped GPKG (2009–2020) |
| **Geometry** | POLYGON, EPSG:28992 |
| **Size** | Whole-NL year file ≈ 0.6–1.0 GB **[U]**; Utrecht bbox extract ≈ **8–15 MB** |
| **Key fields** **[V]** | `gewas` (crop name, NL), `gewascode` (int), `category` ∈ {`Grasland`,`Bouwland`,`Sloot`,`Landschapselement`}, `area` (m²), `jaar` |

Direct downloads **[V]** (schema and URLs read from the fiboa data survey, which mirrors the
PDOK Atom feed):

```
Atom feed index : https://service.pdok.nl/rvo/brpgewaspercelen/atom/v1_0/index.xml
2025 (concept)  : https://service.pdok.nl/rvo/brpgewaspercelen/atom/v1_0/downloads/brpgewaspercelen_concept_2025.gpkg
2021-2024 final : https://service.pdok.nl/rvo/brpgewaspercelen/atom/v1_0/downloads/brpgewaspercelen_definitief_<YEAR>.gpkg
2009-2020 final : https://service.pdok.nl/rvo/brpgewaspercelen/atom/v1_0/downloads/brpgewaspercelen_definitief_<YEAR>.zip
OGC API Features: https://api.pdok.nl/rvo/gewaspercelen/ogc/v1
WFS             : https://service.pdok.nl/rvo/brpgewaspercelen/wfs/v1_0
```

**Recommended (stays inside budget) — clip server-side via OGC API Features:**

```bash
# discover collection names first
ogrinfo "OAPIF:https://api.pdok.nl/rvo/gewaspercelen/ogc/v1"

# Utrecht extract straight to GeoPackage
ogr2ogr -f GPKG utrecht_crops.gpkg \
  "OAPIF:https://api.pdok.nl/rvo/gewaspercelen/ogc/v1" gewaspercelen \
  -spat 4.95 51.98 5.30 52.18 -spat_srs EPSG:4326 \
  -t_srs EPSG:28992 -nln crops -nlt PROMOTE_TO_MULTI
```

**Full-year alternative (if you want multi-year trend charts — download once, clip locally):**

```bash
curl -L -O https://service.pdok.nl/rvo/brpgewaspercelen/atom/v1_0/downloads/brpgewaspercelen_definitief_2024.gpkg
ogr2ogr -f GPKG utrecht_crops_2024.gpkg brpgewaspercelen_definitief_2024.gpkg \
  -spat 127000 443500 151500 466000 -nln crops_2024
```

**Load to PostGIS:**

```bash
ogr2ogr -f PostgreSQL PG:"host=$PGHOST dbname=gis user=$PGUSER password=$PGPASS sslmode=require" \
  utrecht_crops.gpkg -nln ag_crop_parcels \
  -lco GEOMETRY_NAME=geom -lco FID=gid -lco SPATIAL_INDEX=YES \
  -nlt MULTIPOLYGON -t_srs EPSG:28992 -progress
```

**Analytics you get free:** area by crop type, grass-vs-arable ratio per municipality,
crop rotation between years (join on geometry overlap), parcel-size distribution histogram.

### 2.2 Referentiepercelen (agricultural reference parcels / field blocks)

| | |
|---|---|
| **License** | **CC0-1.0** **[V]** |
| **URL** **[V]** | `https://service.pdok.nl/rvo/referentiepercelen/atom/downloads/referentiepercelen.gpkg` |
| **WFS** | `https://service.pdok.nl/rvo/referentiepercelen/wfs/v1_0` |
| **Format / geom** | GeoPackage / POLYGON, EPSG:28992 |
| **Fields** **[V]** | `id`, `area` (m²), `type` ∈ {`Hout`,`Landbouwgrond`,`Overig`,`Water`}, `versiebron` |
| **Size** | whole-NL ≈ several hundred MB **[U]** → prefer the WFS bbox extract |

```bash
ogr2ogr -f GPKG utrecht_refparcels.gpkg \
  "WFS:https://service.pdok.nl/rvo/referentiepercelen/wfs/v1_0" \
  -spat 127000 443500 151500 466000 -nln refparcels
```

### 2.3 ESA WorldCover 2021 v200 (10 m global land cover)

| | |
|---|---|
| **License** | **CC BY 4.0** **[V]** |
| **Format / geom** | Cloud-Optimized GeoTIFF / RASTER, 10 m, EPSG:4326, 3°×3° tiles |
| **Tile for Utrecht** | `N51E003` (covers 51–54 N, 3–6 E) |
| **Size** | full tile ≈ 60–90 MB **[U]**; Utrecht clip ≈ **2 MB** |
| **Classes** | 11 classes: 10 tree, 20 shrub, 30 grass, 40 cropland, 50 built-up, 60 bare, 70 snow, 80 water, 90 herbaceous wetland, 95 mangrove, 100 moss |

URL **[P]** (bucket + `v200/2021/map/` prefix verified; filename follows the documented pattern):

```
https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_N51E003_Map.tif
```

**Clip without downloading the whole tile (GDAL `/vsicurl`) — strongly recommended:**

```bash
gdal_translate -projwin 4.95 52.18 5.30 51.98 -co COMPRESS=DEFLATE -co TILED=YES \
  /vsicurl/https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_N51E003_Map.tif \
  worldcover_utrecht.tif
```

**Load to PostGIS:**

```bash
raster2pgsql -s 4326 -I -C -M -F -t 256x256 worldcover_utrecht.tif public.lc_worldcover2021 \
  | psql "postgresql://$PGUSER:$PGPASS@$PGHOST/gis?sslmode=require"
```

*(Requires `CREATE EXTENSION postgis_raster;` — check your host supports it; if not, polygonise
first with `gdal_polygonize.py worldcover_utrecht.tif -f GPKG lc.gpkg lc class`.)*

### 2.4 ISRIC SoilGrids 250 m

| | |
|---|---|
| **License** | **CC BY 4.0** |
| **Base URL** **[V]** | `https://files.isric.org/soilgrids/latest/data/` (WebDAV, anonymous) |
| **Format / geom** | VRT → GeoTIFF / RASTER, 250 m, Homolosine (`EPSG:152160`-ish custom) |
| **Size** | Utrecht clip per property/depth ≈ **<1 MB** |
| **Properties** | `clay`, `sand`, `silt`, `phh2o`, `soc` (organic carbon), `nitrogen`, `cec`, `bdod`, `ocs` — each at depths `0-5cm`, `5-15cm`, `15-30cm`, `30-60cm`, `60-100cm`, `100-200cm`, statistic `mean`/`Q0.05`/`Q0.95` |

```bash
# clip clay content 0-5 cm mean, reprojected to WGS84
gdal_translate -of GTiff -co COMPRESS=DEFLATE \
  -projwin_srs EPSG:4326 -projwin 4.95 52.18 5.30 51.98 \
  "/vsicurl/https://files.isric.org/soilgrids/latest/data/clay/clay_0-5cm_mean.vrt" \
  soil_clay_0_5_homolosine.tif
gdalwarp -t_srs EPSG:28992 -r bilinear soil_clay_0_5_homolosine.tif soil_clay_0_5_utrecht.tif

# repeat for soc, phh2o, sand, nitrogen  -> 5 rasters, ~3 MB total
```

WCS alternative (server-side subset, no VRT):
`https://maps.isric.org/mapserv?map=/map/clay.map&SERVICE=WCS&VERSION=2.0.1&REQUEST=GetCoverage&COVERAGEID=clay_0-5cm_mean&SUBSET=X(...)&SUBSET=Y(...)&FORMAT=image/tiff` **[U]**

### 2.5 Climate / precipitation

**A. CHELSA V2.1 bioclim (1 km global climatology)** — license **CC0 / free reuse**

Bucket **[V]**: `https://os.unil.cloud.switch.ch/chelsa02/chelsa/global/climatologies/`
File pattern **[P]**: `.../1981-2010/bio/CHELSA_bio12_1981-2010_V.2.1.tif` (bio12 = annual precipitation)

```bash
gdal_translate -projwin 4.95 52.18 5.30 51.98 \
  /vsicurl/https://os.unil.cloud.switch.ch/chelsa02/chelsa/global/climatologies/1981-2010/bio/CHELSA_bio12_1981-2010_V.2.1.tif \
  chelsa_bio12_utrecht.tif      # ~50 KB
```

**B. KNMI De Bilt daily series (station 260 — inside the study area)** ★ best for charts

| | |
|---|---|
| **License** | KNMI open data, free reuse with attribution |
| **URL** **[V]** | `https://cdn.knmi.nl/knmi/map/page/klimatologie/gegevens/daggegevens/etmgeg_260.zip` |
| **Format / geom** | CSV in ZIP → POINT (one station, 52.10 N 5.18 E) |
| **Size** | ≈ 2 MB, ~1901→today, ~45,000 rows |
| **Fields** | `RH` daily precipitation (0.1 mm), `TG`/`TN`/`TX` temps (0.1 °C), `SQ` sunshine, `FG` wind, `UG` humidity, `EV24` evapotranspiration |

```bash
curl -L -O https://cdn.knmi.nl/knmi/map/page/klimatologie/gegevens/daggegevens/etmgeg_260.zip
unzip -o etmgeg_260.zip
# header block is ~50 comment lines starting with '#'
psql "$DATABASE_URL" -c "CREATE TABLE knmi_debilt(stn int, yyyymmdd date, ddvec int, fhvec int, fg int, \
  tg int, tn int, tx int, sq int, sp int, q int, rh int, rhx int, pg int, ug int)"
```

Full station list (all NL stations, for a point layer):
`https://cdn.knmi.nl/knmi/map/page/klimatologie/gegevens/daggegevens/etmgeg_<STN>.zip` **[P]**

### 2.6 EuroCrops (cross-EU harmonised crop parcels) — alternative / comparison layer

| | |
|---|---|
| **License** | CC BY 4.0 |
| **URL** **[V]** | Zenodo record `https://zenodo.org/records/10118572` (per-country zipped shapefiles) |
| **Format / geom** | Shapefile in ZIP / POLYGON |
| **Extra fields** **[V]** | `EC_trans_n` (crop name in English), `EC_hcat_n` (HCAT name), `EC_hcat_c` (10-digit HCAT code) |

Useful if you want a *cross-country* chart (NL vs DE vs FR crop mix) — the NL layer is the
same BRP source, re-tagged with the harmonised taxonomy.

---

## 3. Theme 2 — PARCEL / CADASTRE

### 3.1 BRK Kadastrale Kaart — parcel polygons ★ core dataset

| | |
|---|---|
| **Name** | Kadastrale Kaart (BRK), Kadaster / PDOK |
| **License** | Open — CC BY / public task data, free reuse |
| **OGC API** **[V]** | `https://api.pdok.nl/kadaster/brk-kadastrale-kaart/ogc/v1` |
| **Bulk download viewer** **[V]** | `https://app.pdok.nl/kadaster/kadastralekaart/download-viewer/` (pick municipality → GPKG/GML zip) |
| **Format / geom** | GeoJSON / GeoPackage — **POLYGON** (`perceel`), plus LINESTRING (`kadastralegrens`), POINT (`nummeraanduidingreeks`) |
| **Size** | Utrecht city bbox ≈ 90k parcels ≈ **25–40 MB as GPKG** |
| **Fields** | `identificatieLokaalID`, `kadastraleGemeenteWaarde`, `sectie`, `perceelnummer`, `kadastraleGrootteWaarde` (parcel area m²), `begrenzingPerceel` |
| **Query limit** **[V]** | 1,000 features per request — paginate (GDAL does this for you) |

```bash
# list collections
ogrinfo "OAPIF:https://api.pdok.nl/kadaster/brk-kadastrale-kaart/ogc/v1"

# parcels (POLYGON)
ogr2ogr -f GPKG utrecht_parcels.gpkg \
  "OAPIF:https://api.pdok.nl/kadaster/brk-kadastrale-kaart/ogc/v1" perceel \
  -spat 4.95 51.98 5.30 52.18 -spat_srs EPSG:4326 \
  -t_srs EPSG:28992 -nln parcels -nlt MULTIPOLYGON

# cadastral boundaries (LINESTRING) -- satisfies the "must include LINESTRING" constraint
ogr2ogr -f GPKG utrecht_parcel_lines.gpkg \
  "OAPIF:https://api.pdok.nl/kadaster/brk-kadastrale-kaart/ogc/v1" kadastralegrens \
  -spat 4.95 51.98 5.30 52.18 -spat_srs EPSG:4326 -t_srs EPSG:28992 -nln parcel_boundaries
```

Raw HTTP form of the same request (paste in a browser, no key, no login):

```
https://api.pdok.nl/kadaster/brk-kadastrale-kaart/ogc/v1/collections/perceel/items?bbox=5.05,52.06,5.15,52.12&limit=1000&f=json
```

### 3.2 BAG — buildings + address units (the attribute richness)

| | |
|---|---|
| **License** | Open, public task data (free reuse, attribution Kadaster) |
| **OGC API** **[V]** | `https://api.pdok.nl/lv/bag/ogc/v1` |
| **WFS** **[V]** | `https://service.pdok.nl/lv/bag/wfs/v2_0` |
| **Atom (whole-NL GPKG)** | via `https://www.pdok.nl/atom-downloadservices` — several GB, **do not** use for this project |
| **Collections** **[V]** | `pand`, `verblijfsobject`, `ligplaats`, `standplaats`, `nummeraanduiding`, `openbareruimte`, `woonplaats` |
| **Geometry** | `pand` = POLYGON (building footprint); `verblijfsobject` = POINT |
| **Size** | Utrecht bbox: ~75k buildings ≈ **20 MB GPKG**; ~180k units ≈ 15 MB |
| **Key fields** | `identificatie`, **`bouwjaar`** (construction year), `status`, **`gebruiksdoel`** (residential/office/industry/retail/healthcare/education/sport/lodging/meeting/cell), **`oppervlakte`** (floor area m²) |

```bash
ogr2ogr -f GPKG utrecht_buildings.gpkg "OAPIF:https://api.pdok.nl/lv/bag/ogc/v1" pand \
  -spat 4.95 51.98 5.30 52.18 -spat_srs EPSG:4326 -t_srs EPSG:28992 -nln buildings

ogr2ogr -f GPKG utrecht_units.gpkg "OAPIF:https://api.pdok.nl/lv/bag/ogc/v1" verblijfsobject \
  -spat 4.95 51.98 5.30 52.18 -spat_srs EPSG:4326 -t_srs EPSG:28992 -nln units
```

**Analytics:** buildings by decade of construction (Leidsche Rijn vs binnenstad), floor area
per parcel, mix of `gebruiksdoel` per neighbourhood, floor-space-index (Σ unit area / parcel area).

### 3.3 Property value — CBS neighbourhood WOZ

Dutch parcel-level assessed value is not bulk-open. Use the **neighbourhood average dwelling
value (`g_wozbag` / `gem_woz`)** from the CBS Wijk- en Buurtkaart (§4.1) and join:

```sql
CREATE TABLE parcel_value AS
SELECT p.gid, p.identificatielokaalid, p.kadastralegroottewaarde AS area_m2,
       b.buurtnaam, b.gem_woz AS avg_dwelling_value_k_eur,
       p.kadastralegroottewaarde * (b.gem_woz*1000.0 / NULLIF(b.aantal_woningen,0)) AS crude_value_proxy
FROM parcels p
JOIN cbs_buurten b ON ST_Intersects(b.geom, ST_PointOnSurface(p.geom));
```

### 3.4 Land use / zoning substitutes

- **Bestand Bodemgebruik (CBS land use polygons)** — via PDOK, ~40 land-use classes, POLYGON. **[U]**
  `https://service.pdok.nl/cbs/bestandbodemgebruik/wfs/v1_0`
- **BGT (large-scale topography)** — OGC API `https://api.pdok.nl/lv/bgt/ogc/v1` **[V]**;
  extremely detailed surface-type polygons (road, water, green, building terrain).
- **Ruimtelijke Plannen (statutory zoning)** — open but awkward per-plan GML; only worth it
  if zoning is a hard requirement.

### 3.5 US alternative (only if you need parcel-level zoning + assessed value)

| Dataset | License | URL | Notes |
|---|---|---|---|
| **NYC MapPLUTO** | Public domain (NYC OpenData) | Portal: `https://www.nyc.gov/content/planning/pages/resources/datasets/mappluto-pluto-change` **[V]**; also `https://catalog.data.gov/dataset/primary-land-use-tax-lot-output-map-mappluto` **[V]** | **The single richest open parcel table on earth**: `ZoneDist1`, `LandUse`, `BldgClass`, `AssessTot`, `AssessLand`, `YearBuilt`, `NumFloors`, `BldgArea`, `ResidFAR`. Per-borough shapefile ≈ 100–250 MB; Manhattan only ≈ 40 MB. Exact filename changes each release (`nyc_mappluto_25v3_shp.zip` style) — **[P]**, grab it from the portal page. |
| **King County, WA parcels** | Public domain | ArcGIS Hub, GeoJSON export **[U]** | Parcel polygons + separate assessor CSVs (value, use code) |
| **City of Austin / Travis County** | Public domain | `https://data.austintexas.gov` (Socrata → `/api/geospatial/<id>?method=export&format=GeoJSON`) **[U]** | Zoning polygons are the strong layer here |

---

## 4. Theme 3 — DEMOGRAPHIC

### 4.1 CBS Wijk- en Buurtkaart 2025 ★ core dataset

| | |
|---|---|
| **Name** | CBS Wijk- en Buurtkaart (municipality / district / neighbourhood boundaries + ~120 statistics) |
| **License** | CC BY 4.0 (CBS open data) |
| **URL** **[V]** | `https://geodata.cbs.nl/files/Wijkenbuurtkaart/WijkBuurtkaart_2025_v1.zip` |
| **Also** **[V]** | `https://geodata.cbs.nl/files/Wijkenbuurtkaart/` (directory listing — all years), `WijkBuurtkaart_2024_v2.zip` |
| **Size** **[V]** | **103,269,422 bytes ≈ 103 MB** (2025 v1) |
| **Format / geom** | GeoPackage inside ZIP / **POLYGON**, EPSG:28992 |
| **Layers** | `gemeenten2025`, `wijken2025`, `buurten2025` |
| **Key fields** | `gemeentenaam`, `wijknaam`, `buurtnaam`, `aantal_inwoners`, `mannen`, `vrouwen`, age bands `p_00_14_jr`…`p_65_eo_jr`, `aantal_huishoudens`, `gemiddelde_huishoudensgrootte`, `p_west_al`/`p_n_w_al` (migration background), `aantal_woningen`, `gem_woz` (avg property value ×€1000), `bevolkingsdichtheid_inw_per_km2`, `stedelijkheid_adres_dichtheid`, plus distance-to-service fields (`af_supermarkt`, `af_huisartsenpraktijk`, …) |
| **WFS** **[V]** | `https://service.pdok.nl/cbs/wijkenbuurten/2024/wfs/v1_0?request=GetCapabilities&service=WFS` |

```bash
curl -L -O https://geodata.cbs.nl/files/Wijkenbuurtkaart/WijkBuurtkaart_2025_v1.zip
unzip -o WijkBuurtkaart_2025_v1.zip -d cbs2025
ogrinfo -so cbs2025/*.gpkg                       # list layers

# clip to Utrecht and load
ogr2ogr -f PostgreSQL PG:"$PG_CONN" cbs2025/wijkenbuurten_2025_v1.gpkg buurten \
  -spat 127000 443500 151500 466000 \
  -nln demo_buurten -lco GEOMETRY_NAME=geom -nlt MULTIPOLYGON -t_srs EPSG:28992
```

*This one dataset carries the entire demographic theme — dozens of ready-made chart axes.*

### 4.2 Kontur Population (H3 hexagons, 400 m)

| | |
|---|---|
| **License** | **CC BY 4.0** |
| **NL page** **[V]** | `https://data.humdata.org/dataset/kontur-population-netherlands` |
| **Global/other** **[V]** | `https://data.humdata.org/organization/kontur` (per-country subsets), `https://www.kontur.io/datasets/population-dataset/` |
| **Format / geom** | `.gpkg.gz` / **POLYGON** (H3 hexagons), EPSG:3857 |
| **Size** | NL ≈ **25–40 MB** compressed |
| **Fields** | `h3` (H3 index string), `population` (float) |
| **Filename pattern** **[P]** | `kontur_population_NL_<YYYYMMDD>.gpkg.gz` — HDX resource UUID changes per release, take the download link off the dataset page |

```bash
curl -L -o kontur_population_NL.gpkg.gz "<resource link from the HDX page>"
gunzip kontur_population_NL.gpkg.gz
ogr2ogr -f PostgreSQL PG:"$PG_CONN" kontur_population_NL.gpkg \
  -spat 4.95 51.98 5.30 52.18 -spat_srs EPSG:4326 \
  -nln demo_kontur_h3 -lco GEOMETRY_NAME=geom -nlt MULTIPOLYGON -t_srs EPSG:28992
```

### 4.3 GHSL / GHS-POP R2023A (100 m population raster)

| | |
|---|---|
| **License** | **CC BY 4.0** (JRC / Copernicus) |
| **Tiles dir** **[V]** | `https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_POP_GLOBE_R2023A/GHS_POP_E2020_GLOBE_R2023A_54009_100/V1-0/tiles/` |
| **Tile filename** **[V/P]** | `GHS_POP_E2020_GLOBE_R2023A_54009_100_V1_0_R<row>_C<col>.zip` (`R9_C19` seen live; NL's tile must be read off the tile-schema shapefile in the parent directory) |
| **Global 1 km single file** **[V]** | `https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_POP_GLOBE_R2023A/GHS_POP_E2020_GLOBE_R2023A_54009_1000/V1-0/GHS_POP_E2020_GLOBE_R2023A_54009_1000_V1_0.zip` |
| **Format / geom** | GeoTIFF in ZIP / **RASTER**, World Mollweide ESRI:54009 |
| **Size** | 100 m tile ≈ 20–60 MB; 1 km global ≈ 130 MB |

```bash
# fastest path: browse the tiles/ directory, grab the tile whose extent covers 4.95-5.30E / 51.98-52.18N
curl -L -O https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_POP_GLOBE_R2023A/GHS_POP_E2020_GLOBE_R2023A_54009_100/V1-0/tiles/GHS_POP_E2020_GLOBE_R2023A_54009_100_V1_0_R3_C19.zip
unzip -o GHS_POP_*.zip
gdalwarp -t_srs EPSG:28992 -te 127000 443500 151500 466000 -r near \
  GHS_POP_E2020_GLOBE_R2023A_54009_100_V1_0_R3_C19.tif ghspop_utrecht.tif
raster2pgsql -s 28992 -I -C -t 128x128 ghspop_utrecht.tif public.demo_ghspop | psql "$DATABASE_URL"
```

### 4.4 WorldPop (100 m constrained, UN-adjusted)

| | |
|---|---|
| **License** | **CC BY 4.0** |
| **Portal** **[V]** | `https://hub.worldpop.org/geodata/listing?id=78` (Constrained 2020 100 m); HDX mirror `https://data.humdata.org/dataset/worldpop-population-counts-for-netherlands` |
| **Filename** **[V]** | `nld_ppp_2020_UNadj.tif` |
| **URL pattern** **[P]** | `https://data.worldpop.org/GIS/Population/Global_2000_2020_Constrained/2020/BSGM/NLD/nld_ppp_2020_UNadj_constrained.tif` |
| **Format / geom** | GeoTIFF / RASTER, 3 arc-sec (~100 m), EPSG:4326 |
| **Size** | NL ≈ 10–20 MB |

Redundant with GHS-POP — pick **one** of §4.3/§4.4 to stay in budget. GHS-POP has the better
multi-temporal story (1975→2030), WorldPop the easier download.

### 4.5 Eurostat GISCO NUTS boundaries (context / EU-wide comparison)

| | |
|---|---|
| **License** | Free reuse with attribution (© EuroGeographics) |
| **Distribution root** **[V]** | `https://gisco-services.ec.europa.eu/distribution/v2/nuts/` |
| **File index** **[V]** | `https://gisco-services.ec.europa.eu/distribution/v2/nuts/nuts-2024-files.html` |
| **Naming** **[V]** | `theme_spatialtype_resolution_year_projection_subset.format` e.g. `NUTS_RG_01M_2024_4326_LEVL_3.geojson` |
| **Direct** **[P]** | `https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/NUTS_RG_01M_2024_4326_LEVL_3.geojson` |
| **Format / geom** | GeoJSON / POLYGON |
| **Size** | LEVL_3 @ 01M ≈ 25 MB (all EU); ≈ 1 MB if you filter `CNTR_CODE='NL'` |

```bash
curl -L -o nuts3_2024.geojson \
  https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/NUTS_RG_01M_2024_4326_LEVL_3.geojson
ogr2ogr -f GPKG nuts3_nl.gpkg nuts3_2024.geojson -where "CNTR_CODE='NL'" -nln nuts3_nl
```

### 4.6 US alternative — TIGER + ACS

```bash
# boundaries (public domain)
curl -L -O https://www2.census.gov/geo/tiger/TIGER2024/TRACT/tl_2024_36_tract.zip      # NY tracts [P]
curl -L -O https://www2.census.gov/geo/tiger/TIGER2024/ROADS/tl_2024_36061_roads.zip   # Manhattan roads (LINESTRING) [P]

# ACS 5-year tables, no API key required for <500 calls/day
curl -s "https://api.census.gov/data/2023/acs/acs5?get=NAME,B01003_001E,B19013_001E,B25077_001E&for=tract:*&in=state:36+county:061" \
  -o acs_manhattan.json
```

---

## 5. Theme 4 — TRANSPORTATION

### 5.1 OpenStreetMap road network — Geofabrik Utrecht extract ★ core LINESTRING dataset

| | |
|---|---|
| **License** | **ODbL 1.0** |
| **Page** **[V]** | `https://download.geofabrik.de/europe/netherlands/utrecht.html` |
| **PBF** **[V]** | `https://download.geofabrik.de/europe/netherlands/utrecht-latest.osm.pbf` — **~90 MB** |
| **Shapefile** **[V]** | `https://download.geofabrik.de/europe/netherlands/utrecht-latest-free.shp.zip` — **~144 MB** |
| **Whole NL** **[V]** | `https://download.geofabrik.de/europe/netherlands-latest.osm.pbf` — **~1.3 GB** (too big — do not use) |
| **Format / geom** | PBF → LINESTRING (roads, rail, cycleways), POLYGON (buildings, landuse), POINT (POIs) |
| **Key fields** | `highway`, `maxspeed`, `lanes`, `surface`, `oneway`, `cycleway`, `bicycle`, `name`, `ref`, `bridge`, `tunnel` |

```bash
curl -L -O https://download.geofabrik.de/europe/netherlands/utrecht-latest.osm.pbf

# optional: cut to the city box first (halves the import time)
osmium extract -b 4.95,51.98,5.30,52.18 utrecht-latest.osm.pbf -o utrecht_city.osm.pbf

# full topological import
osm2pgsql --create --slim --drop -G --hstore \
  -d gis -U "$PGUSER" -H "$PGHOST" -P 5432 \
  --number-processes 4 --cache 1500 \
  utrecht_city.osm.pbf

# lightweight alternative (no osm2pgsql): GDAL OSM driver, roads only
ogr2ogr -f GPKG utrecht_roads.gpkg utrecht_city.osm.pbf lines \
  -where "highway IS NOT NULL" -nln roads -nlt MULTILINESTRING
```

### 5.2 Overpass API — bike lanes (exact query string)

License **ODbL**. Endpoint **[V]**: `https://overpass-api.de/api/interpreter`

```bash
curl -X POST -o utrecht_bike.osm https://overpass-api.de/api/interpreter --data-urlencode 'data=
[out:xml][timeout:300];
(
  way["highway"="cycleway"](51.98,4.95,52.18,5.30);
  way["cycleway"~"lane|track|opposite_lane|opposite_track"](51.98,4.95,52.18,5.30);
  way["cycleway:left"](51.98,4.95,52.18,5.30);
  way["cycleway:right"](51.98,4.95,52.18,5.30);
  way["bicycle"="designated"](51.98,4.95,52.18,5.30);
);
(._;>;);
out body;'

ogr2ogr -f GPKG utrecht_bike.gpkg utrecht_bike.osm lines -nln bike_lanes -nlt MULTILINESTRING
ogr2ogr -f PostgreSQL PG:"$PG_CONN" utrecht_bike.gpkg -nln tr_bike_lanes -lco GEOMETRY_NAME=geom
```

Bike-parking points (nice second chart):

```
[out:json][timeout:120];
node["amenity"="bicycle_parking"](51.98,4.95,52.18,5.30);
out body;
```

Expected size: bike lanes ≈ 8–15 MB OSM XML → ~4 MB GPKG.

### 5.3 GTFS — Netherlands national feed

| | |
|---|---|
| **Name** | OVapi / NDOV aggregate GTFS (all 40+ Dutch operators) |
| **License** | Open data (NDOV, free reuse) |
| **URL** **[V]** | `http://gtfs.ovapi.nl/gtfs-nl.zip` |
| **Registry** **[V]** | `https://mobilitydatabase.org/feeds/gtfs/mdb-1077` |
| **Size** **[V]** | **≈ 200 MB zipped, ~1.33 GB unzipped**; 2,775 routes, 52,212 stops, refreshed daily |
| **Format / geom** | GTFS (CSV in ZIP) → POINT (`stops.txt`), LINESTRING (`shapes.txt`) |
| **Key fields** | `stop_id/stop_name/stop_lat/stop_lon`, `route_short_name`, `route_type` (0 tram, 1 metro, 2 rail, 3 bus, 4 ferry), `trip_id`, `arrival_time`, `agency_name` |

**Budget warning:** 200 MB is 20 % of the budget. Keep only what you need:

```bash
curl -L -o gtfs-nl.zip http://gtfs.ovapi.nl/gtfs-nl.zip
unzip -o gtfs-nl.zip -d gtfs stops.txt routes.txt trips.txt agency.txt shapes.txt calendar.txt

# stops as POINT, clipped to Utrecht
ogr2ogr -f GPKG utrecht_stops.gpkg gtfs/stops.txt -oo X_POSSIBLE_NAMES=stop_lon \
  -oo Y_POSSIBLE_NAMES=stop_lat -oo KEEP_GEOM_COLUMNS=NO -a_srs EPSG:4326 \
  -spat 4.95 51.98 5.30 52.18 -nln transit_stops

# route shapes as LINESTRING (GDAL's GTFS driver reads the whole zip)
ogr2ogr -f GPKG utrecht_gtfs.gpkg GTFS:gtfs-nl.zip shapes -spat 4.95 51.98 5.30 52.18 -nln transit_shapes

# straight into PostGIS
ogr2ogr -f PostgreSQL PG:"$PG_CONN" utrecht_stops.gpkg -nln tr_transit_stops -lco GEOMETRY_NAME=geom
```

If you want to skip the 200 MB: use the **Mobility Database** per-agency feeds instead
(`https://mobilitydatabase.org` — search "Netherlands"), each a few MB. **[U]**

### 5.4 NDW traffic counts / speeds (Dutch national road traffic databank)

| | |
|---|---|
| **License** | Open data (NDW), free reuse **[V]** |
| **Portal** **[V]** | `http://opendata.ndw.nu/` — docs at `https://docs.ndw.nu/en/dataformaten/datex2-v3/verkeersgegevens/` |
| **Coverage** **[V]** | >24,000 measurement locations, ~460,000 data points/minute, history back to Oct 2017 |
| **Format / geom** | DATEX II XML (gzipped) → POINT (measurement sites) + time series |
| **Files** **[U]** | `http://opendata.ndw.nu/measurement.xml.gz` (site table, has coordinates), `http://opendata.ndw.nu/trafficspeed.xml.gz`, `http://opendata.ndw.nu/traveltime.xml.gz` |
| **Size** | site table ≈ 15 MB gz; a single minute snapshot ≈ 5–10 MB gz |

```bash
curl -L -o ndw_sites.xml.gz http://opendata.ndw.nu/measurement.xml.gz
gunzip ndw_sites.xml.gz
# DATEX II is not an OGR-native format -- parse to CSV with python/xmlstarlet, then:
ogr2ogr -f GPKG ndw_sites.gpkg ndw_sites.csv -oo X_POSSIBLE_NAMES=lon -oo Y_POSSIBLE_NAMES=lat -a_srs EPSG:4326
```

*Flagged **[U]** — confirm the exact filenames on `opendata.ndw.nu` before scripting. This is
the weakest-verified item in the document. A safe fallback for a "traffic volume" chart is
OSM `maxspeed` + `lanes` + GTFS service frequency per stop.*

---

## 6. Theme 5 — 3D MAP

### 6.1 3DBAG ★ core dataset — the best open 3D building dataset in Europe

**URL templates below were read directly from the 3DBAG viewer's own version manifest
(`https://raw.githubusercontent.com/3DBAG/3dbag-viewer/main/src/assets/3dbag_versions.json`) — [V], authoritative.**

| | |
|---|---|
| **License** **[V]** | **CC BY 4.0** — attribution: "© 3DBAG by tudelft3d and 3DGI" |
| **Latest version** **[V]** | `v2025.09.03` (path component `v20250903`) |
| **Format / geom** | GeoPackage / CityJSON / OBJ / IFC — **POLYGON + 3D MultiSurface**, EPSG:7415 (RD + NAP) |
| **Whole-NL dump** **[V]** | `https://data.3dbag.nl/v20250903/3dbag_nl.gpkg.zip` — **19 GB (111 GB uncompressed)** → **never download this** |
| **Tile index** **[V]** | `https://data.3dbag.nl/v20250903/tile_index.fgb` (FlatGeobuf, a few MB) |
| **Per-tile GPKG** **[V]** | `https://data.3dbag.nl/v20250903/tiles/{X}/{Y}/{Z}/{X}-{Y}-{Z}.gpkg` |
| **Per-tile CityJSON** **[V]** | `https://data.3dbag.nl/v20250903/tiles/{X}/{Y}/{Z}/{X}-{Y}-{Z}.city.json` |
| **Per-tile OBJ** **[V]** | `https://data.3dbag.nl/v20250903/tiles/{X}/{Y}/{Z}/{X}-{Y}-{Z}-obj.zip` |
| **Per-tile IFC** **[V]** | `https://data.3dbag.nl/v20250903/tiles/{X}/{Y}/{Z}/{X}-{Y}-{Z}.ifc.zip` |
| **WFS** **[V]** | `https://data.3dbag.nl/api/BAG3D/wfs` |
| **OGC API** **[V]** | `https://api.3dbag.nl/` |
| **3D Tiles** **[V]** | `https://data.3dbag.nl/v20250903/3dtiles/lod22/tileset.json` (also `lod13`, `lod12`); Cesium variant under `/cesium3dtiles/` |
| **Metadata** **[V]** | `https://data.3dbag.nl/v20250903/metadata.json` |
| **Older stable** **[V]** | `v20241216`, `v20240420`, `v20240228` — same path structure |
| **Size** | one tile ≈ 2–8 MB GPKG; Utrecht city ≈ 8–15 tiles ≈ **40–80 MB** |
| **Key fields** **[V]** | `b3_h_dak_50p` (median roof height), `b3_h_dak_70p`, `b3_h_dak_min/max`, `b3_h_maaiveld` (ground level, 5th pct of AHN points within 4 m), `b3_volume_lod12/lod13/lod22`, `b3_dak_type` (roof type), `b3_opp_dak_plat`/`b3_opp_dak_schuin`, `b3_kas_warenhuis`, `identificatie` (BAG id — joins to §3.2), `oorspronkelijkbouwjaar` |

**Exact workflow — resolve tiles from the index, then download only what you need:**

```bash
# 1. get the tile index and find the tiles covering the Utrecht bbox (RD New)
curl -L -O https://data.3dbag.nl/v20250903/tile_index.fgb
ogr2ogr -f CSV utrecht_tiles.csv tile_index.fgb \
  -spat 127000 443500 151500 466000 -select tile_id -lco GEOMETRY=AS_WKT
cat utrecht_tiles.csv

# 2. download each tile's GPKG (tile_id comes back as X/Y/Z)
while IFS= read -r t; do
  x=${t%%/*}; rest=${t#*/}; y=${rest%%/*}; z=${rest##*/}
  curl -sL -o "3dbag_${x}-${y}-${z}.gpkg" \
    "https://data.3dbag.nl/v20250903/tiles/${x}/${y}/${z}/${x}-${y}-${z}.gpkg"
done < tile_ids.txt

# 3. merge and load (lod22 is the interesting layer)
ogr2ogr -f GPKG utrecht_3dbag.gpkg 3dbag_*.gpkg lod22_3d -nln buildings3d
for f in 3dbag_*.gpkg; do ogr2ogr -f GPKG -append utrecht_3dbag.gpkg "$f" lod22_3d -nln buildings3d; done

ogr2ogr -f PostgreSQL PG:"$PG_CONN" utrecht_3dbag.gpkg buildings3d \
  -nln b3_buildings -lco GEOMETRY_NAME=geom -lco DIM=3 -nlt MULTIPOLYGONZ -t_srs EPSG:28992
```

**Alternative one-liner via WFS (no tile bookkeeping):**

```bash
ogr2ogr -f GPKG utrecht_3dbag_wfs.gpkg "WFS:https://data.3dbag.nl/api/BAG3D/wfs" \
  -spat 127000 443500 151500 466000
```

**Analytics:** building height distribution, volume per neighbourhood, roof type mix
(flat vs pitched → solar-potential story), height vs construction year, 2.5D extrusion in
deck.gl / MapLibre using `b3_h_dak_50p - b3_h_maaiveld` as extrusion height.

### 6.2 Copernicus DEM GLO-30 (terrain)

| | |
|---|---|
| **License** | Free/open for GLO-30 Public (ESA/Copernicus licence, unrestricted reuse w/ attribution) |
| **Registry** **[V]** | `https://registry.opendata.aws/copernicus-dem/`; bucket readme `https://copernicus-dem-30m.s3.amazonaws.com/readme.html` |
| **Naming** **[V]** | `Copernicus_DSM_COG_10_<N/S><lat>_00_<E/W><lon>_00_DEM/` (10 = 30 m; 30 = 90 m) |
| **Tile for Utrecht** **[P]** | `https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_N52_00_E005_00_DEM/Copernicus_DSM_COG_10_N52_00_E005_00_DEM.tif` |
| **Format / geom** | Cloud-Optimized GeoTIFF / **RASTER**, 30 m, EPSG:4326 + EGM2008 heights |
| **Size** | 1°×1° tile ≈ 25–35 MB; Utrecht clip ≈ 1.5 MB |

```bash
gdal_translate -projwin 4.95 52.18 5.30 51.98 -co COMPRESS=DEFLATE -co TILED=YES \
  /vsicurl/https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_N52_00_E005_00_DEM/Copernicus_DSM_COG_10_N52_00_E005_00_DEM.tif \
  dem_utrecht_4326.tif
gdalwarp -t_srs EPSG:28992 -tr 30 30 -r bilinear dem_utrecht_4326.tif dem_utrecht.tif
gdaldem hillshade dem_utrecht.tif dem_utrecht_hillshade.tif -z 3
raster2pgsql -s 28992 -I -C -M -t 128x128 dem_utrecht.tif public.terrain_dem | psql "$DATABASE_URL"
```

Also usable, no signup: `aws s3 ls --no-sign-request s3://copernicus-dem-30m/`

### 6.3 AHN (Dutch 0.5 m lidar DTM/DSM) — the "wow" terrain layer

| | |
|---|---|
| **License** | CC BY 4.0 / public domain (AHN open data) |
| **Portal** **[V]** | `https://geotiles.nl/` and `https://geotiles.citg.tudelft.nl/` (TU Delft ready-made tiles), also the PDOK AHN Atom feed |
| **Coverage** **[V]** | AHN1–AHN5; AHN4 flown 2020–2022; DTM & DSM as GeoTIFF at 0.5 m and 5 m; point clouds split into 1 × 1.25 km sub-tiles |
| **Tile page example** **[V]** | `https://geotiles.citg.tudelft.nl/tiles/html/31HZ1.html` style pages carry the per-tile download links |
| **Size** | 0.5 m DTM per 5 × 6.25 km tile ≈ 40–120 MB — use the **5 m** product for a city-scale project (≈ 2 MB/tile) |
| **Utrecht map sheets** | `31H`, `32C`, `38F`, `39A` (RD sheet grid) **[U]** |

Only add this if you have budget left after §6.1/§6.2 — Copernicus DEM already covers the
terrain requirement, and the Netherlands is famously flat, so 0.5 m detail mostly buys you
dikes, canal banks and overpasses.

### 6.4 Overture Maps buildings (global cross-check / non-NL fallback)

| | |
|---|---|
| **License** | **ODbL** (buildings theme) + CDLA-Permissive 2.0 |
| **Release** **[V]** | `2026-07-22.0` |
| **S3 path** **[V]** | `s3://overturemaps-us-west-2/release/2026-07-22.0/theme=buildings/type=building/*` |
| **Format / geom** | **GeoParquet** / POLYGON |
| **Size** | Utrecht bbox ≈ 15–25 MB as GeoParquet |
| **Key fields** | `height` (m), `num_floors`, `class`, `subtype`, `names.primary`, `sources`, `bbox.{xmin,ymin,xmax,ymax}` |

```bash
duckdb -c "
INSTALL spatial; INSTALL httpfs; LOAD spatial; LOAD httpfs;
SET s3_region='us-west-2';
COPY (
  SELECT id, names.primary AS name, class, subtype, height, num_floors,
         ST_GeomFromWKB(geometry) AS geometry
  FROM read_parquet('s3://overturemaps-us-west-2/release/2026-07-22.0/theme=buildings/type=building/*',
                    hive_partitioning=1)
  WHERE bbox.xmin BETWEEN 4.95 AND 5.30 AND bbox.ymin BETWEEN 51.98 AND 52.18
) TO 'utrecht_overture_buildings.parquet' (FORMAT PARQUET);
"
ogr2ogr -f GPKG utrecht_overture.gpkg utrecht_overture_buildings.parquet
```

Or the official CLI (no AWS credentials needed):

```bash
pip install overturemaps
overturemaps download --bbox=4.95,51.98,5.30,52.18 -f geojson --type=building -o utrecht_ov.geojson
```

### 6.5 OSM buildings with height (already in your PBF)

```bash
ogr2ogr -f GPKG utrecht_osm_buildings.gpkg utrecht_city.osm.pbf multipolygons \
  -where "building IS NOT NULL" -nln osm_buildings
# tags of interest: building, building:levels, height, roof:shape, roof:levels, start_date
```

Coverage of `height`/`building:levels` in NL is patchy (~10–20 %) — 3DBAG is the real source
of truth. Keep OSM buildings as the "what open crowdsourced data gives you" comparison chart.

### 6.6 Terrain tiles (raster RGB, if you want a web-map basemap)

- **AWS Terrain Tiles (Mapzen/Terrarium)**, public domain / mixed attribution **[U]**:
  `https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png`
- Decode: `elevation = (R * 256 + G + B / 256) - 32768`
- ~10–20 KB/tile; a z12–z14 pyramid over Utrecht ≈ 5 MB.

---

## 6b. Theme 6 — REMOTE SENSING

Everything here is free, requires at most a no-cost registration, and is read directly from
cloud-optimised storage — no bulk download.

### 6b.1 Sentinel-2 L2A surface reflectance ★ core dataset

- **STAC API** (footprints, dates, `eo:cloud_cover` — no pixels needed for the scene catalogue):
  `https://earth-search.aws.element84.com/v1/collections/sentinel-2-l2a/items`
- **Pixels**: <https://registry.opendata.aws/sentinel-2-l2a-cogs/> — one COG per band.
- Licence: CC-BY-SA-3.0-IGO (ESA Copernicus).
- Indices used: NDVI `(B08−B04)/(B08+B04)`, NDWI `(B03−B08)/(B03+B08)`,
  NDBI `(B11−B08)/(B11+B08)`, NBR `(B08−B12)/(B08+B12)`.
- COG range requests read only the study-area window of only the bands used, so the
  "download" is a few MB rather than a full 600 MB tile.

**Expect to discard most of the archive.** Over the central Netherlands, roughly 15–20 % of
Sentinel-2 acquisitions come in under 30 % cloud, and the clear dates cluster in summer. Plan
for a composite, not a single date — and see 6b.4 for why the radar layers exist. Section 6b.5 is the one worth reading twice.

### 6b.2 Landsat Collection 2 Level-2 — the thermal band

- <https://registry.opendata.aws/usgs-landsat/> — public domain (US Government work).
- Landsat rather than Sentinel-2 because **only Landsat carries a thermal sensor**. Surface
  temperature is band `ST_B10`, already atmospherically corrected.
- Scaling: `LST_°C = ST_B10 * 0.00341802 + 149.0 − 273.15`.
- 30 m native, 100 m true thermal resolution resampled — fine for a neighbourhood-scale heat
  island study, not for a single building.

### 6b.3 ESA WorldCover — two epochs for change detection

- <https://registry.opendata.aws/esa-worldcover-vito/> — CC-BY-4.0, 10 m, 11 classes.
- v100 (2020) and v200 (2021) give a from/to matrix directly.
- **Caveat worth stating in any writeup**: ESA explicitly say the two versions are not designed
  to be differenced — the algorithms changed between them, so some apparent "change" is
  classifier drift. A defensible study classifies both epochs itself from Sentinel-2 and uses
  WorldCover only as a reference.

### 6b.4 Sentinel-1 GRD — water and flood extent

- <https://registry.opendata.aws/sentinel-1/> — CC-BY-SA-3.0-IGO, VV/VH, IW mode.
- Open water is specular at C-band: it reflects the pulse away from the sensor, so it returns
  very low backscatter and a threshold near **−18 dB on VV** separates it cleanly.
- The reason to use radar at all: **it sees through cloud**, and flooding arrives with exactly
  the weather that hides it from an optical sensor.

### 6b.5 AlphaEarth Foundations satellite embeddings ★ the interesting one

- **Earth Engine**: `GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL` — free for noncommercial use, but needs
  a Google account and a registered project.
- **Without Earth Engine** (what this project uses), CC-BY 4.0:
  - Source Cooperative: <https://source.coop/tge-labs/aef>
  - AWS Open Data: <https://registry.opendata.aws/aef-source/>
  - GCS: `gs://alphaearth_foundations`
  COGs of 8192x8192 pixels x 64 channels, split by year and UTM zone.
- Attribution required: "The AlphaEarth Foundations Satellite Embedding dataset is produced by
  Google and Google DeepMind."

**What it is.** 64 floats per 10 m pixel per year, 2017 to present, distilled from a year of
Sentinel-1, Sentinel-2 and Landsat. **The vectors are unit length**, which is the property that
makes them useful: `dot(a, b)` is directly the cosine similarity, so "find everywhere that looks
like here" needs no model, no inference and no normalisation.

**How to use it on parcels.** Zonal-mean the pixels inside each parcel, then re-normalise — the mean
of unit vectors is not itself unit length. That reduces the whole study area to 64 floats per parcel
per year, a few MB, which fits in Postgres and needs no raster serving.

Two caveats worth stating in any writeup:

- A parcel-mean embedding assumes the parcel is reasonably homogeneous. That is fine for crop
  identification and comparison; it is wrong for within-field zoning, which needs the pixels.
- Averaging discards the within-parcel variance the model encoded. If the question is about
  variability rather than identity, keep the pixel-level vectors.

**Pairs with BRP.** The Dutch crop-parcel register (§2) publishes a declared crop per parcel per
year under CC0. That is a labelled training set sitting directly on top of an embedding dataset,
which is what makes few-shot classification and declaration checking possible without labelling
anything by hand.

### 6b.6 EGMS — InSAR ground motion, already processed

- <https://egms.land.copernicus.eu/> — CC-BY-4.0. Tiles `32ULC` / `32UMC` cover Utrecht.
- The Copernicus Land Monitoring Service publishes **unwrapped, calibrated** persistent-scatterer
  velocities and time series for the whole EU, derived from Sentinel-1. This is the single
  biggest shortcut in this theme: processing raw SLC interferograms yourself needs SNAP or
  ISCE, a lot of disk and a lot of time, and EGMS has already done it.
- Sign convention: **negative velocity is subsidence**. Keep it that way — flipping it to
  "positive means sinking" for display guarantees a sign error against every published map.
- Relevance here: drained peat oxidises and compacts, so the Dutch polder subsides at
  5–10 mm/yr while the sand of the Utrechtse Heuvelrug barely moves. Persistent scatterers
  need a stable reflector, so coverage is dense over towns and sparse over farmland.

---

## 7. Download budget plan (target: < 1 GB)

| # | Dataset | Theme | Geometry | Download | After clip/load |
|---|---|---|---|---|---|
| 1 | OSM `utrecht-latest.osm.pbf` | Transport | LINE/POLY/POINT | **90 MB** | ~250 MB in PG |
| 2 | GTFS `gtfs-nl.zip` | Transport | POINT + LINE | **200 MB** | ~25 MB (stops+shapes only) |
| 3 | CBS `WijkBuurtkaart_2025_v1.zip` | Demographic | POLYGON | **103 MB** | ~8 MB (Utrecht buurten) |
| 4 | 3DBAG tiles (≈12 × GPKG) | 3D | POLYGON Z | **~60 MB** | ~60 MB |
| 5 | Kontur Population NL | Demographic | POLYGON (H3) | **~35 MB** | ~6 MB |
| 6 | GHS-POP 100 m tile | Demographic | RASTER | **~40 MB** | ~2 MB |
| 7 | BRK parcels + boundaries (OAPIF clip) | Cadastre | POLYGON + LINESTRING | **~40 MB** | ~40 MB |
| 8 | BAG panden + verblijfsobjecten (OAPIF clip) | Cadastre | POLYGON + POINT | **~35 MB** | ~35 MB |
| 9 | BRP crop parcels (OAPIF clip) | Agriculture | POLYGON | **~12 MB** | ~12 MB |
| 10 | Copernicus DEM tile (vsicurl clip) | 3D | RASTER | **~2 MB** | ~2 MB |
| 11 | ESA WorldCover (vsicurl clip) | Agriculture | RASTER | **~2 MB** | ~2 MB |
| 12 | SoilGrids ×5 properties (vsicurl clip) | Agriculture | RASTER | **~3 MB** | ~3 MB |
| 13 | CHELSA bio12 clip | Agriculture | RASTER | **<1 MB** | <1 MB |
| 14 | KNMI De Bilt `etmgeg_260.zip` | Agriculture | POINT + series | **~2 MB** | ~4 MB |
| 15 | Overpass bike lanes | Transport | LINESTRING | **~12 MB** | ~4 MB |
| 16 | GISCO NUTS3 (filtered to NL) | Demographic | POLYGON | **~25 MB** | ~1 MB |
| | **TOTAL DOWNLOAD** | | | **≈ 660 MB** | **≈ 200 MB in PostGIS** |

**Geometry-type coverage check:** POLYGON ✔ (1,3,4,5,7,8,9,16) · LINESTRING ✔ (1,2,7,15) ·
POINT ✔ (2,8,14) · RASTER ✔ (6,10,11,12,13) · POLYGON Z ✔ (4).

**Trimming levers if you overrun:** drop GTFS (−200 MB, use per-agency feeds), drop
GHS-POP (Kontur covers the same story, −40 MB), take `utrecht_city.osm.pbf` via a mirror
`osmium extract` instead of the province file.

---

## 8. Free managed Postgres **with PostGIS** — status as of Aug 2026

| Provider | PostGIS on free tier | Storage | Compute | Sleep / expiry | Verdict |
|---|---|---|---|---|---|
| **Aiven** | ✅ **Yes** — "includes popular extensions like PostGIS" **[V]** | **1 GB** **[V]** | 1 vCPU / 1 GB RAM **[V]** | **No sleep, no time limit, no credit card** **[V]** | ★ **Best for this project.** Always-on, and **Amsterdam is an available region** (DigitalOcean SF/NYC/TOR/**AMS**/FRA/LON/BLR) **[V]** — same continent as the data. |
| **Neon** | ✅ Yes — supports standard PG extensions incl. PostGIS **[V]** | **0.5 GB/project** **[V]** | **100 compute-hours/mo**, autoscale-to-zero after **5 min** idle **[V]** | Scale-to-zero (cold start ~0.5–1 s); hitting a monthly limit suspends compute until next cycle **[V]** | ★ **Best DX.** Branching is a genuinely nice portfolio talking point. 0.5 GB is tight — see §8.1. Up to 100 projects, no card **[V]**. |
| **Supabase** | ✅ Yes — `CREATE EXTENSION postgis SCHEMA extensions;`, **not** Pro-gated **[V]** | **500 MB** **[V]** | 500 MB shared RAM **[V]** | ⚠️ **Project pauses after 7 days of inactivity** **[V]**; max **2 active projects** **[V]** | Good if you also want the auto-REST API (PostgREST) and Storage. Needs a keep-alive cron. |
| **Koyeb** | ✅ Yes — "40+ extensions including pgvector, **PostGIS**, TimescaleDB" **[V]** | small (free tier) | 1 GB RAM / 0.25 vCPU, **50 active hours** **[V]** | **Auto-sleep after 5 min** idle **[V]** | Decent, and you can co-locate the API on the same platform. |
| **Render** | PostGIS available on their PG image | **1 GB** **[V]** | shared | ❌ **Free DB expires 30 days after creation**, +14-day grace, then deleted **[V]** | **Not viable** for a portfolio you want to leave up. |
| **Railway** | PostGIS via template | — | — | ❌ **$5 trial credit then services pause**; $1/mo credit after **[V]** | **Not actually free.** |
| **Tembo** | ❓ **Could not verify** a current free tier **[U]** | — | — | — | Check directly before relying on it. |

### 8.1 Fitting ~200 MB of PostGIS into a 0.5 GB free tier

The plan in §7 lands around 200 MB of table data — but indexes, TOAST and WAL push real
usage higher. Three levers:

1. **Simplify geometries on load** — `ogr2ogr -simplify 1.0` (1 m tolerance in RD New) cuts
   OSM/parcel geometry volume 40–60 % with no visible difference above 1:5,000.
2. **Skip raster-in-Postgres.** Store DEM/WorldCover/SoilGrids as COGs on **Cloudflare R2**
   (10 GB free, S3-compatible, zero egress fees) and read them with `/vsicurl` from your API.
   Only keep vector in Postgres. This alone saves ~50 MB and avoids needing `postgis_raster`.
3. **Ship tiles, not features.** Generate **PMTiles** once (`tippecanoe -o utrecht.pmtiles`) and
   host on R2/Cloudflare Pages. The database then only serves analytics queries, not geometry
   for the map — which is also the architecturally correct answer and reads well in a portfolio.

```bash
tippecanoe -o utrecht.pmtiles -zg --drop-densest-as-needed \
  -L parcels:utrecht_parcels.geojson -L crops:utrecht_crops.geojson -L roads:utrecht_roads.geojson
```

### 8.2 Sanity check after provisioning

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_raster;   -- may fail on some hosts; not required if you follow §8.1
SELECT postgis_full_version();
SELECT pg_size_pretty(pg_database_size(current_database()));
```

---

## 9. Free API / container hosting — status as of Aug 2026

| Platform | What's free | Cold start / sleep | Gotchas |
|---|---|---|---|
| **Hugging Face Spaces** | **2 vCPU / 16 GB RAM**, Docker SDK, free forever **[V]** | ⚠️ **Sleeps after 48 h of inactivity** **[V]** | ★ **Best raw resources on this list** — 16 GB RAM will happily run FastAPI + GDAL + a local PMTiles server. Public by default; the HF-branded URL is a slight portfolio downside. |
| **Cloudflare Workers / Pages** | **100,000 requests/day**, resets 00:00 UTC **[V]**; Pages static hosting effectively unlimited | Effectively zero cold start | ⚠️ **10 ms CPU per request on free** **[V]** — fine for tile serving and thin API proxies, **not** for PostGIS-heavy compute in-worker. Pair with R2 (10 GB free) for PMTiles/COGs. Direct TCP to Postgres needs care (Hyperdrive is paid). |
| **Koyeb** | 1 instance, 1 GB RAM / 0.25 vCPU, 50 active hours **[V]** | **Auto-sleep after 5 min** **[V]** | Nice because DB + API live together; 50 h/month is the real constraint. |
| **Render** (web service) | Free instance tier still exists **[U — verify]** | ⚠️ **Sleeps after ~15 min idle, ~50 s cold start** | Their free *database* expires in 30 days **[V]** — don't confuse the two. |
| **Vercel** (Hobby) | 100 GB fast data transfer, ~1 M function invocations, 1 M edge requests **[V]** | Near-zero | ⚠️ **Hobby is personal / non-commercial only** **[V]**; 10 s function execution (Fluid compute). Great for a Next.js frontend, poor for a GDAL backend. |
| **AWS Lambda** | **1 M requests + 400,000 GB-seconds/month, always free** **[U]** | 200 ms–2 s (bigger with a GDAL layer) | API Gateway's free tier is **12 months only** — use **Lambda Function URLs** to stay free forever. 250 MB unzipped package limit → use a container image (10 GB) for GDAL. |
| **Fly.io** | ❌ **No free tier in 2026** — new orgs get a trial of **2 VM-hours / 7 days**, whichever ends first **[V]** | — | The old 3-shared-CPU-VM allowance is **gone** **[V]**. Don't plan around it. |
| **Railway** | ❌ $5 trial, then paused **[V]** | — | Not free. |

### Recommended stack

```
Frontend  : Cloudflare Pages (static MapLibre app)         — free, fast, custom domain
Tiles/COG : Cloudflare R2 (10 GB free, no egress fees)     — PMTiles + DEM/landcover COGs
API       : Hugging Face Spaces (Docker, FastAPI + GDAL)   — 16 GB RAM, wake-on-request
Database  : Aiven free PostgreSQL (Amsterdam, PostGIS)     — always-on, no sleep, 1 GB
Fallback  : Neon (branching demo) if you prefer serverless & can live inside 0.5 GB
```

Rationale: the two things that kill a GIS portfolio demo are (a) a database that pauses and
returns a connection error to a recruiter, and (b) a 50-second cold start on the map load.
**Aiven** solves (a) — it is the only entry here that is always-on with no expiry.
**Cloudflare Pages + R2** solves (b) — the map draws from static PMTiles instantly, and the
API (which may cold-start) is only hit for the analytics charts, where a 2-second spinner is
acceptable.

---

## 10. Attribution block (paste into your app footer)

```
Crop parcels & reference parcels: BRP / Referentiepercelen (RVO, PDOK) — CC0 1.0
Cadastral parcels & buildings:    BRK Kadastrale Kaart, BAG (Kadaster, PDOK)
3D buildings:                     3DBAG © tudelft3d and 3DGI — CC BY 4.0
Demographics:                     CBS Wijk- en Buurtkaart — CC BY 4.0 (Statistics Netherlands)
Population grid:                  © Kontur — CC BY 4.0 / GHSL © European Union, JRC — CC BY 4.0
Roads, bike lanes, POIs:          © OpenStreetMap contributors — ODbL 1.0
Transit:                          OVapi / NDOV open data
Land cover:                       © ESA WorldCover 2021 v200 — CC BY 4.0
Soil:                             ISRIC — World Soil Information, SoilGrids — CC BY 4.0
Terrain:                          Copernicus DEM GLO-30 © ESA / European Union
Optical imagery:                  Contains modified Copernicus Sentinel-2 data — CC BY-SA 3.0 IGO
Radar imagery:                    Contains modified Copernicus Sentinel-1 data — CC BY-SA 3.0 IGO
Thermal / LST:                    USGS Landsat Collection 2 Level-2 — public domain
Satellite embeddings:             AlphaEarth Foundations Satellite Embedding dataset, produced
                                  by Google and Google DeepMind — CC BY 4.0
Ground motion:                    European Ground Motion Service, Copernicus Land Monitoring
                                  Service / EEA — CC BY 4.0
Protected areas:                  Natura 2000 © European Environment Agency — CC BY 4.0
Climate:                          KNMI (station 260 De Bilt); CHELSA V2.1
Boundaries:                       © EuroGeographics / Eurostat GISCO
Buildings (global):               Overture Maps Foundation — ODbL
```

---

## 11. Open items to close before you start building

1. **Run the smoke test in §0** — the five **[U]**-tagged URLs (NDW endpoints, WorldPop
   pattern, Bestand Bodemgebruik WFS, Render free web tier, AWS Lambda always-free) are the
   ones most likely to have drifted.
2. **Confirm the GHS-POP tile ID** for the Netherlands from the tile-schema shapefile in the
   parent directory of the tiles folder — `R3_C19` above is an educated guess.
3. **Pull the current 3DBAG version string** from
   `https://raw.githubusercontent.com/3DBAG/3dbag-viewer/main/src/assets/3dbag_versions.json`
   (`.latest`) rather than hardcoding `v20250903` — it moves every few months, and this file
   is the project's own source of truth.
4. **Check the BRP year** — 2025 was "definitief" as of March 2026, so
   `brpgewaspercelen_definitief_2025.gpkg` should now exist alongside the concept file.
5. **Decide raster-in-PostGIS or not** (§8.1) before you design the schema; `postgis_raster`
   availability varies by free host and it changes the whole data model.
