"""Check delivered static assets and data integrity; no external dependencies."""
import json
import gzip
import importlib.util
from pathlib import Path
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[1]
for name in ["index.html", "styles.css", "app.js", "favicon.svg", "brain-mark.svg", "data.json"]:
    assert (root / "dist" / name).is_file(), "Missing " + name
data = json.loads((root / "dist" / "data.json").read_text(encoding="utf-8"))
summary_settings = json.loads((root / "config" / "summaries.json").read_text(encoding="utf-8"))
config = json.loads((root / "config" / "topics.json").read_text(encoding="utf-8"))
assert gzip.decompress((root / "dist" / "data.json.gz").read_bytes()) == (root / "dist" / "data.json").read_bytes(), "Compressed dataset differs from archive"
assert data["schema_version"] == 1
assert data["update_status"] == "success"
assert data["papers"], "Empty paper dataset"
assert len({p["id"] for p in data["papers"]}) == len(data["papers"]), "Duplicate IDs"
topic_ids = {t["id"] for t in data["topics"]}
assert topic_ids == {t["id"] for t in config["topics"]}, "Dataset taxonomy is out of date"
spec = importlib.util.spec_from_file_location("updater", root / "scripts" / "update_papers.py")
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)
assert data.get("classification_fingerprint") == updater.classification_fingerprint(config), "Run collection after changing topic rules"
assert data["initial_coverage_start"] == config["coverage_start"]
venue_count = len(config.get("monitored_venues", []))
assert len(data["queries"]) == len(config["topics"]) + venue_count, "Missing venue safety sweep"
assert data["scan_mode"] in ("initial-full", "daily-incremental", "daily-plus-previous-week")
allowed_venue_groups = set(config.get("venue_group_labels", {}))
for report in data["queries"]:
    if report["topic"].startswith("topic:"):
        tid = report["topic"].split(":", 1)[1]
        assert tid in topic_ids, "Unknown topic query"
seen_day = lambda p: updater.dt.datetime.fromisoformat(p["first_seen"].replace("Z", "+00:00")).astimezone(updater.dt.timezone(updater.dt.timedelta(hours=8))).date().isoformat()
assert data["update_summary"]["new_papers"] == sum(seen_day(p) == data["update_summary"]["date"] for p in data["papers"])
html = (root / "dist" / "index.html").read_text(encoding="utf-8")
for topic_id in topic_ids:
    assert f'data-view="{topic_id}"' in html, "Missing topic navigation: " + topic_id
for filename in ["feed.xml", *["feed-" + t + ".xml" for t in topic_ids]]:
    feed = ET.parse(root / "dist" / filename).getroot()
    assert feed.findtext("channel/title")
    assert len(feed.findall("channel/item")) <= 50
for p in data["papers"]:
    assert p["title"] and p["first_seen"]
    assert set(p["topics"]) <= topic_ids and p["topics"]
    assert not p["published"] or p["published"] <= data["as_of"]
    assert p["published"] and p["published"] >= config["coverage_start"]
    assert set(p.get("venue_groups", [])) <= allowed_venue_groups
    assert p["topics"] == updater.classify(p, config["topics"])["topics"], "Paper classification is out of date"
    assert urlparse(p["url"]).scheme == "https"
    assert urlparse(p["source_url"]).netloc == "openalex.org"
    assert "<script" not in (p.get("abstract") or "").lower()
    if p.get("summary_zh"):
        assert p["summary_zh"].strip() and p.get("summary_meta", {}).get("source_hash")
        expected = updater.hashlib.sha256((p["title"] + "\n" + p["abstract"]).encode()).hexdigest()
        assert p["summary_meta"]["source_hash"] == expected, "Summary does not match the current abstract"
        assert p["summary_meta"]["prompt_version"] in summary_settings.get("accepted_prompt_versions", [summary_settings["prompt_version"]])
assert data["summary_status"]["mode"] == "automatic"
assert data["summary_status"]["ready"] == sum(bool(p.get("summary_zh")) for p in data["papers"])
assert data["summary_status"]["eligible"] == sum(bool(p.get("abstract", "").strip()) for p in data["papers"])
assert data["summary_status"]["no_abstract"] + data["summary_status"]["eligible"] == len(data["papers"])
for path in [*root.joinpath("dist").glob("*"), *root.joinpath("config").glob("*.json"), *root.joinpath("data").glob("*.json")]:
    if path.is_file() and path.suffix != ".gz":
        assert not updater.re.search(r"sk-[a-zA-Z0-9]{24,}", path.read_text(encoding="utf-8")), "Credential-like text in public files"
print(f"Validated {len(data['papers'])} real literature records, automatic Chinese overviews and static assets.")
for t in data["topics"]:
    print(f"{t['id']}: {sum(t['id'] in p['topics'] for p in data['papers'])}")
