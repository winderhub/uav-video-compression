import os
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from desktop_app.video_compressor.config import CompressionSettings, CpuMode
from desktop_app.video_compressor.media import MediaTools


@unittest.skipUnless(
    os.environ.get("RUN_FFMPEG_INTEGRATION") == "1",
    "set RUN_FFMPEG_INTEGRATION=1 to run the real FFmpeg smoke test",
)
class MediaIntegrationTests(unittest.TestCase):
    def test_real_ffmpeg_encode_and_probe(self):
        with tempfile.TemporaryDirectory(prefix="video_compressor_integration_") as temp_dir:
            root = Path(temp_dir)
            source = root / "source.MP4"
            output = root / "output.MP4"
            log_path = root / "encode.log"
            media = MediaTools()
            subprocess.run(
                [
                    str(media.ffmpeg),
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc2=size=320x240:rate=30:duration=1",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "ultrafast",
                    "-pix_fmt",
                    "yuv420p",
                    "-an",
                    "-y",
                    str(source),
                ],
                check=True,
            )
            source_probe = media.probe(source)
            progress_values = []
            media.encode(
                source,
                output,
                CompressionSettings(mode=CpuMode.QUIET),
                log_path,
                threading.Event(),
                progress_values.append,
                source_probe.duration,
            )
            output_probe = media.probe(output)

            self.assertEqual(source_probe.packets, output_probe.packets)
            self.assertEqual((output_probe.width, output_probe.height), (320, 240))
            self.assertTrue(progress_values)
            self.assertEqual(progress_values[-1], 1.0)


if __name__ == "__main__":
    unittest.main()
