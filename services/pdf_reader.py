from pdf2image import convert_from_path
import cv2
import numpy as np


class PDFReader:

    def read(self, pdf_path, dpi=300, first_page=None, last_page=None):
        kwargs = {"dpi": dpi}
        if first_page is not None:
            kwargs["first_page"] = first_page
        if last_page is not None:
            kwargs["last_page"] = last_page

        pages = convert_from_path(pdf_path, **kwargs)

        images = []
        for page in pages:
            image = np.array(page)
            image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
            images.append(image)

        return images