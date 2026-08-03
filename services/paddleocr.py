import numpy as np
import cv2
from paddleocr import PaddleOCR


class PaddleOCRService:
    def __init__(self, lang: str = "en"):
        # Disable orientation/unwarping — they internally rotate the image and
        # return bboxes in the rotated coordinate space, which breaks TrOCR crops.
        # The census form is always in a known orientation, so no correction needed.
        self._ocr = PaddleOCR(lang=lang)

    def extract(self, image: np.ndarray) -> list[dict]:
        """Detect text regions; return list of {text, confidence, bbox (x,y,w,h)}."""
        results = self._ocr.predict(image)
        regions = []
        for page_result in results:
            regions.extend(self._parse_page_result(page_result))
        return regions

    def _parse_page_result(self, page_result) -> list[dict]:
        regions = []
        try:
            # Newer PaddleOCR (v4 / PaddleX) — dict-like result object
            texts = (
                page_result.get("rec_text")
                or page_result.get("rec_texts")
                or []
            )
            scores = (
                page_result.get("rec_score")
                or page_result.get("rec_scores")
                or [1.0] * len(texts)
            )
            polys = (
                page_result.get("dt_polys")
                or page_result.get("dt_poly")
                or []
            )
            for text, score, poly in zip(texts, scores, polys):
                regions.append({
                    "text": text,
                    "confidence": float(score),
                    "bbox": self._poly_to_rect(np.array(poly)),
                })
        except (AttributeError, TypeError):
            # Old PaddleOCR API — list of [[bbox_points, (text, score)], ...]
            for line in page_result or []:
                if line is None:
                    continue
                try:
                    bbox_points, (text, score) = line
                    regions.append({
                        "text": text,
                        "confidence": float(score),
                        "bbox": self._poly_to_rect(np.array(bbox_points)),
                    })
                except (ValueError, TypeError):
                    continue
        return regions

    def _poly_to_rect(self, poly: np.ndarray) -> tuple:
        """Convert polygon points to (x, y, w, h) axis-aligned bounding rect."""
        x, y, w, h = cv2.boundingRect(poly.reshape(-1, 1, 2).astype(np.int32))
        return (x, y, w, h)
