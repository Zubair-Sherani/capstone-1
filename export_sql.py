import argparse
from pathlib import Path
from typing import List, Optional

from services.dedup import NormalizedSheet
from services.normalizer import NormalizedCensusSheet, NormalizedHouseholdFormSheet, NormalizedValue
from services.review_io import discover_pages, load_sheet


def parse_args():
    parser = argparse.ArgumentParser(
        description="Export normalized page_NNNN.normalized.json files to a .sql file of INSERT statements "
        "matching db/schema.sql."
    )
    parser.add_argument(
        "--output-dir", default="output", help="Directory containing page_NNNN.normalized.json files (default: output)"
    )
    parser.add_argument(
        "--out", default="db/export.sql", help="Path to write the generated .sql file to (default: db/export.sql)"
    )
    return parser.parse_args()


def sql_str(value: Optional[str]) -> str:
    if value is None:
        return "NULL"
    return "'" + value.replace("'", "''") + "'"


def sql_int(value: Optional[int]) -> str:
    return "NULL" if value is None else str(value)


def sql_bool(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def sql_array(values: List[str]) -> str:
    if not values:
        return "'{}'"
    return "ARRAY[" + ",".join(sql_str(v) for v in values) + "]"


def nv_raw(nv: NormalizedValue) -> Optional[str]:
    return nv.raw


def nv_value(nv: NormalizedValue) -> Optional[str]:
    return nv.value


class IdCounter:
    def __init__(self):
        self.next_id = 1

    def take(self) -> int:
        current = self.next_id
        self.next_id += 1
        return current


def export_census_sheet(sheet: NormalizedCensusSheet, ids: dict, out: List[str]) -> None:
    sheet_id = ids["census_sheet"].take()
    out.append(
        "INSERT INTO census_sheet "
        "(id, source_file, page_number, date_censused_raw, date_censused, sector, block, "
        "needs_review, review_reasons, reviewed, reviewed_by, reviewed_at) VALUES "
        f"({sheet_id}, {sql_str(sheet.source_file)}, {sql_int(sheet.page_number)}, "
        f"{sql_str(nv_raw(sheet.date_censused))}, {sql_str(nv_value(sheet.date_censused))}, "
        f"{sql_str(sheet.sector)}, {sql_str(sheet.block)}, {sql_bool(sheet.needs_review)}, "
        f"{sql_array(sheet.review_reasons)}, {sql_bool(sheet.reviewed)}, {sql_str(sheet.reviewed_by)}, "
        f"{sql_str(sheet.reviewed_at)});"
    )

    for row in sheet.rows:
        row_id = ids["census_row"].take()
        dup = row.duplicate_of
        out.append(
            "INSERT INTO census_row "
            "(id, census_sheet_id, row_no, name, status_raw, status, stated_age, sex_raw, sex, occupation, "
            "needs_review, review_reasons, is_possible_duplicate, duplicate_of_source_file, "
            "duplicate_of_page_number, duplicate_of_row_no, duplicate_of_document_type, "
            "reviewed, reviewed_by, reviewed_at) VALUES "
            f"({row_id}, {sheet_id}, {row.row_no}, {sql_str(row.name)}, {sql_str(nv_raw(row.status))}, "
            f"{sql_str(nv_value(row.status))}, {sql_int(row.stated_age)}, {sql_str(nv_raw(row.sex))}, "
            f"{sql_str(nv_value(row.sex))}, {sql_str(row.occupation)}, {sql_bool(row.needs_review)}, "
            f"{sql_array(row.review_reasons)}, {sql_bool(row.is_possible_duplicate)}, "
            f"{sql_str(dup.source_file if dup else None)}, {sql_int(dup.page_number if dup else None)}, "
            f"{sql_int(dup.row_no if dup else None)}, {sql_str(dup.document_type if dup else None)}, "
            f"{sql_bool(row.reviewed)}, {sql_str(row.reviewed_by)}, {sql_str(row.reviewed_at)});"
        )

        for smear in row.smear_results:
            smear_id = ids["census_smear_result"].take()
            out.append(
                "INSERT INTO census_smear_result "
                "(id, census_row_id, smear_date_raw, smear_date, result_raw, result) VALUES "
                f"({smear_id}, {row_id}, {sql_str(nv_raw(smear.smear_date))}, {sql_str(nv_value(smear.smear_date))}, "
                f"{sql_str(nv_raw(smear.result))}, {sql_str(nv_value(smear.result))});"
            )


def export_household_form(sheet: NormalizedHouseholdFormSheet, ids: dict, out: List[str]) -> None:
    form_id = ids["household_form"].take()
    out.append(
        "INSERT INTO household_form "
        "(id, source_file, page_number, card_no, house_number, block_number, date_surveyed_raw, date_surveyed, "
        "needs_review, review_reasons, reviewed, reviewed_by, reviewed_at) VALUES "
        f"({form_id}, {sql_str(sheet.source_file)}, {sql_int(sheet.page_number)}, {sql_str(sheet.card_no)}, "
        f"{sql_str(sheet.house_number)}, {sql_str(sheet.block_number)}, {sql_str(nv_raw(sheet.date_surveyed))}, "
        f"{sql_str(nv_value(sheet.date_surveyed))}, {sql_bool(sheet.needs_review)}, {sql_array(sheet.review_reasons)}, "
        f"{sql_bool(sheet.reviewed)}, {sql_str(sheet.reviewed_by)}, {sql_str(sheet.reviewed_at)});"
    )

    for row in sheet.rows:
        row_id = ids["household_row"].take()
        dup = row.duplicate_of
        out.append(
            "INSERT INTO household_row "
            "(id, household_form_id, row_no, name, status_raw, status, stated_age, stated_age_unit_raw, "
            "stated_age_unit, sex_raw, sex, occupation, symptoms_raw, symptoms, date_smear_taken_raw, "
            "date_smear_taken, result_of_smear_raw, result_of_smear, date_treated_raw, date_treated, "
            "needs_review, review_reasons, is_possible_duplicate, duplicate_of_source_file, "
            "duplicate_of_page_number, duplicate_of_row_no, duplicate_of_document_type, "
            "reviewed, reviewed_by, reviewed_at) VALUES "
            f"({row_id}, {form_id}, {row.row_no}, {sql_str(row.name)}, {sql_str(nv_raw(row.status))}, "
            f"{sql_str(nv_value(row.status))}, {sql_int(row.stated_age)}, {sql_str(nv_raw(row.stated_age_unit))}, "
            f"{sql_str(nv_value(row.stated_age_unit))}, {sql_str(nv_raw(row.sex))}, {sql_str(nv_value(row.sex))}, "
            f"{sql_str(row.occupation)}, {sql_str(nv_raw(row.symptoms))}, {sql_str(nv_value(row.symptoms))}, "
            f"{sql_str(nv_raw(row.date_smear_taken))}, {sql_str(nv_value(row.date_smear_taken))}, "
            f"{sql_str(nv_raw(row.result_of_smear))}, {sql_str(nv_value(row.result_of_smear))}, "
            f"{sql_str(nv_raw(row.date_treated))}, {sql_str(nv_value(row.date_treated))}, "
            f"{sql_bool(row.needs_review)}, {sql_array(row.review_reasons)}, {sql_bool(row.is_possible_duplicate)}, "
            f"{sql_str(dup.source_file if dup else None)}, {sql_int(dup.page_number if dup else None)}, "
            f"{sql_int(dup.row_no if dup else None)}, {sql_str(dup.document_type if dup else None)}, "
            f"{sql_bool(row.reviewed)}, {sql_str(row.reviewed_by)}, {sql_str(row.reviewed_at)});"
        )


def build_inserts(sheets: List[NormalizedSheet]) -> List[str]:
    ids = {
        "census_sheet": IdCounter(),
        "census_row": IdCounter(),
        "census_smear_result": IdCounter(),
        "household_form": IdCounter(),
        "household_row": IdCounter(),
    }
    out: List[str] = []
    for sheet in sheets:
        if isinstance(sheet, NormalizedCensusSheet):
            export_census_sheet(sheet, ids, out)
        elif isinstance(sheet, NormalizedHouseholdFormSheet):
            export_household_form(sheet, ids, out)
        else:
            raise TypeError(f"unsupported sheet type: {type(sheet)}")
    return out


def main():
    args = parse_args()
    output_dir = Path(args.output_dir)

    pages = discover_pages(output_dir)
    if not pages:
        print(f"No normalized page_NNNN.normalized.json files found in {output_dir}")
        return

    sheets = [load_sheet(page_number, output_dir) for page_number, _, _ in pages]
    inserts = build_inserts(sheets)

    # The INSERTs above assign explicit ids (to keep page ordering stable across the whole
    # corpus), so each table's SERIAL sequence never auto-advances on its own — without this,
    # the next INSERT that lets Postgres assign an id (e.g. a live review-app save) collides
    # with an id these statements already used.
    setval_statements = [
        f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE((SELECT MAX(id) FROM {table}), 1));"
        for table in ("census_sheet", "census_row", "census_smear_result", "household_form", "household_row")
    ]

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        f.write("-- Generated by export_sql.py — INSERT statements matching db/schema.sql\n")
        f.write("BEGIN;\n\n")
        f.write("\n".join(inserts))
        f.write("\n\n-- Re-sync SERIAL sequences with the explicit ids inserted above.\n")
        f.write("\n".join(setval_statements))
        f.write("\n\nCOMMIT;\n")

    census_count = sum(1 for s in sheets if isinstance(s, NormalizedCensusSheet))
    household_count = sum(1 for s in sheets if isinstance(s, NormalizedHouseholdFormSheet))
    print(
        f"Exported {len(sheets)} page(s) ({census_count} census sheet, {household_count} household form) "
        f"as {len(inserts)} INSERT statement(s) to {out_path}"
    )


if __name__ == "__main__":
    main()
