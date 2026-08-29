from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = "akerprestation-phase0-discovery-v0a"
EXPECTED_BASE_TAG = "akerminne-v1.0"
EXPECTED_BASE_COMMIT = "4b53ab24e9822f1c36c6cc31931dba3c1855fead"
EXPECTED_FEATURE_BRANCH = "feature/akerprestation-foundation-v0a"
EXPECTED_REFERENCE_YEAR = 2025
EXPECTED_REFERENCE_FIELDS = 128_636

SOIL_CLASS_LAYER_URL = (
    "https://kartportal.ystad.se/arcgis/rest/services/"
    "SAM/SAM_OP_Hansyn/MapServer/32"
)
SOIL_CLASS_QUERY_URL = SOIL_CLASS_LAYER_URL + "/query"
SOIL_CLASS_PROJECT_SOURCE_NOTE = (
    "Previously used ÅkerPass source: Ystad ArcGIS mirror; service description says "
    "former LstM Jord- och skogsklassificering M-län/L-län."
)
JVB_GIS_INFO_URL = (
    "https://jordbruksverket.se/e-tjanster-databaser-och-appar/"
    "e-tjanster-och-databaser-stod/kartor-och-gis"
)
JVB_OPEN_WFS = "https://epub.sjv.se/inspire/opendata/wfs"

SKO_TITLE_RE = re.compile(r"sk[öo]rdeomr", re.IGNORECASE)
SOIL_CLASS_FILE_RE = re.compile(r"(jord.*klass|klass.*jord|class5|class1|jord_skogsklass)", re.IGNORECASE)
SKO_FILE_RE = re.compile(r"(sko|sk[öo]rdeomr|skordeomr)", re.IGNORECASE)
GEODATA_SUFFIXES = {".gpkg", ".shp", ".geojson", ".json", ".parquet"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def text_id(value: Any) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    return s


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            block = fh.read(chunk_size)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def stable_json_dump(value: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def git(root: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=root, text=True, encoding="utf-8", errors="replace",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            "git " + " ".join(args) + f" failed ({proc.returncode}): {proc.stderr.strip()}"
        )
    return proc.stdout.strip()


def repository_snapshot(root: Path) -> dict[str, Any]:
    tag_commit = git(root, "rev-list", "-n", "1", EXPECTED_BASE_TAG)
    if tag_commit != EXPECTED_BASE_COMMIT:
        raise RuntimeError(
            f"{EXPECTED_BASE_TAG} resolves to {tag_commit}, expected {EXPECTED_BASE_COMMIT}"
        )
    head = git(root, "rev-parse", "HEAD")
    branch = git(root, "branch", "--show-current")
    status = git(root, "status", "--short")
    remote = git(root, "remote", "get-url", "origin")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", EXPECTED_BASE_COMMIT, head], cwd=root
    ).returncode == 0
    if not ancestor:
        raise RuntimeError(
            f"HEAD {head} does not descend from frozen ÅkerMinne base {EXPECTED_BASE_COMMIT}"
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "retrieved_utc": utc_now(),
        "repository_root": str(root),
        "origin": remote,
        "branch": branch,
        "head_commit": head,
        "working_tree_clean": status == "",
        "working_tree_status": status.splitlines() if status else [],
        "akerminne_v1_base_tag": EXPECTED_BASE_TAG,
        "akerminne_v1_base_commit": EXPECTED_BASE_COMMIT,
        "base_is_ancestor_of_head": ancestor,
        "reference_year": EXPECTED_REFERENCE_YEAR,
        "expected_reference_fields": EXPECTED_REFERENCE_FIELDS,
        "class5_already_implemented": True,
        "existing_class_scope": [5, 6, 7, 8, 9, 10],
        "existing_class_evidence": [
            "AGRI_CLASS5_10_V0B.md",
            "src/30b_agri_class5plus_v0b.py",
            "src/31c_akerscore_soil_v0c.py",
            "src/41_build_akerpass_public_data.py",
        ],
        "existing_class_public_semantics": (
            "historic_class_status is class_5_10; missing values are labelled "
            "not_in_imported_class_5_10"
        ),
        "new_class_scope_to_discover": [1, 2, 3, 4],
        "akerminne_join_key_contract": "current 2025 field keyed by blockid|skiftesbeteckning",
        "known_structure": {
            "akerminne": [
                "src/62_prepare_akerminne_skane.py",
                "src/63_build_akerminne_municipality.py",
                "src/64_run_akerminne_skane.py",
                "src/65_verify_akerminne_skane.py",
                "src/67_build_akerminne_skane_web.py",
            ],
            "field_source": "config/local_paths.json -> skiften",
            "build": ["data/derived", "dist"],
            "web": ["src/41_build_akerpass_public_data.py", "web/akerpass_v1.html"],
            "tests": "tests/test_*.py via unittest",
            "gis": ["geopandas", "EPSG:3006", "GeoPackage"],
        },
    }


def http_bytes(url: str, params: dict[str, Any] | None = None, timeout: int = 120) -> bytes:
    if params:
        query = urllib.parse.urlencode(params, doseq=True)
        url = url + ("&" if "?" in url else "?") + query
    req = urllib.request.Request(url, headers={"User-Agent": "AkerSync/1.0 phase0-discovery"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def http_json(url: str, params: dict[str, Any] | None = None, timeout: int = 120) -> Any:
    return json.loads(http_bytes(url, params=params, timeout=timeout).decode("utf-8"))


def renderer_class_domain(layer_metadata: dict[str, Any]) -> list[dict[str, Any]]:
    renderer = ((layer_metadata.get("drawingInfo") or {}).get("renderer") or {})
    rows: list[dict[str, Any]] = []
    for item in renderer.get("uniqueValueInfos") or []:
        raw = item.get("value")
        try:
            value = int(float(raw))
        except (TypeError, ValueError):
            value = raw
        rows.append({"value": value, "label": item.get("label")})
    return sorted(rows, key=lambda row: str(row["value"]).zfill(8))


def infer_arable_class_domain(domain_rows: Iterable[dict[str, Any]]) -> list[int]:
    values: list[int] = []
    for row in domain_rows:
        try:
            value = int(row.get("value"))
        except (TypeError, ValueError):
            continue
        label = str(row.get("label") or "").lower()
        if 1 <= value <= 10 and "skogsmark" not in label:
            values.append(value)
    return sorted(set(values))


def class_counts_from_arcgis() -> list[dict[str, Any]]:
    statistics = json.dumps(
        [{
            "statisticType": "count",
            "onStatisticField": "OBJECTID_12",
            "outStatisticFieldName": "feature_count",
        }],
        separators=(",", ":"),
    )
    payload = http_json(
        SOIL_CLASS_QUERY_URL,
        {
            "where": "1=1",
            "outStatistics": statistics,
            "groupByFieldsForStatistics": "KLASS",
            "orderByFields": "KLASS",
            "returnGeometry": "false",
            "f": "json",
        },
    )
    if "error" in payload:
        raise RuntimeError("ArcGIS statistics query failed: " + json.dumps(payload["error"]))
    rows = []
    for feature in payload.get("features") or []:
        attrs = feature.get("attributes") or {}
        raw = attrs.get("KLASS")
        try:
            klass = int(float(raw))
        except (TypeError, ValueError):
            klass = raw
        rows.append({"class_raw": klass, "feature_count": int(attrs.get("feature_count") or 0)})
    return rows


def download_arcgis_class_geojson(class_min: int = 1, class_max: int = 10) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    offset = 0
    page_size = 1000
    where = f"KLASS >= {class_min} AND KLASS <= {class_max}"
    while True:
        payload = http_json(
            SOIL_CLASS_QUERY_URL,
            {
                "where": where,
                "outFields": "OBJECTID_12,OBJECTID_1,KLASS",
                "returnGeometry": "true",
                "outSR": "4326",
                "orderByFields": "OBJECTID_12",
                "resultOffset": offset,
                "resultRecordCount": page_size,
                "f": "geojson",
            },
            timeout=180,
        )
        if "error" in payload:
            raise RuntimeError("ArcGIS geometry query failed: " + json.dumps(payload["error"]))
        batch = payload.get("features") or []
        features.extend(batch)
        if len(batch) < page_size:
            break
        offset += len(batch)
    return {"type": "FeatureCollection", "features": features}


def find_sko_feature_type(capabilities_xml: bytes) -> dict[str, str]:
    root = ET.fromstring(capabilities_xml)
    candidates: list[dict[str, str]] = []
    for feature_type in root.findall(".//{*}FeatureType"):
        name_node = feature_type.find("{*}Name")
        title_node = feature_type.find("{*}Title")
        name = (name_node.text or "").strip() if name_node is not None else ""
        title = (title_node.text or "").strip() if title_node is not None else ""
        if SKO_TITLE_RE.search(name) or SKO_TITLE_RE.search(title):
            candidates.append({"name": name, "title": title})
    if len(candidates) != 1:
        raise RuntimeError(
            "Expected exactly one SKO feature type in Jordbruksverket WFS; found "
            + json.dumps(candidates, ensure_ascii=False)
        )
    return candidates[0]


def wfs_describe_feature_type(type_name: str) -> dict[str, Any]:
    xml = http_bytes(
        JVB_OPEN_WFS,
        {
            "service": "WFS",
            "version": "2.0.0",
            "request": "DescribeFeatureType",
            "typeNames": type_name,
        },
    )
    root = ET.fromstring(xml)
    fields = []
    for element in root.findall(".//{http://www.w3.org/2001/XMLSchema}element"):
        name = element.attrib.get("name")
        typ = element.attrib.get("type")
        if name:
            fields.append({"name": name, "type": typ})
    return {"fields": fields}


def download_sko_geojson(type_name: str) -> dict[str, Any]:
    payload = http_json(
        JVB_OPEN_WFS,
        {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeNames": type_name,
            "outputFormat": "application/json",
            "srsName": "EPSG:3006",
            "count": 1000,
        },
        timeout=180,
    )
    if payload.get("type") != "FeatureCollection":
        raise RuntimeError("Unexpected WFS response for SKO: " + str(payload)[:500])
    return payload


def choose_sko_id_field(features: list[dict[str, Any]], describe: dict[str, Any]) -> str | None:
    field_names = [str(row.get("name") or "") for row in describe.get("fields") or []]
    property_names: list[str] = []
    for feature in features[:25]:
        property_names.extend((feature.get("properties") or {}).keys())
    names = list(dict.fromkeys(field_names + property_names))
    ranked = []
    for name in names:
        lowered = name.lower()
        score = 0
        if lowered in {"sko", "sko_id", "skoid", "skordeomrade", "skördeområde"}:
            score += 100
        if "sko" in lowered:
            score += 50
        if "skord" in lowered or "skörd" in lowered:
            score += 30
        if lowered.endswith("id") or "kod" in lowered:
            score += 10
        if score:
            ranked.append((score, name))
    ranked.sort(key=lambda pair: (-pair[0], pair[1]))
    return ranked[0][1] if ranked else None


def raw_sko_ids(features: list[dict[str, Any]], field: str | None) -> list[str]:
    if not field:
        return []
    return [text_id((feature.get("properties") or {}).get(field)) for feature in features]


def leading_zero_evidence(values: Iterable[str]) -> dict[str, Any]:
    vals = [str(v) for v in values if str(v) != ""]
    return {
        "count": len(vals),
        "unique_count": len(set(vals)),
        "has_leading_zero": any(len(v) > 1 and v.startswith("0") for v in vals),
        "sample": vals[:20],
    }


def discover_candidate_files(roots: Iterable[Path], pattern: re.Pattern[str], max_files: int = 200) -> list[str]:
    matches: list[str] = []
    seen: set[str] = set()
    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        try:
            iterator = root.rglob("*")
            for path in iterator:
                if len(matches) >= max_files:
                    return matches
                if not path.is_file() or path.suffix.lower() not in GEODATA_SUFFIXES:
                    continue
                if pattern.search(path.name):
                    resolved = str(path.resolve())
                    if resolved not in seen:
                        seen.add(resolved)
                        matches.append(resolved)
        except (OSError, PermissionError):
            continue
    return matches


def path_roots(project_config: dict[str, Any], akerminne_local: dict[str, Any], root: Path) -> list[Path]:
    values: list[Path] = []
    raw_root = akerminne_local.get("raw_root")
    if raw_root:
        values.append(Path(raw_root))
    for key in ("blocks", "skiften", "soil_zip", "dem_dir"):
        value = project_config.get(key)
        if value:
            p = Path(value)
            values.append(p if p.is_dir() else p.parent)
    build_dir = Path(project_config.get("build_dir", "data/derived"))
    if not build_dir.is_absolute():
        build_dir = root / build_dir
    values.extend([build_dir, root / "data"])
    result: list[Path] = []
    seen: set[str] = set()
    for path in values:
        key = os.path.normcase(str(path))
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result


def geometry_schema(gdf: Any) -> dict[str, Any]:
    crs = None
    try:
        crs = gdf.crs.to_string() if gdf.crs is not None else None
    except Exception:
        crs = str(gdf.crs) if getattr(gdf, "crs", None) else None
    geom_types = Counter(str(v) for v in gdf.geometry.geom_type.dropna().tolist())
    invalid = int((~gdf.geometry.is_valid & gdf.geometry.notna() & ~gdf.geometry.is_empty).sum())
    empty = int((gdf.geometry.isna() | gdf.geometry.is_empty).sum())
    return {
        "feature_count": int(len(gdf)),
        "crs": crs,
        "geometry_types": dict(sorted(geom_types.items())),
        "invalid_geometry_count": invalid,
        "empty_geometry_count": empty,
        "columns": [
            {"name": str(name), "dtype": str(dtype)}
            for name, dtype in zip(gdf.columns, gdf.dtypes)
        ],
    }


def overlap_summary(gdf: Any, class_field: str | None = None, max_examples: int = 20) -> dict[str, Any]:
    # Discovery-only source QA. Raw source is never modified.
    work = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].reset_index(drop=True)
    try:
        sindex = work.sindex
    except Exception:
        return {"status": "WARN_NO_SPATIAL_INDEX", "pair_count": None, "examples": []}
    overlap_area = 0.0
    pairs = 0
    examples = []
    for i, geom in enumerate(work.geometry):
        try:
            candidates = list(sindex.query(geom, predicate="intersects"))
        except Exception:
            candidates = list(sindex.query(geom))
        for j in candidates:
            j = int(j)
            if j <= i:
                continue
            other = work.geometry.iloc[j]
            try:
                inter = geom.intersection(other)
                area = float(inter.area) if not inter.is_empty else 0.0
            except Exception:
                continue
            if area <= 1e-6:
                continue
            pairs += 1
            overlap_area += area
            if len(examples) < max_examples:
                row = {"left_index": i, "right_index": j, "overlap_area_m2": area}
                if class_field and class_field in work.columns:
                    row["left_class"] = text_id(work.iloc[i][class_field])
                    row["right_class"] = text_id(work.iloc[j][class_field])
                examples.append(row)
    return {
        "status": "OK",
        "pair_count": pairs,
        "total_pairwise_overlap_area_m2": overlap_area,
        "examples": examples,
    }


def class_area_summary(classes: Any, field: str = "KLASS") -> list[dict[str, Any]]:
    work = classes.copy()
    work[field] = work[field].map(lambda v: int(float(v)) if str(v).strip() not in {"", "None", "nan"} else None)
    rows = []
    for value, group in work.groupby(field, dropna=False):
        rows.append({
            "class_raw": value,
            "feature_count": int(len(group)),
            "raw_polygon_area_m2": float(group.geometry.area.sum()),
        })
    return rows


def source_coverage_against_fields(fields: Any, reference: Any) -> dict[str, Any]:
    if fields.empty or reference.empty:
        return {"status": "NOT_COMPUTED_EMPTY_INPUT"}
    f = fields.to_crs(3006) if getattr(fields, "crs", None) is not None else fields
    r = reference.to_crs(3006) if getattr(reference, "crs", None) is not None else reference
    valid_f = f[f.geometry.notna() & ~f.geometry.is_empty].copy()
    valid_r = r[r.geometry.notna() & ~r.geometry.is_empty].copy()
    if valid_f.empty or valid_r.empty:
        return {"status": "NOT_COMPUTED_EMPTY_GEOMETRY"}
    union = valid_r.geometry.union_all() if hasattr(valid_r.geometry, "union_all") else valid_r.geometry.unary_union
    field_area = float(valid_f.geometry.area.sum())
    intersections = valid_f.geometry.intersection(union)
    intersection_area = float(intersections.area.sum())
    return {
        "status": "OK",
        "total_field_area_m2": field_area,
        "intersection_area_m2": intersection_area,
        "coverage_raw": (intersection_area / field_area) if field_area else None,
    }
