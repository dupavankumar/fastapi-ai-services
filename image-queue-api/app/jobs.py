import logging
from PIL import Image, ImageOps
from pathlib import Path
from fastapi import HTTPException
from app.logging_config import configure_logging

configure_logging()
logger = logging.getLogger(__name__)
def create_thumbnail(
    input_path:str,
    height:int,
    width:int,
    output_format : str | None
):
    logger.info(
        "Thumbnail processing started input=%s width=%s height=%s format=%s",
        input_path,
        width,
        height,
        output_format,
    )
    try:
        img = Image.open(input_path)
        actual_format = img.format
        final_format = output_format.lower() if output_format else actual_format.lower()
        thumbnail = ImageOps.fit(img, (width, height))
        output_path = (
            Path(input_path).parent
            / f"{Path(input_path).stem}_thumbnail.{final_format}"
        )
        
        if final_format.lower() == "jpeg" and thumbnail.mode in ("RGBA", "P"):
            thumbnail = thumbnail.convert("RGB")
            
        thumbnail.save(output_path)
        logger.info(
            "Thumbnail processing completed output=%s",
            output_path,
        )
        return str(output_path)
    except Exception:
        logger.exception(
            "Thumbnail processing failed input=%s",
            input_path,
        )
        raise HTTPException(status_code=404, detail="")