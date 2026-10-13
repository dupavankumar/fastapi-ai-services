import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from rq import SimpleWorker

from app.main import app
from app.queue import task_queue
from app.redis_client import redis_client

client = TestClient(app)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_redis():
    """Start every test with an empty Redis DB so job state doesn't leak
    between tests. NOTE: this flushes the *entire* Redis DB configured in
    app/redis_client.py — fine for local dev (db 0, nothing else using it),
    but don't point this at a shared/production Redis instance.
    """
    redis_client.flushdb()
    yield


def drain_queue(max_passes=3):
    """Process every currently queued job synchronously, in this process,
    instead of relying on a separately running `rq worker`. This is what
    makes these tests deterministic and able to run with no worker process
    up at all.

    TEMPORARY: verbose diagnostics while we track down why jobs sometimes
    end up stuck in 'started'. Remove once root-caused.
    """
    for i in range(max_passes):
        print(f"\n[drain_queue] pass {i}: queue_count={task_queue.count} job_ids={task_queue.job_ids}")
        worker = SimpleWorker([task_queue], connection=redis_client)
        processed = worker.work(burst=True)
        print(f"[drain_queue] pass {i}: work() returned {processed!r}, queue_count_after={task_queue.count}")
        if not processed:
            break


@pytest.fixture
def jpeg_bytes():
    def _factory():
        img = Image.new("RGB", (60, 40), color=(10, 20, 30))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        buf.seek(0)
        return buf
    return _factory


@pytest.fixture
def png_rgba_bytes():
    def _factory():
        img = Image.new("RGBA", (60, 40), color=(10, 20, 30, 128))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return buf
    return _factory


def create_sample_task(jpeg_bytes, **overrides):
    data = {"width": "50", "height": "50"}
    data.update(overrides)
    files = {"image": ("sample.jpg", jpeg_bytes(), "image/jpeg")}
    response = client.post("/tasks", files=files, data=data)
    return response


# ---------------------------------------------------------------------------
# /health, /ready
# ---------------------------------------------------------------------------

def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "OK"
    }


def test_ready_when_redis_available():
    response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["Status"] == "OK"
    assert body["Redis "] == "UP"


# ---------------------------------------------------------------------------
# POST /tasks
# ---------------------------------------------------------------------------

def test_create_task_success(jpeg_bytes):
    response = create_sample_task(jpeg_bytes)
    assert response.status_code == 202
    body = response.json()
    assert "task_id" in body
    assert body["status"] == "queued"
    assert body["filename"] == "sample.jpg"


def test_create_task_rejects_invalid_content_type():
    files = {"image": ("notes.txt", io.BytesIO(b"hello world"), "text/plain")}
    response = client.post("/tasks", files=files, data={"width": "50", "height": "50"})
    assert response.status_code == 400


def test_create_task_requires_dimensions(jpeg_bytes):
    files = {"image": ("sample.jpg", jpeg_bytes(), "image/jpeg")}
    response = client.post("/tasks", files=files, data={})
    assert response.status_code == 400


def test_create_task_rejects_non_positive_dimensions(jpeg_bytes):
    files = {"image": ("sample.jpg", jpeg_bytes(), "image/jpeg")}
    response = client.post("/tasks", files=files, data={"width": "0", "height": "50"})
    assert response.status_code == 400


def test_create_task_rejects_invalid_output_format(jpeg_bytes):
    response = create_sample_task(jpeg_bytes, output_format="bmp")
    assert response.status_code == 400


def test_create_task_rejects_corrupted_image_data():
    files = {"image": ("fake.jpg", io.BytesIO(b"not a real image"), "image/jpeg")}
    response = client.post("/tasks", files=files, data={"width": "50", "height": "50"})
    assert response.status_code == 400


def test_png_with_transparency_converts_to_jpeg_without_crashing(png_rgba_bytes):
    # Regression test: RGBA PNG -> JPEG used to crash before the
    # thumbnail.mode check was added in app/jobs.py.
    files = {"image": ("transparent.png", png_rgba_bytes(), "image/png")}
    data = {"width": "50", "height": "50", "output_format": "jpeg"}
    create_response = client.post("/tasks", files=files, data=data)
    assert create_response.status_code == 202
    task_id = create_response.json()["task_id"]

    drain_queue()

    from rq.job import Job
    job = Job.fetch(task_id, connection=redis_client)
    print(f"[diag] status={job.get_status()!r} exc_info={job.exc_info!r} result={job.result!r}")

    status_response = client.get(f"/tasks/{task_id}")
    assert status_response.json()["status"] == "finished"


# ---------------------------------------------------------------------------
# GET /tasks/{task_id}
# ---------------------------------------------------------------------------

def test_get_task_status_not_found():
    response = client.get("/tasks/does-not-exist")
    assert response.status_code == 404


def test_get_task_status_finished(jpeg_bytes):
    create_response = create_sample_task(jpeg_bytes)
    task_id = create_response.json()["task_id"]

    drain_queue()

    from rq.job import Job
    job = Job.fetch(task_id, connection=redis_client)
    print(f"[diag] status={job.get_status()!r} exc_info={job.exc_info!r} result={job.result!r} worker_name={job.worker_name!r}")

    response = client.get(f"/tasks/{task_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "finished"
    assert body["result"] is not None
    assert Path(body["result"]).exists()


# ---------------------------------------------------------------------------
# GET /tasks
# ---------------------------------------------------------------------------

def test_list_tasks_includes_created_job(jpeg_bytes):
    create_response = create_sample_task(jpeg_bytes)
    task_id = create_response.json()["task_id"]

    response = client.get("/tasks")
    assert response.status_code == 200
    job_ids = [entry["job_id"] for entry in response.json()]
    assert task_id in job_ids


# ---------------------------------------------------------------------------
# DELETE /tasks/{task_id}
# ---------------------------------------------------------------------------

def test_delete_queued_task(jpeg_bytes):
    create_response = create_sample_task(jpeg_bytes)
    task_id = create_response.json()["task_id"]

    response = client.delete(f"/tasks/{task_id}")
    assert response.status_code == 200
    assert response.json() == {"job_id": task_id, "status": "deleted"}


def test_delete_nonexistent_task():
    response = client.delete("/tasks/does-not-exist")
    assert response.status_code == 404


def test_delete_finished_task_rejected(jpeg_bytes):
    create_response = create_sample_task(jpeg_bytes)
    task_id = create_response.json()["task_id"]

    drain_queue()

    response = client.delete(f"/tasks/{task_id}")
    assert response.status_code == 409


# ---------------------------------------------------------------------------
# GET /tasks/{task_id}/download
# ---------------------------------------------------------------------------

def test_download_before_finished_rejected(jpeg_bytes):
    create_response = create_sample_task(jpeg_bytes)
    task_id = create_response.json()["task_id"]

    response = client.get(f"/tasks/{task_id}/download")
    assert response.status_code == 409


def test_download_after_finished(jpeg_bytes):
    create_response = create_sample_task(jpeg_bytes)
    task_id = create_response.json()["task_id"]

    drain_queue()

    response = client.get(f"/tasks/{task_id}/download")
    assert response.status_code == 200
    assert len(response.content) > 0


def test_download_nonexistent_task():
    response = client.get("/tasks/does-not-exist/download")
    assert response.status_code == 404
