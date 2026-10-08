import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from robodojo_collab import storage

class StorageTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def test_requires_https_origin_and_no_credentials(self):
        for url in ('http://cloud.example','file:///etc/passwd','https://user:pass@cloud.example','https://cloud.example/path'):
            with self.assertRaises(storage.StorageError):storage.Seafile(url,'12345678-1234-1234-1234-123456789abc','test')
        self.assertFalse(storage.public_probe('file:///etc/passwd')['ok'])
    def test_rename_conflict_is_not_swallowed(self):
        p=self.root/'file.bin';p.write_bytes(b'abc')
        class Fake(storage.Seafile):
            def __init__(self):self.calls=0;self.verifications=0;self.repo='test-library'
            def remote_file(self,name):self.calls+=1;return None if self.calls==1 else {'name':name}
            def api(self,*args,**kwargs):return 'https://storage.example/upload'
            def verify(self,*args):self.verifications+=1;return {'ok':True}
        client=Fake()
        with patch.object(storage,'urlopen',return_value=io.BytesIO(json.dumps([{'name':'renamed-file.bin'}]).encode())):
            with self.assertRaises(storage.StorageError):client.upload(p)
        self.assertEqual(client.verifications,0)
    def test_multipart_filename_rejected(self):
        p=self.root/'bad"name.bin';p.write_bytes(b'abc')
        c=storage.Seafile('https://cloud.example','12345678-1234-1234-1234-123456789abc','test')
        with self.assertRaises(storage.StorageError):c.upload(p)
    def test_token_inside_repo_and_symlink_rejected(self):
        repo=Path(storage.__file__).resolve().parents[1]
        with self.assertRaises(storage.StorageError):storage.credential_destination(repo/'private-token')
        target=self.root/'external';target.write_text('x');link=self.root/'link';link.symlink_to(target)
        with self.assertRaises(storage.StorageError):storage.credential_destination(link)
    def test_chunks_idempotent_and_never_overwrite_other_file(self):
        p=self.root/'archive.tar';p.write_bytes(b'x'*(1024*1024+13));out=self.root/'chunks'
        args=SimpleNamespace(file=str(p),output=str(out),chunk_mib=1)
        with contextlib.redirect_stdout(io.StringIO()):storage.pack(args)
        before=(out/'chunks.json').read_bytes();m=json.loads(before);self.assertEqual(len(m['chunks']),2)
        self.assertEqual(b''.join((out/c['path']).read_bytes() for c in m['chunks']),p.read_bytes())
        with contextlib.redirect_stdout(io.StringIO()):storage.pack(args)
        self.assertEqual(before,(out/'chunks.json').read_bytes())
        p.write_bytes(b'different')
        with self.assertRaises(storage.StorageError):storage.pack(args)
        self.assertEqual(before,(out/'chunks.json').read_bytes())
    def test_chunk_interruption_leaves_no_partial_named_chunk(self):
        p=self.root/'archive.tar';p.write_bytes(b'data');out=self.root/'chunks'
        args=SimpleNamespace(file=str(p),output=str(out),chunk_mib=1)
        with patch.object(storage.os,'link',side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):storage.pack(args)
        self.assertEqual(list(out.iterdir()),[])
    def test_local_library_publication_lock(self):
        with patch.object(storage.Path,'home',return_value=self.root):
            with storage.publication_lock('https://cloud.example','library'):
                with self.assertRaises(storage.StorageError):
                    with storage.publication_lock('https://cloud.example','library'):pass
            with storage.publication_lock('https://cloud.example','library'):pass

if __name__=='__main__':unittest.main()
