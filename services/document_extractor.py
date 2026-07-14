import base64
import time
from enum import Enum
from typing import List, Optional, Tuple, Type

import anthropic
import cv2
import numpy as np
from pydantic import BaseModel

TRANSIENT_STRUCTURED_OUTPUT_ERRORS = ("Schema is too complex", "Grammar compilation timed out")

MODEL = "claude-opus-4-8"
CLASSIFICATION_MODEL = "claude-haiku-4-5-20251001"

CENSUS_SHEET_PROMPT = (
    "Transcribe this handwritten Census Sheet exactly as written. "
    "The 'Smear Dates and Results' section repeats as Date/+ -/ pairs per person — "
    "pair each smear date with its +/- result in the order they appear, one entry per exam. "
    "Leave a field null if illegible or blank rather than guessing. "
    "Only emit a row for numbered table rows that have a name written in the Name column — "
    "skip rows that are entirely blank. "
    "Some sheets have handwritten notes in the margin (e.g. a guest's name with an arrow "
    "pointing at a smear date) that fall outside the row/column grid — attach that date to "
    "the row it visually annotates rather than inventing a new row for it; if it can't be "
    "tied to an existing row, omit it rather than fabricating one."
)

HOUSEHOLD_FORM_PROMPT = (
    "Transcribe this handwritten Household Form (Malaria Survey) exactly as written. "
    "The header fields are Card No., House Number, Block Number, and Date Surveyed. "
    "The Sex column is two separate checkbox columns labeled M and F — record 'M' if the "
    "M box is checked, 'F' if the F box is checked, matching the single-letter convention "
    "used elsewhere in this pipeline; leave sex null if neither box is clearly marked. "
    "The Stated Age column may be written in months or years (e.g. '6 mos' or '34') — "
    "record the number in stated_age and record stated_age_unit as 'MONTHS' if "
    "months/mo/mos is written next to it, otherwise assume 'YEARS'; leave both null if the "
    "age is illegible or blank. "
    "The form instructs writing 'none' in the Symptoms column when there are no symptoms — "
    "transcribe exactly what is written there, including the literal word 'none' when "
    "that's what's written; only leave symptoms null if the cell itself was left entirely "
    "blank, not when it was filled in with 'none'. "
    "Leave any other field null if illegible or blank rather than guessing. "
    "Only emit a row for numbered table rows that have a name written in the Name column — "
    "skip rows that are entirely blank. "
    "Do not fabricate rows or infer values that aren't visibly written on the page."
)

CLASSIFICATION_PROMPT = (
    "Look at this scanned handwritten form and classify its layout. There are exactly "
    "two known layouts. CENSUS_SHEET: header has 'Date Censused', 'Sector', and 'Block' "
    "fields, and a 'Smear Dates and Results' section with repeating Date/+- pairs. "
    "HOUSEHOLD_FORM: header reads 'GREENTOWN HOUSEHOLD FORM - MALARIA SURVEY' and has "
    "'Card No.', 'HOUSE NUMBER', 'BLOCK NUMBER', 'DATE SURVEYED' fields, with a 'Symptoms' "
    "column and two separate M/F checkbox columns for sex. Classify based on the header "
    "title and field labels only, not the handwritten content. If the page doesn't clearly "
    "match either known layout (blank page, cover page, an unrecognized form), classify it "
    "as UNKNOWN rather than guessing."
)


class DocumentType(str, Enum):
    CENSUS_SHEET = "CENSUS_SHEET"
    HOUSEHOLD_FORM = "HOUSEHOLD_FORM"
    UNKNOWN = "UNKNOWN"


class DocumentClassification(BaseModel):
    document_type: DocumentType
    reason: Optional[str] = None


class SmearResult(BaseModel):
    smear_date: Optional[str] = None
    result: Optional[str] = None


class CensusRow(BaseModel):
    row_no: int
    name: str
    status: Optional[str] = None
    stated_age: Optional[int] = None
    sex: Optional[str] = None
    occupation: Optional[str] = None
    smear_results: List[SmearResult] = []


class CensusSheetExtraction(BaseModel):
    date_censused: Optional[str] = None
    sector: Optional[str] = None
    block: Optional[str] = None
    rows: List[CensusRow] = []


class HouseholdRow(BaseModel):
    row_no: int
    name: str
    status: Optional[str] = None
    stated_age: Optional[int] = None
    stated_age_unit: Optional[str] = None
    sex: Optional[str] = None
    symptoms: Optional[str] = None
    date_smear_taken: Optional[str] = None
    result_of_smear: Optional[str] = None
    date_treated: Optional[str] = None
    occupation: Optional[str] = None


class HouseholdFormHeader(BaseModel):
    card_no: Optional[str] = None
    house_number: Optional[str] = None
    block_number: Optional[str] = None
    date_surveyed: Optional[str] = None


class HouseholdFormExtraction(BaseModel):
    # header is nested (rather than 4 flat top-level optional fields, mirroring
    # CensusSheetExtraction's shape) because the flat version was rejected by the API
    # with "Schema is too complex." — verified empirically that nesting resolves it.
    header: HouseholdFormHeader = HouseholdFormHeader()
    rows: List[HouseholdRow] = []


class DocumentExtractor:

    def __init__(self):
        self.client = anthropic.Anthropic()

    def _parse_page(
        self, image: np.ndarray, prompt: str, output_format: Type[BaseModel], model: str, max_tokens: int = 4096
    ) -> BaseModel:
        ok, encoded = cv2.imencode(".png", image)
        image_data = base64.standard_b64encode(encoded.tobytes()).decode("utf-8")

        # The structured-output grammar compiler occasionally fails transiently on
        # schemas near its complexity limit (observed empirically: identical schema,
        # identical request, alternating pass/fail) — retry a couple times before
        # giving up rather than failing the whole page on a flake.
        attempts = 3
        for attempt in range(attempts):
            try:
                response = self.client.messages.parse(
                    model=model,
                    max_tokens=max_tokens,
                    messages=[{
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": image_data,
                                },
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }],
                    output_format=output_format,
                )
                return response.parsed_output
            except anthropic.BadRequestError as e:
                is_transient = any(msg in str(e) for msg in TRANSIENT_STRUCTURED_OUTPUT_ERRORS)
                if not is_transient or attempt == attempts - 1:
                    raise
                time.sleep(2)

    def classify_document(self, image: np.ndarray) -> DocumentClassification:
        return self._parse_page(
            image, CLASSIFICATION_PROMPT, DocumentClassification, model=CLASSIFICATION_MODEL, max_tokens=256
        )

    def extract_census_sheet(self, image: np.ndarray) -> CensusSheetExtraction:
        return self._parse_page(image, CENSUS_SHEET_PROMPT, CensusSheetExtraction, model=MODEL)

    def extract_household_form(self, image: np.ndarray) -> HouseholdFormExtraction:
        return self._parse_page(image, HOUSEHOLD_FORM_PROMPT, HouseholdFormExtraction, model=MODEL)

    def extract(self, image: np.ndarray) -> Tuple[DocumentType, Optional[BaseModel]]:
        classification = self.classify_document(image)
        if classification.document_type == DocumentType.CENSUS_SHEET:
            return DocumentType.CENSUS_SHEET, self.extract_census_sheet(image)
        if classification.document_type == DocumentType.HOUSEHOLD_FORM:
            return DocumentType.HOUSEHOLD_FORM, self.extract_household_form(image)
        return DocumentType.UNKNOWN, None
