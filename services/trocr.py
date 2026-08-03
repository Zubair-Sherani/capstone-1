import numpy as np
import cv2
from PIL import Image
from transformers import TrOCRProcessor, VisionEncoderDecoderModel
import torch


class TrOCRService:
    MODEL_ID = "microsoft/trocr-large-handwritten"

    def __init__(self):
        self._processor = TrOCRProcessor.from_pretrained(self.MODEL_ID)
        self._model = VisionEncoderDecoderModel.from_pretrained(self.MODEL_ID)
        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        self._model.to(self._device)
        self._model.eval()

    def recognize(self, image_crop: np.ndarray) -> str:
        """Recognize handwritten text in a single cropped region."""
        if image_crop.size == 0:
            return ""
        if len(image_crop.shape) == 2:
            pil_img = Image.fromarray(image_crop).convert("RGB")
        else:
            pil_img = Image.fromarray(cv2.cvtColor(image_crop, cv2.COLOR_BGR2RGB))

        pixel_values = self._processor(
            images=pil_img, return_tensors="pt"
        ).pixel_values.to(self._device)

        with torch.no_grad():
            generated_ids = self._model.generate(pixel_values, max_new_tokens=128)

        return self._processor.batch_decode(
            generated_ids, skip_special_tokens=True
        )[0].strip()

    def recognize_regions(
        self, image: np.ndarray, regions: list[dict]
    ) -> list[dict]:
        """Crop each bbox from image and run TrOCR; adds 'trocr_text' key."""
        h_img, w_img = image.shape[:2]
        enriched = []
        for region in regions:
            x, y, w, h = region["bbox"]
            x1, y1 = max(x, 0), max(y, 0)
            x2, y2 = min(x + w, w_img), min(y + h, h_img)
            if x2 <= x1 or y2 <= y1:
                enriched.append({**region, "trocr_text": ""})
                continue
            crop = image[y1:y2, x1:x2]
            enriched.append({**region, "trocr_text": self.recognize(crop)})
        return enriched
