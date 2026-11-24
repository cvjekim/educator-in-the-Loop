"""Development-only private file storage. Metadata stays in PostgreSQL."""
import hashlib
from pathlib import Path
from uuid import uuid4

class Files:
    def __init__(self,root):
        self.root=Path(root).resolve();self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
    def path(self,key):
        path=(self.root/key).resolve()
        if self.root not in path.parents:raise ValueError('Invalid storage key')
        return path
    def write(self,category,data,suffix=''):
        key=f'{category}/{uuid4().hex}{suffix}'
        path=self.path(key);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        with path.open('xb') as f:f.write(data)
        path.chmod(0o600)
        return key,hashlib.sha256(data).hexdigest()
    def read(self,key):return self.path(key).read_bytes()
    def delete(self,key):self.path(key).unlink(missing_ok=True)
