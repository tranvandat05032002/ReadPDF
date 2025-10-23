# Xử lý OCR

import os, io
from typing import Tuple
from pdfminer.high_level import extract_text as pdf_extract_text
from PIL import Image
import pytesseract
import pypdfium2 as pdfium


SUPPORTED_IMG = {"png","jpg","jpeg","bmp","tif","tiff"}


# Cho Windows: nếu có biến env TESSERACT_CMD thì dùng
TESSERACT_CMD = os.getenv("TESSERACT_CMD")
if TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD




def mime_to_ext(mime: str) -> str:
    return {
        "image/png":"png","image/jpeg":"jpg","image/jpg":"jpg",
        "image/bmp":"bmp","image/tiff":"tiff","image/tif":"tif",
        "application/pdf":"pdf"
    }.get((mime or "").lower(), "")




def extract_text_bytes(data: bytes, mime: str, ocr_langs: str = "eng") -> Tuple[str, str]:
    """Trả về (text, mode). mode in {"pdf_text","pdf_ocr","image_ocr"}
    - PDF: thử lấy text layer bằng pdfminer; nếu rỗng → raster từng trang bằng pdfium rồi OCR.
    - Ảnh: OCR trực tiếp.
    """
    ext = mime_to_ext(mime)
    if ext == "pdf":
        text = pdf_extract_text(io.BytesIO(data)) or ""
        if text.strip():
            return text, "pdf_text"
        # OCR từng trang
        text_pages = []
        pdf = pdfium.PdfDocument(data)
        for page_index in range(len(pdf)):
            page = pdf.get_page(page_index)
            bitmap = page.render(scale=2.0).to_pil()
            txt = pytesseract.image_to_string(bitmap, lang=ocr_langs)
            if txt:
                text_pages.append(txt)
        return "\n".join(text_pages), "pdf_ocr"
    else:
        im = Image.open(io.BytesIO(data))
        txt = pytesseract.image_to_string(im, lang=ocr_langs)
        return txt, "image_ocr"