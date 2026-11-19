import math
import re
from dataclasses import dataclass
from pathlib import Path

import typst
from PIL import Image

WEBP_MAX_DIMENSION = 16383


def process_image_to_webp(
    source_path: str,
    output_dir: str,
    stem_name: str,
    split_height: int,
) -> list[str]:
    """Convert a rendered PNG into one or more WebP images.

    Args:
        source_path: Source PNG path.
        output_dir: Directory for generated WebP images.
        stem_name: Base filename for generated images.
        split_height: Height of each chunk when the image exceeds WebP limits.

    Returns:
        Generated WebP image paths in display order.

    Raises:
        RuntimeError: If the source image cannot be processed.
    """
    images = []
    src_path_obj = Path(source_path)
    out_dir_obj = Path(output_dir)

    if not src_path_obj.exists():
        return []
    try:
        with Image.open(src_path_obj) as img:
            if img.height <= WEBP_MAX_DIMENSION:
                webp_path = out_dir_obj / f"{stem_name}.webp"
                img.save(webp_path, "WEBP", quality=80, method=6)
                images.append(str(webp_path))
            else:
                width, total_height = img.size
                chunks = math.ceil(total_height / split_height)
                for i in range(chunks):
                    top = i * split_height
                    bottom = min((i + 1) * split_height, total_height)

                    box = (0, top, width, bottom)
                    chunk = img.crop(box)

                    chunk_path = out_dir_obj / f"{stem_name}_part{i + 1}.webp"
                    chunk.save(chunk_path, "WEBP", quality=80, method=6)
                    images.append(str(chunk_path))

    except Exception as exc:
        raise RuntimeError(f"Image processing failed: {exc}") from exc

    return images


@dataclass
class RenderTask:
    template_path: str
    json_str: str
    output_png_path: str
    output_dir: str
    timestamp: str
    query: str | None
    split_height: int
    ppi: float


def execute_render_task(task: RenderTask) -> list[str]:
    """Compile a Typst template and convert its PNG output to WebP.

    Args:
        task: Complete synchronous rendering input.

    Returns:
        Generated WebP image paths in display order.
    """
    sys_inputs = {
        "json_string": task.json_str,
        "timestamp": task.timestamp,
    }
    if task.query:
        sys_inputs["query_regex"] = re.escape(task.query)

    typst.compile(
        task.template_path,
        output=task.output_png_path,
        font_paths=[str(Path(__file__).resolve().parents[1] / "fonts")],
        format="png",
        ppi=task.ppi,
        sys_inputs=sys_inputs,
    )

    src_path = Path(task.output_png_path)
    return process_image_to_webp(
        source_path=task.output_png_path,
        output_dir=task.output_dir,
        stem_name=src_path.stem,
        split_height=task.split_height,
    )
