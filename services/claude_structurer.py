import json
import anthropic


_CENSUS_SCHEMA = {
    "type": "object",
    "properties": {
        "records": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name":       {"type": "string"},
                    "status":     {"type": "string"},
                    "stated_age": {"type": "string"},
                    "sex":        {"type": "string"},
                    "occupation": {"type": "string"},
                    "smear_results": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "date":   {"type": "string"},
                                "result": {"type": "string"},
                            },
                            "required": ["date", "result"],
                            "additionalProperties": False,
                        },
                    },
                    "confidence": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                    },
                },
                "required": [
                    "name", "status", "stated_age", "sex",
                    "occupation", "smear_results", "confidence",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["records"],
    "additionalProperties": False,
}


class ClaudeStructurer:
    """Reconstructs census table structure from OCR text + bounding boxes.

    Sends text-only data to Claude (no images) to keep API costs low.
    """

    def __init__(self, model: str = "claude-opus-5"):
        self._client = anthropic.Anthropic()
        self._model = model

    def structure(
        self,
        regions: list[dict],
        image_width: int,
        image_height: int,
    ) -> dict:
        """Return structured census records from OCR region list.

        Args:
            regions: [{text, trocr_text, bbox (x,y,w,h), confidence}, ...]
            image_width: full image width in pixels (used for column mapping)
            image_height: full image height in pixels
        """
        prompt = self._build_prompt(regions, image_width, image_height)

        with self._client.messages.stream(
            model=self._model,
            max_tokens=8192,
            output_config={
                "format": {
                    "type": "json_schema",
                    "schema": _CENSUS_SCHEMA,
                }
            },
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            response = stream.get_final_message()

        text = next(
            (b.text for b in response.content if b.type == "text"), "{}"
        )
        return json.loads(text)

    def _build_prompt(
        self,
        regions: list[dict],
        image_width: int,
        image_height: int,
    ) -> str:
        header = [
            "You are reconstructing records from a 1980 Pakistan census form scanned at 300 DPI.",
            "",
            "IMPORTANT — the page is rotated 90°. The form layout is TRANSPOSED:",
            "  • The Y-axis maps to form FIELDS (columns in the original form).",
            "  • The X-axis maps to individual PEOPLE (rows in the original form).",
            "",
            "Field layout along the Y-axis (measured from detected form headers):",
            "  Name:            y = 0  – 700",
            "  Status:          y = 700 – 930   (Head, Wife, Son, Daughter, Brother, …)",
            "  Stated Age:      y = 930 – 1200",
            "  Sex:             y = 1200 – 1470  (M or F)",
            "  Occupation:      y = 1470 – 1900",
            "  Smear results:   y = 1900+        (alternating date / result sub-fields)",
            "",
            "Each person occupies a vertical strip ~60–100 px wide along the X-axis.",
            "Group regions with similar x-coordinates (within ~80 px) as one person.",
            "",
            f"Image size: {image_width}×{image_height} px.",
            "",
            "OCR regions (format: [id] bbox=(x,y,w,h) paddle=\"…\" trocr=\"…\" conf=score):",
            "  paddle = PaddleOCR reading (better for printed text)",
            "  trocr  = TrOCR reading (better for handwriting)",
            "  Use whichever reading looks like real words/numbers; ignore obvious noise.",
            "  — sorted left-to-right (x), then top-to-bottom (y) within each person.",
            "",
        ]

        # Sort by x first (person), then y (field within that person)
        sorted_regions = sorted(
            regions, key=lambda r: (r["bbox"][0], r["bbox"][1])
        )

        rows = []
        for i, r in enumerate(sorted_regions):
            x, y, w, h = r["bbox"]
            paddle_text = r.get("text", "")
            trocr_text = r.get("trocr_text", "")
            conf = r.get("confidence", 0.0)
            # Show both readings; Claude picks whichever looks like real text
            rows.append(
                f"  [{i:03d}] bbox=({x},{y},{w},{h})  "
                f"paddle=\"{paddle_text}\"  trocr=\"{trocr_text}\"  conf={conf:.2f}"
            )

        footer = [
            "",
            "Instructions:",
            "1. Group regions with similar x-coordinates (within ~80 px) as one person.",
            "2. Within each person's group, assign text to the field by its y-coordinate.",
            "3. Combine multi-fragment text (e.g. first + last name) in reading order.",
            "4. Skip form header labels ('Name', 'Status', 'Occupation', 'Sex', 'Stated', etc.).",
            "5. Mark confidence='low' for illegible or fragmented entries.",
            "6. Include every identifiable person — do not skip partial records.",
        ]

        return "\n".join(header + rows + footer)
