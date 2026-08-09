from typing import Tuple

from services.dedup import NormalizedSheet
from services.normalizer import NormalizedCensusSheet, NormalizedHouseholdFormSheet, NormalizedValue

DB_NAME = "capstone_census"


def _nv(value: NormalizedValue) -> Tuple[object, object]:
    return value.raw, value.value


def sync_sheet(sheet: NormalizedSheet, conn) -> None:
    """Delete and re-insert one page's rows in the SQL database so review edits stay
    in sync with db/export.sql's field mapping (see export_sql.py for the portable-file
    equivalent of this same mapping)."""
    if isinstance(sheet, NormalizedCensusSheet):
        _sync_census_sheet(sheet, conn)
    elif isinstance(sheet, NormalizedHouseholdFormSheet):
        _sync_household_form(sheet, conn)
    else:
        raise TypeError(f"unsupported sheet type: {type(sheet)}")
    conn.commit()


def _sync_census_sheet(sheet: NormalizedCensusSheet, conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM census_sheet WHERE source_file = %s AND page_number = %s",
            (sheet.source_file, sheet.page_number),
        )
        date_raw, date_value = _nv(sheet.date_censused)
        cur.execute(
            """
            INSERT INTO census_sheet
                (source_file, page_number, date_censused_raw, date_censused, sector, block,
                 needs_review, review_reasons, reviewed, reviewed_by, reviewed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                sheet.source_file, sheet.page_number, date_raw, date_value, sheet.sector, sheet.block,
                sheet.needs_review, sheet.review_reasons, sheet.reviewed, sheet.reviewed_by, sheet.reviewed_at,
            ),
        )
        sheet_id = cur.fetchone()[0]

        for row in sheet.rows:
            status_raw, status_value = _nv(row.status)
            sex_raw, sex_value = _nv(row.sex)
            dup = row.duplicate_of
            cur.execute(
                """
                INSERT INTO census_row
                    (census_sheet_id, row_no, name, status_raw, status, stated_age, sex_raw, sex, occupation,
                     needs_review, review_reasons, is_possible_duplicate,
                     duplicate_of_source_file, duplicate_of_page_number, duplicate_of_row_no, duplicate_of_document_type,
                     reviewed, reviewed_by, reviewed_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    sheet_id, row.row_no, row.name, status_raw, status_value, row.stated_age, sex_raw, sex_value,
                    row.occupation, row.needs_review, row.review_reasons, row.is_possible_duplicate,
                    dup.source_file if dup else None, dup.page_number if dup else None,
                    dup.row_no if dup else None, dup.document_type if dup else None,
                    row.reviewed, row.reviewed_by, row.reviewed_at,
                ),
            )
            row_id = cur.fetchone()[0]

            for smear in row.smear_results:
                d_raw, d_value = _nv(smear.smear_date)
                r_raw, r_value = _nv(smear.result)
                cur.execute(
                    """
                    INSERT INTO census_smear_result (census_row_id, smear_date_raw, smear_date, result_raw, result)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (row_id, d_raw, d_value, r_raw, r_value),
                )


def _sync_household_form(sheet: NormalizedHouseholdFormSheet, conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM household_form WHERE source_file = %s AND page_number = %s",
            (sheet.source_file, sheet.page_number),
        )
        date_raw, date_value = _nv(sheet.date_surveyed)
        cur.execute(
            """
            INSERT INTO household_form
                (source_file, page_number, card_no, house_number, block_number, date_surveyed_raw, date_surveyed,
                 needs_review, review_reasons, reviewed, reviewed_by, reviewed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                sheet.source_file, sheet.page_number, sheet.card_no, sheet.house_number, sheet.block_number,
                date_raw, date_value, sheet.needs_review, sheet.review_reasons, sheet.reviewed, sheet.reviewed_by,
                sheet.reviewed_at,
            ),
        )
        form_id = cur.fetchone()[0]

        for row in sheet.rows:
            status_raw, status_value = _nv(row.status)
            age_unit_raw, age_unit_value = _nv(row.stated_age_unit)
            sex_raw, sex_value = _nv(row.sex)
            symptoms_raw, symptoms_value = _nv(row.symptoms)
            dst_raw, dst_value = _nv(row.date_smear_taken)
            ros_raw, ros_value = _nv(row.result_of_smear)
            dt_raw, dt_value = _nv(row.date_treated)
            dup = row.duplicate_of
            cur.execute(
                """
                INSERT INTO household_row
                    (household_form_id, row_no, name, status_raw, status, stated_age, stated_age_unit_raw,
                     stated_age_unit, sex_raw, sex, occupation, symptoms_raw, symptoms, date_smear_taken_raw,
                     date_smear_taken, result_of_smear_raw, result_of_smear, date_treated_raw, date_treated,
                     needs_review, review_reasons, is_possible_duplicate,
                     duplicate_of_source_file, duplicate_of_page_number, duplicate_of_row_no, duplicate_of_document_type,
                     reviewed, reviewed_by, reviewed_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s)
                """,
                (
                    form_id, row.row_no, row.name, status_raw, status_value, row.stated_age, age_unit_raw,
                    age_unit_value, sex_raw, sex_value, row.occupation, symptoms_raw, symptoms_value, dst_raw,
                    dst_value, ros_raw, ros_value, dt_raw, dt_value,
                    row.needs_review, row.review_reasons, row.is_possible_duplicate,
                    dup.source_file if dup else None, dup.page_number if dup else None,
                    dup.row_no if dup else None, dup.document_type if dup else None,
                    row.reviewed, row.reviewed_by, row.reviewed_at,
                ),
            )
