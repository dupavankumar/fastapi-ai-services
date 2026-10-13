# Image Task Queue API

A FastAPI service that accepts image-processing jobs (resize/convert/thumbnail),
runs them asynchronously on a Redis-backed RQ worker, and lets clients poll for
the result. 

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) — see "Installing uv" below if you don't have it
- Redis server running locally — see "Installing Redis" below

### Installing uv (if you don't have it)

Check first: `uv --version`. If that fails, install it with whichever fits your machine:

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# or, if you already have Python + pip and just want a quick install
pip install uv
```

Restart your terminal (or `source ~/.bashrc` / `~/.zshrc`) if `uv --version` still isn't found after installing.

### Installing Redis

**Option A — system package (Debian/Ubuntu):**

```bash
sudo apt update
sudo apt install redis-server

# start it now + on every boot
sudo systemctl enable --now redis-server

# verify it's running
redis-cli ping    # should print: PONG
```

**Option B — Docker (no system install, easy to tear down):**

```bash
docker run -d --name redis -p 6379:6379 redis:7-alpine
redis-cli ping    # should print: PONG
```

## Environment setup (uv)

```bash
# from inside image-queue-api/

# create a virtual environment (creates .venv/)
uv venv

# activate it
source .venv/bin/activate

# install dependencies from requirements.txt
uv pip install -r requirements.txt

# verify installed versions
uv pip list
```



To deactivate the environment when done:

```bash
deactivate
```

## Running the project

This service has two processes that both need to be running at the same time:
the **API** (accepts requests, enqueues jobs) and the **worker** (actually does
the image processing). They talk to each other through Redis, so Redis must
already be up (see "Installing Redis" above) before you start either one.

**Terminal 1 — start the API (with auto-reload for development):**

```bash
# from inside image-queue-api/, with .venv activated
uvicorn app.main:app --reload
```

- API base URL: `http://127.0.0.1:8000`
- Interactive docs (Swagger UI): `http://127.0.0.1:8000/docs`
- `--reload` restarts the server automatically whenever you save a code change
  — convenient for development, but don't use it in production.

**Terminal 2 — start the worker (processes queued jobs):**

```bash
# from inside image-queue-api/, with .venv activated
rq worker image_processing_tasks
```

Leave this running — it's what actually picks up jobs from the queue and runs
`create_thumbnail` on them. If this isn't running, uploaded tasks will sit in
`queued` status forever.

### Quick smoke test

1. Open `http://127.0.0.1:8000/docs`
2. Try `GET /health` → `{"status": "OK"}`
3. Try `GET /ready` → confirms the API can reach Redis
4. Try `POST /tasks` with an image file + width/height → returns a `task_id`
5. Try `GET /tasks/{task_id}` → status moves from `queued` → `started` → `finished`
6. Try `GET /tasks/{task_id}/download` once finished → downloads the processed image

### Useful Redis commands while developing

```bash
redis-cli ping       # check Redis is alive
redis-cli FLUSHDB    # wipe all queued/finished job data (fresh start)
```

## Status

🚧 Core API + async queue working (upload → enqueue → process → poll → download).
Docker Compose setup for one-command `api + worker + redis` startup coming next.
