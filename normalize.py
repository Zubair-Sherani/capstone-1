import argparse
import json
import re
from pathlib import Path

from services.dedup import find_duplicates
from services.document_extractor import CensusSheetExtraction, HouseholdFormExtraction
from services.normalizer import (
    normalize_sheet,
    normalize_household_form,
    NormalizedCensusSheet,
    NormalizedHouseholdFormSheet,
)

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


def _preserve_reviewed(new_sheet, output_dir: Path):
    existing_path = output_dir / f"page_{new_sheet.page_number:04}.normalized.json"
    if not existing_path.exists():
        return new_sheet

    old_sheet = type(new_sheet).model_validate(json.loads(existing_path.read_text()))
    old_rows_by_no = {r.row_no: r for r in old_sheet.rows}
    merged_rows = [
        old_rows_by_no[row.row_no] if row.row_no in old_rows_by_no and old_rows_by_no[row.row_no].reviewed else row
        for row in new_sheet.rows
    ]

    if old_sheet.reviewed:
        return old_sheet.model_copy(update={"rows": merged_rows})
    return new_sheet.model_copy(update={"rows": merged_rows})


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

        doc_type = wrapper["document_type"]
        if doc_type == "CENSUS_SHEET":
            extraction = CensusSheetExtraction.model_validate(wrapper["data"])
            sheets.append(normalize_sheet(extraction, source_file=args.source_file, page_number=page_number))
        elif doc_type == "HOUSEHOLD_FORM":
            household_extraction = HouseholdFormExtraction.model_validate(wrapper["data"])
            sheets.append(
                normalize_household_form(household_extraction, source_file=args.source_file, page_number=page_number)
            )
        else:
            print(f"Skipping {path.name}: document_type={doc_type!r} not yet handled by normalize.py")
            skipped += 1
            continue

    if not sheets:
        print(f"No recognized pages to normalize ({skipped} skipped).")
        return

    find_duplicates(sheets)

    census_sheets = [s for s in sheets if isinstance(s, NormalizedCensusSheet)]
    household_sheets = [s for s in sheets if isinstance(s, NormalizedHouseholdFormSheet)]

    for sheet in sheets:
        sheet = _preserve_reviewed(sheet, output_dir)
        out_path = output_dir / f"page_{sheet.page_number:04}.normalized.json"
        with open(out_path, "w") as f:
            json.dump(sheet.model_dump(), f, indent=2)

    census_review = sum(1 for s in census_sheets if s.needs_review)
    household_review = sum(1 for s in household_sheets if s.needs_review)
    duplicate_count = sum(1 for s in sheets for row in s.rows if row.is_possible_duplicate)

    print(
        f"Normalized {len(census_sheets)} census sheet(s), {len(household_sheets)} household form(s) "
        f"({skipped} skipped). {census_review} census / {household_review} household need review. "
        f"{duplicate_count} possible duplicate row(s)."
    )


if __name__ == "__main__":
    main()
