"""CPU-only publication packaging checks; no network or experiment calls."""
import importlib.util
from pathlib import Path
import tarfile
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('publish_panel', Path(__file__).resolve().parents[1] / 'scripts/publish_panel.py')
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


class PanelPackagingTests(unittest.TestCase):
    def test_exact_members_no_video_duplicate_or_directory_sweep(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); bundle = root / 'run'; bundle.mkdir()
            for name in ('publication-manifest.json', 'trajectory.json', 'video.mp4', 'unlisted-image.png'):
                (bundle / name).write_bytes(b'fixture')
            m = {'run_id': 'fixture-run', 'artifacts': [
                {'path': 'trajectory.json', 'kind': 'trajectory'},
                {'path': 'video.mp4', 'kind': 'native_video'}]}
            path = publisher.metadata_tar([(bundle, m)], root / 'panel.tar')
            with tarfile.open(path) as t:
                self.assertEqual(t.getnames(), ['fixture-run/publication-manifest.json', 'fixture-run/trajectory.json'])
            original = path.read_bytes()
            publisher.metadata_tar([(bundle, m)], path)
            self.assertEqual(path.read_bytes(), original)
            (bundle / 'trajectory.json').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'immutable'):
                publisher.metadata_tar([(bundle, m)], path)
            self.assertEqual(path.read_bytes(), original)

    def test_symlink_member_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); bundle = root / 'run'; bundle.mkdir()
            (root / 'data.json').write_text('{}')
            (bundle / 'publication-manifest.json').symlink_to(root / 'data.json')
            with self.assertRaisesRegex(ValueError, 'Symlink'):
                publisher.metadata_tar([(bundle, {'run_id': 'fixture-run', 'artifacts': []})], root / 'panel.tar')


if __name__ == '__main__':
    unittest.main()
