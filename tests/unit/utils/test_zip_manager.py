#!/usr/bin/env python3
"""
Comprehensive test suite for zip_manager.py
Testing ZIP file creation, caching, and reference counting
"""

import pytest
import zipfile
from pathlib import Path
from PIL import Image
from src.utils.zip_manager import ZIPManager, get_zip_manager


class TestZIPManagerInit:
    """Test ZIPManager initialization"""

    def test_init_with_temp_dir(self, tmp_path):
        """Test initialization with custom temp directory"""
        manager = ZIPManager(temp_dir=tmp_path)
        assert manager.temp_dir == tmp_path
        assert tmp_path.exists()

    def test_init_without_temp_dir(self):
        """Test initialization uses system temp if not provided"""
        manager = ZIPManager()
        assert manager.temp_dir is not None
        assert manager.temp_dir.exists()

    def test_init_creates_temp_dir(self, tmp_path):
        """Test initialization creates temp directory if missing"""
        temp_dir = tmp_path / "new_temp"
        assert not temp_dir.exists()
        manager = ZIPManager(temp_dir=temp_dir)
        assert temp_dir.exists()

    def test_cache_initialized_empty(self, tmp_path):
        """Test cache is initialized empty"""
        manager = ZIPManager(temp_dir=tmp_path)
        assert manager.zip_cache == {}

    def test_lock_initialized(self, tmp_path):
        """Test threading lock is initialized"""
        manager = ZIPManager(temp_dir=tmp_path)
        assert manager.lock is not None


class TestCreateOrReuseZip:
    """Test ZIP creation and reuse logic"""

    @pytest.fixture
    def gallery_folder(self, tmp_path):
        """Create a test gallery folder with images"""
        folder = tmp_path / "gallery"
        folder.mkdir()
        # Create test images
        for i in range(3):
            img = Image.new('RGB', (100, 100), color='red')
            img.save(folder / f"image{i}.jpg")
        return folder

    def test_create_new_zip(self, tmp_path, gallery_folder):
        """Test creating a new ZIP file"""
        manager = ZIPManager(temp_dir=tmp_path)
        zip_path = manager.create_or_reuse_zip(
            db_id=1,
            folder_path=gallery_folder,
            gallery_name="Test Gallery"
        )

        assert zip_path.exists()
        assert zip_path.suffix == ".zip"
        assert zipfile.is_zipfile(zip_path)

    def test_zip_added_to_cache(self, tmp_path, gallery_folder):
        """Test created ZIP is added to cache"""
        manager = ZIPManager(temp_dir=tmp_path)
        zip_path = manager.create_or_reuse_zip(1, gallery_folder)

        assert 1 in manager.zip_cache
        cached_path, ref_count = manager.zip_cache[1]
        assert cached_path == zip_path
        assert ref_count == 1

    def test_reuse_existing_zip(self, tmp_path, gallery_folder):
        """Test reusing existing cached ZIP"""
        manager = ZIPManager(temp_dir=tmp_path)

        # Create first time
        zip_path1 = manager.create_or_reuse_zip(1, gallery_folder)

        # Request again - should reuse
        zip_path2 = manager.create_or_reuse_zip(1, gallery_folder)

        assert zip_path1 == zip_path2
        _, ref_count = manager.zip_cache[1]
        assert ref_count == 2

    def test_zip_name_with_gallery_name(self, tmp_path, gallery_folder):
        """Test ZIP filename includes gallery name"""
        manager = ZIPManager(temp_dir=tmp_path)
        zip_path = manager.create_or_reuse_zip(
            db_id=42,
            folder_path=gallery_folder,
            gallery_name="My Test Gallery"
        )

        assert "42" in zip_path.name
        assert "My_Test_Gallery" in zip_path.name or "My" in zip_path.name

    def test_zip_name_without_gallery_name(self, tmp_path, gallery_folder):
        """Test ZIP filename without gallery name"""
        manager = ZIPManager(temp_dir=tmp_path)
        zip_path = manager.create_or_reuse_zip(
            db_id=42,
            folder_path=gallery_folder
        )

        assert "42" in zip_path.name
        assert "gallery" in zip_path.name.lower()

    def test_zip_contains_images(self, tmp_path, gallery_folder):
        """Test ZIP contains all images from folder"""
        manager = ZIPManager(temp_dir=tmp_path)
        zip_path = manager.create_or_reuse_zip(1, gallery_folder)

        with zipfile.ZipFile(zip_path, 'r') as zf:
            files = zf.namelist()
            assert len(files) == 3
            assert "image0.jpg" in files
            assert "image1.jpg" in files
            assert "image2.jpg" in files

    def test_zip_uses_store_mode(self, tmp_path, gallery_folder):
        """Test ZIP uses STORED (no compression) mode"""
        manager = ZIPManager(temp_dir=tmp_path)
        zip_path = manager.create_or_reuse_zip(1, gallery_folder)

        with zipfile.ZipFile(zip_path, 'r') as zf:
            for info in zf.infolist():
                assert info.compress_type == zipfile.ZIP_STORED

    def test_empty_folder_raises_error(self, tmp_path):
        """Test empty folder raises ValueError"""
        empty_folder = tmp_path / "empty"
        empty_folder.mkdir()

        manager = ZIPManager(temp_dir=tmp_path)
        with pytest.raises(ValueError, match="No image files found"):
            manager.create_or_reuse_zip(1, empty_folder)

    def test_nonexistent_folder_raises_error(self, tmp_path):
        """Test nonexistent folder raises FileNotFoundError"""
        manager = ZIPManager(temp_dir=tmp_path)
        with pytest.raises(FileNotFoundError):
            manager.create_or_reuse_zip(1, tmp_path / "nonexistent")

    def test_file_instead_of_folder_raises_error(self, tmp_path):
        """Test passing a file instead of folder raises ValueError"""
        test_file = tmp_path / "file.txt"
        test_file.touch()

        manager = ZIPManager(temp_dir=tmp_path)
        with pytest.raises(ValueError, match="not a directory"):
            manager.create_or_reuse_zip(1, test_file)

    def test_cached_zip_deleted_externally(self, tmp_path, gallery_folder):
        """Test handling when cached ZIP is deleted externally"""
        manager = ZIPManager(temp_dir=tmp_path)

        # Create ZIP
        zip_path1 = manager.create_or_reuse_zip(1, gallery_folder)

        # Delete ZIP externally
        zip_path1.unlink()

        # Request again - should recreate
        zip_path2 = manager.create_or_reuse_zip(1, gallery_folder)
        assert zip_path2.exists()
        assert zip_path2 == zip_path1  # Same path

    def test_multiple_galleries(self, tmp_path, gallery_folder):
        """Test managing ZIPs for multiple galleries"""
        manager = ZIPManager(temp_dir=tmp_path)

        zip1 = manager.create_or_reuse_zip(1, gallery_folder)
        zip2 = manager.create_or_reuse_zip(2, gallery_folder)

        assert zip1 != zip2
        assert len(manager.zip_cache) == 2
        assert 1 in manager.zip_cache
        assert 2 in manager.zip_cache


class TestReleaseZip:
    """Test ZIP reference release and cleanup"""

    @pytest.fixture
    def gallery_folder(self, tmp_path):
        """Create test gallery folder"""
        folder = tmp_path / "gallery"
        folder.mkdir()
        img = Image.new('RGB', (100, 100), color='red')
        img.save(folder / "image.jpg")
        return folder

    def test_release_decrements_ref_count(self, tmp_path, gallery_folder):
        """Test release decrements reference count"""
        manager = ZIPManager(temp_dir=tmp_path)
        manager.create_or_reuse_zip(1, gallery_folder)
        manager.create_or_reuse_zip(1, gallery_folder)  # ref_count = 2

        deleted = manager.release_zip(1)

        assert not deleted
        _, ref_count = manager.zip_cache[1]
        assert ref_count == 1

    def test_release_last_reference_deletes(self, tmp_path, gallery_folder):
        """Test releasing last reference deletes ZIP"""
        manager = ZIPManager(temp_dir=tmp_path)
        zip_path = manager.create_or_reuse_zip(1, gallery_folder)

        deleted = manager.release_zip(1)

        assert deleted
        assert not zip_path.exists()
        assert 1 not in manager.zip_cache

    def test_force_delete(self, tmp_path, gallery_folder):
        """Test force_delete ignores ref count"""
        manager = ZIPManager(temp_dir=tmp_path)
        zip_path = manager.create_or_reuse_zip(1, gallery_folder)
        manager.create_or_reuse_zip(1, gallery_folder)  # ref_count = 2

        deleted = manager.release_zip(1, force_delete=True)

        assert deleted
        assert not zip_path.exists()
        assert 1 not in manager.zip_cache

    def test_release_nonexistent_gallery(self, tmp_path):
        """Test releasing nonexistent gallery returns False"""
        manager = ZIPManager(temp_dir=tmp_path)
        result = manager.release_zip(999)
        assert result == False

    def test_release_already_deleted_zip(self, tmp_path, gallery_folder):
        """Test releasing when ZIP file already deleted"""
        manager = ZIPManager(temp_dir=tmp_path)
        zip_path = manager.create_or_reuse_zip(1, gallery_folder)

        # Delete file but leave in cache
        zip_path.unlink()

        deleted = manager.release_zip(1)

        # Should still remove from cache
        assert deleted == False  # File already gone
        assert 1 not in manager.zip_cache


class TestCleanupMethods:
    """Test cleanup methods"""

    @pytest.fixture
    def gallery_folder(self, tmp_path):
        """Create test gallery folder"""
        folder = tmp_path / "gallery"
        folder.mkdir()
        img = Image.new('RGB', (100, 100), color='red')
        img.save(folder / "image.jpg")
        return folder

    def test_cleanup_gallery(self, tmp_path, gallery_folder):
        """Test cleanup_gallery force deletes"""
        manager = ZIPManager(temp_dir=tmp_path)
        zip_path = manager.create_or_reuse_zip(1, gallery_folder)
        manager.create_or_reuse_zip(1, gallery_folder)  # ref_count = 2

        manager.cleanup_gallery(1)

        assert not zip_path.exists()
        assert 1 not in manager.zip_cache

    def test_cleanup_all(self, tmp_path, gallery_folder):
        """Test cleanup_all deletes all ZIPs"""
        manager = ZIPManager(temp_dir=tmp_path)

        zip1 = manager.create_or_reuse_zip(1, gallery_folder)
        zip2 = manager.create_or_reuse_zip(2, gallery_folder)
        zip3 = manager.create_or_reuse_zip(3, gallery_folder)

        deleted_count = manager.cleanup_all()

        assert deleted_count == 3
        assert not zip1.exists()
        assert not zip2.exists()
        assert not zip3.exists()
        assert len(manager.zip_cache) == 0

    def test_cleanup_all_empty_cache(self, tmp_path):
        """Test cleanup_all with empty cache"""
        manager = ZIPManager(temp_dir=tmp_path)
        deleted_count = manager.cleanup_all()
        assert deleted_count == 0


class TestGetCacheInfo:
    """Test cache information retrieval"""

    @pytest.fixture
    def gallery_folder(self, tmp_path):
        """Create test gallery folder"""
        folder = tmp_path / "gallery"
        folder.mkdir()
        img = Image.new('RGB', (100, 100), color='red')
        img.save(folder / "image.jpg")
        return folder

    def test_cache_info_structure(self, tmp_path, gallery_folder):
        """Test cache info returns correct structure"""
        manager = ZIPManager(temp_dir=tmp_path)
        manager.create_or_reuse_zip(1, gallery_folder)

        info = manager.get_cache_info()

        assert 1 in info
        assert 'path' in info[1]
        assert 'ref_count' in info[1]
        assert 'exists' in info[1]
        assert 'size_mb' in info[1]

    def test_cache_info_values(self, tmp_path, gallery_folder):
        """Test cache info contains correct values"""
        manager = ZIPManager(temp_dir=tmp_path)
        zip_path = manager.create_or_reuse_zip(1, gallery_folder)

        info = manager.get_cache_info()

        assert info[1]['path'] == str(zip_path)
        assert info[1]['ref_count'] == 1
        assert info[1]['exists'] == True
        assert info[1]['size_mb'] > 0

    def test_cache_info_multiple_galleries(self, tmp_path, gallery_folder):
        """Test cache info with multiple galleries"""
        manager = ZIPManager(temp_dir=tmp_path)
        manager.create_or_reuse_zip(1, gallery_folder)
        manager.create_or_reuse_zip(2, gallery_folder)

        info = manager.get_cache_info()

        assert len(info) == 2
        assert 1 in info
        assert 2 in info

    def test_cache_info_after_deletion(self, tmp_path, gallery_folder):
        """Test cache info after ZIP deleted externally"""
        manager = ZIPManager(temp_dir=tmp_path)
        zip_path = manager.create_or_reuse_zip(1, gallery_folder)
        zip_path.unlink()

        info = manager.get_cache_info()

        assert info[1]['exists'] == False
        assert info[1]['size_mb'] == 0


class TestGetZipManager:
    """Test global singleton getter"""

    def test_singleton_returns_instance(self):
        """Test get_zip_manager returns ZIPManager instance"""
        manager = get_zip_manager()
        assert isinstance(manager, ZIPManager)

    def test_singleton_same_instance(self):
        """Test multiple calls return same instance"""
        manager1 = get_zip_manager()
        manager2 = get_zip_manager()
        assert manager1 is manager2

    def test_singleton_has_temp_dir(self):
        """Test singleton instance has temp directory"""
        manager = get_zip_manager()
        assert manager.temp_dir is not None
        assert manager.temp_dir.exists()


class TestGenerateZipName:
    """Test ZIP filename generation"""

    def test_name_with_gallery_name(self, tmp_path):
        """Test filename includes gallery name"""
        manager = ZIPManager(temp_dir=tmp_path)
        name = manager._generate_zip_name(42, "Test Gallery")
        assert "42" in name
        assert "Test" in name
        assert name.endswith(".zip")

    def test_name_without_gallery_name(self, tmp_path):
        """Test filename without gallery name"""
        manager = ZIPManager(temp_dir=tmp_path)
        name = manager._generate_zip_name(42)
        assert name == "imxup_gallery_42.zip"

    def test_name_sanitization(self, tmp_path):
        """Test gallery name is sanitized"""
        manager = ZIPManager(temp_dir=tmp_path)
        name = manager._generate_zip_name(1, "Test<>Gallery/Name")
        # Should only contain alphanumeric, space, dash, underscore
        assert "<" not in name
        assert ">" not in name
        assert "/" not in name

    def test_name_length_limit(self, tmp_path):
        """Test long gallery names are truncated"""
        manager = ZIPManager(temp_dir=tmp_path)
        long_name = "A" * 100
        name = manager._generate_zip_name(1, long_name)
        # Name should be limited (50 chars for gallery name part)
        assert len(name) < 100

    def test_empty_gallery_name_uses_default(self, tmp_path):
        """Test empty gallery name uses default format"""
        manager = ZIPManager(temp_dir=tmp_path)
        name = manager._generate_zip_name(1, "")
        assert name == "imxup_gallery_1.zip"
