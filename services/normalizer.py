import re
from datetime import date
from typing import List, Optional, Tuple

from pydantic import BaseModel

from services.document_extractor import CensusRow, CensusSheetExtraction, HouseholdRow, HouseholdFormExtraction

MONTH_NAMES = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

NUMERIC_DATE_RE = re.compile(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{2}|\d{4})$")
TEXTUAL_DATE_RE = re.compile(r"^([A-Za-z]+)\.?\s+(\d{1,2})\s*[,/]?\s*(\d{2}|\d{4})$")

STATUS_MAP = {
    "HEAD": "HEAD",
    "WIFE": "WIFE",
    "W": "WIFE",
    "HUSBAND": "HUSBAND",
    "S": "SON",
    "SON": "SON",
    "D": "DAUGHTER",
    "DAUGHTER": "DAUGHTER",
    "GUEST": "GUEST",
}

DASH_CHARS = {"-", "—", "−"}


class NormalizedValue(BaseModel):
    raw: Optional[str] = None
    value: Optional[str] = None


class DuplicateRef(BaseModel):
    source_file: str
    page_number: int
    row_no: int
    document_type: str


class NormalizedSmearResult(BaseModel):
    smear_date: NormalizedValue
    result: NormalizedValue


class NormalizedCensusRow(BaseModel):
    row_no: int
    name: str
    status: NormalizedValue
    stated_age: Optional[int] = None
    sex: NormalizedValue
    occupation: Optional[str] = None
    smear_results: List[NormalizedSmearResult] = []
    needs_review: bool = False
    review_reasons: List[str] = []
    is_possible_duplicate: bool = False
    duplicate_of: Optional[DuplicateRef] = None
    reviewed: bool = False
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None


class NormalizedCensusSheet(BaseModel):
    source_file: str
    page_number: int
    date_censused: NormalizedValue
    sector: Optional[str] = None
    block: Optional[str] = None
    rows: List[NormalizedCensusRow] = []
    needs_review: bool = False
    review_reasons: List[str] = []
    reviewed: bool = False
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None


class NormalizedHouseholdRow(BaseModel):
    row_no: int
    name: str
    status: NormalizedValue
    stated_age: Optional[int] = None
    stated_age_unit: NormalizedValue
    sex: NormalizedValue
    occupation: Optional[str] = None
    symptoms: NormalizedValue
    date_smear_taken: NormalizedValue
    result_of_smear: NormalizedValue
    date_treated: NormalizedValue
    needs_review: bool = False
    review_reasons: List[str] = []
    is_possible_duplicate: bool = False
    duplicate_of: Optional[DuplicateRef] = None
    reviewed: bool = False
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None


class NormalizedHouseholdFormSheet(BaseModel):
    source_file: str
    page_number: int
    card_no: Optional[str] = None
    house_number: Optional[str] = None
    block_number: Optional[str] = None
    date_surveyed: NormalizedValue
    rows: List[NormalizedHouseholdRow] = []
    needs_review: bool = False
    review_reasons: List[str] = []
    reviewed: bool = False
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None


def _expand_year(year_str: str) -> int:
    # ledger is confirmed 1980-81 throughout; 2-digit years assumed 19xx
    return int(year_str) if len(year_str) == 4 else 1900 + int(year_str)


def _build_date(raw: str, year: int, month: int, day: int) -> Tuple[Optional[str], Optional[str]]:
    try:
        d = date(year, month, day)
    except ValueError:
        return None, f"unparseable_date: '{raw}' -> invalid calendar date {year}-{month}-{day}"
    return d.isoformat(), None


def normalize_date(raw: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if raw is None or not raw.strip():
        return None, None
    text = raw.strip()

    textual_match = TEXTUAL_DATE_RE.match(text)
    if textual_match:
        month_name, day_str, year_str = textual_match.groups()
        month = MONTH_NAMES.get(month_name.lower())
        if month is None:
            return None, f"unparseable_date: unrecognized month in '{raw}'"
        return _build_date(raw, _expand_year(year_str), month, int(day_str))

    numeric_match = NUMERIC_DATE_RE.match(text)
    if numeric_match:
        day_str, month_str, year_str = numeric_match.groups()
        month = int(month_str)
        if not (1 <= month <= 12):
            return None, f"unparseable_date: '{raw}' doesn't fit day-first D.M.Y (month={month} invalid)"
        return _build_date(raw, _expand_year(year_str), month, int(day_str))

    return None, f"unparseable_date: '{raw}' matches no known format"


def normalize_sex(raw: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if raw is None:
        return None, None
    text = raw.strip().upper()
    if text in ("M", "F"):
        return text, None
    return None, f"sex_unrecognized: raw='{raw}'"


def normalize_status(raw: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if raw is None:
        return None, None
    key = re.sub(r"\s+", " ", raw.replace(".", "")).strip().upper()
    if key in STATUS_MAP:
        return STATUS_MAP[key], None
    return "OTHER", f"status_unrecognized: raw='{raw}'"


def normalize_smear_result(raw: Optional[str]) -> Tuple[str, Optional[str]]:
    if raw is None or not raw.strip():
        return "UNKNOWN", "smear_result_missing"
    text = raw.strip()
    stripped = text
    if stripped.startswith("(") and stripped.endswith(")"):
        stripped = stripped[1:-1].strip()
    if stripped in DASH_CHARS:
        return "NEGATIVE", None
    if text.lstrip().startswith("+"):
        return "POSITIVE", None
    return "UNKNOWN", f"smear_result_unrecognized: raw='{raw}'"


def normalize_age_unit(raw: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if raw is None:
        return None, None
    text = raw.strip().upper()
    if text in ("YEARS", "MONTHS"):
        return text, None
    return None, f"age_unit_unrecognized: raw='{raw}'"


def normalize_symptoms(raw: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if raw is None or not raw.strip():
        return None, None
    if raw.strip().lower() == "none":
        return "NONE", None
    return "PRESENT", None


def _normalize_row(row: CensusRow) -> NormalizedCensusRow:
    reasons: List[str] = []

    if not row.name or not row.name.strip():
        reasons.append("missing_name")
    if row.status is None:
        reasons.append("missing_status")
    if row.stated_age is None:
        reasons.append("missing_stated_age")
    if row.sex is None:
        reasons.append("missing_sex")

    status_value, status_reason = normalize_status(row.status)
    if status_reason:
        reasons.append(status_reason)

    sex_value, sex_reason = normalize_sex(row.sex)
    if sex_reason:
        reasons.append(sex_reason)

    smear_results = []
    for i, smear in enumerate(row.smear_results):
        date_value, date_reason = normalize_date(smear.smear_date)
        if smear.smear_date is not None and date_reason:
            reasons.append(f"smear_date_unparseable[{i}]: raw='{smear.smear_date}'")

        result_value, result_reason = normalize_smear_result(smear.result)
        if result_value == "UNKNOWN":
            reasons.append(f"smear_result_unknown[{i}]: raw='{smear.result}'")

        if smear.smear_date is None and smear.result is not None:
            reasons.append(f"smear_entry_missing_date[{i}]")
        elif smear.smear_date is None and smear.result is None:
            reasons.append(f"smear_entry_empty[{i}]")

        smear_results.append(
            NormalizedSmearResult(
                smear_date=NormalizedValue(raw=smear.smear_date, value=date_value),
                result=NormalizedValue(raw=smear.result, value=result_value),
            )
        )

    return NormalizedCensusRow(
        row_no=row.row_no,
        name=row.name,
        status=NormalizedValue(raw=row.status, value=status_value),
        stated_age=row.stated_age,
        sex=NormalizedValue(raw=row.sex, value=sex_value),
        occupation=row.occupation,
        smear_results=smear_results,
        needs_review=len(reasons) > 0,
        review_reasons=reasons,
    )


def normalize_sheet(
    extraction: CensusSheetExtraction, source_file: str, page_number: int
) -> NormalizedCensusSheet:
    reasons: List[str] = []

    date_value, date_reason = normalize_date(extraction.date_censused)
    if extraction.date_censused is not None and date_reason:
        reasons.append(f"date_censused_unparseable: raw='{extraction.date_censused}'")

    if extraction.sector is None:
        reasons.append("missing_household_identifier")
    if not extraction.rows:
        reasons.append("no_rows_extracted")

    rows = [_normalize_row(row) for row in extraction.rows]

    seen_row_nos = set()
    for row in rows:
        if row.row_no in seen_row_nos:
            row.review_reasons.append("duplicate_row_no")
            row.needs_review = True
        seen_row_nos.add(row.row_no)

    needs_review = len(reasons) > 0 or any(row.needs_review for row in rows)

    return NormalizedCensusSheet(
        source_file=source_file,
        page_number=page_number,
        date_censused=NormalizedValue(raw=extraction.date_censused, value=date_value),
        sector=extraction.sector,
        block=extraction.block,
        rows=rows,
        needs_review=needs_review,
        review_reasons=reasons,
    )


def _normalize_household_row(row: HouseholdRow) -> NormalizedHouseholdRow:
    reasons: List[str] = []

    if not row.name or not row.name.strip():
        reasons.append("missing_name")
    if row.status is None:
        reasons.append("missing_status")
    if row.stated_age is None:
        reasons.append("missing_stated_age")
    if row.sex is None:
        reasons.append("missing_sex")

    status_value, status_reason = normalize_status(row.status)
    if status_reason:
        reasons.append(status_reason)

    sex_value, sex_reason = normalize_sex(row.sex)
    if sex_reason:
        reasons.append(sex_reason)

    age_unit_value, age_unit_reason = normalize_age_unit(row.stated_age_unit)
    if age_unit_reason:
        reasons.append(age_unit_reason)
    if row.stated_age is not None and row.stated_age_unit is None:
        reasons.append("missing_stated_age_unit")

    symptoms_value, _ = normalize_symptoms(row.symptoms)

    date_value, date_reason = normalize_date(row.date_smear_taken)
    if row.date_smear_taken is not None and date_reason:
        reasons.append(f"date_smear_taken_unparseable: raw='{row.date_smear_taken}'")

    result_value, _ = normalize_smear_result(row.result_of_smear)
    if row.result_of_smear is not None and result_value == "UNKNOWN":
        reasons.append(f"smear_result_unrecognized: raw='{row.result_of_smear}'")

    if row.date_smear_taken is not None and row.result_of_smear is None:
        reasons.append("smear_taken_missing_result")
    elif row.date_smear_taken is None and row.result_of_smear is not None:
        reasons.append("smear_result_missing_date")

    treated_value, treated_reason = normalize_date(row.date_treated)
    if row.date_treated is not None and treated_reason:
        reasons.append(f"date_treated_unparseable: raw='{row.date_treated}'")
    if row.date_treated is not None and row.date_smear_taken is None and row.result_of_smear is None:
        reasons.append("date_treated_without_smear_record")

    return NormalizedHouseholdRow(
        row_no=row.row_no,
        name=row.name,
        status=NormalizedValue(raw=row.status, value=status_value),
        stated_age=row.stated_age,
        stated_age_unit=NormalizedValue(raw=row.stated_age_unit, value=age_unit_value),
        sex=NormalizedValue(raw=row.sex, value=sex_value),
        occupation=row.occupation,
        symptoms=NormalizedValue(raw=row.symptoms, value=symptoms_value),
        date_smear_taken=NormalizedValue(raw=row.date_smear_taken, value=date_value),
        result_of_smear=NormalizedValue(raw=row.result_of_smear, value=result_value),
        date_treated=NormalizedValue(raw=row.date_treated, value=treated_value),
        needs_review=len(reasons) > 0,
        review_reasons=reasons,
    )


def normalize_household_form(
    extraction: HouseholdFormExtraction, source_file: str, page_number: int
) -> NormalizedHouseholdFormSheet:
    reasons: List[str] = []

    date_value, date_reason = normalize_date(extraction.header.date_surveyed)
    if extraction.header.date_surveyed is not None and date_reason:
        reasons.append(f"date_surveyed_unparseable: raw='{extraction.header.date_surveyed}'")

    if extraction.header.house_number is None:
        reasons.append("missing_household_identifier")
    if not extraction.rows:
        reasons.append("no_rows_extracted")

    rows = [_normalize_household_row(row) for row in extraction.rows]

    seen_row_nos = set()
    for row in rows:
        if row.row_no in seen_row_nos:
            row.review_reasons.append("duplicate_row_no")
            row.needs_review = True
        seen_row_nos.add(row.row_no)

    needs_review = len(reasons) > 0 or any(row.needs_review for row in rows)

    return NormalizedHouseholdFormSheet(
        source_file=source_file,
        page_number=page_number,
        card_no=extraction.header.card_no,
        house_number=extraction.header.house_number,
        block_number=extraction.header.block_number,
        date_surveyed=NormalizedValue(raw=extraction.header.date_surveyed, value=date_value),
        rows=rows,
        needs_review=needs_review,
        review_reasons=reasons,
    )
