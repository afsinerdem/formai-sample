from __future__ import annotations

import io

from formai.errors import IntegrationUnavailable
from formai.models import BoundingBox, RenderedPage


def crop_rendered_page(
    page: RenderedPage,
    box: BoundingBox,
    *,
    context_pixels: int = 24,
    horizontal_pad_ratio: float = 0.10,
    vertical_pad_ratio: float = 0.18,
    extra_left_ratio: float = 0.28,
) -> RenderedPage:
    try:
        from PIL import Image
    except ImportError as exc:
        raise IntegrationUnavailable("Pillow is required for field crop extraction.") from exc

    pixel_box = _scale_box_to_page(box, page)
    left_pad = max(context_pixels, int(round(pixel_box.width * horizontal_pad_ratio)))
    right_pad = max(context_pixels, int(round(pixel_box.width * horizontal_pad_ratio)))
    top_pad = max(context_pixels // 2, int(round(pixel_box.height * vertical_pad_ratio)))
    bottom_pad = max(context_pixels // 2, int(round(pixel_box.height * vertical_pad_ratio)))
    extra_left = max(context_pixels, int(round(pixel_box.width * extra_left_ratio)))

    crop_left = max(0, int(pixel_box.left) - extra_left)
    crop_top = max(0, int(pixel_box.top) - top_pad)
    crop_right = min(page.width, int(pixel_box.right) + right_pad)
    crop_bottom = min(page.height, int(pixel_box.bottom) + bottom_pad)

    if crop_right <= crop_left:
        crop_right = min(page.width, crop_left + max(1, int(pixel_box.width) + right_pad))
    if crop_bottom <= crop_top:
        crop_bottom = min(page.height, crop_top + max(1, int(pixel_box.height) + bottom_pad))

    image = Image.open(io.BytesIO(page.image_bytes))
    cropped = image.crop((crop_left, crop_top, crop_right, crop_bottom))
    buffer = io.BytesIO()
    cropped.save(buffer, format="PNG")
    width, height = cropped.size
    return RenderedPage(
        page_number=page.page_number,
        mime_type="image/png",
        image_bytes=buffer.getvalue(),
        width=width,
        height=height,
    )


def _scale_box_to_page(box: BoundingBox, page: RenderedPage) -> BoundingBox:
    reference_width = box.reference_width or page.width
    reference_height = box.reference_height or page.height
    if reference_width <= 0 or reference_height <= 0:
        return box
    if abs(reference_width - page.width) < 1 and abs(reference_height - page.height) < 1:
        return box
    scale_x = page.width / reference_width
    scale_y = page.height / reference_height
    return BoundingBox(
        page_number=box.page_number,
        left=box.left * scale_x,
        top=box.top * scale_y,
        right=box.right * scale_x,
        bottom=box.bottom * scale_y,
        reference_width=page.width,
        reference_height=page.height,
    )
