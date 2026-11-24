"""Vercel invokes this subscriber independently of the browser/API request."""
import asyncio
import os
from uuid import UUID

from vercel.queue import subscribe
from .store import Store
from .worker import process_once


@subscribe(topic='educator-jobs', consumer_group='agent-worker', max_concurrency=2, max_attempts=3, retry_after=30)
async def consume_job(payload: dict[str, str]) -> None:
    run_id = str(UUID(payload['run_id']))
    if os.getenv('API_STORAGE') == 'normalized':
        from .normalized.cloud import consume
        await asyncio.to_thread(consume, run_id)
        return
    store = Store(os.environ['DATABASE_URL'])
    await asyncio.to_thread(process_once, store, run_id=run_id)
