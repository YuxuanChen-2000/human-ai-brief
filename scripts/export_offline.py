"""Produce a self-contained, double-clickable HTML snapshot and clean source zip."""
import argparse
import base64
import json
import re
from pathlib import Path
import shutil
import zipfile

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
html = (root / "dist" / "index.html").read_text(encoding="utf-8")
css = (root / "dist" / "styles.css").read_text(encoding="utf-8")
js = (root / "dist" / "app.js").read_text(encoding="utf-8")
data = json.loads((root / "dist" / "data.json").read_text(encoding="utf-8"))
embedded = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
html = html.replace('<link rel="stylesheet" href="./styles.css">', '<style>' + css + '</style>')
html = html.replace('<link rel="icon" href="./favicon.svg" type="image/svg+xml">', '<link rel="icon" href="data:,">')
if (root / "dist" / "brain-mark.svg").exists():
    brain = base64.b64encode((root / "dist" / "brain-mark.svg").read_bytes()).decode()
    html = html.replace('src="./brain-mark.svg"', 'src="data:image/svg+xml;base64,' + brain + '"')
html = html.replace('<script defer src="./app.js"></script>', '')
html = html.replace('</body>', '<script type="application/json" id="snapshot-data">' + embedded + '</script><script>' + js.replace('</script', '<\\/script') + '</script></body>')
offline = args.output / "HumanAIBrief-离线文献站.html"
offline.write_text(html, encoding="utf-8")
shutil.copyfile(root / "README.md", args.output / "HumanAIBrief-使用与部署说明.md")
archive = args.output / "HumanAIBrief-网站源码.zip"
with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
    for rel in ["dist", "config", "scripts", "tests", "data", ".github"]:
        for p in (root / rel).rglob("*"):
            if p.is_file() and "__pycache__" not in p.parts and p.suffix not in (".pyc", ".tmp"):
                z.write(p, p.relative_to(root))
    for rel in ["README.md", ".gitignore"]:
        z.write(root / rel, rel)
print(json.dumps({"offline": str(offline), "source_zip": str(archive), "papers": len(data["papers"])}, ensure_ascii=False))
stored = offline.read_text(encoding="utf-8")
roundtrip = json.loads(re.search(r'<script type="application/json" id="snapshot-data">(.*?)</script>', stored, re.S).group(1))
assert len(roundtrip["papers"]) == len(data["papers"])
assert 'src="./app.js"' not in stored and 'href="./styles.css"' not in stored
with zipfile.ZipFile(archive) as check:
    assert ".github/workflows/daily-update.yml" in check.namelist()
    assert not any(n.startswith((".git/", ".openai/")) for n in check.namelist())
print("Offline dataset and portable source archive verified.")

