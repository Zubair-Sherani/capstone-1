from datetime import date, datetime, timezone
from pathlib import Path
from typing import List, Optional

import streamlit as st

from services.dedup import NormalizedSheet
from services.normalizer import (
    NormalizedCensusRow,
    NormalizedCensusSheet,
    NormalizedSmearResult,
    NormalizedValue,
)
from services.review_io import discover_pages, load_sheet, save_sheet

OUTPUT_DIR = Path("output")

STATUS_OPTIONS = ["", "HEAD", "WIFE", "HUSBAND", "SON", "DAUGHTER", "GUEST", "OTHER"]
SEX_OPTIONS = ["", "M", "F"]
AGE_UNIT_OPTIONS = ["", "YEARS", "MONTHS"]
SYMPTOMS_OPTIONS = ["", "NONE", "PRESENT"]
RESULT_OPTIONS = ["", "POSITIVE", "NEGATIVE", "UNKNOWN"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _option_index(options: List[str], value: Optional[str]) -> int:
    return options.index(value) if value in options else 0


def _validate_date(value: str) -> Optional[str]:
    if not value:
        return None
    try:
        date.fromisoformat(value)
    except ValueError:
        return f"'{value}' is not a valid ISO date (YYYY-MM-DD)."
    return None


def _validate_int(value: str) -> Optional[str]:
    if not value.strip():
        return None
    try:
        int(value)
    except ValueError:
        return f"'{value}' is not a valid whole number."
    return None


def _sheet_resolved(sheet: NormalizedSheet) -> bool:
    if sheet.needs_review and not sheet.reviewed:
        return False
    return all(not (row.needs_review and not row.reviewed) for row in sheet.rows)


def render_sidebar(page_numbers: List[int]) -> Optional[int]:
    st.sidebar.text_input("Reviewer name", key="reviewer_name")
    show_flagged_only = st.sidebar.checkbox("Show only pages needing review", value=True)
    st.sidebar.caption(
        "Note: review edits survive re-running normalize.py, but not re-extracting "
        "a page whose row numbering has changed."
    )

    summaries = []
    for page_number in page_numbers:
        sheet = load_sheet(page_number, OUTPUT_DIR)
        doc_type = "CENSUS_SHEET" if isinstance(sheet, NormalizedCensusSheet) else "HOUSEHOLD_FORM"
        flagged_rows = [row for row in sheet.rows if row.needs_review]
        unreviewed_rows = [row for row in flagged_rows if not row.reviewed]
        resolved = _sheet_resolved(sheet)
        summaries.append(
            {
                "page_number": page_number,
                "doc_type": doc_type,
                "flagged": len(flagged_rows),
                "unreviewed": len(unreviewed_rows),
                "resolved": resolved,
            }
        )

    if show_flagged_only:
        summaries = [s for s in summaries if not s["resolved"]]

    if not summaries:
        st.sidebar.success("No pages need review.")
        return None

    summaries.sort(key=lambda s: (s["resolved"], s["page_number"]))

    labels = []
    for s in summaries:
        if s["resolved"]:
            icon = "🟢"
            detail = "clean" if s["flagged"] == 0 else "reviewed"
        elif s["unreviewed"] == s["flagged"]:
            icon = "🔴"
            detail = f"{s['flagged']} row(s) need review"
        else:
            icon = "🟡"
            detail = f"{s['flagged'] - s['unreviewed']}/{s['flagged']} flagged rows reviewed"
        labels.append(f"{icon} Page {s['page_number']} — {s['doc_type']} — {detail}")

    page_number_list = [s["page_number"] for s in summaries]
    label_by_page_number = dict(zip(page_number_list, labels))

    if "page_radio_widget" not in st.session_state or st.session_state["page_radio_widget"] not in page_number_list:
        st.session_state["page_radio_widget"] = page_number_list[0]

    return st.sidebar.radio(
        "Select page",
        options=page_number_list,
        format_func=lambda page_number: label_by_page_number[page_number],
        key="page_radio_widget",
    )


def render_sheet_header(sheet: NormalizedSheet, output_dir: Path) -> None:
    reviewer_name = st.session_state.get("reviewer_name", "")
    is_census = isinstance(sheet, NormalizedCensusSheet)

    with st.form(key=f"header_form_{sheet.page_number}"):
        if is_census:
            date_value = st.text_input(
                "Date censused", value=sheet.date_censused.value or sheet.date_censused.raw or ""
            )
            st.caption(f"OCR read: {sheet.date_censused.raw!r}")
            sector = st.text_input("Sector", value=sheet.sector or "")
            block = st.text_input("Block", value=sheet.block or "")
        else:
            date_value = st.text_input(
                "Date surveyed", value=sheet.date_surveyed.value or sheet.date_surveyed.raw or ""
            )
            st.caption(f"OCR read: {sheet.date_surveyed.raw!r}")
            house_number = st.text_input("House number", value=sheet.house_number or "")
            block_number = st.text_input("Block number", value=sheet.block_number or "")
            card_no = st.text_input("Card no.", value=sheet.card_no or "")

        submitted = st.form_submit_button("Save header")

    if not submitted:
        return

    date_error = _validate_date(date_value)
    if date_error:
        st.error(date_error)
        return

    if is_census:
        sheet.date_censused = NormalizedValue(raw=sheet.date_censused.raw, value=date_value or None)
        sheet.sector = sector or None
        sheet.block = block or None
    else:
        sheet.date_surveyed = NormalizedValue(raw=sheet.date_surveyed.raw, value=date_value or None)
        sheet.house_number = house_number or None
        sheet.block_number = block_number or None
        sheet.card_no = card_no or None

    sheet.reviewed = True
    sheet.reviewed_by = reviewer_name
    sheet.reviewed_at = _now_iso()

    save_sheet(sheet, output_dir)
    st.success("Header saved.")
    st.rerun()


def render_row_editor(sheet: NormalizedSheet, row, output_dir: Path) -> None:
    reviewer_name = st.session_state.get("reviewer_name", "")
    is_census_row = isinstance(row, NormalizedCensusRow)
    prefix = f"{sheet.page_number}_{row.row_no}"

    title = f"Row {row.row_no}: {row.name}" + (" ✅" if row.reviewed else "")
    with st.expander(title, expanded=(row.needs_review and not row.reviewed)):
        if row.review_reasons:
            st.warning("; ".join(row.review_reasons))
        if row.is_possible_duplicate:
            if row.duplicate_of:
                st.info(
                    f"Possible duplicate of page {row.duplicate_of.page_number} "
                    f"row {row.duplicate_of.row_no} ({row.duplicate_of.document_type})"
                )
            else:
                st.info("Possible duplicate (this is the earlier/canonical occurrence).")

        smear_count_key = f"smear_count_{prefix}"
        if is_census_row:
            if smear_count_key not in st.session_state:
                st.session_state[smear_count_key] = len(row.smear_results)
            if st.button("＋ Add smear result", key=f"add_smear_{prefix}"):
                st.session_state[smear_count_key] += 1

        with st.form(key=f"row_form_{prefix}"):
            name = st.text_input("Name", value=row.name, key=f"name_{prefix}")
            status = st.selectbox(
                "Status", STATUS_OPTIONS, index=_option_index(STATUS_OPTIONS, row.status.value), key=f"status_{prefix}"
            )
            st.caption(f"OCR read: {row.status.raw!r}")
            stated_age = st.text_input(
                "Stated age", value=str(row.stated_age) if row.stated_age is not None else "", key=f"age_{prefix}"
            )
            sex = st.selectbox("Sex", SEX_OPTIONS, index=_option_index(SEX_OPTIONS, row.sex.value), key=f"sex_{prefix}")
            st.caption(f"OCR read: {row.sex.raw!r}")
            occupation = st.text_input("Occupation", value=row.occupation or "", key=f"occ_{prefix}")

            smear_edits = []
            household_fields = {}
            if is_census_row:
                count = st.session_state.get(smear_count_key, len(row.smear_results))
                for i in range(count):
                    existing = row.smear_results[i] if i < len(row.smear_results) else None
                    col1, col2, col3 = st.columns([2, 2, 1])
                    with col1:
                        d = st.text_input(
                            f"Smear date {i + 1}",
                            value=(existing.smear_date.value or existing.smear_date.raw or "") if existing else "",
                            key=f"smear_date_{prefix}_{i}",
                        )
                    with col2:
                        r = st.selectbox(
                            f"Result {i + 1}",
                            RESULT_OPTIONS,
                            index=_option_index(RESULT_OPTIONS, existing.result.value if existing else None),
                            key=f"smear_result_{prefix}_{i}",
                        )
                    with col3:
                        remove = st.checkbox("Remove", key=f"smear_remove_{prefix}_{i}")
                    smear_edits.append((d, r, remove, existing))
            else:
                household_fields["stated_age_unit"] = st.selectbox(
                    "Age unit",
                    AGE_UNIT_OPTIONS,
                    index=_option_index(AGE_UNIT_OPTIONS, row.stated_age_unit.value),
                    key=f"age_unit_{prefix}",
                )
                household_fields["symptoms"] = st.selectbox(
                    "Symptoms",
                    SYMPTOMS_OPTIONS,
                    index=_option_index(SYMPTOMS_OPTIONS, row.symptoms.value),
                    key=f"symptoms_{prefix}",
                )
                st.caption(f"OCR read: {row.symptoms.raw!r}")
                household_fields["date_smear_taken"] = st.text_input(
                    "Date smear taken",
                    value=row.date_smear_taken.value or row.date_smear_taken.raw or "",
                    key=f"dst_{prefix}",
                )
                household_fields["result_of_smear"] = st.selectbox(
                    "Result of smear",
                    RESULT_OPTIONS,
                    index=_option_index(RESULT_OPTIONS, row.result_of_smear.value),
                    key=f"ros_{prefix}",
                )
                household_fields["date_treated"] = st.text_input(
                    "Date treated", value=row.date_treated.value or row.date_treated.raw or "", key=f"dt_{prefix}"
                )

            submitted = st.form_submit_button("Save row")

        if not submitted:
            return

        errors = [e for e in [_validate_int(stated_age)] if e]
        if is_census_row:
            for d, _r, _remove, _existing in smear_edits:
                err = _validate_date(d)
                if err:
                    errors.append(err)
        else:
            for value in (household_fields["date_smear_taken"], household_fields["date_treated"]):
                err = _validate_date(value)
                if err:
                    errors.append(err)

        if errors:
            for e in errors:
                st.error(e)
            return

        row.name = name
        row.status = NormalizedValue(raw=row.status.raw, value=status or None)
        row.stated_age = int(stated_age) if stated_age.strip() else None
        row.sex = NormalizedValue(raw=row.sex.raw, value=sex or None)
        row.occupation = occupation or None

        if is_census_row:
            new_smear_results = []
            for d, r, remove, existing in smear_edits:
                if remove or (not d and not r):
                    continue
                raw_date = existing.smear_date.raw if existing else None
                raw_result = existing.result.raw if existing else None
                new_smear_results.append(
                    NormalizedSmearResult(
                        smear_date=NormalizedValue(raw=raw_date, value=d or None),
                        result=NormalizedValue(raw=raw_result, value=r or None),
                    )
                )
            row.smear_results = new_smear_results
            st.session_state[smear_count_key] = len(new_smear_results)
        else:
            row.stated_age_unit = NormalizedValue(raw=row.stated_age_unit.raw, value=household_fields["stated_age_unit"] or None)
            row.symptoms = NormalizedValue(raw=row.symptoms.raw, value=household_fields["symptoms"] or None)
            row.date_smear_taken = NormalizedValue(
                raw=row.date_smear_taken.raw, value=household_fields["date_smear_taken"] or None
            )
            row.result_of_smear = NormalizedValue(
                raw=row.result_of_smear.raw, value=household_fields["result_of_smear"] or None
            )
            row.date_treated = NormalizedValue(raw=row.date_treated.raw, value=household_fields["date_treated"] or None)

        row.reviewed = True
        row.reviewed_by = reviewer_name
        row.reviewed_at = _now_iso()

        save_sheet(sheet, output_dir)
        st.success(f"Row {row.row_no} saved.")
        st.rerun()


def render_page(sheet: NormalizedSheet, image_path: Path, output_dir: Path) -> None:
    total_rows = len(sheet.rows)
    reviewed_rows = sum(1 for row in sheet.rows if row.reviewed)
    st.metric("Rows reviewed on this page", f"{reviewed_rows}/{total_rows}")

    col_img, col_data = st.columns(2)
    with col_img:
        if image_path.exists():
            st.image(str(image_path), width="stretch")
        else:
            st.warning(f"Image not found: {image_path}")

    with col_data:
        if sheet.needs_review and sheet.review_reasons:
            st.warning("Sheet: " + "; ".join(sheet.review_reasons))
        render_sheet_header(sheet, output_dir)
        for row in sheet.rows:
            render_row_editor(sheet, row, output_dir)


def main() -> None:
    st.set_page_config(page_title="Census / Household Form Review", layout="wide")
    st.title("Census / Household Form Review")

    if not OUTPUT_DIR.exists():
        st.error(f"Output directory {OUTPUT_DIR} does not exist.")
        return

    pages = discover_pages(OUTPUT_DIR)
    if not pages:
        st.info("No normalized pages found. Run main.py --extract and normalize.py first.")
        return

    page_numbers = [p[0] for p in pages]
    selected_page = render_sidebar(page_numbers)
    if selected_page is None:
        return

    sheet = load_sheet(selected_page, OUTPUT_DIR)
    image_path = OUTPUT_DIR / f"page_{selected_page:04}.png"
    render_page(sheet, image_path, OUTPUT_DIR)


if __name__ == "__main__":
    main()
