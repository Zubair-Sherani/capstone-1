import os
import json
import cv2
from dotenv import load_dotenv

load_dotenv()

from services.pdf_reader import PDFReader
from services.image_preprocessor import ImagePreprocessor
from services.paddleocr import PaddleOCRService
from services.trocr import TrOCRService
from services.claude_structurer import ClaudeStructurer

OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

reader = PDFReader()
preprocessor = ImagePreprocessor()
paddle_svc = PaddleOCRService()
trocr_svc = TrOCRService()
claude_svc = ClaudeStructurer()

page_num = 5
pages = reader.read("11.PDF", first_page=page_num, last_page=page_num)

for page in pages:
    print(f"Processing page {page_num}...")

    cleaned = preprocessor.preprocess(page)
    cv2.imwrite(f"{OUTPUT_DIR}/page_{page_num:04}.png", cleaned)

    print("  Running PaddleOCR layout detection...")
    regions = paddle_svc.extract(page)
    print(f"  Found {len(regions)} text regions")

    print("  Running TrOCR on each region...")
    regions = trocr_svc.recognize_regions(page, regions)

    print("  Sending to Claude for table reconstruction...")
    h, w = page.shape[:2]
    structured = claude_svc.structure(regions, image_width=w, image_height=h)

    out_path = f"{OUTPUT_DIR}/page_{page_num:04}_records.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(structured, f, indent=2, ensure_ascii=False)

    print(f"  Saved {len(structured.get('records', []))} records to {out_path}")

print("Finished.")
