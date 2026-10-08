import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('public_checker',ROOT/'scripts/check_public.py')
checker=importlib.util.module_from_spec(spec);spec.loader.exec_module(checker)

class PublicCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.git('init');self.git('config','user.name','Test');self.git('config','user.email','test@example.invalid')
    def tearDown(self):self.tmp.cleanup()
    def git(self,*args):return subprocess.run(['git',*args],cwd=self.root,text=True,capture_output=True,check=True).stdout.strip()
    def put(self,name,text):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text);self.git('add',name);return p
    def test_clean_text_and_ignored_private_files(self):
        self.put('README.md','Public repository\n');(self.root/'auth.json').write_text('{"access_token":"do-not-read"}')
        self.assertEqual(checker.scan_repo(self.root)['issues'],[])
    def test_tracked_credentials_and_private_paths_fail_without_leaking_values(self):
        secret='s'+'k-'+'A'*30
        self.put('settings.json',json.dumps({'access_token':secret,'path':'/'+'Users/alice/private'}))
        issues=checker.scan_repo(self.root)['issues'];self.assertTrue(issues)
        self.assertNotIn(secret,json.dumps(issues))
        self.assertTrue(any('private absolute path' in x for x in issues))
    def test_auth_filename_and_binary_artifact_fail(self):
        self.put('auth.json','{}');self.put('movie.mp4','not-actually-video')
        issues=checker.scan_repo(self.root)['issues'];self.assertEqual(len(issues),2)
    def test_camelcase_account_and_generic_secret_fields(self):
        self.put('unapproved.json',json.dumps({'accountId':'private-account','clientSecret':'private-secret'}))
        issues=checker.scan_repo(self.root)['issues']
        self.assertTrue(any('accountId' in x for x in issues));self.assertTrue(any('clientSecret' in x for x in issues))
    def test_narrow_test_fixture_not_blanket_exemption(self):
        existing=(ROOT/'tests/test_core.py').read_text()
        self.put('tests/test_core.py',existing)
        self.assertEqual(checker.scan_repo(self.root)['issues'],[])
        self.put('tests/test_core.py',existing+'\nleak = "'+'s'+'k-'+'Z'*35+'"\n')
        self.assertTrue(any('credential-shaped' in x for x in checker.scan_repo(self.root)['issues']))
    def test_scanner_definitions_self_check(self):
        self.put('scripts/check_public.py',(ROOT/'scripts/check_public.py').read_text())
        self.put('robodojo_collab/schema.py',(ROOT/'robodojo_collab/schema.py').read_text())
        self.assertEqual(checker.scan_repo(self.root)['issues'],[])
    def test_immutable_manifest_update_delete_and_new_attempt(self):
        self.put('results/original/manifest.json','{"run_id":"original"}\n');self.git('commit','-m','Publish original');base=self.git('rev-parse','HEAD')
        self.put('results/next/manifest.json','{"run_id":"next"}\n')
        self.assertEqual(checker.scan_repo(self.root,base)['issues'],[])
        self.put('results/original/manifest.json','{"run_id":"changed"}\n')
        self.assertTrue(any('immutable published manifest changed' in x for x in checker.scan_repo(self.root,base)['issues']))
        self.git('rm','--force','results/original/manifest.json')
        self.assertTrue(any('removed/renamed' in x for x in checker.scan_repo(self.root,base)['issues']))
    def test_symlink_rejected(self):
        target=self.put('README.md','safe');(self.root/'shortcut').symlink_to(target);self.git('add','shortcut')
        self.assertTrue(any('symlinks' in x for x in checker.scan_repo(self.root)['issues']))

if __name__=='__main__':unittest.main()
