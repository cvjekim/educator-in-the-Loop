"""Persistent storage regression against a local PostgreSQL test database."""
import os
from uuid import uuid4
from urllib.parse import urlparse
import pytest
from apps.api.normalized.cloud import DatabaseFiles, storage


def test_private_files_survive_instances_and_reject_overwrite():
    dsn=os.getenv('TEST_DATABASE_URL')
    if not dsn:pytest.skip('Local PostgreSQL required')
    assert urlparse(dsn).hostname in ('localhost','127.0.0.1','::1')
    DatabaseFiles.provision(dsn)
    first=DatabaseFiles(dsn);second=DatabaseFiles(dsn)
    key='test/'+uuid4().hex
    data=b'Synthetic notebook and lecture bytes\x00\xff'
    try:
        _,digest=first.put(key,data)
        assert second.read(key)==data
        assert second.put(key,data)==(key,digest)
        with pytest.raises(ValueError,match='conflict'):second.put(key,b'changed')
        assert first.read(key)==data
    finally:first.delete(key)
    with pytest.raises(FileNotFoundError):second.read(key)


def test_vercel_refuses_ephemeral_files(monkeypatch):
    monkeypatch.setenv('VERCEL','1');monkeypatch.delenv('FILE_STORAGE',raising=False)
    with pytest.raises(RuntimeError,match='persistent'):storage(None)
