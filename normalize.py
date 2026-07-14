import argparse
import json
import re
from pathlib import Path

from services.dedup import find_duplicates
from services.document_extractor import CensusSheetExtraction
from services.normalizer import normalize_sheet

PAGE_FILE_RE = re.compile(r"^page_(\d{4})\.json$")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Normalize extracted census sheet JSON, flag rows for review, and detect duplicate people."
    )
    parser.add_argument(
        "--output-dir", default="output", help="Directory containing page_NNNN.json extractions (default: output)"
    )
    parser.add_argument(
        "--source-file", required=True, help="Path/name of the source PDF these pages were extracted from"
    )
    return parser.parse_args()


def find_extraction_files(output_dir: Path):
    files = []
    for path in output_dir.iterdir():
        match = PAGE_FILE_RE.match(path.name)
        if match:
            files.append((int(match.group(1)), path))
    return sorted(files)


def main():
    args = parse_args()
    output_dir = Path(args.output_dir)

    files = find_extraction_files(output_dir)
    if not files:
        print(f"No page_NNNN.json files found in {output_dir}")
        return

    sheets = []
    skipped = 0
    for page_number, path in files:
        with open(path) as f:
            wrapper = json.load(f)

        if "document_type" not in wrapper:
            raise ValueError(
                f"{path} has no 'document_type' field — this looks like output from a "
                f"version of main.py before document-type routing was added. Re-run "
                f"extraction on this page with the current main.py before normalizing."
            )

        if wrapper["document_type"] != "CENSUS_SHEET":
            print(f"Skipping {path.name}: document_type={wrapper['document_type']!r} not yet handled by normalize.py")
            skipped += 1
            continue

        extraction = CensusSheetExtraction.model_validate(wrapper["data"])
        sheets.append(normalize_sheet(extraction, source_file=args.source_file, page_number=page_number))

    if not sheets:
        print(f"No CENSUS_SHEET pages to normalize ({skipped} skipped).")
        return

    find_duplicates(sheets)

    review_count = 0
    duplicate_count = 0
    for sheet in sheets:
        out_path = output_dir / f"page_{sheet.page_number:04}.normalized.json"
        with open(out_path, "w") as f:
            json.dump(sheet.model_dump(), f, indent=2)
        if sheet.needs_review:
            review_count += 1
        duplicate_count += sum(1 for row in sheet.rows if row.is_possible_duplicate)

    print(
        f"Normalized {len(sheets)} sheet(s) ({skipped} skipped). "
        f"{review_count} need review. {duplicate_count} possible duplicate row(s)."
    )


if __name__ == "__main__":
    main()
