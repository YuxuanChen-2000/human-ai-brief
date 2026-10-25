"""Fetch actual scholarly records from the OpenAlex API. Standard library only.

Fail closed: keep the previous dataset if any topic fails or pagination
truncates. Publication dates are stored verbatim; nothing is fabricated.
OpenAlex is the free substitute for the mixed WoS / ACM DL / Scopus / IEEE
coverage the site targets; WoS/Scopus membership is approximated through the
curated venue list in config/topics.json and cannot be verified per record via
the free API.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.openalex.org/works"
MAILTO = "research@example.com"

# OpenAlex record types we keep as "papers". Everything else (books, chapters,
# datasets, editorials, letters, errata, ...) is dropped before classification.
ALLOWED_TYPES = {"article", "review", "preprint", "conference-paper"}


def searchable_text(value):
    """Normalize for matching: lowercase, hyphens/dashes become spaces."""
    return re.sub(r"\s+", " ", re.sub(r"[-–—‑−]", " ", (value or "").lower())).strip()


def term_present(term, text):
    term = searchable_text(term)
    if not term:
        return False
    pattern = re.escape(term.rstrip("*")) + (r"[a-z]*" if term.endswith("*") else "")
    return re.search(r"(?<![a-z0-9])" + pattern + r"(?![a-z0-9])", text) is not None


def normalize_doi(doi):
    return re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", (doi or "").strip(), flags=re.I).lower()


def clause(term):
    value = term.rstrip("*").strip()
    return '"' + value + '"'


def topic_query(topic):
    """Same vocabulary drives the upstream search and the local classifier."""
    if topic.get("query"):
        return topic["query"]
    groups = topic.get("required_term_groups", [topic.get("evidence_terms", [])])
    focus = topic.get("require_focus_terms")
    if focus:
        groups = [*groups, focus]
    return " AND ".join(
        "(" + " OR ".join(clause(term) for term in group if term.strip()) + ")"
        for group in groups if group
    )


def venue_filter(venue):
    kind = venue.get("kind")
    if kind == "host":
        return "locations.source.host_organization:" + venue["host_organization"]
    if kind == "source":
        return "locations.source.id:" + venue["source_id"]
    if kind == "issn":
        issns = [i for i in (venue.get("issns") or [venue.get("issn")]) if i]
        return "locations.source.issn:" + "|".join(issns)
    raise ValueError("Unknown venue kind: " + repr(kind))


def paper_text(paper):
    return searchable_text(" ".join(
        [paper.get("title") or "", paper.get("abstract") or "", *[k or "" for k in paper.get("keywords", [])]]
    ))


def classify(paper, topics):
    text = paper_text(paper)
    evidence = {}
    for topic in topics:
        if any(term_present(term, text) for term in topic.get("exclude_terms", [])):
            continue
        focus = topic.get("require_focus_terms")
        if focus and not any(term_present(term, text) for term in focus):
            continue
        groups = topic.get("required_term_groups", [topic.get("evidence_terms", [])])
        if not groups:
            continue
        if all(any(term_present(term, text) for term in group) for group in groups):
            evidence[topic["id"]] = [
                term for term in topic.get("evidence_terms", []) if term_present(term, text)
            ]
    return {**paper, "topics": list(evidence), "evidence": evidence}


def classification_fingerprint(config):
    rules = {
        k: config.get(k)
        for k in ("topics", "coverage_start", "monitored_venues", "topic_allowed_groups", "classification_version")
    }
    return hashlib.sha256(
        json.dumps(rules, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def valid_date(value):
    try:
        return dt.date.fromisoformat(str(value)[:10]).isoformat()
    except (TypeError, ValueError):
        return None


def reconstruct_abstract(inverted):
    if not isinstance(inverted, dict) or not inverted:
        return None
    position = -1
    for indexes in inverted.values():
        if isinstance(indexes, list):
            for i in indexes:
                if isinstance(i, int):
                    position = max(position, i)
    if position < 0:
        return None
    words = [""] * (position + 1)
    for word, indexes in inverted.items():
        if isinstance(indexes, list):
            for i in indexes:
                if isinstance(i, int) and 0 <= i <= position:
                    words[i] = word
    return re.sub(r"\s+", " ", " ".join(words)).strip()


def request_json(params):
    from urllib.error import HTTPError
    retryable = {401, 403, 429, 500, 502, 503, 504}
    for attempt in range(6):
        try:
            req = Request(API + "?" + urlencode(params), headers={
                "User-Agent": "HumanAIBrief/0.1 (academic literature tracker; mailto:" + MAILTO + ")",
                "Accept": "application/json",
            })
            with urlopen(req, timeout=60) as response:
                data = json.load(response)
            if "meta" not in data or "results" not in data:
                raise ValueError("Unexpected OpenAlex response schema")
            return data
        except HTTPError as exc:
            if exc.code not in retryable or attempt == 5:
                raise
            time.sleep(3 * (attempt + 1))
        except Exception:
            if attempt == 5:
                raise
            time.sleep(2 ** (attempt + 1))


def chunk_windows(windows, max_days=7):
    """Split date windows into small chunks so broad queries never exceed the
    per-query candidate cap of page-based pagination."""
    out = []
    for begin, finish in windows:
        start = dt.date.fromisoformat(begin)
        end = dt.date.fromisoformat(finish)
        cur = start
        while cur <= end:
            chunk_end = min(end, cur + dt.timedelta(days=max_days - 1))
            out.append((cur.isoformat(), chunk_end.isoformat()))
            cur = chunk_end + dt.timedelta(days=1)
    return out


def fetch_rows(filter_value, start, end, windows, query_label):
    """Fetch all rows for a filter across date windows using page pagination."""
    rows = []
    for begin, finish in chunk_windows(windows):
        base = filter_value + ",from_publication_date:" + begin + ",to_publication_date:" + finish
        window_rows = []
        page = 1
        while True:
            params = {
                "filter": base,
                "per-page": "200",
                "page": str(page),
                "mailto": MAILTO,
            }
            key = os.environ.get("OPENALEX_API_KEY")
            if key:
                params["api_key"] = key
            data = request_json(params)
            batch = data["results"]
            window_rows.extend(batch)
            total = int(data["meta"].get("count") or 0)
            if not batch or len(window_rows) >= total:
                break
            if page >= 50:
                raise RuntimeError(
                    "Pagination limit exceeded for " + query_label
                    + " window " + begin + ".." + finish
                    + ": " + str(len(window_rows)) + "/" + str(total)
                    + "; old data preserved"
                )
            page += 1
            time.sleep(0.25)
        rows.extend(window_rows)
    return rows


def collection_plan(today, old, config):
    start = config["coverage_start"]
    stamp = old.get("updated_at")
    overlap = config.get("update_policy", {}).get("daily_overlap_days", 1)
    if not stamp:
        return {
            "mode": "initial-full",
            "change_start": start,
            "publication_windows": [(start, today.isoformat())],
            "weekly_review_through": None,
            "coverage_start": start,
        }
    try:
        last = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(
            dt.timezone(dt.timedelta(hours=8))
        ).date()
    except (TypeError, ValueError):
        last = today
    last = min(last, today)
    daily_start = max(start, (last - dt.timedelta(days=overlap)).isoformat())
    windows = [(daily_start, today.isoformat())]
    monday = today - dt.timedelta(days=today.weekday())
    previous_sunday = (monday - dt.timedelta(days=1)).isoformat()
    reviewed = old.get("weekly_review_through")
    weekly_due = (
        (today.weekday() == 0 or bool(reviewed and reviewed < previous_sunday))
        and reviewed != previous_sunday
    )
    if weekly_due and previous_sunday >= start:
        windows.append((max(start, (monday - dt.timedelta(days=7)).isoformat()), previous_sunday))
        reviewed = previous_sunday
    return {
        "mode": "daily-plus-previous-week" if len(windows) > 1 else "daily-incremental",
        "change_start": daily_start,
        "publication_windows": windows,
        "weekly_review_through": reviewed,
        "coverage_start": start,
    }


def source_of(row):
    source = (row.get("primary_location") or {}).get("source") or {}
    return source


def normalized_issn(value):
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def groups_for_issns(issns, venues):
    norm = {normalized_issn(i) for i in issns if i}
    groups = []
    for venue in venues:
        if venue.get("kind") != "issn":
            continue
        for i in (venue.get("issns") or [venue.get("issn")]):
            if i and normalized_issn(i) in norm:
                groups.append(venue.get("group"))
                break
    return sorted(set(groups))


def venue_groups_for(row, venues):
    source = source_of(row)
    if not source:
        return []
    host = (source.get("host_organization") or "").rstrip("/").split("/")[-1]
    source_id = (source.get("id") or "").rstrip("/").split("/")[-1]
    issns = set(source.get("issn") or [])
    if source.get("issn_l"):
        issns.add(source["issn_l"])
    groups = groups_for_issns(issns, venues)
    for venue in venues:
        kind = venue.get("kind")
        if kind == "host" and host and host == venue.get("host_organization"):
            groups.append(venue["group"])
        elif kind == "source" and source_id and source_id == venue.get("source_id"):
            groups.append(venue["group"])
    return sorted(set(groups))


def allowed_groups_for_topics(topic_ids, config):
    mapping = config.get("topic_allowed_groups", {})
    groups = set()
    for tid in topic_ids:
        groups.update(mapping.get(tid, []))
    return groups


def groups_for_paper(paper, venues):
    groups = groups_for_issns(paper.get("journal_issns") or [], venues)
    sid = paper.get("venue_source_id")
    if sid:
        for venue in venues:
            if venue.get("kind") == "source" and venue.get("source_id") == sid:
                groups.append(venue.get("group"))
                break
    return sorted(set(groups))


def paper_passes_journal_filter(paper, config):
    mapping = config.get("topic_allowed_groups")
    if not mapping:
        return True
    venues = config.get("monitored_venues", [])
    groups = set(groups_for_paper(paper, venues))
    if not groups:
        return False
    allowed = allowed_groups_for_topics(paper.get("topics", []), config)
    return bool(groups & allowed)


def source_filters_for_topic(topic_id, config, max_values=100):
    allowed = allowed_groups_for_topics([topic_id], config)
    issns = []
    sids = []
    seen_issn = set()
    seen_sid = set()
    for venue in config.get("monitored_venues", []):
        if venue.get("group") not in allowed:
            continue
        kind = venue.get("kind")
        if kind == "issn":
            for i in (venue.get("issns") or [venue.get("issn")]):
                n = normalized_issn(i)
                if i and n and n not in seen_issn:
                    seen_issn.add(n)
                    issns.append(i)
        elif kind == "source":
            sid = venue.get("source_id")
            if sid and sid not in seen_sid:
                seen_sid.add(sid)
                sids.append(sid)
    filters = []
    for pos in range(0, len(issns), max_values):
        chunk = issns[pos:pos + max_values]
        filters.append("locations.source.issn:" + "|".join(chunk))
    for pos in range(0, len(sids), max_values):
        chunk = sids[pos:pos + max_values]
        filters.append("locations.source.id:" + "|".join(chunk))
    return filters


def normalize(row, today, seen, venues):
    title = (row.get("title") or row.get("display_name") or "").strip()
    if not title:
        return None
    record_type = (row.get("type") or "").lower()
    if record_type not in ALLOWED_TYPES:
        return None
    published = valid_date(row.get("publication_date"))
    if published and published > today:
        return None
    doi = normalize_doi(row.get("doi"))
    source_id = (row.get("id") or "").rstrip("/").split("/")[-1]
    key = ("doi:" + doi) if doi else ("oa:" + source_id)
    aliases = [("oa:" + source_id) if source_id else None, ("doi:" + doi) if doi else None]
    aliases = [a for a in aliases if a]
    if any(a in seen for a in [key, *aliases]):
        return None
    seen.add(key)
    for a in aliases:
        seen.add(a)
    abstract = reconstruct_abstract(row.get("abstract_inverted_index"))
    authors = ", ".join(
        (a.get("author") or {}).get("display_name") or ""
        for a in (row.get("authorships") or [])
        if (a.get("author") or {}).get("display_name")
    )
    source = source_of(row)
    venue_type = source.get("type") if source else None
    issns = sorted(set(source.get("issn") or [])) if source else []
    venue_source_id = (source.get("id") or "").rstrip("/").split("/")[-1] if source else None
    keywords = [k.get("display_name") for k in (row.get("keywords") or []) if k.get("display_name")]
    type_crossref = row.get("type_crossref")
    is_preprint = (
        record_type == "preprint"
        or (type_crossref or "") == "posted-content"
        or (venue_type == "repository" if venue_type else False)
    )
    is_review = record_type == "review" or (type_crossref or "") == "review"
    landing = (row.get("primary_location") or {}).get("landing_page_url") or ""
    if not str(landing).startswith("https://"):
        landing = ""
    url = row.get("doi") or landing or row.get("id")
    source_url = row.get("id") or ""
    venue_groups = venue_groups_for(row, venues)
    return {
        "id": key,
        "doi": doi,
        "source": "openalex",
        "source_id": source_id,
        "record_aliases": aliases,
        "title": title,
        "authors": authors,
        "journal": (source.get("display_name") if source else None) or "来源未提供",
        "journal_issns": issns,
        "venue_source_id": venue_source_id,
        "venue_type": venue_type,
        "published": published,
        "publication_year": str(row.get("publication_year") or "") or None,
        "indexed": None,
        "abstract": abstract or "",
        "abstract_language": "original",
        "is_preprint": is_preprint,
        "keywords": keywords,
        "mesh_terms": [],
        "publication_types": [t for t in [record_type, type_crossref] if t],
        "is_review": is_review,
        "is_open_access": bool((row.get("open_access") or {}).get("is_oa")),
        "indexed_in": row.get("indexed_in") or [],
        "venue_groups": venue_groups,
        "is_monitored_venue": bool(venue_groups),
        "source_url": source_url,
        "url": url,
    }


def build_dataset(old, results, config, today, now):
    seen = set()
    items = []
    for source in old.get("papers", []):
        if source.get("id"):
            seen.add(source["id"])
            for alias in source.get("record_aliases", []):
                seen.add(alias)
    for rows in results:
        for row in rows:
            item = normalize(row, today, seen, config.get("monitored_venues", []))
            if item:
                item = classify(item, config["topics"])
                if item["topics"] and paper_passes_journal_filter(item, config):
                    item["first_seen"] = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(timespec="seconds")
                    items.append(item)
    # Merge with previous records so the archive keeps accumulating.
    by_id = {p["id"]: p for p in old.get("papers", [])}
    for p in items:
        by_id[p["id"]] = p
    merged = list(by_id.values())
    merged.sort(key=lambda p: (p.get("published") or "", p.get("id") or ""), reverse=True)
    start = config["coverage_start"]
    eligible = [p for p in merged if p.get("published") and start <= p["published"] <= today and paper_passes_journal_filter(p, config)]
    local_date = dt.datetime.fromisoformat(now.replace("Z", "+00:00")).astimezone(
        dt.timezone(dt.timedelta(hours=8))
    ).date().isoformat()

    def seen_day(p):
        return dt.datetime.fromisoformat(p["first_seen"].replace("Z", "+00:00")).astimezone(
            dt.timezone(dt.timedelta(hours=8))
        ).date().isoformat()

    old_aliases = {a for p in old.get("papers", []) for a in [p["id"], *p.get("record_aliases", [])]}
    new_in_run = sum(
        not ({p["id"], *p.get("record_aliases", [])} & old_aliases)
        for p in eligible
    )
    return {
        "schema_version": 1,
        "updated_at": now,
        "as_of": today,
        "classification_version": config.get("classification_version", "custom"),
        "classification_fingerprint": classification_fingerprint(config),
        "update_mode": "github-actions" if os.environ.get("GITHUB_ACTIONS") == "true" else "manual",
        "initial_coverage_start": start,
        "update_summary": {
            "date": local_date,
            "new_papers": sum(seen_day(p) == local_date for p in eligible),
            "new_in_run": new_in_run,
            "latest_publication": max((p["published"] for p in eligible), default=None),
        },
        "source": {
            "name": "OpenAlex",
            "url": "https://api.openalex.org/",
            "description": "OpenAlex 学术图谱；覆盖 ACM/IEEE/WoS/Scopus 主要期刊与会议，WoS/Scopus 收录身份按关注来源清单近似标记。",
        },
        "monitored_venues": config.get("monitored_venues", []),
        "venue_group_labels": config.get("venue_group_labels", {}),
        "update_status": "success",
        "topics": [
            {k: v for k, v in t.items() if k in ("id", "name", "short_name", "description")}
            for t in config["topics"]
        ],
        "queries": [],
        "papers": eligible,
    }


def reclassify_only(config, today):
    """Re-apply the current topic classifier AND the journal allowlist to every
    archived paper without refetching. Drops records that no longer belong to an
    allowed journal for their assigned topics; updates the fingerprint."""
    path = ROOT / "dist" / "data.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    kept = []
    for p in data["papers"]:
        rec = classify(p, config["topics"])
        p["topics"] = rec["topics"]
        p["evidence"] = rec["evidence"]
        if p["topics"] and paper_passes_journal_filter(p, config):
            kept.append(p)
    data["papers"] = kept
    venues = config.get("monitored_venues", [])
    for p in kept:
        p["venue_groups"] = groups_for_issns(p.get("journal_issns") or [], venues)
        p["is_monitored_venue"] = bool(p["venue_groups"])
    data["classification_version"] = config.get("classification_version", "custom")
    data["classification_fingerprint"] = classification_fingerprint(config)
    data["topics"] = [
        {k: v for k, v in t.items() if k in ("id", "name", "short_name", "description")}
        for t in config["topics"]
    ]
    data["monitored_venues"] = config.get("monitored_venues", [])
    data["venue_group_labels"] = config.get("venue_group_labels", {})
    data["queries"] = []
    for topic in config["topics"]:
        keyword = "title_and_abstract.search:" + topic_query(topic)
        source_filters = source_filters_for_topic(topic["id"], config)
        first_search = keyword + ("," + source_filters[0] if source_filters else "")
        data["queries"].append({
            "topic": topic["id"],
            "query": topic_query(topic),
            "candidate_count": sum(topic["id"] in x["topics"] for x in kept),
            "request_url": API + "?" + urlencode({"filter": first_search, "mailto": MAILTO}),
        })
    local_date = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat()

    def seen_day(p):
        return dt.datetime.fromisoformat(p["first_seen"].replace("Z", "+00:00")).astimezone(
            dt.timezone(dt.timedelta(hours=8))
        ).date().isoformat()

    data["update_summary"]["new_papers"] = sum(seen_day(p) == data["update_summary"]["date"] for p in data["papers"])
    data["update_summary"]["new_in_run"] = data["update_summary"]["new_papers"]
    ready = sum(bool(p.get("summary_zh")) for p in data["papers"])
    eligible = sum(bool(p.get("abstract", "").strip()) for p in data["papers"])
    mode = json.loads((ROOT / "config" / "summaries.json").read_text(encoding="utf-8")).get("mode", "automatic")
    old_status = data.get("summary_status") or {}
    data["summary_status"] = {
        "mode": mode,
        "ready": ready,
        "eligible": eligible,
        "pending": eligible - ready,
        "no_abstract": len(data["papers"]) - eligible,
        "held": 0,
        "errors": 0,
        "current_version": old_status.get("current_version"),
        "description": old_status.get("description", ""),
    }
    data["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    import os as _os
    _os.replace(temp, path)
    print(f"Refiltered {len(data['papers'])} unique papers; fingerprint updated.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", default=dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat())
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "data.json")
    parser.add_argument("--reclassify-only", action="store_true")
    args = parser.parse_args()
    today = dt.date.fromisoformat(args.as_of)
    config = json.loads((ROOT / "config" / "topics.json").read_text(encoding="utf-8"))
    if args.reclassify_only:
        reclassify_only(config, today)
        return
    old = json.loads(args.output.read_text(encoding="utf-8")) if args.output.exists() else {}
    plan = collection_plan(today, old, config)
    windows = plan["publication_windows"]
    start = config["coverage_start"]
    results = []
    queries = []
    for topic in config["topics"]:
        label = "topic:" + topic["id"]
        keyword = "title_and_abstract.search:" + topic_query(topic)
        source_filters = source_filters_for_topic(topic["id"], config)
        rows = []
        for src_filter in source_filters:
            search = keyword + ("," + src_filter if src_filter else "")
            rows.extend(fetch_rows(search, start, today.isoformat(), windows, label))
        print(f"{topic['id']}: {len(rows)} candidates", flush=True)
        results.append(rows)
        first_search = keyword + ("," + source_filters[0] if source_filters else "")
        queries.append({
            "topic": topic["id"],
            "query": topic_query(topic),
            "candidate_count": len(rows),
            "request_url": API + "?" + urlencode({"filter": first_search, "mailto": MAILTO}),
        })
        time.sleep(0.4)
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    dataset = build_dataset(old, results, config, today.isoformat(), now)
    dataset["queries"] = queries
    dataset["scan_mode"] = plan["mode"]
    dataset["collection_plan"] = plan
    dataset["weekly_review_through"] = plan["weekly_review_through"]
    for report in dataset["queries"]:
        if report["topic"].startswith("topic:"):
            tid = report["topic"].split(":", 1)[1]
            report["retained_topic_count"] = sum(tid in p["topics"] for p in dataset["papers"])
    if not dataset["papers"]:
        raise RuntimeError("No records returned; refusing to replace the last successful dataset")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(".json.tmp")
    temp.write_text(json.dumps(dataset, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    os.replace(temp, args.output)
    print(f"Saved {len(dataset['papers'])} unique papers to {args.output}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Update failed; previous data retained: {exc}", file=sys.stderr)
        sys.exit(1)







