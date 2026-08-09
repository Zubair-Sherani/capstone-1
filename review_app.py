import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import List, Optional

import psycopg2
import streamlit as st

from services.dedup import NormalizedSheet
from services.normalizer import (
    NormalizedCensusRow,
    NormalizedCensusSheet,
    NormalizedSmearResult,
    NormalizedValue,
)
from services.review_io import discover_pages, load_sheet, save_sheet
from services.sql_sync import DB_NAME, sync_sheet

OUTPUT_DIR = Path("output")

PAGE_FILE_RE = re.compile(r"^page_(\d{4})\.json$")

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


@st.cache_resource
def _get_db_connection():
    return psycopg2.connect(dbname=DB_NAME)


def _persist_sheet(sheet: NormalizedSheet, output_dir: Path) -> None:
    # JSON is the source of truth for the review workflow; the SQL sync is
    # best-effort so a Postgres hiccup never blocks saving a review.
    save_sheet(sheet, output_dir)
    try:
        sync_sheet(sheet, _get_db_connection())
    except Exception as e:
        _get_db_connection.clear()
        st.warning(f"Saved locally, but couldn't sync to the SQL database: {e}")


def _sheet_resolved(sheet: NormalizedSheet) -> bool:
    if sheet.needs_review and not sheet.reviewed:
        return False
    return all(not (row.needs_review and not row.reviewed) for row in sheet.rows)


def _discover_all_page_numbers(output_dir: Path) -> List[int]:
    numbers = []
    for path in output_dir.iterdir():
        if path.name.endswith(".normalized.json"):
            continue
        match = PAGE_FILE_RE.match(path.name)
        if match:
            numbers.append(int(match.group(1)))
    return sorted(numbers)


@st.cache_data(show_spinner=False)
def _page_summary(page_number: int, mtime: float, output_dir_str: str) -> dict:
    # `mtime` is only used as a cache key so an edited/saved page is the one
    # whose summary gets recomputed, instead of re-reading all pages from
    # disk on every rerun (Streamlit reruns the whole script on any widget
    # interaction, and this output dir holds 500+ pages).
    sheet = load_sheet(page_number, Path(output_dir_str))
    doc_type = "CENSUS_SHEET" if isinstance(sheet, NormalizedCensusSheet) else "HOUSEHOLD_FORM"
    flagged_rows = [row for row in sheet.rows if row.needs_review]
    unreviewed_rows = [row for row in flagged_rows if not row.reviewed]
    return {
        "page_number": page_number,
        "doc_type": doc_type,
        "flagged": len(flagged_rows),
        "unreviewed": len(unreviewed_rows),
        "resolved": _sheet_resolved(sheet),
    }


@st.cache_data(show_spinner=False)
def _unclassified_summary(page_number: int, mtime: float, output_dir_str: str) -> dict:
    # Pages main.py flagged UNKNOWN (didn't match either known layout) never get a
    # .normalized.json, so they're real pages with nothing else tracking them —
    # give them a summary too instead of letting them silently disappear from the count.
    path = Path(output_dir_str) / f"page_{page_number:04}.json"
    data = json.loads(path.read_text())
    reviewed = bool(data.get("reviewed", False))
    return {
        "page_number": page_number,
        "doc_type": data.get("document_type", "UNKNOWN"),
        "flagged": 1,
        "unreviewed": 0 if reviewed else 1,
        "resolved": reviewed,
    }


def render_sidebar(output_dir: Path) -> Optional[int]:
    st.sidebar.text_input("Reviewer name", key="reviewer_name")

    classified_pages = discover_pages(output_dir)
    classified_numbers = {page_number for page_number, _json_path, _normalized_path in classified_pages}
    unclassified_numbers = [n for n in _discover_all_page_numbers(output_dir) if n not in classified_numbers]

    summaries = [
        _page_summary(page_number, normalized_path.stat().st_mtime, str(output_dir))
        for page_number, _json_path, normalized_path in classified_pages
    ]
    summaries += [
        _unclassified_summary(page_number, (output_dir / f"page_{page_number:04}.json").stat().st_mtime, str(output_dir))
        for page_number in unclassified_numbers
    ]

    total = len(summaries)
    resolved_total = sum(1 for s in summaries if s["resolved"])
    flagged_total = sum(s["flagged"] for s in summaries)
    census_total = sum(1 for s in summaries if s["doc_type"] == "CENSUS_SHEET")
    household_total = sum(1 for s in summaries if s["doc_type"] == "HOUSEHOLD_FORM")
    unclassified_total = total - census_total - household_total
    st.sidebar.progress(
        resolved_total / total if total else 0.0, text=f"{resolved_total}/{total} pages resolved"
    )
    st.sidebar.caption(
        f"{census_total} census sheet(s) · {household_total} household form(s) · "
        f"{unclassified_total} unclassified · {flagged_total} row(s)/page(s) flagged"
    )

    show_flagged_only = st.sidebar.checkbox("Show only pages needing review", value=True)
    doc_filter = st.sidebar.radio(
        "Document type", ["All", "Census", "Household", "Unclassified"], horizontal=True
    )

    filtered = summaries
    if show_flagged_only:
        filtered = [s for s in filtered if not s["resolved"]]
    if doc_filter == "Census":
        filtered = [s for s in filtered if s["doc_type"] == "CENSUS_SHEET"]
    elif doc_filter == "Household":
        filtered = [s for s in filtered if s["doc_type"] == "HOUSEHOLD_FORM"]
    elif doc_filter == "Unclassified":
        filtered = [s for s in filtered if s["doc_type"] not in ("CENSUS_SHEET", "HOUSEHOLD_FORM")]

    if not filtered:
        st.sidebar.success("No pages match the current filters.")
        return None

    filtered.sort(key=lambda s: (s["resolved"], s["page_number"]))

    def _label(s: dict) -> str:
        if s["doc_type"] not in ("CENSUS_SHEET", "HOUSEHOLD_FORM"):
            icon = "🟢" if s["resolved"] else "🟣"
            detail = "reviewed" if s["resolved"] else "unclassified — needs a look"
            return f"{icon} p.{s['page_number']} · ?? · {detail}"
        short_doc = "CS" if s["doc_type"] == "CENSUS_SHEET" else "HH"
        if s["resolved"]:
            icon, detail = "🟢", ("clean" if s["flagged"] == 0 else "reviewed")
        elif s["unreviewed"] == s["flagged"]:
            icon, detail = "🔴", f"{s['flagged']} flagged"
        else:
            icon, detail = "🟡", f"{s['flagged'] - s['unreviewed']}/{s['flagged']} done"
        return f"{icon} p.{s['page_number']} · {short_doc} · {detail}"

    page_number_list = [s["page_number"] for s in filtered]
    label_by_page_number = {s["page_number"]: _label(s) for s in filtered}

    if "page_radio_widget" not in st.session_state or st.session_state["page_radio_widget"] not in page_number_list:
        st.session_state["page_radio_widget"] = page_number_list[0]

    current_index = page_number_list.index(st.session_state["page_radio_widget"])
    col_prev, col_next = st.sidebar.columns(2)
    with col_prev:
        if st.button("◀ Prev", disabled=current_index == 0, width="stretch"):
            st.session_state["page_radio_widget"] = page_number_list[current_index - 1]
            st.rerun()
    with col_next:
        if st.button("Next ▶", disabled=current_index == len(page_number_list) - 1, width="stretch"):
            st.session_state["page_radio_widget"] = page_number_list[current_index + 1]
            st.rerun()

    selected = st.sidebar.selectbox(
        f"Page ({len(page_number_list)} shown — type to search)",
        options=page_number_list,
        format_func=lambda page_number: label_by_page_number[page_number],
        key="page_radio_widget",
    )

    st.sidebar.caption(
        "Review edits survive re-running normalize.py, but not re-extracting "
        "a page whose row numbering has changed."
    )

    return selected


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

    _persist_sheet(sheet, output_dir)
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

        _persist_sheet(sheet, output_dir)
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


def render_unclassified_page(page_number: int, output_dir: Path) -> None:
    reviewer_name = st.session_state.get("reviewer_name", "")
    json_path = output_dir / f"page_{page_number:04}.json"
    data = json.loads(json_path.read_text())

    st.warning(
        f"Page {page_number} didn't match either known form layout "
        f"(document_type={data.get('document_type')!r}) — nothing was extracted from it. "
        "Check the image below: confirm it's genuinely a blank/cover page, or flag it for "
        "re-extraction if the layout should have matched."
    )

    image_path = output_dir / f"page_{page_number:04}.png"
    if image_path.exists():
        st.image(str(image_path), width="stretch")
    else:
        st.warning(f"Image not found: {image_path}")

    reviewed = bool(data.get("reviewed", False))
    if reviewed:
        st.success(f"Marked reviewed by {data.get('reviewed_by') or '(unnamed)'} at {data.get('reviewed_at')}")

    if st.button("Mark reviewed" if not reviewed else "Un-mark reviewed", key=f"unclassified_review_{page_number}"):
        data["reviewed"] = not reviewed
        data["reviewed_by"] = reviewer_name
        data["reviewed_at"] = _now_iso()
        with open(json_path, "w") as f:
            json.dump(data, f, indent=2)
        st.rerun()


def main() -> None:
    st.set_page_config(page_title="Census / Household Form Review", layout="wide")
    st.title("Census / Household Form Review")

    if not OUTPUT_DIR.exists():
        st.error(f"Output directory {OUTPUT_DIR} does not exist.")
        return

    if not _discover_all_page_numbers(OUTPUT_DIR):
        st.info("No extracted pages found. Run main.py --extract first.")
        return

    selected_page = render_sidebar(OUTPUT_DIR)
    if selected_page is None:
        return

    normalized_path = OUTPUT_DIR / f"page_{selected_page:04}.normalized.json"
    if normalized_path.exists():
        sheet = load_sheet(selected_page, OUTPUT_DIR)
        image_path = OUTPUT_DIR / f"page_{selected_page:04}.png"
        render_page(sheet, image_path, OUTPUT_DIR)
    else:
        render_unclassified_page(selected_page, OUTPUT_DIR)


if __name__ == "__main__":
    main()
