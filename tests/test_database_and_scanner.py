import tempfile
import unittest
import os
from pathlib import Path

from desktop_app.video_compressor.database import COMPLETED, PENDING, TaskDatabase
from desktop_app.video_compressor.scanner import scan_videos


class DatabaseAndScannerTests(unittest.TestCase):
    def test_scan_excludes_runtime_files_and_state_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "DJI_0001.MP4").write_bytes(b"video")
            (root / "DJI_0002.mp4.compress_tmp.MP4").write_bytes(b"partial")
            state_dir = root / ".video-compressor"
            state_dir.mkdir()
            (state_dir / "hidden.MP4").write_bytes(b"hidden")

            summary = scan_videos(root)

            self.assertEqual([path.name for path in summary.paths], ["DJI_0001.MP4"])
            self.assertEqual(summary.total_bytes, 5)

    def test_completed_record_is_preserved_when_output_matches(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "DJI_0001.MP4"
            source.write_bytes(b"original")
            original_mtime = source.stat().st_mtime_ns
            database = TaskDatabase(root)
            database.register_files([source])
            task = database.list_tasks()[0]
            source.write_bytes(b"small")
            database.update(task.id, COMPLETED, output_size=source.stat().st_size)
            # The engine restores the original mtime before marking completion.
            os.utime(source, ns=(source.stat().st_atime_ns, original_mtime))
            database.register_files([source])

            self.assertEqual(database.get(task.id).status, COMPLETED)

    def test_changed_source_resets_noncompleted_task(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "DJI_0001.MP4"
            source.write_bytes(b"first")
            database = TaskDatabase(root)
            database.register_files([source])
            task = database.list_tasks()[0]
            database.update(task.id, "failed", error="test")
            source.write_bytes(b"replacement-content")
            database.register_files([source])

            refreshed = database.get(task.id)
            self.assertEqual(refreshed.status, PENDING)
            self.assertIsNone(refreshed.error)


if __name__ == "__main__":
    unittest.main()
