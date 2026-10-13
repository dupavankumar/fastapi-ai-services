from rq import Queue
from app.redis_client import redis_client

task_queue = Queue(name="image_processing_tasks",
                   connection=redis_client)