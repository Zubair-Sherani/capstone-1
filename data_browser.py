import pandas as pd
import psycopg2
import streamlit as st

DB_NAME = "capstone_census"

PAGE_SIZE_OPTIONS = [25, 50, 100, 200]

CENSUS_PEOPLE_BASE = """
    SELECT
        cs.page_number, cs.source_file, cs.sector, cs.block, cs.date_censused,
        cr.row_no, cr.name, cr.status, cr.stated_age, cr.sex, cr.occupation,
        cr.needs_review, cr.is_possible_duplicate,
        (
            SELECT string_agg(COALESCE(sm.smear_date::text, '?') || ':' || COALESCE(sm.result, '?'), ', ' ORDER BY sm.id)
            FROM census_smear_result sm WHERE sm.census_row_id = cr.id
        ) AS smear_results
    FROM census_row cr
    JOIN census_sheet cs ON cs.id = cr.census_sheet_id
"""

HOUSEHOLD_PEOPLE_BASE = """
    SELECT
        hf.page_number, hf.source_file, hf.house_number, hf.block_number, hf.card_no, hf.date_surveyed,
        hr.row_no, hr.name, hr.status, hr.stated_age, hr.stated_age_unit, hr.sex, hr.occupation,
        hr.symptoms, hr.date_smear_taken, hr.result_of_smear, hr.date_treated,
        hr.needs_review, hr.is_possible_duplicate
    FROM household_row hr
    JOIN household_form hf ON hf.id = hr.household_form_id
"""

CENSUS_SHEETS_BASE = "SELECT * FROM census_sheet"
HOUSEHOLD_FORMS_BASE = "SELECT * FROM household_form"

VIEWS = {
    "Census people": {
        "base": CENSUS_PEOPLE_BASE,
        "order": "cs.page_number, cr.row_no",
        "search_col": "cr.name",
        "page_col": "cs.page_number",
        "needs_review_col": "cr.needs_review",
        "duplicate_col": "cr.is_possible_duplicate",
    },
    "Household people": {
        "base": HOUSEHOLD_PEOPLE_BASE,
        "order": "hf.page_number, hr.row_no",
        "search_col": "hr.name",
        "page_col": "hf.page_number",
        "needs_review_col": "hr.needs_review",
        "duplicate_col": "hr.is_possible_duplicate",
    },
    "Census sheets (raw)": {
        "base": CENSUS_SHEETS_BASE,
        "order": "page_number",
        "search_col": "sector",
        "page_col": "page_number",
        "needs_review_col": "needs_review",
        "duplicate_col": None,
    },
    "Household forms (raw)": {
        "base": HOUSEHOLD_FORMS_BASE,
        "order": "page_number",
        "search_col": "house_number",
        "page_col": "page_number",
        "needs_review_col": "needs_review",
        "duplicate_col": None,
    },
}


@st.cache_resource
def get_connection():
    return psycopg2.connect(dbname=DB_NAME)


@st.cache_data(ttl=30, show_spinner=False)
def run_query(sql: str, params: tuple) -> pd.DataFrame:
    return pd.read_sql_query(sql, get_connection(), params=params)


@st.cache_data(ttl=30, show_spinner=False)
def scalar_count(sql: str, params: tuple) -> int:
    with get_connection().cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()[0]


@st.cache_data(ttl=30, show_spinner=False)
def load_stats() -> dict:
    with get_connection().cursor() as cur:
        cur.execute("""
            SELECT
                (SELECT count(*) FROM census_sheet),
                (SELECT count(*) FROM census_row),
                (SELECT count(*) FROM census_smear_result),
                (SELECT count(*) FROM household_form),
                (SELECT count(*) FROM household_row),
                (SELECT count(*) FROM census_row WHERE needs_review),
                (SELECT count(*) FROM household_row WHERE needs_review),
                (SELECT count(*) FROM census_row WHERE is_possible_duplicate),
                (SELECT count(*) FROM household_row WHERE is_possible_duplicate)
        """)
        row = cur.fetchone()
    keys = [
        "census_sheets", "census_rows", "smear_results", "household_forms", "household_rows",
        "census_flagged", "household_flagged", "census_dup", "household_dup",
    ]
    return dict(zip(keys, row))


def render_stats():
    stats = load_stats()
    cols = st.columns(5)
    cols[0].metric("Census sheets", stats["census_sheets"])
    cols[1].metric("Census rows (people)", stats["census_rows"])
    cols[2].metric("Smear results", stats["smear_results"])
    cols[3].metric("Household forms", stats["household_forms"])
    cols[4].metric("Household rows (people)", stats["household_rows"])
    st.caption(
        f"{stats['census_flagged']} census / {stats['household_flagged']} household row(s) flagged for review · "
        f"{stats['census_dup']} census / {stats['household_dup']} household row(s) marked as possible duplicates"
    )


def render_table_view(view_name: str, config: dict):
    base_sql = config["base"]
    where_clauses = []
    params: list = []

    search = st.text_input("Search name" if "search_col" in config and "people" in view_name.lower() else "Search", key=f"search_{view_name}")
    col1, col2, col3 = st.columns(3)
    with col1:
        page_min = st.number_input("Page from", min_value=1, max_value=512, value=1, step=1, key=f"pmin_{view_name}")
    with col2:
        page_max = st.number_input("Page to", min_value=1, max_value=512, value=512, step=1, key=f"pmax_{view_name}")
    with col3:
        review_filter = st.selectbox("Review status", ["All", "Needs review", "Clean"], key=f"rev_{view_name}")

    if search:
        where_clauses.append(f"{config['search_col']} ILIKE %s")
        params.append(f"%{search}%")
    where_clauses.append(f"{config['page_col']} BETWEEN %s AND %s")
    params.extend([page_min, page_max])
    if review_filter == "Needs review":
        where_clauses.append(f"{config['needs_review_col']}")
    elif review_filter == "Clean":
        where_clauses.append(f"NOT {config['needs_review_col']}")

    if config["duplicate_col"]:
        dup_only = st.checkbox("Only possible duplicates", key=f"dup_{view_name}")
        if dup_only:
            where_clauses.append(f"{config['duplicate_col']}")

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    count_sql = f"SELECT count(*) FROM ({base_sql} {where_sql}) t"
    total = scalar_count(count_sql, tuple(params))

    page_size = st.selectbox("Rows per page", PAGE_SIZE_OPTIONS, index=1, key=f"size_{view_name}")
    max_page = max((total - 1) // page_size, 0)
    page_num = st.number_input(
        f"Page (1-{max_page + 1})", min_value=1, max_value=max_page + 1, value=1, step=1, key=f"pgnum_{view_name}"
    )
    offset = (page_num - 1) * page_size

    data_sql = f"{base_sql} {where_sql} ORDER BY {config['order']} LIMIT %s OFFSET %s"
    df = run_query(data_sql, tuple(params + [page_size, offset]))

    st.caption(f"{total} row(s) match · showing {offset + 1}-{min(offset + page_size, total)}")
    st.dataframe(df, width="stretch", height=500)

    full_df = run_query(f"{base_sql} {where_sql} ORDER BY {config['order']}", tuple(params))
    st.download_button(
        "Download filtered result as CSV",
        data=full_df.to_csv(index=False).encode("utf-8"),
        file_name=f"{view_name.lower().replace(' ', '_')}.csv",
        mime="text/csv",
        key=f"dl_{view_name}",
    )


def render_custom_query():
    st.caption("Read-only SELECT queries against census_sheet, census_row, census_smear_result, household_form, household_row.")
    default_query = "SELECT * FROM census_row ORDER BY census_sheet_id, row_no LIMIT 100"
    query = st.text_area("SQL query", value=default_query, height=120)
    if st.button("Run query"):
        stripped = query.strip().rstrip(";")
        if not stripped.lower().startswith("select") and not stripped.lower().startswith("with"):
            st.error("Only SELECT (or WITH ... SELECT) queries are allowed here.")
            return
        try:
            df = run_query(stripped, ())
        except Exception as e:
            st.error(f"Query failed: {e}")
            return
        st.caption(f"{len(df)} row(s) returned")
        st.dataframe(df, width="stretch", height=500)
        st.download_button(
            "Download result as CSV",
            data=df.to_csv(index=False).encode("utf-8"),
            file_name="query_result.csv",
            mime="text/csv",
        )


def main():
    st.set_page_config(page_title="Census / Household Data Browser", layout="wide")
    st.title("Census / Household Data Browser")
    st.caption(f"Reading from Postgres database `{DB_NAME}` (loaded from db/export.sql)")

    try:
        render_stats()
    except psycopg2.OperationalError as e:
        st.error(
            f"Could not connect to database `{DB_NAME}`. Make sure it exists and Postgres is running.\n\n{e}"
        )
        return

    tab_names = list(VIEWS.keys()) + ["Custom SQL query"]
    tabs = st.tabs(tab_names)
    for tab, name in zip(tabs, tab_names):
        with tab:
            if name == "Custom SQL query":
                render_custom_query()
            else:
                render_table_view(name, VIEWS[name])


if __name__ == "__main__":
    main()
