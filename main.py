import argparse
import json
import os

import cv2
from dotenv import load_dotenv

from services.pdf_reader import PDFReader
from services.image_preprocessor import ImagePreprocessor
from services.document_extractor import DocumentExtractor, DocumentType

load_dotenv()


def parse_args():
    parser = argparse.ArgumentParser(
        description="Extract and preprocess pages from a scanned PDF."
    )
    parser.add_argument("pdf_path", help="Path to the source PDF")
    parser.add_argument(
        "--first-page", type=int, default=1, help="First page to process (1-indexed, default: 1)"
    )
    parser.add_argument(
        "--last-page", type=int, default=None, help="Last page to process (default: same as --first-page)"
    )
    parser.add_argument(
        "--output-dir", default="output", help="Directory to write processed pages to (default: output)"
    )
    parser.add_argument(
        "--extract", action="store_true",
        help="Also run OCR extraction (Claude) on each page and write page_NNNN.json"
    )
    return parser.parse_args()


def main():
    args = parse_args()
    last_page = args.last_page if args.last_page is not None else args.first_page

    os.makedirs(args.output_dir, exist_ok=True)

    reader = PDFReader()
    preprocessor = ImagePreprocessor()
    extractor = DocumentExtractor() if args.extract else None

    # Pages are loaded one at a time (via first_page/last_page) to avoid
    # running out of memory on large, multi-hundred-page scans.
    pages = reader.read(args.pdf_path, first_page=args.first_page, last_page=last_page)

    for offset, page in enumerate(pages):
        page_num = args.first_page + offset
        print("Processing page:", page_num)
        cleaned = preprocessor.preprocess(page)
        cv2.imwrite(f"{args.output_dir}/page_{page_num:04}.png", cleaned)

        if extractor is not None:
            print("Extracting page:", page_num)
            doc_type, extraction = extractor.extract(cleaned)
            if doc_type == DocumentType.UNKNOWN:
                print(f"  WARNING: page {page_num} did not match a known layout — flagged UNKNOWN for manual review")
            output = {
                "document_type": doc_type.value,
                "data": extraction.model_dump() if extraction is not None else None,
            }
            with open(f"{args.output_dir}/page_{page_num:04}.json", "w") as f:
                json.dump(output, f, indent=2)

    print("Finished.")


if __name__ == "__main__":
    main()
