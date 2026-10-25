"""Precompress the public archive for static hosts without server configuration."""
import gzip
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
payload = (ROOT / "dist" / "data.json").read_bytes()
(ROOT / "dist" / "data.json.gz").write_bytes(gzip.compress(payload, mtime=0))
print("Built compressed public dataset.")
