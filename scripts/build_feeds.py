"""Build RSS from the same public dataset, without fetching or model calls."""
import datetime as dt
from email.utils import format_datetime
import json
from pathlib import Path
from urllib.parse import urlencode
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
ATOM = "http://www.w3.org/2005/Atom"
ET.register_namespace("atom", ATOM)


def make_feed(data, site, topic=None):
    title = site["name"] + (" · " + topic["name"] if topic else " · 最新文献")
    filename = "feed-" + topic["id"] + ".xml" if topic else "feed.xml"
    root = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(root, "channel")
    values = {"title": title, "link": site["url"] + ("?" + urlencode({"topic": topic["id"]}) if topic else ""),
              "description": topic["description"] if topic else site["description"], "language": "zh-CN",
              "lastBuildDate": format_datetime(dt.datetime.fromisoformat(data["updated_at"])), "ttl": "1440"}
    for key, value in values.items():
        ET.SubElement(channel, key).text = value
    ET.SubElement(channel, "{" + ATOM + "}link", {"href": site["url"] + filename, "rel": "self", "type": "application/rss+xml"})
    papers = [p for p in data["papers"] if not topic or topic["id"] in p["topics"]]
    for paper in papers[:50]:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = paper["title"]
        ET.SubElement(item, "link").text = paper["url"]
        ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = paper["id"]
        ET.SubElement(item, "description").text = ("[预印本] " if paper["is_preprint"] else "") + paper["journal"] + "\n\n" + (paper["abstract"] or "来源未提供摘要。")
        if paper.get("published"):
            ET.SubElement(item, "pubDate").text = format_datetime(dt.datetime.fromisoformat(paper["published"]).replace(tzinfo=dt.timezone.utc))
        for name in paper["topics"]:
            ET.SubElement(item, "category").text = next(t["name"] for t in data["topics"] if t["id"] == name)
    return filename, ET.tostring(root, encoding="utf-8", xml_declaration=True)


def main():
    data = json.loads((ROOT / "dist" / "data.json").read_text(encoding="utf-8"))
    site = json.loads((ROOT / "config" / "site.json").read_text(encoding="utf-8"))
    for topic in [None, *data["topics"]]:
        name, payload = make_feed(data, site, topic)
        (ROOT / "dist" / name).write_bytes(payload)
    print("Built main RSS and four topic feeds.")


if __name__ == "__main__":
    main()

