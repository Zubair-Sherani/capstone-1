import json
import re
from pathlib import Path
from typing import List, Tuple

from services.dedup import NormalizedSheet
from services.normalizer import NormalizedCensusSheet, NormalizedHouseholdFormSheet

PAGE_FILE_RE = re.compile(r"^page_(\d{4})\.json$")


def discover_pages(output_dir: Path) -> List[Tuple[int, Path, Path]]:
    pages = []
    for path in output_dir.iterdir():
        match = PAGE_FILE_RE.match(path.name)
        if not match:
            continue
        page_number = int(match.group(1))
        normalized_path = output_dir / f"page_{page_number:04}.normalized.json"
        if normalized_path.exists():
            pages.append((page_number, path, normalized_path))
    return sorted(pages)


def load_sheet(page_number: int, output_dir: Path) -> NormalizedSheet:
    json_path = output_dir / f"page_{page_number:04}.json"
    normalized_path = output_dir / f"page_{page_number:04}.normalized.json"

    doc_type = json.loads(json_path.read_text())["document_type"]
    data = json.loads(normalized_path.read_text())

    if doc_type == "CENSUS_SHEET":
        return NormalizedCensusSheet.model_validate(data)
    if doc_type == "HOUSEHOLD_FORM":
        return NormalizedHouseholdFormSheet.model_validate(data)
    raise ValueError(f"page {page_number} has unsupported document_type={doc_type!r}")


def save_sheet(sheet: NormalizedSheet, output_dir: Path) -> None:
    out_path = output_dir / f"page_{sheet.page_number:04}.normalized.json"
    with open(out_path, "w") as f:
        json.dump(sheet.model_dump(), f, indent=2)
