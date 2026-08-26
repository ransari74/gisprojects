"""Agriculture analytics -- the numbers behind the D3 panels."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import CurrentUser, require_permission
from app.services.analysis_cache import analysis_cache

router = APIRouter(prefix="/agriculture", tags=["agriculture"])

Db = Annotated[AsyncSession, Depends(get_db)]
Read = Annotated[CurrentUser, Depends(require_permission("agriculture:read"))]


@router.get("/summary")
async def summary(_: Read, db: Db, crop_year: int | None = None) -> dict:
    row = (
        await db.execute(
            text(
                """
                SELECT
                    count(*)::int                                AS field_count,
                    round(sum(area_ha)::numeric, 1)::float8      AS total_area_ha,
                    round(avg(area_ha)::numeric, 2)::float8      AS mean_field_ha,
                    round(avg(yield_t_ha)::numeric, 2)::float8   AS mean_yield,
                    round(avg(soil_ph)::numeric, 2)::float8      AS mean_ph,
                    round(avg(soil_organic_c)::numeric, 1)::float8 AS mean_soc,
                    round(avg(ndvi_mean)::numeric, 3)::float8    AS mean_ndvi,
                    count(*) FILTER (WHERE irrigated)::int       AS irrigated_fields,
                    count(*) FILTER (WHERE organic)::int         AS organic_fields,
                    count(DISTINCT crop_type)::int               AS crop_types
                FROM agri.fields
                WHERE (CAST(:crop_year AS int) IS NULL OR crop_year = :crop_year)
                """
            ),
            {"crop_year": crop_year},
        )
    ).mappings().one()
    return dict(row)


@router.get("/yield-by-crop")
async def yield_by_crop(_: Read, db: Db, crop_year: int | None = None) -> list[dict]:
    """Grouped bar chart: mean yield and area per crop, with a spread band."""
    rows = (
        await db.execute(
            text(
                """
                SELECT crop_type,
                       count(*)::int                              AS fields,
                       round(sum(area_ha)::numeric, 1)::float8    AS area_ha,
                       round(avg(yield_t_ha)::numeric, 2)::float8 AS mean_yield,
                       round(percentile_cont(0.25) WITHIN GROUP (ORDER BY yield_t_ha)::numeric, 2)::float8 AS p25,
                       round(percentile_cont(0.50) WITHIN GROUP (ORDER BY yield_t_ha)::numeric, 2)::float8 AS median,
                       round(percentile_cont(0.75) WITHIN GROUP (ORDER BY yield_t_ha)::numeric, 2)::float8 AS p75,
                       round(min(yield_t_ha)::numeric, 2)::float8 AS min_yield,
                       round(max(yield_t_ha)::numeric, 2)::float8 AS max_yield
                FROM agri.fields
                WHERE yield_t_ha IS NOT NULL
                  AND (CAST(:crop_year AS int) IS NULL OR crop_year = :crop_year)
                GROUP BY crop_type
                ORDER BY area_ha DESC
                """
            ),
            {"crop_year": crop_year},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/soil-yield-correlation")
async def soil_yield_correlation(
    _: Read,
    db: Db,
    x: Annotated[str, Query(pattern="^(soil_ph|soil_organic_c|soil_clay_pct|soil_sand_pct|ndvi_mean|elevation_m|slope_deg)$")] = "soil_organic_c",
    crop_type: str | None = None,
    limit: Annotated[int, Query(ge=50, le=5000)] = 1500,
) -> dict:
    """Scatter data plus correlation statistics for the soil-vs-yield panel.

    Absolute yield is not comparable across crops -- sugarbeet runs at ~80 t/ha
    and barley at ~7 -- so a raw correlation over the whole table is dominated
    by the crop mix and reads as no relationship at all. The query therefore
    also returns a *yield index*: each field's yield divided by the mean for its
    own crop. The index removes the between-crop variance and exposes the soil
    effect, which is the relationship the panel is actually about.

    Both coefficients are returned so the chart can show the naive number next
    to the controlled one. Note that soil pH is deliberately *not* the default
    x column: pH acts through an optimum near 6.5, so a linear coefficient
    reads near zero even though the effect is real -- selecting it in the UI
    is a good illustration of exactly that trap.

    The x column is constrained by the route's regex, so interpolating it is
    safe -- only the seven listed names can ever reach the query.
    """
    params: dict = {"limit": limit, "crop_type": crop_type}
    crop_filter = "AND (CAST(:crop_type AS text) IS NULL OR crop_type = :crop_type)"

    rows = (
        await db.execute(
            text(
                f"""
                WITH crop_mean AS (
                    SELECT crop_type, avg(yield_t_ha) AS mean_yield
                    FROM agri.fields
                    WHERE yield_t_ha IS NOT NULL
                    GROUP BY crop_type
                )
                SELECT f.id, f.field_code, f.crop_type, f.soil_texture,
                       f.{x}::float8         AS x,
                       f.yield_t_ha::float8  AS y,
                       round((f.yield_t_ha / NULLIF(m.mean_yield, 0))::numeric, 4)::float8 AS y_index,
                       f.area_ha::float8     AS size
                FROM agri.fields f
                JOIN crop_mean m ON m.crop_type = f.crop_type
                WHERE f.{x} IS NOT NULL AND f.yield_t_ha IS NOT NULL
                  {crop_filter.replace('crop_type =', 'f.crop_type =')}
                ORDER BY random()
                LIMIT :limit
                """
            ),
            params,
        )
    ).mappings().all()

    stats = (
        await db.execute(
            text(
                f"""
                WITH crop_mean AS (
                    SELECT crop_type, avg(yield_t_ha) AS mean_yield
                    FROM agri.fields
                    WHERE yield_t_ha IS NOT NULL
                    GROUP BY crop_type
                ),
                indexed AS (
                    SELECT f.{x}::float8 AS x,
                           f.yield_t_ha::float8 AS y,
                           (f.yield_t_ha / NULLIF(m.mean_yield, 0))::float8 AS y_index
                    FROM agri.fields f
                    JOIN crop_mean m ON m.crop_type = f.crop_type
                    WHERE f.{x} IS NOT NULL AND f.yield_t_ha IS NOT NULL
                      {crop_filter.replace('crop_type =', 'f.crop_type =')}
                )
                SELECT round(corr(x, y)::numeric, 4)::float8              AS pearson_r,
                       round(corr(x, y_index)::numeric, 4)::float8        AS pearson_r_indexed,
                       round(regr_r2(y_index, x)::numeric, 4)::float8     AS r_squared_indexed,
                       round(regr_slope(y_index, x)::numeric, 5)::float8  AS slope,
                       round(regr_intercept(y_index, x)::numeric, 5)::float8 AS intercept,
                       count(*)::int AS n
                FROM indexed
                """
            ),
            {"crop_type": crop_type},
        )
    ).mappings().one()

    return {
        "xColumn": x,
        "cropType": crop_type,
        "yUnit": "t/ha",
        "yIndexNote": "yield / mean yield for the same crop (1.0 = crop average)",
        "points": [dict(r) for r in rows],
        **dict(stats),
    }


@router.get("/ndvi-timeseries")
async def ndvi_timeseries(
    _: Read,
    db: Db,
    crop_type: str | None = None,
    field_id: int | None = None,
) -> list[dict]:
    """Multi-line chart: mean NDVI per date, split by crop (or one field)."""
    rows = (
        await db.execute(
            text(
                """
                SELECT ts.obs_date::text                       AS date,
                       f.crop_type                             AS series,
                       round(avg(ts.ndvi)::numeric, 4)::float8 AS ndvi,
                       round(percentile_cont(0.1) WITHIN GROUP (ORDER BY ts.ndvi)::numeric, 4)::float8 AS lower,
                       round(percentile_cont(0.9) WITHIN GROUP (ORDER BY ts.ndvi)::numeric, 4)::float8 AS upper,
                       count(*)::int                           AS samples
                FROM agri.field_ndvi_timeseries ts
                JOIN agri.fields f ON f.id = ts.field_id
                WHERE (CAST(:crop_type AS text) IS NULL OR f.crop_type = :crop_type)
                  AND (CAST(:field_id AS int) IS NULL OR f.id = :field_id)
                GROUP BY ts.obs_date, f.crop_type
                ORDER BY ts.obs_date, f.crop_type
                """
            ),
            {"crop_type": crop_type, "field_id": field_id},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/soil-texture-triangle")
async def soil_texture_triangle(_: Read, db: Db, limit: int = 800) -> list[dict]:
    """Sand/silt/clay fractions for the USDA texture-triangle scatter."""
    rows = (
        await db.execute(
            text(
                """
                SELECT id, field_code, soil_texture,
                       soil_sand_pct::float8 AS sand,
                       soil_silt_pct::float8 AS silt,
                       soil_clay_pct::float8 AS clay,
                       yield_t_ha::float8    AS yield_t_ha
                FROM agri.fields
                WHERE soil_sand_pct IS NOT NULL AND soil_clay_pct IS NOT NULL
                ORDER BY random()
                LIMIT :limit
                """
            ),
            {"limit": min(max(limit, 10), 3000)},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/irrigation-coverage")
async def irrigation_coverage(_: Read, db: Db, buffer_m: int = 250) -> dict:
    """Share of field area within `buffer_m` of a canal.

    Geography casts give a metre buffer that is correct at any latitude without
    picking a local projected SRID per study area.
    """
    row = (
        await db.execute(
            text(
                """
                WITH served AS (
                    SELECT DISTINCT f.id, f.area_ha
                    FROM agri.fields f
                    JOIN agri.irrigation_canals c
                      ON ST_DWithin(f.geom::geography, c.geom::geography, :buffer_m)
                )
                SELECT
                    (SELECT count(*) FROM agri.fields)::int                       AS total_fields,
                    (SELECT count(*) FROM served)::int                            AS served_fields,
                    round((SELECT sum(area_ha) FROM agri.fields)::numeric, 1)::float8  AS total_area_ha,
                    round((SELECT COALESCE(sum(area_ha), 0) FROM served)::numeric, 1)::float8 AS served_area_ha,
                    round((SELECT COALESCE(sum(length_m), 0) / 1000 FROM agri.irrigation_canals)::numeric, 1)::float8 AS canal_km
                """
            ),
            {"buffer_m": buffer_m},
        )
    ).mappings().one()
    data = dict(row)
    data["buffer_m"] = buffer_m
    data["served_area_pct"] = (
        round(100 * data["served_area_ha"] / data["total_area_ha"], 1)
        if data["total_area_ha"]
        else 0.0
    )
    return data


# ---------------------------------------------------------------------------
# AlphaEarth satellite embeddings
#
# Each parcel carries a 64-dimensional unit vector per year, zonal-averaged
# from Google's AlphaEarth Foundations dataset. Because the vectors are
# unit-length, a dot product is their cosine similarity -- so "find fields like
# this one" is one SQL expression and needs no model at request time.
#
# The classifier below is nearest-centroid: average the training vectors of a
# class, re-normalise, and assign each parcel to whichever class centroid it
# points most nearly toward. It is deliberately not a gradient-boosted tree.
# Nearest-centroid is the standard strong baseline for well-formed embeddings,
# it stays inside SQL alongside every other analysis in this project, and it
# has the property that actually matters here: it degrades gracefully as
# labels are removed, which is what the learning curve is there to show.
# ---------------------------------------------------------------------------

#: Label budgets the learning curve is evaluated at. The point of the chart is
#: the left-hand end -- how little supervision the embedding needs before it is
#: useful -- so the sampling is dense there and sparse afterwards.
LABEL_BUDGETS = (1, 2, 3, 5, 8, 12, 20, 35, 60, 100)


@router.get("/embedding-years")
async def embedding_years(_: Read, db: Db) -> dict:
    rows = (
        await db.execute(text("SELECT DISTINCT year FROM agri.field_embeddings ORDER BY year"))
    ).scalars().all()
    return {"years": [int(y) for y in rows], "latest": int(rows[-1]) if rows else None}


@router.get("/similar-fields")
async def similar_fields(
    _: Read,
    db: Db,
    field_id: Annotated[int, Query(ge=1)],
    year: Annotated[int | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 12,
) -> dict:
    """Parcels ranked by cosine similarity to the query parcel's embedding."""
    target_year = year or (
        await db.execute(text("SELECT max(year) FROM agri.field_embeddings"))
    ).scalar_one()

    query_field = (
        await db.execute(
            text(
                """
                SELECT f.id, f.field_code, f.farm_name, f.crop_type, f.soil_texture,
                       round(f.area_ha::numeric, 2)::float8    AS area_ha,
                       round(f.yield_t_ha::numeric, 2)::float8 AS yield_t_ha,
                       round(f.ndvi_mean::numeric, 3)::float8  AS ndvi_mean,
                       f.irrigated, f.organic, e.declared_crop, e.pixel_count
                FROM agri.fields f
                JOIN agri.field_embeddings e ON e.field_id = f.id AND e.year = :year
                WHERE f.id = :field_id
                """
            ),
            {"field_id": field_id, "year": target_year},
        )
    ).mappings().one_or_none()

    if query_field is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"No embedding for field {field_id} in {target_year}",
        )

    matches = (
        await db.execute(
            text(
                """
                WITH q AS (
                    SELECT embedding FROM agri.field_embeddings
                    WHERE field_id = :field_id AND year = :year
                )
                SELECT f.id, f.field_code, f.farm_name, f.crop_type, f.soil_texture,
                       round(f.area_ha::numeric, 2)::float8      AS area_ha,
                       round(f.yield_t_ha::numeric, 2)::float8   AS yield_t_ha,
                       round(f.ndvi_mean::numeric, 3)::float8    AS ndvi_mean,
                       f.irrigated, f.organic,
                       round(agri.embedding_similarity(e.embedding, q.embedding)::numeric, 4)::float8
                           AS similarity
                FROM agri.field_embeddings e
                JOIN agri.fields f ON f.id = e.field_id
                CROSS JOIN q
                WHERE e.year = :year AND e.field_id <> :field_id
                ORDER BY similarity DESC
                LIMIT :limit
                """
            ),
            {"field_id": field_id, "year": target_year, "limit": limit},
        )
    ).mappings().all()

    # How often the top matches share the query's crop and soil. This is the
    # honest quality read on the ranking: a similarity search that returns
    # confident-looking numbers for unrelated parcels is worse than none.
    hits = [dict(m) for m in matches]
    crop_agreement = (
        sum(1 for m in hits if m["crop_type"] == query_field["crop_type"]) / len(hits)
        if hits else 0.0
    )
    soil_agreement = (
        sum(1 for m in hits if m["soil_texture"] == query_field["soil_texture"]) / len(hits)
        if hits else 0.0
    )

    return {
        "year": int(target_year),
        "query": dict(query_field),
        "matches": hits,
        "cropAgreement": round(crop_agreement, 3),
        "soilAgreement": round(soil_agreement, 3),
    }


#: Evaluates every label budget in one statement: build a per-class centroid
#: from the first k labels of each class, normalise it, then score every parcel
#: against every centroid and keep the best. Looping in Python instead would
#: mean shipping 9,600 x 64 floats to the app for arithmetic Postgres already
#: does well.
CLASSIFY_SQL = text(
    """
    WITH ranked AS (
        SELECT field_id, declared_crop, embedding,
               row_number() OVER (
                   PARTITION BY declared_crop ORDER BY hashint4(field_id)
               ) AS rn
        FROM agri.field_embeddings
        WHERE year = :year
    ),
    budgets AS (SELECT unnest(CAST(:budgets AS int[])) AS k),
    centroid_parts AS (
        SELECT b.k, r.declared_crop, i AS dim, sum(r.embedding[i]) AS total
        FROM ranked r
        CROSS JOIN budgets b
        CROSS JOIN generate_series(1, 64) AS i
        WHERE r.rn <= b.k
        GROUP BY b.k, r.declared_crop, i
    ),
    centroids AS (
        SELECT k, declared_crop, array_agg(total ORDER BY dim) AS raw
        FROM centroid_parts GROUP BY k, declared_crop
    ),
    -- Re-normalise: the mean of unit vectors is not itself unit-length, and an
    -- unnormalised centroid biases classification toward whichever class
    -- happens to be most internally consistent.
    unit_centroids AS (
        SELECT c.k, c.declared_crop,
               (SELECT array_agg(v / nullif(n.norm, 0) ORDER BY ord)
                FROM unnest(c.raw) WITH ORDINALITY AS t(v, ord)) AS centroid
        FROM centroids c,
             LATERAL (SELECT sqrt(sum(x * x)) AS norm FROM unnest(c.raw) AS x) n
    ),
    -- Evaluate on held-out parcels only. Scoring the training examples too
    -- would report how well the centroid remembers its own inputs, which for a
    -- nearest-centroid classifier is flattering and meaningless -- and it is
    -- exactly the mistake that makes a few-shot result look better than it is.
    scored AS (
        SELECT r.k, r.field_id, r.declared_crop AS actual, c.declared_crop AS predicted,
               row_number() OVER (
                   PARTITION BY r.k, r.field_id
                   ORDER BY agri.embedding_similarity(r.embedding, c.centroid) DESC
               ) AS rank
        FROM (SELECT b.k, x.* FROM ranked x CROSS JOIN budgets b WHERE x.rn > b.k) r
        JOIN unit_centroids c ON c.k = r.k
    )
    SELECT k, actual, predicted, field_id FROM scored WHERE rank = 1
    """
)


@router.get("/crop-classification")
async def crop_classification(
    _: Read,
    db: Db,
    year: Annotated[int | None, Query()] = None,
    labels_per_class: Annotated[int, Query(ge=1, le=400)] = 20,
) -> dict:
    """Few-shot nearest-centroid crop classification, plus the learning curve.

    The training sample is drawn deterministically (`ORDER BY hashint4`) rather
    than randomly, so accuracy is stable across requests and the learning curve
    does not jitter on every refresh.
    """
    target_year = year or (
        await db.execute(text("SELECT max(year) FROM agri.field_embeddings"))
    ).scalar_one()

    budgets = sorted({*LABEL_BUDGETS, labels_per_class})

    # Roughly five seconds of Postgres, and the same five seconds every time --
    # nothing here depends on the request beyond the key. See
    # services/analysis_cache.py for why this is process-local rather than Redis.
    cache_key = f"crop-classification:{target_year}:{','.join(map(str, budgets))}"
    cached = analysis_cache.get(cache_key)
    if cached is not None:
        rows = cached
    else:
        rows = [
            dict(r)
            for r in (
                await db.execute(CLASSIFY_SQL, {"year": target_year, "budgets": budgets})
            ).mappings().all()
        ]
        analysis_cache.set(cache_key, rows)

    by_budget: dict[int, list[dict]] = {}
    for row in rows:
        by_budget.setdefault(int(row["k"]), []).append(row)

    class_sizes = {
        r["declared_crop"]: int(r["n"])
        for r in (
            await db.execute(
                text(
                    """
                    SELECT declared_crop, count(*) AS n
                    FROM agri.field_embeddings WHERE year = :year
                    GROUP BY declared_crop
                    """
                ),
                {"year": target_year},
            )
        ).mappings().all()
    }
    # A class with fewer parcels than the budget contributes all of them, so
    # past the rarest class the curve cannot move. Reported so the flat tail is
    # explainable rather than odd.
    smallest_class = min(class_sizes.values()) if class_sizes else 0

    curve = []
    for k in budgets:
        preds = by_budget.get(k, [])
        if not preds:
            continue
        correct = sum(1 for p in preds if p["actual"] == p["predicted"])
        curve.append({
            "labelsPerClass": k,
            "accuracy": round(100 * correct / len(preds), 2),
            "labelsUsed": sum(min(k, n) for n in class_sizes.values()),
            "evaluatedOn": len(preds),
            # Past the rarest class there are no labels left to add for it, so
            # the curve cannot move for the right reason any more.
            "saturated": k >= smallest_class,
        })

    selected = by_budget.get(labels_per_class, [])
    per_class: dict[str, dict] = {}
    confusion: dict[tuple[str, str], int] = {}
    for p in selected:
        actual, predicted = p["actual"], p["predicted"]
        confusion[(actual, predicted)] = confusion.get((actual, predicted), 0) + 1
        stats = per_class.setdefault(actual, {"support": 0, "correct": 0, "predicted_as": 0})
        stats["support"] += 1
        if actual == predicted:
            stats["correct"] += 1
    for p in selected:
        per_class.setdefault(
            p["predicted"], {"support": 0, "correct": 0, "predicted_as": 0}
        )["predicted_as"] += 1

    accuracy = (
        round(100 * sum(1 for p in selected if p["actual"] == p["predicted"]) / len(selected), 2)
        if selected else 0.0
    )

    return {
        "year": int(target_year),
        "labelsPerClass": labels_per_class,
        "accuracy": accuracy,
        "classCount": len(class_sizes),
        "parcelCount": len(selected),
        "smallestClass": smallest_class,
        "curve": curve,
        "perClass": [
            {
                "crop": crop,
                "support": s["support"],
                "recall": round(100 * s["correct"] / s["support"], 1) if s["support"] else 0.0,
                "precision": (
                    round(100 * s["correct"] / s["predicted_as"], 1) if s["predicted_as"] else 0.0
                ),
            }
            for crop, s in sorted(per_class.items(), key=lambda kv: -kv[1]["support"])
        ],
        "confusion": [
            {"actual": a, "predicted": p, "count": n}
            for (a, p), n in sorted(confusion.items(), key=lambda kv: -kv[1])
            if a != p
        ],
    }


@router.get("/rotation")
async def rotation(_: Read, db: Db) -> dict:
    """Year-over-year embedding similarity, split by whether the crop changed.

    The practical question behind it: can the imagery alone tell you a parcel
    was rotated, without reading the declaration? If it can, the same test
    flags parcels whose declaration is missing or stale.
    """
    rows = (
        await db.execute(
            text(
                """
                SELECT a.declared_crop <> b.declared_crop AS rotated,
                       agri.embedding_similarity(a.embedding, b.embedding) AS similarity
                FROM agri.field_embeddings a
                JOIN agri.field_embeddings b
                  ON b.field_id = a.field_id AND b.year = a.year + 1
                """
            )
        )
    ).mappings().all()

    changed = [r["similarity"] for r in rows if r["rotated"]]
    unchanged = [r["similarity"] for r in rows if not r["rotated"]]

    # Both groups are binned on one shared set of edges so the chart can
    # overlay them; separate edges would make the overlap unreadable, and the
    # overlap is the honest part of the result.
    bins, lo, hi = 22, 0.0, 1.0

    def histogram(values: list[float]) -> list[dict]:
        counts = [0] * bins
        for v in values:
            counts[min(bins - 1, max(0, int((v - lo) / (hi - lo) * bins)))] += 1
        return [
            {"x0": lo + (hi - lo) * i / bins, "x1": lo + (hi - lo) * (i + 1) / bins, "count": c}
            for i, c in enumerate(counts)
        ]

    # Rank-based separability: the chance a rotated pair scores below an
    # unchanged pair. Reported instead of the difference of means because the
    # means sit close together -- a parcel keeps its soil and drainage
    # signature through a rotation -- while the distributions still separate.
    auc = 0.0
    if changed and unchanged:
        ordered = sorted([(v, 0) for v in changed] + [(v, 1) for v in unchanged])
        seen_changed = 0
        wins = 0
        for _value, group in ordered:
            if group == 0:
                seen_changed += 1
            else:
                wins += seen_changed
        auc = wins / (len(changed) * len(unchanged))

    by_crop = (
        await db.execute(
            text(
                """
                WITH consecutive AS (
                    SELECT a.declared_crop AS from_crop,
                           (a.declared_crop <> b.declared_crop) AS rotated
                    FROM agri.field_embeddings a
                    JOIN agri.field_embeddings b
                      ON b.field_id = a.field_id AND b.year = a.year + 1
                )
                SELECT from_crop,
                       count(*)::int                                        AS transitions,
                       round(100.0 * avg(rotated::int)::numeric, 1)::float8 AS rotated_pct
                FROM consecutive
                GROUP BY from_crop
                ORDER BY rotated_pct DESC
                """
            )
        )
    ).mappings().all()

    return {
        "pairCount": len(rows),
        "changedCount": len(changed),
        "unchangedCount": len(unchanged),
        "meanChanged": round(sum(changed) / len(changed), 4) if changed else None,
        "meanUnchanged": round(sum(unchanged) / len(unchanged), 4) if unchanged else None,
        "separability": round(auc, 4),
        "changedHistogram": histogram(changed),
        "unchangedHistogram": histogram(unchanged),
        "byCrop": [dict(r) for r in by_crop],
    }
