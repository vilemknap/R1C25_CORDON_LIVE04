"""Read-only, evidence-only SDP route incidence over the 15A2 two-mode SQLite store.

No Visum COM calls, network mutations, OD writes, calibration targets or optimization.
Two competing station-pair meanings are intentionally emitted as diagnostics.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sqlite3
import struct
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import quote

CATEGORIES = ("OA", "LNA", "STNA", "TNA", "BUS")
METHODS = ("ALL_ORDERED_UNIQUE_PAIRS", "EXACT_TWO_HITS")
REQUIRED_TABLES = ("metadata", "geometry", "volumes", "edges", "segments")


class EvidenceError(RuntimeError):
    pass


def read_rows(path):
    with open(path, encoding="utf-8-sig", newline="") as stream:
        text = stream.read(8192)
        stream.seek(0)
        sep = ";" if text.count(";") >= text.count(",") else ","
        return list(csv.DictReader(stream, delimiter=sep))


def write_rows(path, rows, columns):
    with open(path, "w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, delimiter=";", extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def station_mapping(path, *, expected_station_count=16):
    rows = read_rows(path)
    index = {}
    station_edge_counts = Counter()
    for row in rows:
        try:
            station = int(row["station_id"])
            edge = tuple(int(row[field]) for field in ("link_no", "from_node_no", "to_node_no"))
        except (ValueError, KeyError) as err:
            raise EvidenceError("INVALID_STATION_MAPPING") from err
        if station < 1 or station > expected_station_count:
            raise EvidenceError("STATION_ID_OUTSIDE_APPROVED_RANGE")
        if edge in index and index[edge] != station:
            raise EvidenceError("DIRECTIONAL_EDGE_MAPPED_TO_TWO_STATIONS")
        if edge not in index:
            index[edge] = station
            station_edge_counts[station] += 1
    if set(station_edge_counts) != set(range(1, expected_station_count + 1)):
        raise EvidenceError("MISSING_STATION_MAPPING")
    if any(n != 2 for n in station_edge_counts.values()):
        raise EvidenceError("STATION_DOES_NOT_HAVE_EXACTLY_TWO_DIRECTIONAL_EDGES")
    return index


def observations(path, *, category="OA", expected_station_count=16):
    out = {}
    coverage = Counter()
    for row in read_rows(path):
        if row.get("category", "").upper() != category.upper():
            continue
        if row.get("trip_type", "").upper() != "ALL" or row.get("level", "").upper() != "RPDI":
            continue
        try:
            o, d = int(row["origin_station_id"]), int(row["destination_station_id"])
            v = float(row["rpdi_value"])
        except (ValueError, KeyError) as err:
            raise EvidenceError("INVALID_SURVEY_OBSERVATION") from err
        if not math.isfinite(v) or v < 0 or not (1 <= o <= expected_station_count and 1 <= d <= expected_station_count):
            raise EvidenceError("INVALID_SURVEY_QUANTITY_OR_STATION")
        if (o,d) in out:
            raise EvidenceError("DUPLICATE_STATION_PAIR_TARGET")
        out[o,d] = v
        coverage["all"] += 1
        if o != d:
            coverage["offdiag"] += 1
    if coverage["all"] != expected_station_count**2:
        raise EvidenceError("INCOMPLETE_FULL_SDP_TARGET_MATRIX")
    return out


def c17_budgets(path, *, category="OA", expected_station_count=16):
    out = {}
    for r in read_rows(path):
        if r.get("category", "").upper() != category.upper():
            continue
        name=r.get("station", "")
        if not name.startswith("SDP"):
            raise EvidenceError("INVALID_C17_STATION_NAME")
        station=int(name[3:])
        if station in out:
            raise EvidenceError("DUPLICATE_C17_STATION")
        left=float(r["D3_RPDI_station_to_C17"])
        right=float(r["D3_RPDI_C17_to_station"])
        if not (math.isfinite(left) and math.isfinite(right) and left >= 0 and right >= 0):
            raise EvidenceError("INVALID_C17_MARGIN")
        if abs(left-right)>1e-6:
            raise EvidenceError("EXPECTED_SYMMETRIC_D3_C17_MARGIN")
        out[station]=left
    if set(out)!=set(range(1,expected_station_count+1)):
        raise EvidenceError("INCOMPLETE_C17_STATION_BUDGET")
    return out


def extract_pairs(hits):
    """Return both historical candidate semantics without approving either."""
    ordered=[]
    seen=set()
    for sid in hits:
        if sid not in seen:
            ordered.append(sid)
            seen.add(sid)
    repeated=len(hits)!=len(ordered)
    candidates={method:set() for method in METHODS}
    if repeated:
        return candidates, True
    candidates["ALL_ORDERED_UNIQUE_PAIRS"]={
        (a,b) for ix,a in enumerate(ordered) for b in ordered[ix+1:] if a!=b
    }
    if len(hits)==2 and hits[0]!=hits[1]:
        candidates["EXACT_TWO_HITS"].add((hits[0],hits[1]))
    return candidates, False


def _read_only_sqlite(path):
    p=Path(path).resolve()
    if not p.is_file():
        raise EvidenceError("MISSING_FROZEN_15A2_SQLITE_STORE")
    uri="file:%s?mode=ro" % quote(str(p),safe="/:\\")
    connection=sqlite3.connect(uri, uri=True)
    connection.execute("PRAGMA query_only=ON")
    return connection


def route_diagnostic(db_path, link_map, *, selected_dsegs=None, max_geometry_routes=0):
    """Read ordered source BLOBs and independently stored segment volumes, no COM export.

    This is a diagnostic, not an approved calibration incidence operator.
    Streaming SQL ordering keeps memory proportional to one route and 16x16 counts.
    """
    if not selected_dsegs:
        raise EvidenceError("EXPLICIT_DSEG_SCOPE_REQUIRED")
    if any(not (isinstance(s,str) and s and (s.startswith("NATIVE_") or s.startswith("EXOG_EE_"))) for s in selected_dsegs):
        raise EvidenceError("UNVERIFIED_VEHICLE_CATEGORY_SCOPE")
    if len(set(selected_dsegs))!=len(selected_dsegs):
        raise EvidenceError("DUPLICATE_DSEG_SCOPE")
    db=_read_only_sqlite(db_path)
    counts={method:defaultdict(float) for method in METHODS}
    raw_hits=Counter()
    status=Counter()
    by_dseg=defaultdict(lambda:defaultdict(float))
    try:
        tables={v[0] for v in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not set(REQUIRED_TABLES).issubset(tables):
            raise EvidenceError("NOT_A_TWO_MODE_15A2_SQLITE_STORE")
        meta=dict(db.execute("SELECT key,value FROM metadata"))
        if not str(meta.get("geometry_identity", "")).startswith(("PROVISIONAL", "VERIFIED", "PROVEN", "FULL")):
            raise EvidenceError("UNKNOWN_GEOMETRY_STATUS")
        edge_lookup={int(eid):(int(ln),int(fr),int(to)) for eid,ln,fr,to in db.execute(
            "SELECT eid,link_no,from_no,to_no FROM edges")}
        missing_mapping=sorted(set(link_map)-set(edge_lookup.values()))
        if missing_mapping:
            raise EvidenceError("MAPPING_EDGES_MISSING_FROM_15A2_CACHE:%s" % missing_mapping[:3])
        inventory={r[0] for r in db.execute("SELECT dseg FROM segments")}
        missing_dsegs=set(selected_dsegs)-inventory
        if missing_dsegs:
            raise EvidenceError("REQUESTED_DSEG_NOT_IN_CACHE:%s" % sorted(missing_dsegs))
        marks=",".join("?" for _ in selected_dsegs)
        query=("SELECT g.gid,g.edge_ids,g.edge_count,g.sequence_sha256,v.dseg,v.volume "
          "FROM geometry g JOIN volumes v ON v.gid=g.gid "
          "WHERE v.dseg IN ("+marks+") ORDER BY g.gid,v.dseg")
        cursor=db.execute(query,tuple(selected_dsegs))
        previous_gid=None
        grouped=[]
        geometry_count=0
        def flush_group(entries):
            nonlocal geometry_count
            if not entries:
                return
            gid,blob,edge_count,sha,_,_=entries[0]
            geometry_count+=1
            if blob is None or edge_count is None or len(blob)%4 or len(blob)//4 != int(edge_count):
                raise EvidenceError("INVALID_OR_INCOMPLETE_GEOMETRY:%s" % gid)
            if sha and hashlib.sha256(blob).hexdigest() != sha:
                raise EvidenceError("GEOMETRY_BLOB_HASH_MISMATCH:%s" % gid)
            eids=struct.unpack("<%dI" % (len(blob)//4),blob) if blob else ()
            try:station_hits=[link_map[edge_lookup[x]] for x in eids if edge_lookup[x] in link_map]
            except KeyError as err:raise EvidenceError("GEOMETRY_EDGE_DICTIONARY_MISSING") from err
            stat,repeat=extract_pairs(station_hits)
            status["route_groups"]+=1
            if not eids:status["zero_link_route_groups"]+=1
            if not station_hits:status["routes_without_sdp"]+=1
            if repeat:status["repeated_station_route_groups_excluded"]+=1
            if len(station_hits)>2:status["routes_with_more_than_two_hits"]+=1
            for _,_,_,_,dseg,vol in entries:
                vol=float(vol)
                if not math.isfinite(vol) or vol<0:
                    raise EvidenceError("INVALID_SAVED_PATH_VOLUME")
                if vol<=0:continue
                status["positive_segment_routes"]+=1
                status["positive_volume"]+=vol
                if repeat:status["repeated_station_positive_volume_excluded"]+=vol
                for method,pairs in stat.items():
                    for pair in pairs:
                        counts[method][pair]+=vol
                        by_dseg[(method,dseg)][pair]+=vol
            for sid in station_hits:
                raw_hits[sid]+=1
        for row in cursor:
            gid=row[0]
            if previous_gid is not None and gid != previous_gid:
                flush_group(grouped)
                grouped=[]
                if max_geometry_routes and geometry_count>=max_geometry_routes:
                    status["truncated_by_max_geometry_routes"]+=1
                    break
            grouped.append(row)
            previous_gid=gid
        else:
            flush_group(grouped)
        result={
            "metadata":{"schema":meta.get("schema"),"parent_hash":meta.get("parent_hash"),
                        "geometry_identity":meta.get("geometry_identity"),"apply_permitted":meta.get("apply_permitted")},
            "metrics":dict(status),"station_hits":dict(sorted(raw_hits.items())),
            "counts":{m:{"%d>%d" % key:val for key,val in sorted(rows.items())} for m,rows in counts.items()},
            "ds_counts":{(m+":"+dseg):{"%d>%d" % p:v for p,v in sorted(group.items())}
                        for (m,dseg),group in sorted(by_dseg.items())},
            "complete":not bool(status.get("truncated_by_max_geometry_routes")),
            "dsegs":list(selected_dsegs),
        }
        return result
    finally:
        db.close()


def static_preflight(mapping, targets, budget_csv, category="OA", expected_station_count=16):
    idx=station_mapping(mapping,expected_station_count=expected_station_count)
    obs=observations(targets,category=category,expected_station_count=expected_station_count)
    c17=c17_budgets(budget_csv,category=category,expected_station_count=expected_station_count)
    return {"status":"STATIC_INPUT_PASS_DIAGNOSTIC_ONLY", "category":category,
      "mapped_station_count":expected_station_count,"mapped_directed_edges":len(idx),
      "target_offdiag_pairs":sum(o!=d for o,d in obs),
      "target_offdiag_sum":sum(v for (o,d),v in obs.items() if o!=d),
      "c17_symmetric_one_margin":sum(c17.values()),
      "unknown_pair_tolerance":"NOT_ALLOCATED_AS_INDEPENDENT_PAIR_INTERVALS",
      "survey_year":2026,"model_year":2025,"year_alignment_approved":False,
      "orientation_approved":False,"station_pair_semantics_approved":False,
      "allowed_to_calibrate":False,"allowed_to_modify_visum":False}


def build_baseline_rows(survey, path_results):
    out={}
    for method in METHODS:
        predicted=path_results['counts'][method]
        rows=[]
        for (o,d),value in sorted(survey.items()):
            if o==d:continue
            model=predicted.get("%d>%d" % (o,d),0.0)
            rows.append({"candidate_method":method,"matrix_row_station":o,
                "matrix_column_station":d,"observed_RPDI":value,"model_routes":model,
                "difference_model_minus_observed":model-value,
                "calibration_role":"DIAGNOSTIC_ONLY_NOT_YET_APPROVED"})
        out[method]=rows
    return out


def cli():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mapping',required=True)
    p.add_argument('--targets',required=True)
    p.add_argument('--c17-budget',required=True)
    p.add_argument('--output',required=True)
    p.add_argument('--category',default='OA',choices=CATEGORIES)
    p.add_argument('--route-store',default='')
    p.add_argument('--dseg',action='append',default=[])
    p.add_argument('--max-geometry-routes',type=int,default=0)
    args=p.parse_args()
    out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    preflight=static_preflight(args.mapping,args.targets,args.c17_budget,category=args.category)
    output={"preflight":preflight,"route_evidence":"NO_ROUTE_STORE_GIVEN"}
    if args.route_store:
        if args.category!='OA':raise EvidenceError("EXPLICIT_PERSONAL_CAR_DSEG_MAPPING_ONLY_FOR_OA")
        link_map=station_mapping(args.mapping)
        rout=route_diagnostic(args.route_store,link_map,selected_dsegs=args.dseg,max_geometry_routes=args.max_geometry_routes)
        output['route_evidence']={k:v for k,v in rout.items() if k not in ('counts','ds_counts')}
        t=observations(args.targets,category=args.category)
        compare=build_baseline_rows(t,rout)
        for method,rows in compare.items():
            write_rows(out/(method+'.csv'),rows,list(rows[0]))
        # Per-DSeg volumes are summary evidence, not yet accepted category mapping.
        with (out/'PAIR_VOLUMES_BY_DSEG.json').open('w',encoding='utf-8') as f:
            json.dump(rout['ds_counts'],f,sort_keys=True,indent=2)
    with (out/'00_READONLY_SUMMARY.json').open('w',encoding='utf-8') as f:
        json.dump(output,f,sort_keys=True,indent=2)
    print(json.dumps(output,sort_keys=True,indent=2))


if __name__=='__main__':
    cli()
