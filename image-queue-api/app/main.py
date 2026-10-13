from fastapi import FastAPI, UploadFile, Form, File
from fastapi import HTTPException
from PIL import Image, ImageOps
from pathlib import Path

from rq.job import Job
from rq.exceptions import NoSuchJobError
from rq.registry import StartedJobRegistry, FailedJobRegistry, FinishedJobRegistry

import uuid

from app.redis_client import redis_client
from fastapi.responses import FileResponse

from app.queue import task_queue
from app.jobs import create_thumbnail
import shutil
import logging

from app.logging_config import configure_logging

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="Image Processing Queue API",
              version="0.1.0")

@app.get("/health")
async def health():
    return {"status":"OK"}

@app.get("/ready")
async def ready():
    try:
        redis_client.ping()
    except Exception:
        raise HTTPException(status_code=503, detail="Redis is unavailable....")
    return {
        "Status" : "OK",
        "Redis " : "UP"
    }


@app.post("/tasks", status_code=202)
async def create_task(
    image : UploadFile = File(...),
    height : int | None = Form(None),
    width : int | None = Form(None),
    output_format : str | None = Form(None)
):
    logger.info(
        "Received task request filename=%s width=%s height=%s format=%s",
        image.filename,
        width,
        height,
        output_format,
    )
    allowed_types = [
            "image/jpeg",
            "image/png",
            "image/webp"
        ]
    output_types = [
        "jpeg",
        "png",
        "webp"
    ]
    if output_format is None:
        output_format = "jpeg"
        
    if image.content_type not in allowed_types:
            raise HTTPException(
                status_code=400,
                detail="Supports only JPEG, PNG, WEBP formats ....."
            )
    if height is None or height <= 0 or width is None or width <= 0:
            raise HTTPException(
                status_code=400,
                detail="To Create thumbnail, needs both height and width...."
            )
    if output_format not in output_types:
        raise HTTPException(
            status_code = 400,
            detail = "Invalid output format...."
        )
    upload_dir = Path("uploads")
    upload_dir.mkdir(exist_ok=True)

    unique_name = f"{uuid.uuid4().hex}_{image.filename}"
    inp_path = upload_dir/unique_name
    
    with inp_path.open("wb") as buffer:
        shutil.copyfileobj(image.file, buffer)
    
    try:
        img = Image.open(inp_path)
        img.verify()
    except Exception:
        logger.warning(
            "Rejected unsupported file filename=%s content_type=%s",
            image.filename,
            image.content_type,
        )
        raise HTTPException(
            status_code=400,
            detail = "Invalid image .... "
        )
        
    try:
        job = task_queue.enqueue(
            create_thumbnail,
                            str(inp_path),
                            height,
                            width,
                            output_format
        )
        logger.info(
        "Task queued task_id=%s filename=%s",
        job.id,
        image.filename,
    )
    except Exception:
        logger.exception(
            "Failed to enqueue task filename=%s",
            image.filename,
        )
        raise HTTPException(
            status_code = 503,
            detail = "Queue is not available ...."
        )
    return {
        "task_id":job.id,
        "status":"queued",
        "filename":image.filename
    }


@app.get("/tasks")
async def lists_task():
    tasks = []
    started_registry = StartedJobRegistry(queue=task_queue, connection=redis_client)
    finished_registry = FinishedJobRegistry(queue=task_queue, connection=redis_client)
    failed_registry = FailedJobRegistry(queue=task_queue, connection=redis_client)
    
    ids_with_status = []
    
    for job_id in task_queue.job_ids:
        ids_with_status.append({"job_id":job_id, "status" : "queued"})
    
    for job_id in started_registry.get_job_ids():
        ids_with_status.append({"job_id":job_id, "status" :"started"})
    
    for job_id in finished_registry.get_job_ids():
        ids_with_status.append({"job_id":job_id, "status" :"finished"})
    
    for job_id in failed_registry.get_job_ids():
        ids_with_status.append({"job_id":job_id, "status" :"image processing failed"})
        
    return ids_with_status

@app.get("/tasks/{task_id}")
async def get_status(
    task_id:str
):
    try:
        job = Job.fetch(task_id, connection=redis_client)
    except NoSuchJobError:
        raise HTTPException(status_code=404, detail="No such Job....")
    
    job.refresh()
    status = job.get_status()
    job_status = {"task_id": job.id,
                  "status": status
                  }
    if status == "finished":
        job_status["result"] = job.result
    
    if status == "failed":
        job_status["error"] = "Image Processing Failed..."
        
    return job_status


    
    
@app.delete("/tasks/{job_id}")
async def delete_jobs(job_id:str):
    try:
        job = Job.fetch(job_id, connection=redis_client)
    except NoSuchJobError:
        raise HTTPException(status_code=404, detail = "No such job....")
    
    status = job.get_status()
    
    if status != "queued":
        raise HTTPException(status_code=409, detail="Job can't be deleted, only queued jobs can be deleted....")

    job.cancel()
    return {
        "job_id":job_id,
        "status": "deleted"
    }

@app.get("/tasks/{task_id}/download")
async def download_finished_jobs(task_id:str):
    try:
        job = Job.fetch(task_id, connection=redis_client)
    except NoSuchJobError:
        raise HTTPException(status_code=404, detail="No such job")
    
    status = job.get_status()
    
    if status != "finished":
        raise HTTPException(status_code = 409, detail = f"{task_id} not finished, Only finished jobs can be downloaded...")
    
    output_path = job.result
    
    if not output_path or not Path(output_path).exists():
        raise HTTPException(status_code=404, detail = "Processed image not found.....")

    return FileResponse(path = output_path, filename=Path(output_path).name)
    
    
    
    

# @app.post("/upload_image")
# async def create_task(
#     image: UploadFile = File(...),
#     height: int | None = Form(None),
#     width: int | None = Form(None),
#     output_format: str | None = Form(None)
# ):
#     allowed_types = [
#         "image/jpeg",
#         "image/png",
#         "image/webp"
#     ]
#     if image.content_type not in allowed_types:
#         raise HTTPException(
#             status_code=400,
#             detail="Supports only JPEG, PNG, WEBP formats ....."
#         )
#     if height is None or width is None:
#         raise HTTPException(
#             status_code=400,
#             detail="To Create thumbnail, needs both height and width...."
#         )
    
#     try:
#         img = Image.open(image.file)
#         actual_width, actual_height = img.size
#         actual_format = img.format
#         thumbnail = ImageOps.fit(img, (width, height))
#         output_filename = Path(image.filename).stem + "_thumbnail."
        
#         output_filename += output_format if output_format else actual_format.lower()
            
#         thumbnail.save(output_filename)
#     except Exception:
#         raise HTTPException(
#             status_code=400,
#             detail="Uploaded image is not a valid image...."
#         )
#     return {
#         "filename": image.filename,
#         "image_height" : actual_height,
#         "image_width" : actual_width,
#         "image_format" : actual_format,
#         "thumbnail_height" : height,
#         "thumbnail_width" : width,
#         "thumbnail_format" : output_format
#     }
   