"""Download CMS DE-SynPUF sample files (inpatient claims + 3 beneficiary summary years).

Usage: uv run python scripts/download_synpuf.py [--sample 1]
Source page: https://www.cms.gov/data-research/statistics-trends-and-reports/medicare-claims-synthetic-public-use-files/cms-2008-2010-data-entrepreneurs-synthetic-public-use-file-de-synpuf
"""
import argparse
import urllib.request
import zipfile
from pathlib import Path

BASE = "https://www.cms.gov/research-statistics-data-and-systems/downloadable-public-use-files/synpufs/downloads/"
# CMS quirk (checked 2026-10-16): the 2010 beneficiary link for Sample 1 points to a file named
# "..._sample_20.zip" under a different path, but the zip contains the Sample 1 CSV.
QUIRK_2010_S1 = ("https://www.cms.gov/research-statistics-data-and-systems/statistics-trends-and-reports/"
                 "synpufs/downloads/de1_0_2010_beneficiary_summary_file_sample_20.zip")


def urls(sample: int) -> list[str]:
    out = [f"{BASE}de1_0_2008_to_2010_inpatient_claims_sample_{sample}.zip"]
    for year in (2008, 2009, 2010):
        out.append(f"{BASE}de1_0_{year}_beneficiary_summary_file_sample_{sample}.zip")
    if sample == 1:
        out[-1] = QUIRK_2010_S1
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=1, choices=range(1, 21))
    ap.add_argument("--out", default="data/raw")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for url in urls(a.sample):
        dest = out / url.rsplit("/", 1)[1]
        if not dest.exists():
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req) as r, open(dest, "wb") as f:
                f.write(r.read())
        if not zipfile.is_zipfile(dest):
            dest.unlink()
            raise SystemExit(f"Not a zip (CMS link may have moved): {url}")
        with zipfile.ZipFile(dest) as z:
            z.extractall(out)
        print("ok", dest.name)


if __name__ == "__main__":
    main()
