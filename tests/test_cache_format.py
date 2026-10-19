import tempfile
import unittest
from pathlib import Path

from app.cache_format import (
    CacheFormat,
    ContentGroup,
    detect_cache_format,
    parse_media3_filename,
    group_media3_segments,
    is_single_stream_media3,
)


class FormatDetectionTests(unittest.TestCase):
    def test_detect_legacy_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "0.0.segment.exo").write_bytes(b"data")
            (root / "1.0.segment.exo").write_bytes(b"data")
            self.assertEqual(detect_cache_format(root), CacheFormat.LEGACY)

    def test_detect_media3_v3_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "0.0.1697456789123.v3.exo").write_bytes(b"data")
            (root / "0.1048576.1697456789456.v3.exo").write_bytes(b"data")
            self.assertEqual(detect_cache_format(root), CacheFormat.MEDIA3_V3)

    def test_detect_empty_folder_returns_legacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(detect_cache_format(Path(tmp)), CacheFormat.LEGACY)

    def test_detect_mixed_prefers_media3(self):
        """When both formats exist, Media3 v3 files take priority."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "0.0.segment.exo").write_bytes(b"data")
            (root / "0.0.1697456789123.v3.exo").write_bytes(b"data")
            self.assertEqual(detect_cache_format(root), CacheFormat.MEDIA3_V3)


class Media3ParsingTests(unittest.TestCase):
    def test_parse_valid_v3_filename(self):
        result = parse_media3_filename("0.0.1697456789123.v3.exo")
        self.assertEqual(result, (0, 0, 1697456789123))

    def test_parse_v3_with_large_offset(self):
        result = parse_media3_filename("1.5242880.1697456790000.v3.exo")
        self.assertEqual(result, (1, 5242880, 1697456790000))

    def test_parse_legacy_filename_returns_none(self):
        self.assertIsNone(parse_media3_filename("0.0.segment.exo"))

    def test_parse_non_exo_returns_none(self):
        self.assertIsNone(parse_media3_filename("readme.txt"))


class ContentGroupingTests(unittest.TestCase):
    def test_groups_by_content_id_sorted_by_offset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Content 0 (video): two chunks
            (root / "0.1048576.1697456789456.v3.exo").write_bytes(b"chunk2")
            (root / "0.0.1697456789123.v3.exo").write_bytes(b"chunk1")
            # Content 1 (audio): one chunk
            (root / "1.0.1697456789789.v3.exo").write_bytes(b"audio1")

            groups = group_media3_segments(root)

            self.assertEqual(len(groups), 2)
            # Group 0: video, sorted by offset
            self.assertEqual(groups[0].content_id, 0)
            self.assertEqual(len(groups[0].segments), 2)
            self.assertEqual(groups[0].segments[0].name, "0.0.1697456789123.v3.exo")
            self.assertEqual(groups[0].segments[1].name, "0.1048576.1697456789456.v3.exo")
            # Group 1: audio
            self.assertEqual(groups[1].content_id, 1)
            self.assertEqual(len(groups[1].segments), 1)

    def test_recursive_discovery_in_numbered_subdirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sub = root / "0"
            sub.mkdir()
            (sub / "0.0.1697456789123.v3.exo").write_bytes(b"data")
            (sub / "0.1048576.1697456789456.v3.exo").write_bytes(b"data")

            groups = group_media3_segments(root)

            self.assertEqual(len(groups), 1)
            self.assertEqual(len(groups[0].segments), 2)

    def test_empty_files_are_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "0.0.1697456789123.v3.exo").write_bytes(b"data")
            (root / "0.1048576.1697456789456.v3.exo").write_bytes(b"")  # empty

            groups = group_media3_segments(root)

            self.assertEqual(len(groups[0].segments), 1)


class SingleStreamTests(unittest.TestCase):
    """Test the anime vs YouTube single-stream heuristic."""

    def test_anime_style_all_offset_zero_is_single_stream(self):
        """Each content_id has 1 fragment at offset 0 → single stream."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in range(5):
                (root / f"{i}.0.{1000+i}.v3.exo").write_bytes(b"data")

            groups = group_media3_segments(root)
            self.assertTrue(is_single_stream_media3(groups))

    def test_youtube_style_multi_chunk_is_not_single_stream(self):
        """Content_id with multiple fragments → multi-track."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Video track with 2 chunks
            (root / "0.0.1000.v3.exo").write_bytes(b"chunk1")
            (root / "0.1048576.1001.v3.exo").write_bytes(b"chunk2")
            # Audio track
            (root / "1.0.1002.v3.exo").write_bytes(b"audio")

            groups = group_media3_segments(root)
            self.assertFalse(is_single_stream_media3(groups))

    def test_empty_groups_returns_false(self):
        self.assertFalse(is_single_stream_media3([]))


if __name__ == "__main__":
    unittest.main()
