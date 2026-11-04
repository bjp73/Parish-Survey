"""Orient, register, optionally OCR, and rectify one survey PDF page.

Python packages:
    python -m pip install pymupdf opencv-python numpy pytesseract

Tesseract OCR is only required when ``return_barcode_data=True`` (the default).
On Windows, add tesseract.exe to PATH or pass its path via ``tesseract_cmd``.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence, overload, Literal
import cv2
import fitz
import numpy as np
import pytesseract
from io import BytesIO
import csv
import PIL.Image
sys.path.append(r"C:\GIT\MPG") 
import general_routines as gr
from datetime import datetime as dt


from openpyxl import Workbook
from openpyxl.drawing.image import Image


class SurveyProcessingError(RuntimeError):
    """Raised when a survey page cannot be validated or registered."""


class BarcodeReadError(SurveyProcessingError):
    """OCR failure containing the cropped barcode region as PNG bytes.

    Attributes:
        barcode_png: PNG bytes for the barcode alignment-box crop.
    """

    def __init__(self, message: str, barcode_png: bytes):
        super().__init__(message)
        self.barcode_png = barcode_png

    def save_barcode_crop(self, output_file: str | Path) -> None:
        """Save the diagnostic barcode crop carried by this error."""
        Path(output_file).write_bytes(self.barcode_png)


class BlueTextOCRError(RuntimeError):
    """Raised when sufficient blue content exists but OCR cannot read it."""


def read_blue_text(
    png_image: str | Path | bytes,
    min_blue_pixels: int,
    min_blue: int = 100,
    blue_margin: int = 30,
    tesseract_cmd: str | Path | None = None,
) -> str | None:
    """
    Apply OCR only to blue content in a PNG image.

    A pixel is considered blue when:
        blue >= min_blue
        blue >= red + blue_margin
        blue >= green + blue_margin

    Parameters
    ----------
    png_image:
        Path to a PNG file, or PNG image data as bytes.

    min_blue_pixels:
        Minimum number of blue pixels required before OCR is attempted.

    min_blue:
        Minimum permitted intensity of the blue channel, from 0 to 255.

    blue_margin:
        Amount by which blue must exceed both red and green.

    tesseract_cmd:
        Optional path to the Tesseract executable. For example:
        r"C:\\Program Files\\Tesseract-OCR\\tesseract.exe"

    Returns
    -------
    str | None:
        Recognised blue text as a string.

        Returns None if the image contains fewer than min_blue_pixels
        qualifying blue pixels.

    Raises
    ------
    FileNotFoundError:
        If an input filename does not exist.

    ValueError:
        If an input threshold is invalid.

    BlueTextOCRError:
        If sufficient blue pixels exist but OCR cannot decipher any text.
    """

    if min_blue_pixels < 0:
        raise ValueError("min_blue_pixels must be zero or greater")

    if not 0 <= min_blue <= 255:
        raise ValueError("min_blue must be between 0 and 255")

    if not 0 <= blue_margin <= 255:
        raise ValueError("blue_margin must be between 0 and 255")

    if tesseract_cmd is not None:
        pytesseract.pytesseract.tesseract_cmd = str(tesseract_cmd)

    # Open either a filename or PNG bytes.
    if isinstance(png_image, bytes):
        image = PIL.Image.open(BytesIO(png_image)).convert("RGB")
    else:
        image_path = Path(png_image)

        if not image_path.is_file():
            raise FileNotFoundError(f"PNG image not found: {image_path}")

        image = PIL.Image.open(image_path).convert("RGB")

    image_array = np.asarray(image)

    # Convert to signed integers before adding blue_margin. This avoids
    # overflow because ordinary image arrays use unsigned 8-bit integers.
    red = image_array[:, :, 0].astype(np.int16)
    green = image_array[:, :, 1].astype(np.int16)
    blue = image_array[:, :, 2].astype(np.int16)

    blue_mask = (
        (blue >= min_blue)
        & (blue >= red + blue_margin)
        & (blue >= green + blue_margin)
    )

    blue_pixel_count = int(np.count_nonzero(blue_mask))

    # Insufficient blue content is not considered an OCR error.
    if blue_pixel_count < min_blue_pixels:
        return None

    # Produce a high-contrast OCR image:
    # qualifying blue pixels become black; everything else becomes white.
    ocr_array = np.full(
        (image_array.shape[0], image_array.shape[1]),
        255,
        dtype=np.uint8,
    )
    ocr_array[blue_mask] = 0

    ocr_image = PIL.Image.fromarray(ocr_array, mode="L")

    try:
        text = pytesseract.image_to_string(
            ocr_image,
            config="--oem 3 --psm 6",
        ).strip()
    except Exception as exc:
        raise BlueTextOCRError(
            f"OCR could not be applied to the blue text: {exc}"
        ) from exc

    if not text:
        raise BlueTextOCRError(
            f"Found {blue_pixel_count} qualifying blue pixels but OCR could not decipher any text."
        )

    return text
    

def has_blue_pixels(
    png_data,
    min_pixels,
    min_blue=100,
    blue_margin=30,
):
    """
    Returns True if the image contains more than min_pixels blue pixels.

    Parameters
    ----------
    png_data: png binary data
        Input PNG file.

    min_pixels : int
        Minimum number of blue pixels required.

    min_blue : int
        Minimum blue channel intensity.

    r_g_max : int
        both red and green must be less than this amount.

    Returns
    -------
    bool
    """
    image = np.array(PIL.Image.open(BytesIO(png_data)).convert("RGB"))

#    image = np.array(PIL.Image.open(png_file).convert("RGB"))

    r = image[:, :, 0]
    g = image[:, :, 1]
    b = image[:, :, 2]

    blue_mask = (
        (b >= min_blue)
        & (b - blue_margin > r )
        & (b - blue_margin > g )
    )

    return np.count_nonzero(blue_mask) > min_pixels




def crop_png(
    png_data: bytes,
    coords: Sequence[float],
    output_file: str | Path | None = None,
) -> bytes:
    """
    Crop a PNG image using normalized coordinates.

    Parameters
    ----------
    png_file : bytes
        Input PNG image as binary file.

    coords : [x1, y1, x2, y2]
        Normalized coordinates where:
            (0,0) = top left
            (1,0) = top right
            (0,1) = bottom left
            (1,1) = bottom right

    output_file : str or Path, optional
        If supplied, save the cropped PNG.

    Returns
    -------
    bytes
        PNG image data.
    """

    if len(coords) != 4:
        raise ValueError("coords must contain [x1, y1, x2, y2]")

    x1, y1, x2, y2 = map(float, coords)

    if not (0 <= x1 < x2 <= 1):
        raise ValueError("Require 0 <= x1 < x2 <= 1")

    if not (0 <= y1 < y2 <= 1):
        raise ValueError("Require 0 <= y1 < y2 <= 1")

    # Open PNG directly from binary data
#    with Image.open(BytesIO(png_data)) as image:
    with PIL.Image.open(BytesIO(png_data)) as image:
        width, height = image.size

        left = round(x1 * width)
        top = round(y1 * height)
        right = round(x2 * width)
        bottom = round(y2 * height)

        cropped = image.crop((left, top, right, bottom))

        buffer = BytesIO()
        cropped.save(buffer, format="PNG")
        png_bytes = buffer.getvalue()

    if output_file is not None:
        Path(output_file).write_bytes(png_bytes)

    return png_bytes
    


def _load_json(path: str | Path) -> Mapping[str, Any]:
    try:
        with Path(path).open("r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except Exception as exc:
        raise SurveyProcessingError(f"Cannot open or parse JSON file '{path}': {exc}") from exc
    if not isinstance(data, Mapping):
        raise SurveyProcessingError("The JSON root must be an object")
    return data


def _render_page(pdf_file: str | Path, page_number: int, dpi: int) -> np.ndarray:
    if not isinstance(page_number, int) or isinstance(page_number, bool):
        raise SurveyProcessingError("page_number must be an integer using 1-based numbering")
    if dpi <= 0:
        raise SurveyProcessingError("dpi must be greater than zero")
    try:
        document = fitz.open(pdf_file)
    except Exception as exc:
        raise SurveyProcessingError(f"Cannot open PDF file '{pdf_file}': {exc}") from exc
    try:
        if document.needs_pass:
            raise SurveyProcessingError("The PDF is password protected")
        if not 1 <= page_number <= document.page_count:
            raise SurveyProcessingError(
                f"Invalid page number {page_number}; PDF contains {document.page_count} page(s)"
            )
        pixmap = document.load_page(page_number - 1).get_pixmap(
            matrix=fitz.Matrix(dpi / 72.0, dpi / 72.0), alpha=False
        )
        pixels = np.frombuffer(pixmap.samples, np.uint8).reshape(
            pixmap.height, pixmap.width, pixmap.n
        )
        conversion = cv2.COLOR_RGBA2BGR if pixmap.n == 4 else cv2.COLOR_RGB2BGR
        return cv2.cvtColor(pixels, conversion)
    except SurveyProcessingError:
        raise
    except Exception as exc:
        raise SurveyProcessingError(f"Cannot render PDF page: {exc}") from exc
    finally:
        document.close()


def _pixel_box(box: Sequence[float], width: int, height: int) -> tuple[int, int, int, int]:
    try:
        x1, y1, x2, y2 = map(float, box)
    except Exception as exc:
        raise SurveyProcessingError(f"Invalid four-value coordinate box: {box!r}") from exc
    if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
        raise SurveyProcessingError(f"Invalid Page Coordinate box: {box!r}")
    return (
        int(round(x1 * width)), int(round(y1 * height)),
        int(round(x2 * width)), int(round(y2 * height)),
    )


def _dark_mask(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    return cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]


def _triangle_score(image: np.ndarray, box: Sequence[float]) -> float:
    height, width = image.shape[:2]
    x1, y1, x2, y2 = _pixel_box(box, width, height)
    mask = _dark_mask(image[y1:y2, x1:x2])
    region_area = float(mask.shape[0] * mask.shape[1])
    best = 0.0
    for contour in cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
        area = cv2.contourArea(contour)
        if not 0.015 * region_area <= area <= 0.85 * region_area:
            continue
        perimeter = cv2.arcLength(contour, True)
        if perimeter <= 0:
            continue
        vertex_count = len(cv2.approxPolyDP(contour, 0.045 * perimeter, True))
        _, _, w, h = cv2.boundingRect(contour)
        if min(w, h) < 5 or vertex_count not in (3, 4):
            continue
        fill = area / float(w * h)
        best = max(best, (1.0 if vertex_count == 3 else 0.72) * fill * (area / region_area) ** 0.5)
    return best


def _orient(image: np.ndarray, boxes: Mapping[str, Any]) -> np.ndarray:
    try:
        top_score = _triangle_score(image, boxes["top_centre_triangle"])
        bottom_score = _triangle_score(image, boxes["bottom_centre_triangle"])
    except KeyError as exc:
        raise SurveyProcessingError(f"Missing triangle search box: {exc.args[0]}") from exc
    if max(top_score, bottom_score) < 0.055:
        raise SurveyProcessingError(
            f"No black triangle detected (top={top_score:.3f}, bottom={bottom_score:.3f})"
        )
    return cv2.rotate(image, cv2.ROTATE_180) if bottom_score > top_score else image


def _square_bounds(image: np.ndarray, box: Sequence[float], name: str) -> tuple[int, int, int, int]:
    height, width = image.shape[:2]
    sx1, sy1, sx2, sy2 = _pixel_box(box, width, height)
    mask = cv2.morphologyEx(
        _dark_mask(image[sy1:sy2, sx1:sx2]),
        cv2.MORPH_CLOSE,
        np.ones((3, 3), np.uint8),
    )
    region_area = float(mask.shape[0] * mask.shape[1])
    candidates = []
    for contour in cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
        area = cv2.contourArea(contour)
        x, y, w, h = cv2.boundingRect(contour)
        if not 0.008 * region_area <= area <= 0.8 * region_area or min(w, h) < 5:
            continue
        aspect = w / h
        fill = area / (w * h)
        vertices = len(cv2.approxPolyDP(contour, 0.04 * cv2.arcLength(contour, True), True))
        if 0.65 <= aspect <= 1.5 and fill >= 0.55 and 4 <= vertices <= 6:
            score = fill - abs(1 - aspect) * 0.2 + min(area / region_area, 0.25)
            candidates.append((score, (sx1 + x, sy1 + y, sx1 + x + w - 1, sy1 + y + h - 1)))
    if not candidates:
        raise SurveyProcessingError(f"Alignment square '{name}' was not located")
    return max(candidates, key=lambda item: item[0])[1]


def _alignment_corners(image: np.ndarray, boxes: Mapping[str, Any]) -> np.ndarray:
    names = ("top_left_square", "top_right_square", "bottom_left_square", "bottom_right_square")
    missing = [name for name in names if name not in boxes]
    if missing:
        raise SurveyProcessingError("Missing square search box(es): " + ", ".join(missing))
    bounds = {name: _square_bounds(image, boxes[name], name) for name in names}
    tl, tr = bounds["top_left_square"], bounds["top_right_square"]
    bl, br = bounds["bottom_left_square"], bounds["bottom_right_square"]
    corners = np.float32([
        [tl[2], tl[3]], [tr[0], tr[3]], [br[0], br[1]], [bl[2], bl[1]]
    ])
    if cv2.contourArea(corners) <= 0:
        raise SurveyProcessingError("Alignment corners do not form a valid quadrilateral")
    return corners


def _barcode_boxes(data: Mapping[str, Any]) -> list[list[float]]:
    try:
        raw = data["barcode"]["alignment_box"]
    except (KeyError, TypeError) as exc:
        raise SurveyProcessingError("JSON does not contain barcode.alignment_box") from exc
    if isinstance(raw, Sequence) and len(raw) == 4 and all(isinstance(v, (int, float)) for v in raw):
        raw = [raw]
    if not isinstance(raw, Sequence) or not raw:
        raise SurveyProcessingError("barcode.alignment_box must contain at least one box")
    boxes = []
    for item in raw:
        if not isinstance(item, Sequence) or len(item) != 4:
            raise SurveyProcessingError(f"Invalid barcode alignment box: {item!r}")
        boxes.append(list(map(float, item)))
    return boxes


def _alignment_homography(corners: np.ndarray) -> np.ndarray:
    unit = np.float32([[0, 0], [1, 0], [1, 1], [0, 1]])
    return cv2.getPerspectiveTransform(unit, corners)


def _map_points(points: Sequence[Sequence[float]], transform: np.ndarray) -> np.ndarray:
    values = np.float32(points).reshape(-1, 1, 2)
    return cv2.perspectiveTransform(values, transform).reshape(-1, 2)


def _extract_quad(image: np.ndarray, quad: np.ndarray, scale: float = 6.0) -> np.ndarray:
    tl, tr, br, bl = np.float32(quad)
    width = max(20, int(round(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)) * scale)))
    height = max(20, int(round(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)) * scale)))
    destination = np.float32([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]])
    matrix = cv2.getPerspectiveTransform(np.float32(quad), destination)
    return cv2.warpPerspective(
        image, matrix, (width, height), flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def _encode_png(image: np.ndarray) -> bytes:
    success, encoded = cv2.imencode(".png", image, [cv2.IMWRITE_PNG_COMPRESSION, 3])
    if not success:
        raise SurveyProcessingError("OpenCV failed to encode a PNG")
    return encoded.tobytes()


def _combined_barcode_crop(image: np.ndarray, boxes: list[list[float]], transform: np.ndarray) -> np.ndarray:
    crops = []
    for x1, y1, x2, y2 in boxes:
        polygon = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
        crops.append(_extract_quad(image, _map_points(polygon, transform)))
    if len(crops) == 1:
        return crops[0]
    target_height = max(crop.shape[0] for crop in crops)
    padded = []
    for crop in crops:
        bottom = target_height - crop.shape[0]
        padded.append(cv2.copyMakeBorder(crop, 0, bottom, 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255)))
    return cv2.hconcat(padded)


def _ocr_barcode(barcode_crop: np.ndarray, tesseract_cmd: str | Path | None) -> tuple[str, str]:
    if tesseract_cmd is not None:
        pytesseract.pytesseract.tesseract_cmd = str(tesseract_cmd)
    gray = cv2.cvtColor(barcode_crop, cv2.COLOR_BGR2GRAY)
    gray = cv2.copyMakeBorder(gray, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    variants = [gray, cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]]
    readings = []
    for variant in variants:
        try:
            readings.append(pytesseract.image_to_string(
                variant,
                config="--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789Pp",
            ))
        except Exception as exc:
            raise SurveyProcessingError(f"Barcode OCR could not run: {exc}") from exc
    cleaned = re.sub(r"[^0-9Pp]", "", " ".join(readings)).upper()
    matches = list(dict.fromkeys(re.findall(r"(\d{4})(P[24])", cleaned)))
    if len(matches) != 1:
        raise ValueError(
            "OCR did not produce exactly one four-digit survey number followed by P4 or P2; "
            f"cleaned OCR text was {cleaned!r}"
        )
    return matches[0]


def _rectify(image: np.ndarray, corners: np.ndarray) -> np.ndarray:
    tl, tr, br, bl = corners
    width = max(2, round((np.linalg.norm(tr - tl) + np.linalg.norm(br - bl)) / 2))
    height = max(2, round((np.linalg.norm(bl - tl) + np.linalg.norm(br - tr)) / 2))
    destination = np.float32([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]])
    matrix = cv2.getPerspectiveTransform(corners, destination)
    return cv2.warpPerspective(
        image, matrix, (width, height), flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


@overload
def rectify_survey_page(
    pdf_file: str | Path, page_number: int, json_file: str | Path,
    output_png: str | Path | None = None, dpi: int = 300,
    return_barcode_data: Literal[True] = True,
    tesseract_cmd: str | Path | None = None,
) -> tuple[bytes, str, str]: ...


@overload
def rectify_survey_page(
    pdf_file: str | Path, page_number: int, json_file: str | Path,
    output_png: str | Path | None = None, dpi: int = 300,
    return_barcode_data: Literal[False] = False,
    tesseract_cmd: str | Path | None = None,
) -> bytes: ...


def rectify_survey_page(
    pdf_file: str | Path,
    page_number: int,
    json_file: str | Path,
    output_png: str | Path | None = None,
    dpi: int = 300,
    return_barcode_data: bool = True,
    tesseract_cmd: str | Path | None = None,
) -> bytes | tuple[bytes, str, str]:
    """Rectify a survey page and optionally return its barcode data.

    With the default ``return_barcode_data=True``, returns:
        ``(page_png_bytes, survey_number, page_code)``

    With ``return_barcode_data=False``, skips all barcode OCR and returns:
        ``page_png_bytes``

    The barcode alignment box is never drawn on the output page. If barcode
    OCR is requested but validation fails, ``BarcodeReadError`` is raised and
    its ``barcode_png`` attribute contains a PNG crop of the barcode box.
    """
    data = _load_json(json_file)
    try:
        search_boxes = data["coordinate_system"]["Page Coordinate"]["alignment_search_boxes"]
    except (KeyError, TypeError) as exc:
        raise SurveyProcessingError(
            "JSON must contain coordinate_system.Page Coordinate.alignment_search_boxes"
        ) from exc

    oriented = _orient(_render_page(pdf_file, page_number, dpi), search_boxes)
    corners = _alignment_corners(oriented, search_boxes)
    rectified = _rectify(oriented, corners)
    page_png = _encode_png(rectified)

    if output_png is not None:
        try:
            Path(output_png).write_bytes(page_png)
        except OSError as exc:
            raise SurveyProcessingError(f"Cannot write PNG '{output_png}': {exc}") from exc

    if not return_barcode_data:
        return page_png

    transform = _alignment_homography(corners)
    barcode_crop = _combined_barcode_crop(oriented, _barcode_boxes(data), transform)
    barcode_png = _encode_png(barcode_crop)
    try:
        survey_number, page_code = _ocr_barcode(barcode_crop, tesseract_cmd)
    except ValueError as exc:
        raise BarcodeReadError(str(exc), barcode_png) from exc

    return page_png, survey_number, page_code


if __name__ == "__main__":
    png, survey, page = rectify_survey_page(
        "Test Surveys.pdf", 1, "Survey_coords_7OCT.9.json",
        output_png="rectified_page_1.png",
    )
    print(f"survey_number={survey}, page_number={page}, png_bytes={len(png)}")


def csv_to_excel_with_images(
    csv_file,
    excel_file=None,
    image_height=100
):
    """
    Convert a CSV results file to Excel and insert PNG images.

    Expected directory structure:

        parent/
            results/
                results.csv
            pngs/
                image1.png
                image2.png

    The PNG filename is stored in column 9 of the CSV.

    CSV columns 1-8 are written to Excel columns A-H.
    The PNG referenced in CSV column 9 is inserted into Excel column I.

    Parameters
    ----------
    csv_file : str | Path
        Input CSV file located in the results directory.

    excel_file : str | Path | None
        Output Excel file. If None, the Excel file is created
        beside the CSV file.

    image_height : int
        Height of inserted images in pixels.

    Returns
    -------
    Path
        Path to the created Excel file.
    """

    csv_file = Path(csv_file)

    if not csv_file.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_file}")

    # CSV is:
    # parent/results/file.csv
    #
    # PNG directory is:
    # parent/pngs/

    parent_folder = csv_file.parent.parent
    png_folder = parent_folder / "pngs"

    if excel_file is None:
        excel_file = csv_file.with_suffix(".xlsx")
    else:
        excel_file = Path(excel_file)

    wb = Workbook()
    ws = wb.active
    ws.title = "Results"

    # Image column
    ws.column_dimensions["I"].width = 40

    with csv_file.open(
        "r",
        newline="",
        encoding="utf-8-sig"
    ) as f:

        reader = csv.reader(f)

        for excel_row, csv_row in enumerate(reader, start=1):

            # Write CSV columns 1-8 into Excel A-H
            for col, value in enumerate(csv_row[:8], start=1):
                ws.cell(
                    row=excel_row,
                    column=col,
                    value=value.strip()
                )

            # Column 9 contains PNG filename
            if len(csv_row) >= 9:

                png_name = csv_row[8].strip()

                if png_name:

                    # Strip any existing directory information.
                    # We only want the filename because all PNGs
                    # are stored in the pngs folder.
                    png_name = Path(
                        png_name.replace("\\", "/")
                    ).name

                    png_path = png_folder / png_name

                    if (
                        png_path.suffix.lower() == ".png"
                        and png_path.exists()
                    ):

                        img = Image(str(png_path))

                        # Maintain aspect ratio
                        ratio = image_height / img.height
                        img.height = image_height
                        img.width = img.width * ratio

                        # Insert image into Excel column I
                        ws.add_image(
                            img,
                            f"I{excel_row}"
                        )

                        # Excel row height is measured in points
                        ws.row_dimensions[excel_row].height = (
                            image_height * 0.75
                        )

                    else:
                        print(
                            f"PNG not found on row {excel_row}: "
                            f"{png_path}"
                        )

    wb.save(excel_file)

    return excel_file