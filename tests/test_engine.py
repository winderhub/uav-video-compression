import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from desktop_app.video_compressor.config import CompressionSettings, CpuMode, ENCODE_TEMP_SUFFIX
from desktop_app.video_compressor.database import (
    COMPLETED,
    FAILED,
    SKIPPED_LOW_BITRATE,
    WAITING_REPLACE,
    TaskDatabase,
)
from desktop_app.video_compressor.engine import (
    CompressionEngine,
    ReplacementBlocked,
    StorageUnavailable,
)
from desktop_app.video_compressor.media import MediaCancelled, ProbeResult


class FakeMedia:
    def __init__(self, source_bitrate=130_000_000, output_packets=100):
        self.source_bitrate = source_bitrate
        self.output_packets = output_packets
        self.encode_calls = 0

    def cancel_active(self):
        return None

    def probe(self, path, stop_event=None):
        if path.name.endswith(ENCODE_TEMP_SUFFIX) or path.name.endswith(".restore_partial.MP4"):
            return ProbeResult(self.output_packets, 90_000_000, 60.0, 3840, 2160)
        if path.read_bytes().startswith(b"compressed"):
            return ProbeResult(self.output_packets, 90_000_000, 60.0, 3840, 2160)
        return ProbeResult(100, self.source_bitrate, 60.0, 3840, 2160)

    def encode(self, source, output, settings, log_path, stop_event, progress, duration):
        self.encode_calls += 1
        log_path.write_text("fake encode\n", encoding="utf-8")
        output.write_bytes(b"compressed-video")
        progress(1.0)


class MutatingFakeMedia(FakeMedia):
    def encode(self, source, output, settings, log_path, stop_event, progress, duration):
        super().encode(source, output, settings, log_path, stop_event, progress, duration)
        source.write_bytes(b"source-changed-during-encode")


class EngineTests(unittest.TestCase):
    def make_engine(self, root, media):
        database = TaskDatabase(root)
        source = root / "DJI_0001.MP4"
        database.register_files([source])
        engine = CompressionEngine(
            source_root=root,
            database=database,
            media=media,
            settings=CompressionSettings(mode=CpuMode.BALANCED),
            stop_event=threading.Event(),
        )
        return engine, database, source

    def test_same_volume_compression_replaces_one_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "DJI_0001.MP4"
            source.write_bytes(b"original-video-content")
            original_mtime = source.stat().st_mtime_ns
            media = FakeMedia()
            engine, database, source = self.make_engine(root, media)

            result = engine.run()

            task = database.list_tasks()[0]
            self.assertEqual(task.status, COMPLETED)
            self.assertEqual(source.read_bytes(), b"compressed-video")
            self.assertEqual(source.stat().st_mtime_ns, original_mtime)
            self.assertEqual(media.encode_calls, 1)
            self.assertEqual(result.completed, 1)
            self.assertTrue(result.report_path.is_file())
            self.assertFalse(Path(str(source) + ENCODE_TEMP_SUFFIX).exists())

    def test_low_bitrate_source_is_skipped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "DJI_0001.MP4"
            source.write_bytes(b"original-video-content")
            media = FakeMedia(source_bitrate=60_000_000)
            engine, database, source = self.make_engine(root, media)

            engine.run()

            self.assertEqual(database.list_tasks()[0].status, SKIPPED_LOW_BITRATE)
            self.assertEqual(source.read_bytes(), b"original-video-content")
            self.assertEqual(media.encode_calls, 0)

    def test_verification_failure_deletes_temp_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "DJI_0001.MP4"
            source.write_bytes(b"original-video-content")
            media = FakeMedia(output_packets=1)
            engine, database, source = self.make_engine(root, media)

            engine.run()

            self.assertEqual(database.list_tasks()[0].status, FAILED)
            self.assertEqual(source.read_bytes(), b"original-video-content")
            self.assertFalse(Path(str(source) + ENCODE_TEMP_SUFFIX).exists())

    def test_replace_permission_error_pauses_and_keeps_single_verified_temp(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "DJI_0001.MP4"
            source.write_bytes(b"original-video-content")
            media = FakeMedia()
            engine, database, source = self.make_engine(root, media)

            with mock.patch("desktop_app.video_compressor.engine.os.replace", side_effect=PermissionError("busy")):
                with self.assertRaises(ReplacementBlocked):
                    engine.run()

            task = database.list_tasks()[0]
            self.assertEqual(task.status, WAITING_REPLACE)
            self.assertEqual(source.read_bytes(), b"original-video-content")
            self.assertTrue(Path(task.temp_path).is_file())

            resumed = CompressionEngine(
                source_root=root,
                database=database,
                media=media,
                settings=CompressionSettings(mode=CpuMode.BALANCED),
            )
            result = resumed.run()
            self.assertEqual(result.completed, 1)
            self.assertEqual(source.read_bytes(), b"compressed-video")
            self.assertEqual(media.encode_calls, 1)

    def test_source_change_during_encode_pauses_without_overwrite(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "DJI_0001.MP4"
            source.write_bytes(b"original-video-content")
            media = MutatingFakeMedia()
            engine, database, source = self.make_engine(root, media)

            with self.assertRaises(StorageUnavailable):
                engine.run()

            task = database.list_tasks()[0]
            self.assertEqual(task.status, WAITING_REPLACE)
            self.assertEqual(source.read_bytes(), b"source-changed-during-encode")
            self.assertTrue(Path(task.temp_path).is_file())

    def test_external_staging_writes_back_and_removes_staging_copy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "source"
            staging = base / "staging"
            root.mkdir()
            staging.mkdir()
            source = root / "DJI_0001.MP4"
            source.write_bytes(b"original-video-content")
            media = FakeMedia()
            database = TaskDatabase(root)
            database.register_files([source])
            engine = CompressionEngine(
                source_root=root,
                database=database,
                media=media,
                settings=CompressionSettings(mode=CpuMode.BALANCED),
                staging_dir=staging,
            )
            resolved_root = root.resolve()

            def fake_available(path):
                return 0 if Path(path).resolve() == resolved_root else 100 * 1024**3

            with mock.patch("desktop_app.video_compressor.engine.available_bytes", side_effect=fake_available), mock.patch(
                "desktop_app.video_compressor.engine.same_filesystem", return_value=False
            ):
                result = engine.run()

            self.assertEqual(result.completed, 1)
            self.assertEqual(source.read_bytes(), b"compressed-video")
            self.assertEqual(database.list_tasks()[0].status, COMPLETED)
            self.assertFalse((staging / ".video-compressor-staging").exists())

    def test_external_copy_interruption_recovers_from_verified_staging_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "source"
            staging = base / "staging"
            root.mkdir()
            staging.mkdir()
            source = root / "DJI_0001.MP4"
            source.write_bytes(b"original-video-content")
            media = FakeMedia()
            database = TaskDatabase(root)
            database.register_files([source])
            interrupted = CompressionEngine(
                source_root=root,
                database=database,
                media=media,
                settings=CompressionSettings(mode=CpuMode.BALANCED),
                staging_dir=staging,
            )
            resolved_root = root.resolve()

            def fake_available(path):
                return 0 if Path(path).resolve() == resolved_root else 100 * 1024**3

            with mock.patch("desktop_app.video_compressor.engine.available_bytes", side_effect=fake_available), mock.patch(
                "desktop_app.video_compressor.engine.same_filesystem", return_value=False
            ), mock.patch.object(
                interrupted, "_copy_with_progress", side_effect=MediaCancelled("stop")
            ):
                with self.assertRaises(MediaCancelled):
                    interrupted.run()

            interrupted_task = database.list_tasks()[0]
            self.assertFalse(source.exists())
            self.assertTrue(Path(interrupted_task.temp_path).is_file())

            resumed = CompressionEngine(
                source_root=root,
                database=database,
                media=media,
                settings=CompressionSettings(mode=CpuMode.BALANCED),
                staging_dir=staging,
            )
            result = resumed.run()

            self.assertEqual(result.completed, 1)
            self.assertEqual(source.read_bytes(), b"compressed-video")
            self.assertEqual(database.list_tasks()[0].status, COMPLETED)

    def test_preflight_occupied_file_creates_no_temp(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "DJI_0001.MP4"
            source.write_bytes(b"original-video-content")
            media = FakeMedia()
            engine, database, source = self.make_engine(root, media)

            with mock.patch("desktop_app.video_compressor.engine.is_file_in_use", return_value=True):
                result = engine.run()

            self.assertEqual(result.blocked, 1)
            self.assertEqual(media.encode_calls, 0)
            self.assertFalse(Path(str(source) + ENCODE_TEMP_SUFFIX).exists())


if __name__ == "__main__":
    unittest.main()
