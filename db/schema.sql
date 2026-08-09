-- Target data model for extracted documents.
-- Source: handwritten Census Sheet and Household Form (Malaria Survey) ledgers.
--
-- Review/dedup columns mirror services/normalizer.py's NormalizedValue-wrapped
-- fields and services/dedup.py's duplicate-detection output.

-- ==========================================================
-- Census Sheet
-- ==========================================================

CREATE TABLE census_sheet (
    id             SERIAL PRIMARY KEY,
    source_file    TEXT NOT NULL,
    page_number    INT,
    date_censused_raw  TEXT,
    date_censused  DATE,
    sector         TEXT,
    block          TEXT,
    needs_review   BOOLEAN NOT NULL DEFAULT FALSE,
    review_reasons TEXT[] NOT NULL DEFAULT '{}',
    reviewed       BOOLEAN NOT NULL DEFAULT FALSE,
    reviewed_by    TEXT,
    reviewed_at    TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE census_row (
    id               SERIAL PRIMARY KEY,
    census_sheet_id  INT NOT NULL REFERENCES census_sheet(id) ON DELETE CASCADE,
    row_no           INT NOT NULL,
    name             TEXT NOT NULL,
    status_raw       TEXT,
    status           TEXT,   -- e.g. HEAD, WIFE, SON, DAUGHTER, GUEST, OTHER
    stated_age       INT,
    sex_raw          TEXT,
    sex              CHAR(1),  -- M / F
    occupation       TEXT,
    needs_review          BOOLEAN NOT NULL DEFAULT FALSE,
    review_reasons        TEXT[] NOT NULL DEFAULT '{}',
    is_possible_duplicate BOOLEAN NOT NULL DEFAULT FALSE,
    duplicate_of_source_file    TEXT,
    duplicate_of_page_number    INT,
    duplicate_of_row_no         INT,
    duplicate_of_document_type  TEXT,
    reviewed       BOOLEAN NOT NULL DEFAULT FALSE,
    reviewed_by    TEXT,
    reviewed_at    TIMESTAMPTZ
);

CREATE TABLE census_smear_result (
    id             SERIAL PRIMARY KEY,
    census_row_id  INT NOT NULL REFERENCES census_row(id) ON DELETE CASCADE,
    smear_date_raw TEXT,
    smear_date     DATE,
    result_raw     TEXT,
    result         TEXT  -- POSITIVE / NEGATIVE / UNKNOWN
);

-- ==========================================================
-- Household Form (Malaria Survey)
-- ==========================================================

CREATE TABLE household_form (
    id             SERIAL PRIMARY KEY,
    source_file    TEXT NOT NULL,
    page_number    INT,
    card_no        TEXT,
    house_number   TEXT,
    block_number   TEXT,
    date_surveyed_raw  TEXT,
    date_surveyed  DATE,
    needs_review   BOOLEAN NOT NULL DEFAULT FALSE,
    review_reasons TEXT[] NOT NULL DEFAULT '{}',
    reviewed       BOOLEAN NOT NULL DEFAULT FALSE,
    reviewed_by    TEXT,
    reviewed_at    TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE household_row (
    id                 SERIAL PRIMARY KEY,
    household_form_id  INT NOT NULL REFERENCES household_form(id) ON DELETE CASCADE,
    row_no             INT NOT NULL,
    name               TEXT NOT NULL,
    status_raw         TEXT,
    status             TEXT,   -- e.g. HEAD, WIFE, SON, DAUGHTER, GUEST, OTHER
    stated_age         INT,
    stated_age_unit_raw TEXT,
    stated_age_unit    TEXT,  -- YEARS / MONTHS
    sex_raw            TEXT,
    sex                CHAR(1),  -- M / F
    occupation         TEXT,
    symptoms_raw       TEXT,
    symptoms           TEXT,  -- NONE / PRESENT
    date_smear_taken_raw  TEXT,
    date_smear_taken   DATE,
    result_of_smear_raw   TEXT,
    result_of_smear    TEXT,  -- POSITIVE / NEGATIVE / UNKNOWN
    date_treated_raw   TEXT,
    date_treated       DATE,
    needs_review          BOOLEAN NOT NULL DEFAULT FALSE,
    review_reasons        TEXT[] NOT NULL DEFAULT '{}',
    is_possible_duplicate BOOLEAN NOT NULL DEFAULT FALSE,
    duplicate_of_source_file    TEXT,
    duplicate_of_page_number    INT,
    duplicate_of_row_no         INT,
    duplicate_of_document_type  TEXT,
    reviewed       BOOLEAN NOT NULL DEFAULT FALSE,
    reviewed_by    TEXT,
    reviewed_at    TIMESTAMPTZ
);
