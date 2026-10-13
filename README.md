# FastAPI AI Services

A collection of FastAPI projects, each one building on the last.

## Projects

| Project | Description |
|---|---|
| [`image-queue-api`](./image-queue-api) | A FastAPI service that accepts image-processing jobs (resize/convert/thumbnail), runs them asynchronously via a Redis-backed RQ worker, and lets clients poll for status and download the result. |
