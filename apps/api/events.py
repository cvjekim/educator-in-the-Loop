"""Commit-driven notifications. No periodic database queries or model execution."""
import asyncio
from contextlib import asynccontextmanager, suppress
import hashlib
import json
import os
from pathlib import Path
import socket
import time
from uuid import uuid4


def local_directory(path):
    key = hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:20]
    directory = Path('/tmp') / ('educator-events-' + key)
    directory.mkdir(mode=0o700, exist_ok=True)
    return directory


def notify_local(path):
    # SQLite development API and worker are separate processes on the same host.
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sender:
        sender.setblocking(False)
        for target in local_directory(path).glob('*.sock'):
            try:
                sender.sendto(b'changed', str(target))
            except (FileNotFoundError, ConnectionRefusedError):
                target.unlink(missing_ok=True)
            except OSError:
                pass  # A full buffer already contains a wakeup; reconnect resyncs state.


@asynccontextmanager
async def listen(store, course_id):
    if store.dsn:
        import psycopg
        # Transaction-pooled connections cannot retain LISTEN session state.
        dsn = (os.getenv('DATABASE_URL_UNPOOLED') or store.dsn) if store.dsn == os.getenv('DATABASE_URL') else store.dsn
        conn = await psycopg.AsyncConnection.connect(dsn, autocommit=True, connect_timeout=10)
        try:
            channel = 'course_' + hashlib.md5(course_id.encode()).hexdigest()
            await conn.execute(psycopg.sql.SQL('LISTEN {}').format(psycopg.sql.Identifier(channel)))
            await conn.execute('LISTEN educator_access')
            async def wait():
                notifications = conn.notifies(stop_after=1)
                try:
                    await anext(notifications)
                finally:
                    await notifications.aclose()
            yield wait
        finally:
            await conn.close()
    else:
        path = local_directory(store.path) / (uuid4().hex[:16] + '.sock')
        receiver = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            receiver.bind(str(path))
            receiver.setblocking(False)
            async def wait():
                await asyncio.get_running_loop().sock_recv(receiver, 32)
            yield wait
        finally:
            receiver.close()
            path.unlink(missing_ok=True)


def frame(event, data):
    return f'event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n'


async def stream(store, course_id, snapshot, duration=240, heartbeat=20):
    """Subscribe before snapshot; reconnect resyncs instead of replaying private data."""
    pending = None
    try:
        async with listen(store, course_id) as wait:
            try:
                deadline = time.monotonic() + duration
                previous = None
                while True:
                    data = await asyncio.to_thread(snapshot)
                    encoded = json.dumps(data, sort_keys=True, ensure_ascii=False)
                    if encoded != previous:
                        yield frame('runs.snapshot', data)
                        previous = encoded
                    pending = asyncio.create_task(wait())
                    while True:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            yield frame('stream.reconnect', {})
                            return
                        done, _ = await asyncio.wait({pending}, timeout=min(heartbeat, remaining))
                        if done:
                            await pending
                            pending = None
                            break
                        # Transport keepalive only: no DB read, no React update.
                        yield ': keepalive\n\n'
            finally:
                if pending:
                    pending.cancel()
                    with suppress(asyncio.CancelledError, Exception):
                        await pending
                    pending = None
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        from fastapi import HTTPException
        if isinstance(exc, HTTPException) and exc.status_code in (401, 404):
            yield frame('stream.denied', {'message': '접근 권한이 변경됐습니다. 다시 로그인해 주세요.'})
        else:
            yield frame('stream.error', {'message': '실시간 연결이 끊겼습니다. 다시 연결합니다.'})
    finally:
        if pending:
            pending.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await pending
