from contextlib import redirect_stdout
from io import StringIO
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.exo_merger import (
    build_ffmpeg_command,
    discover_segments,
    discover_episode_dirs,
    discover_subtitles,
    main,
    resolve_subtitle,
    validate_segments,
)


class DiscoveryTests(unittest.TestCase):
    def test_episode_directories_are_discovered_for_batch_mode(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for episode in ("Episode 01", "Episode 02"):
                episode_dir = root / episode / "chunks"
                episode_dir.mkdir(parents=True)
                (episode_dir / "0.0.segment.exo").write_bytes(b"segment")

            self.assertEqual(
                [path.name for path in discover_episode_dirs(root)],
                ["Episode 01", "Episode 02"],
            )

    def test_segments_are_sorted_by_numeric_prefix(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "10.0.segment.exo").touch()
            (root / "2.0.segment.exo").touch()
            (root / "notes.txt").touch()

            segments = discover_segments(root)

        self.assertEqual([path.name for path in segments], ["2.0.segment.exo", "10.0.segment.exo"])

    def test_subtitle_discovery_includes_language_and_common_formats(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "captions.en").touch()
            (root / "captions.in_ID").touch()
            (root / "captions.vtt").touch()
            (root / "unrelated.txt").touch()

            subtitles = discover_subtitles(root)

        self.assertEqual(
            {path.name for path in subtitles},
            {"captions.en", "captions.in_ID", "captions.vtt"},
        )

    def test_subtitle_can_be_selected_by_language_code_or_filename(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            indonesian = root / "captions.in_ID"
            english = root / "captions.en"
            indonesian.touch()
            english.touch()
            subtitles = discover_subtitles(root)

            self.assertEqual(resolve_subtitle(subtitles, "in_ID"), indonesian)
            self.assertEqual(resolve_subtitle(subtitles, "captions.en"), english)
            self.assertIsNone(resolve_subtitle(subtitles, "none"))

    def test_auto_prefers_indonesian_sidecar_over_duplicate_vtt(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            indonesian = root / "captions.in_ID"
            duplicate = root / "subtitle_indo.vtt"
            indonesian.touch()
            duplicate.touch()
            subtitles = discover_subtitles(root)

        self.assertEqual(resolve_subtitle(subtitles, None), indonesian)

    def test_indonesian_language_code_prefers_canonical_sidecar(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            indonesian = root / "captions.in_ID"
            duplicate = root / "subtitle_indo.vtt"
            indonesian.touch()
            duplicate.touch()
            subtitles = discover_subtitles(root)

        self.assertEqual(resolve_subtitle(subtitles, "in_ID"), indonesian)

    def test_segment_gaps_are_rejected_unless_explicitly_allowed(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            first = root / "0.0.segment.exo"
            last = root / "2.0.segment.exo"
            first.write_bytes(b"segment")
            last.write_bytes(b"segment")
            segments = discover_segments(root)

            with self.assertRaisesRegex(ValueError, "Missing"):
                validate_segments(segments)

            validate_segments(segments, allow_gaps=True)

    def test_duplicate_segment_indexes_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            first_directory = root / "0"
            second_directory = root / "1"
            first_directory.mkdir()
            second_directory.mkdir()
            (first_directory / "0.0.segment.exo").write_bytes(b"segment")
            (second_directory / "0.1.segment.exo").write_bytes(b"segment")

            with self.assertRaisesRegex(ValueError, "Duplicate"):
                validate_segments(discover_segments(root))

    def test_ffmpeg_command_stream_copies_when_subtitles_are_disabled(self):
        command = build_ffmpeg_command(
            "ffmpeg", Path("joined.ts"), Path("result.mp4"), None, "ultrafast", 23
        )

        self.assertIn("-c", command)
        self.assertIn("copy", command)
        self.assertNotIn("-vf", command)

    def test_list_subtitles_does_not_require_ffmpeg_or_overwrite_output(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "captions.en").write_bytes(b"subtitle")
            output = root / "existing.mp4"
            output.write_bytes(b"keep")

            with patch("app.exo_merger._find_executable", side_effect=AssertionError("FFmpeg must not run")):
                with redirect_stdout(StringIO()):
                    result = main(["--input-dir", str(root), "--output", str(output), "--list-subtitles"])

            self.assertEqual(result, 0)
            self.assertEqual(output.read_bytes(), b"keep")


if __name__ == "__main__":
    unittest.main()
