import re
from datetime import date
from difflib import SequenceMatcher
from typing import List, Optional, Union

from services.normalizer import DuplicateRef, NormalizedCensusSheet, NormalizedHouseholdFormSheet

NormalizedSheet = Union[NormalizedCensusSheet, NormalizedHouseholdFormSheet]

AGE_TOLERANCE_YEARS = 1
AGE_TOLERANCE_FALLBACK_YEARS = 2
SECTOR_SIMILARITY_THRESHOLD = 0.5

HOUSE_NUMBER_RE = re.compile(r"\d+")


def normalize_name_for_match(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().rstrip(".")).upper()


def _document_type(sheet: NormalizedSheet) -> str:
    if isinstance(sheet, NormalizedCensusSheet):
        return "CENSUS_SHEET"
    if isinstance(sheet, NormalizedHouseholdFormSheet):
        return "HOUSEHOLD_FORM"
    raise TypeError(f"unsupported sheet type: {type(sheet)}")


def _house_key(sheet: NormalizedSheet) -> Optional[str]:
    if isinstance(sheet, NormalizedCensusSheet):
        fields = (sheet.sector, sheet.block)
    elif isinstance(sheet, NormalizedHouseholdFormSheet):
        fields = (sheet.house_number, sheet.block_number)
    else:
        raise TypeError(f"unsupported sheet type: {type(sheet)}")
    for field in fields:
        if field:
            match = HOUSE_NUMBER_RE.search(field)
            if match:
                return match.group()
    return None


def _reference_date(sheet: NormalizedSheet) -> Optional[str]:
    if isinstance(sheet, NormalizedCensusSheet):
        return sheet.date_censused.value
    if isinstance(sheet, NormalizedHouseholdFormSheet):
        return sheet.date_surveyed.value
    raise TypeError(f"unsupported sheet type: {type(sheet)}")


def _sector_text(sheet: NormalizedSheet) -> Optional[str]:
    if isinstance(sheet, NormalizedCensusSheet):
        parts = (sheet.sector, sheet.block)
    elif isinstance(sheet, NormalizedHouseholdFormSheet):
        parts = (sheet.house_number, sheet.block_number)
    else:
        raise TypeError(f"unsupported sheet type: {type(sheet)}")
    joined = " ".join(p for p in parts if p)
    return joined or None


def _sector_key(sector: Optional[str]) -> str:
    return re.sub(r"[^A-Z0-9]", "", (sector or "").upper())


def _sectors_similar(sector_a: Optional[str], sector_b: Optional[str]) -> bool:
    ratio = SequenceMatcher(None, _sector_key(sector_a), _sector_key(sector_b)).ratio()
    return ratio >= SECTOR_SIMILARITY_THRESHOLD


def _expected_age_diff(date_a: str, date_b: str) -> Optional[int]:
    try:
        d_a = date.fromisoformat(date_a)
        d_b = date.fromisoformat(date_b)
    except ValueError:
        return None
    days_between = abs((d_b - d_a).days)
    return round(days_between / 365.25)


def _stated_age_in_years(row) -> Optional[float]:
    if row.stated_age is None:
        return None
    unit = getattr(row, "stated_age_unit", None)
    if unit is not None and unit.value == "MONTHS":
        return row.stated_age / 12
    return float(row.stated_age)


def _rows_match(entry_a, entry_b) -> bool:
    sheet_a, row_a = entry_a
    sheet_b, row_b = entry_b

    if normalize_name_for_match(row_a.name) != normalize_name_for_match(row_b.name):
        return False

    if row_a.sex.value is not None and row_b.sex.value is not None:
        if row_a.sex.value != row_b.sex.value:
            return False

    age_a = _stated_age_in_years(row_a)
    age_b = _stated_age_in_years(row_b)
    if age_a is not None and age_b is not None:
        actual_diff = abs(age_a - age_b)
        date_a = _reference_date(sheet_a)
        date_b = _reference_date(sheet_b)
        if date_a and date_b:
            expected_diff = _expected_age_diff(date_a, date_b)
            if expected_diff is None or abs(actual_diff - expected_diff) > AGE_TOLERANCE_YEARS:
                return False
        else:
            if actual_diff > AGE_TOLERANCE_FALLBACK_YEARS:
                return False

    return True


def find_duplicates(sheets: List[NormalizedSheet]) -> None:
    buckets: dict = {}
    for sheet in sheets:
        key = _house_key(sheet)
        if key is None:
            continue
        for row in sheet.rows:
            buckets.setdefault(key, []).append((sheet, row))

    for entries in buckets.values():
        entries.sort(key=lambda e: (_reference_date(e[0]) or "", e[0].page_number, e[1].row_no))

        for i, entry in enumerate(entries):
            sheet, row = entry
            for j in range(i - 1, -1, -1):
                earlier_sheet, earlier_row = entries[j]
                if earlier_sheet is sheet:
                    continue
                if not _sectors_similar(_sector_text(sheet), _sector_text(earlier_sheet)):
                    continue
                if _rows_match(entries[j], entry):
                    row.is_possible_duplicate = True
                    row.duplicate_of = DuplicateRef(
                        source_file=earlier_sheet.source_file,
                        page_number=earlier_sheet.page_number,
                        row_no=earlier_row.row_no,
                        document_type=_document_type(earlier_sheet),
                    )
                    earlier_row.is_possible_duplicate = True
                    break
