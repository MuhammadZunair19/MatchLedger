import os
from redis import Redis
from rq import Worker, SpawnWorker, Queue
from .config import settings
from .services.documents.jobs import recover_all


if __name__ == '__main__':
    recover_all()
    connection = Redis.from_url(settings.redis_url)
    worker_class = SpawnWorker if os.name == 'nt' else Worker
    worker_class([Queue('documents', connection=connection)], connection=connection).work()
