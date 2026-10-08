"""Crop a normalized region from a PDF page and return it as a PNG bitmap.

Coordinates use a normalized top-left coordinate system:
    (0, 0) = top-left of page
    (1, 1) = bottom-right of page

Dependency:
    python -m pip install pymupdf
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Tuple, Union

import fitz  # PyMuPDF


CoordinateBox = Tuple[float, float, float, float]
PathLike = Union[str, Path]


def crop_pdf_page_to_png(
    pdf_file: PathLike,
    page_number: int,
    crop_box: CoordinateBox,
    dpi: int = 600,
    output_file: PathLike | None = None,
) -> bytes:
    """Render a cropped region of a PDF page as PNG data.

    Args:
        pdf_file: Path to the input PDF.
        page_number: Page number using 1-based numbering; the first page is 1.
        crop_box: Normalized ``(x1, y1, x2, y2)`` coordinates. Values must
            be between 0 and 1, with ``x2 > x1`` and ``y2 > y1``.
        dpi: Rendering resolution. Defaults to 300 DPI.
        output_file: Optional path at which to save the PNG.

    Returns:
        The PNG bitmap as ``bytes``. This can be written to a file, placed in
        a ``BytesIO`` object, or opened directly with Pillow.

    Raises:
        FileNotFoundError: If the PDF does not exist.
        ValueError: If the page number, crop box, or DPI is invalid.
        RuntimeError: If the PDF cannot be opened or rendered.
    """
    pdf_path = Path(pdf_file)

    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    if not isinstance(page_number, int) or isinstance(page_number, bool):
        raise ValueError("page_number must be an integer using 1-based numbering")

    if dpi <= 0:
        raise ValueError("dpi must be greater than zero")

    try:
        x1, y1, x2, y2 = map(float, crop_box)
    except (TypeError, ValueError) as exc:
        raise ValueError("crop_box must contain four numeric values") from exc

    if not all(0.0 <= value <= 1.0 for value in (x1, y1, x2, y2)):
        raise ValueError("All crop coordinates must be between 0 and 1")

    if x2 <= x1 or y2 <= y1:
        raise ValueError("crop_box must satisfy x2 > x1 and y2 > y1")

    try:
        with fitz.open(pdf_path) as document:
            if document.needs_pass:
                raise ValueError("The PDF is password protected")

            if not 1 <= page_number <= document.page_count:
                raise ValueError(
                    f"page_number must be between 1 and {document.page_count}"
                )

            page = document.load_page(page_number - 1)
            page_rect = page.rect

            clip = fitz.Rect(
                page_rect.x0 + x1 * page_rect.width,
                page_rect.y0 + y1 * page_rect.height,
                page_rect.x0 + x2 * page_rect.width,
                page_rect.y0 + y2 * page_rect.height,
            )

            scale = dpi / 72.0
            pixmap = page.get_pixmap(
                matrix=fitz.Matrix(scale, scale),
                clip=clip,
                alpha=False,
            )
            png_data = pixmap.tobytes("png")

    except (FileNotFoundError, ValueError):
        raise
    except Exception as exc:
        raise RuntimeError(f"Unable to crop PDF '{pdf_path}': {exc}") from exc

    if output_file is not None:
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(png_data)

    return png_data


def crop_pdf_page_to_stream(
    pdf_file: PathLike,
    page_number: int,
    crop_box: CoordinateBox,
    dpi: int = 300,
) -> BytesIO:
    """Return the cropped PNG wrapped in an in-memory binary stream."""
    return BytesIO(
        crop_pdf_page_to_png(
            pdf_file=pdf_file,
            page_number=page_number,
            crop_box=crop_box,
            dpi=dpi,
        )
    )


if __name__ == "__main__":
    # Example: crop the central half of page 1 and save it as a PNG.
    crop_pdf_page_to_png(
        pdf_file="input.pdf",
        page_number=1,
        crop_box=(0.25, 0.25, 0.75, 0.75),
        dpi=300,
        output_file="cropped_region.png",
    )
