-- Target data model for extracted documents.
-- Source: handwritten Census Sheet and Clinic Summary Form ledgers.

-- ==========================================================
-- Census Sheet
-- ==========================================================

CREATE TABLE census_sheet (
    id             SERIAL PRIMARY KEY,
    source_file    TEXT NOT NULL,
    page_number    INT,
    date_censused  DATE,
    sector         TEXT,
    block          TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE census_row (
    id               SERIAL PRIMARY KEY,
    census_sheet_id  INT NOT NULL REFERENCES census_sheet(id) ON DELETE CASCADE,
    row_no           INT NOT NULL,
    name             TEXT NOT NULL,
    status           TEXT,   -- e.g. HEAD, WIFE, S (son), D (daughter)
    stated_age       INT,
    sex              CHAR(1),  -- M / F
    occupation       TEXT
);

CREATE TABLE census_smear_result (
    id             SERIAL PRIMARY KEY,
    census_row_id  INT NOT NULL REFERENCES census_row(id) ON DELETE CASCADE,
    smear_date     DATE,
    result         TEXT  -- '+' / '-'
);

-- ==========================================================
-- Clinic Summary Form
-- ==========================================================

CREATE TABLE clinic_report (
    id           SERIAL PRIMARY KEY,
    source_file  TEXT NOT NULL,
    page_number  INT,
    house_no     TEXT,
    block_no     TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE clinic_row (
    id                SERIAL PRIMARY KEY,
    clinic_report_id  INT NOT NULL REFERENCES clinic_report(id) ON DELETE CASCADE,
    row_no            INT NOT NULL,
    name              TEXT NOT NULL,
    age               INT,
    sex               CHAR(1)  -- M / F
);

CREATE TABLE clinic_visit (
    id             SERIAL PRIMARY KEY,
    clinic_row_id  INT NOT NULL REFERENCES clinic_row(id) ON DELETE CASCADE,
    visit_date     DATE,
    notes          TEXT  -- raw diagnosis/treatment text as written
);
