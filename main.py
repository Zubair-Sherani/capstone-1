import os
import cv2

from services.pdf_reader import PDFReader
from services.image_preprocessor import ImagePreprocessor

OUTPUT_DIR = "output"

os.makedirs(OUTPUT_DIR, exist_ok=True)

reader = PDFReader()
preprocessor = ImagePreprocessor()

# 512-page PDF — load one page at a time to avoid running out of memory
page_num = 6
pages = reader.read("11.PDF", first_page=page_num, last_page=page_num)

print("Processing page:", page_num)
for i, page in enumerate(pages):
    cleaned = preprocessor.preprocess(page)
    cv2.imwrite(f"{OUTPUT_DIR}/page_{page_num:04}.png", cleaned)

print("Finished.")