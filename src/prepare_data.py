"""Berlin-wide building feature pipeline (Path B: ALKIS-labeled, Zhou et al. reproduction).

Lifted from notebooks/berlin_mitte.ipynb's Path B (clf2) cells and generalized to run once
over all of Berlin instead of one borough at a time -- see docs/phase4-findings.md and the
plan this was built from for why per-borough looping was rejected (it would undercount
road/parking proximity at every internal Bezirk boundary). Every feature builder here runs
once on city-wide GeoDataFrames; Bezirk boundaries only come in afterward as a bookkeeping
column via assign_bezirk().

Path C (the accuracy-focused pedestrian/compactness/building-levels experiment in
berlin_mitte.ipynb) is deliberately NOT ported here -- it underperformed Path B under
cross-validation at Mitte's ~5k-row scale and is parked pending a re-test at full-Berlin
scale, not validated for production use.
"""

import urllib.parse
import warnings
from pathlib import Path

import geopandas as gpd
import mapclassify
import pandas as pd
from pyrosm import OSM

ALKIS_WFS_BASE = "https://gdi.berlin.de/services/wfs"

# pyrosm returns dozens of raw OSM columns per layer (email, phone, url, wikipedia, a whole
# nested 'tags' dict, ...) that nothing downstream reads. At full-Berlin scale (~500k+
# buildings) carrying all of them caused an OOM kill on a 15GB laptop -- prune to what the
# feature builders below actually use, right after loading.
_BUILDING_KEEP_COLS = [
    "geometry", "building", "addr:street", "building:levels", "shop", "website", "brand",
    "amenity", "name", "source",
]
_ROAD_KEEP_COLS = ["geometry", "highway"]
_LANDUSE_KEEP_COLS = ["geometry", "landuse"]
_PARKING_KEEP_COLS = ["geometry"]


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def load_berlin_osm(pbf_path: str) -> dict[str, gpd.GeoDataFrame]:
    """Extract buildings/landuse/roads/parking from a local Berlin .osm.pbf via pyrosm.

    Columns verified (src/pyrosm_smoke_test.ipynb) to match what the feature builders below
    expect: building, addr:street, building:levels, shop, website, amenity, name, source on
    buildings; landuse on landuse; highway on roads. 'brand' is not a first-class pyrosm
    column -- add_tag_presence_features() already tolerates a missing column.
    """
    osm = OSM(pbf_path)

    buildings = osm.get_buildings()
    buildings = buildings[[c for c in _BUILDING_KEEP_COLS if c in buildings.columns]]
    buildings = buildings.to_crs(epsg=25833)
    buildings = buildings[buildings.geom_type.isin(["Polygon", "MultiPolygon"])].copy()

    landuse = osm.get_landuse()
    if landuse is not None:
        landuse = landuse[[c for c in _LANDUSE_KEEP_COLS if c in landuse.columns]]
        landuse = landuse.to_crs(epsg=25833)
    else:
        landuse = gpd.GeoDataFrame(columns=["landuse", "geometry"], geometry="geometry", crs="EPSG:25833")

    roads = osm.get_network(network_type="all")
    roads = roads[[c for c in _ROAD_KEEP_COLS if c in roads.columns]]
    roads = roads.to_crs(epsg=25833)

    parking = osm.get_data_by_custom_criteria(
        custom_filter={"amenity": ["parking", "parking_space"]},
        filter_type="keep",
        keep_nodes=False, keep_ways=True, keep_relations=True,
    )
    if parking is not None:
        parking = parking[[c for c in _PARKING_KEEP_COLS if c in parking.columns]]
        parking = parking.to_crs(epsg=25833)
        parking = parking[parking.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    else:
        parking = gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs="EPSG:25833")

    return {"buildings": buildings, "landuse": landuse, "roads": roads, "parking": parking}


def _wfs_get_feature(type_names: str, bbox: tuple | None = None, page_size: int = 50_000) -> gpd.GeoDataFrame:
    """Paginated WFS 2.0 GetFeature fetch. alkis_gebaeude's GetCapabilities declares
    CountDefault=1_000_000 and ImplementsResultPaging=TRUE (verified live) -- paging here is
    cheap insurance rather than a response to a confirmed limit.
    """
    
    service = type_names.split(":")[0]
    base_params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": type_names,
        "outputFormat": "application/json",
        "srsName": "EPSG:25833",
    }
    if bbox is not None:
        minx, miny, maxx, maxy = bbox
        base_params["bbox"] = f"{minx},{miny},{maxx},{maxy},EPSG:25833"

    pages = []
    start_index = 0
    while True:
        params = dict(base_params, count=page_size, startIndex=start_index)
        url = f"{ALKIS_WFS_BASE}/{service}?" + urllib.parse.urlencode(params)
        page = gpd.read_file(url)
        if page.empty:
            break
        pages.append(page)
        if len(page) < page_size:
            break
        start_index += page_size

    if not pages:
        return gpd.GeoDataFrame()
    result = pd.concat(pages, ignore_index=True)
    return gpd.GeoDataFrame(result, geometry="geometry", crs=pages[0].crs)


def fetch_bezirksgrenzen() -> gpd.GeoDataFrame:
    """All 12 Berlin Bezirke, already in EPSG:25833. 'namgem' column has the Bezirk name."""
    return _wfs_get_feature("alkis_bezirke:bezirksgrenzen")


def fetch_alkis_buildings(bbox: tuple | None = None) -> gpd.GeoDataFrame:
    """ALKIS cadastral buildings. bbox=None fetches all of Berlin in one paginated call."""
    return _wfs_get_feature("alkis_gebaeude:gebaeude", bbox=bbox)


# ---------------------------------------------------------------------------
# Road / parking proximity features -- run ONCE on city-wide GeoDataFrames
# ---------------------------------------------------------------------------

def road_bucket(highway_value):
    if highway_value in ["residential", "living_street"]:
        return "residential"
    if highway_value in ["primary", "secondary", "tertiary"]:
        return "highway"
    if highway_value in ["motorway", "trunk"]:
        return "motorway"
    if highway_value in ["service"]:
        return "service"
    return None


def _buffer_and_match(buildings, sub_features, distance):
    """Buffer buildings by `distance` and test intersection against sub_features, without
    copying every other column in `buildings` per call. The original approach did
    buildings.copy() (all columns) once per buffer distance -- 12x for roads, 9x for
    parking -- which duplicated the whole table repeatedly and caused an OOM kill on a
    full-Berlin run. This builds a minimal index+geometry frame instead, discarded right
    after extracting the matched index.
    """
    buffered_geom = buildings.geometry.buffer(distance)
    buffered = gpd.GeoDataFrame(geometry=buffered_geom, index=buildings.index, crs=buildings.crs)
    joined = gpd.sjoin(buffered, sub_features[["geometry"]], predicate="intersects", how="inner")
    return buildings.index.isin(joined.index.unique())


def add_road_proximity_features(buildings, roads, buffers=(30, 60, 90)):
    roads = roads[["highway", "geometry"]].copy()
    roads["bucket"] = roads["highway"].apply(road_bucket)
    buildings = buildings.copy()
    for bucket in ["residential", "highway", "motorway", "service"]:
        sub_roads = roads.loc[roads["bucket"] == bucket, ["geometry"]]
        for d in buffers:
            col = f"road_{bucket}_{d}m"
            if sub_roads.empty:
                buildings[col] = 0
                continue
            buildings[col] = _buffer_and_match(buildings, sub_roads, d).astype(int)
    return buildings


def fit_parking_size_classifier(parking) -> mapclassify.FisherJenks:
    """Fit ONCE on Berlin-wide parking-lot areas. Fitting per-borough (the original
    notebook's approach) makes size-class thresholds incomparable once boroughs are pooled.
    """
    return mapclassify.FisherJenks(parking.geometry.area, k=3)


def add_parking_proximity_features(buildings, parking, classifier, buffers=(30, 60, 90)):
    parking = parking[["geometry"]].copy()
    parking["size_class"] = parking.geometry.area.apply(classifier.find_bin)
    buildings = buildings.copy()
    for size_class in range(3):
        sub_parking = parking.loc[parking["size_class"] == size_class, ["geometry"]]
        for d in buffers:
            col = f"parking_size{size_class}_{d}m"
            if sub_parking.empty:
                buildings[col] = 0
                continue
            buildings[col] = _buffer_and_match(buildings, sub_parking, d).astype(int)
    return buildings


# ---------------------------------------------------------------------------
# Landuse -- fixed canonical value list, same pattern as PAPER_BUILDING_VALUES below
# ---------------------------------------------------------------------------

# PROVISIONAL: union of landuse=* values observed across two Mitte-only osmnx runs (the sets
# differed between runs due to live-Overpass timing variance -- exactly the bug this fixed
# list exists to prevent). Re-review against a real full-Berlin landuse pull and update this
# list + docs/phase0-taxonomy.md; add_landuse_features() warns (doesn't silently drop) if it
# sees a value outside this list, which is how that review gets triggered.
CANONICAL_LANDUSE_VALUES = [
    "allotments", "brownfield", "cemetery", "civic_admin", "commercial", "construction",
    "education", "farmland", "farmyard", "flowerbed", "forest", "garages", "government",
    "governmental", "grass", "greenfield", "industrial", "institutional", "meadow",
    "military", "railway", "recreation_ground", "religious", "residential", "retail",
    "vineyard",
]


def add_landuse_features(buildings, landuse):
    observed = set(landuse["landuse"].dropna().unique())
    unexpected = observed - set(CANONICAL_LANDUSE_VALUES)
    if unexpected:
        warnings.warn(
            f"landuse values outside CANONICAL_LANDUSE_VALUES observed: {sorted(unexpected)} "
            "-- review and add to the canonical list in src/prepare_data.py; until then these "
            "buildings' landuse signal for those values is silently dropped."
        )

    landuse_joined = gpd.sjoin(
        buildings[["geometry"]], landuse[["geometry", "landuse"]],
        predicate="intersects", how="left",
    )
    landuse_val = landuse_joined["landuse"].where(landuse_joined["landuse"].isin(CANONICAL_LANDUSE_VALUES))
    landuse_dummies = pd.get_dummies(landuse_val, prefix="landuse")
    for val in CANONICAL_LANDUSE_VALUES:
        col = f"landuse_{val}"
        if col not in landuse_dummies.columns:
            landuse_dummies[col] = 0
    landuse_features = landuse_dummies.groupby(landuse_joined.index).max()
    landuse_features = landuse_features.reindex(buildings.index).fillna(0).astype(int)

    buildings = buildings.copy()
    return pd.concat([buildings, landuse_features], axis=1)


# ---------------------------------------------------------------------------
# OSM tag presence + building-type dummies -- already borough-agnostic, fixed lists
# ---------------------------------------------------------------------------

DEFAULT_HAS_TAGS = ["name", "source", "addr:street", "building:levels", "shop", "website", "brand", "amenity"]


def add_tag_presence_features(buildings, tag_cols=DEFAULT_HAS_TAGS):
    buildings = buildings.copy()
    for col in tag_cols:
        buildings[f"has_{col}"] = buildings[col].notna().astype(int) if col in buildings.columns else 0
    return buildings


PAPER_BUILDING_VALUES = [
    "apartments", "church", "civic", "commercial", "construction", "detached", "dormitory",
    "garage", "garages", "greenhouse", "hospital", "hotel", "house", "industrial",
    "kindergarten", "office", "parking", "public", "residential", "retail", "roof", "school",
    "semidetached_house", "service", "shed", "static_caravan", "terrace", "warehouse", "yes",
]


def add_building_type_dummies(buildings):
    building_val = buildings["building"].where(buildings["building"].isin(PAPER_BUILDING_VALUES), "miscellaneous")
    building_dummies = pd.get_dummies(building_val, prefix="building")
    buildings = buildings.drop(columns=building_dummies.columns, errors="ignore")
    return pd.concat([buildings, building_dummies], axis=1)


# ---------------------------------------------------------------------------
# ALKIS labels
# ---------------------------------------------------------------------------

# PROVISIONAL: hand-built from Mitte/Friedrichshain-Kreuzberg's ~120-150 observed bezgfk
# values (docs/phase0-taxonomy.md Sec 2b). docs/phase4-findings.md explicitly flags this for
# re-review once the full Berlin-wide value_counts are available -- new categories are
# expected to appear in outer boroughs.
RESIDENTIAL_BEZGFK = {
    "Wohnhaus", "Wohngebäude", "Wohnheim",
    "Studenten-, Schülerwohnheim", "Schwesternwohnheim",
}

EXCLUDED_BEZGFK = {
    # officially mixed residential + non-residential use -- can't force a binary label
    "Wohngebäude mit Handel und Dienstleistungen",
    "Gebäude für Handel und Dienstleistung mit Wohnen",
    "Wohngebäude mit Gewerbe und Industrie",
    "Gemischt genutztes Gebäude mit Wohnen",
    "Wohngebäude mit Gemeinbedarf",
    "Gebäude für Gewerbe und Industrie mit Wohnen",
    "Gebäude für öffentliche Zwecke mit Wohnen",
    # ancillary parking/storage -- attaches to either residential or commercial parents
    "Garage", "Tiefgarage", "Schuppen", "Parkhaus", "Parkdeck", "Gebäude zum Parken", "Gartenhaus",
    # agricultural
    "Stall", "Stall im Zoo", "Land- und forstwirtschaftliches Betriebsgebäude",
    "Gebäude für Land- und Forstwirtschaft", "Scheune und Stall", "Treibhaus",
    # ambiguous institutional/residential care
    "Seniorenheim", "Obdachlosenheim", "Kinderheim",
    "Heilanstalt, Pflegeanstalt, Pflegestation", "Kaserne",
    # unspecified / not clearly a building type
    "Nach Quellenlage nicht zu spezifizieren", "Toilette", "Empfangsgebäude",
    "Wochenendhaus", "Bootshaus",
}


def alkis_label(bezgfk):
    if bezgfk is None:
        return None
    if bezgfk in RESIDENTIAL_BEZGFK:
        return "residential"
    if bezgfk in EXCLUDED_BEZGFK:
        return None
    return "non_residential"


def match_alkis_to_osm(buildings, alkis_buildings, min_overlap_ratio=0.5):
    """Largest-overlap spatial match, requiring >=min_overlap_ratio, ALKIS filtered to valid
    (non-excluded) labels BEFORE ranking by overlap area (see docs/phase4-findings.md item 7
    for why filter-then-rank matters).
    """
    alkis_buildings = alkis_buildings.copy()
    alkis_buildings["label"] = alkis_buildings["bezgfk"].apply(alkis_label)
    alkis_valid = alkis_buildings[alkis_buildings["label"].notna()].copy()

    buildings = buildings.reset_index(drop=True)
    buildings["_bid"] = buildings.index
    buildings["_osm_area"] = buildings.geometry.area

    overlay = gpd.overlay(
        buildings[["_bid", "_osm_area", "geometry"]],
        alkis_valid[["geometry", "label"]].rename(columns={"label": "alkis_label"}),
        how="intersection",
    )
    overlay["overlap_area"] = overlay.geometry.area
    overlay["overlap_ratio"] = overlay["overlap_area"] / overlay["_osm_area"]
    overlay = overlay[overlay["overlap_ratio"] >= min_overlap_ratio]

    best_match = (
        overlay.sort_values("overlap_area", ascending=False)
        .drop_duplicates(subset="_bid")
        .set_index("_bid")["alkis_label"]
    )
    buildings["alkis_label"] = buildings["_bid"].map(best_match)
    return buildings


# ---------------------------------------------------------------------------
# Bookkeeping -- never used to filter/scope the feature computations above
# ---------------------------------------------------------------------------

def assign_bezirk(buildings, bezirksgrenzen):
    """Cheap point-in-polygon join (building centroid) adding a 'bezirk' column, for
    breakdowns/spatial-CV grouping only.
    """
    centroids = gpd.GeoDataFrame(geometry=buildings.geometry.centroid, index=buildings.index, crs=buildings.crs)
    joined = gpd.sjoin(
        centroids, bezirksgrenzen[["namgem", "geometry"]],
        predicate="within", how="left",
    )
    joined = joined[~joined.index.duplicated(keep="first")]
    buildings = buildings.copy()
    buildings["bezirk"] = joined["namgem"]
    return buildings


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def feature_columns(buildings):
    return (
        [c for c in buildings.columns if c.startswith("road_")]
        + [c for c in buildings.columns if c.startswith("parking_")]
        + [c for c in buildings.columns if c.startswith("landuse_")]
        + [c for c in buildings.columns if c.startswith("has_")]
        + ["area_m2"]
        + [c for c in buildings.columns if c.startswith("building_")]
    )


def build_feature_table(
    pbf_path: str,
    cache_dir: str = "data/raw",
    out_path: str = "data/processed/berlin_buildings_features.parquet",
) -> gpd.GeoDataFrame:
    """Top-level driver. Idempotent: skips recompute of any step whose checkpoint already
    exists, so a failure/rerun doesn't redo the slow PBF parse or the network fetches.
    """
    cache_dir = Path(cache_dir)
    out_path = Path(out_path)
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if out_path.exists():
        return gpd.read_parquet(out_path)

    osm_ckpt = {name: cache_dir / f"berlin_osm_{name}.parquet" for name in ["buildings", "landuse", "roads", "parking"]}
    if all(p.exists() for p in osm_ckpt.values()):
        osm_data = {name: gpd.read_parquet(p) for name, p in osm_ckpt.items()}
    else:
        osm_data = load_berlin_osm(pbf_path)
        for name, gdf in osm_data.items():
            gdf.to_parquet(osm_ckpt[name])

    bezirke_ckpt = cache_dir / "bezirksgrenzen.parquet"
    if bezirke_ckpt.exists():
        bezirksgrenzen = gpd.read_parquet(bezirke_ckpt)
    else:
        bezirksgrenzen = fetch_bezirksgrenzen()
        bezirksgrenzen.to_parquet(bezirke_ckpt)

    alkis_ckpt = cache_dir / "alkis_buildings_berlin.parquet"
    if alkis_ckpt.exists():
        alkis_buildings = gpd.read_parquet(alkis_ckpt)
    else:
        alkis_buildings = fetch_alkis_buildings(bbox=None)
        alkis_buildings.to_parquet(alkis_ckpt)

    buildings = osm_data["buildings"].copy()
    buildings["area_m2"] = buildings.geometry.area
    buildings = add_road_proximity_features(buildings, osm_data["roads"])
    parking_classifier = fit_parking_size_classifier(osm_data["parking"])
    buildings = add_parking_proximity_features(buildings, osm_data["parking"], parking_classifier)
    buildings = add_landuse_features(buildings, osm_data["landuse"])
    buildings = add_tag_presence_features(buildings)
    buildings = match_alkis_to_osm(buildings, alkis_buildings)
    buildings = add_building_type_dummies(buildings)
    buildings = assign_bezirk(buildings, bezirksgrenzen)

    buildings.to_parquet(out_path)
    return buildings
