"""
单元测试：NASHandler

测试 NAS 目录操作，包括：
- 目录自动创建
- 文件保存
- 文件列举
- 过期文件清理
- 磁盘空间检查
"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from nas.handler import NASHandler


@pytest.fixture
def nas(tmp_path: Path) -> NASHandler:
    return NASHandler(output_dir=str(tmp_path / "nas"))


@pytest.fixture
def sample_xlsx(tmp_path: Path) -> Path:
    """创建一个临时 xlsx 文件用于测试复制"""
    f = tmp_path / "sample.xlsx"
    f.write_bytes(b"PK\x03\x04")  # xlsx 文件魔数前缀（非真实 xlsx，仅测试复制）
    return f


class TestNASHandlerDirectory:
    """目录管理测试"""

    def test_ensure_dir_creates_path(self, nas: NASHandler):
        target = nas.ensure_dir("test/subdir")
        assert target.exists() and target.is_dir()

    def test_ensure_dir_default_creates_year_month(self, nas: NASHandler):
        from datetime import datetime
        now = datetime.now()
        expected_suffix = f"{now.year}/{now.month:02d}"
        target = nas.ensure_dir()
        assert target.exists()
        assert str(target).endswith(expected_suffix)

    def test_get_monthly_dir_creates_correct_path(self, nas: NASHandler):
        target = nas.get_monthly_dir(year=2024, month=3)
        assert target.exists()
        assert "2024/03" in str(target)


class TestNASHandlerFiles:
    """文件操作测试"""

    def test_save_file_copies_to_nas(self, nas: NASHandler, sample_xlsx: Path):
        dest = nas.save_file(str(sample_xlsx))
        assert Path(dest).exists(), "文件应被复制到 NAS"

    def test_save_file_with_custom_name(self, nas: NASHandler, sample_xlsx: Path):
        dest = nas.save_file(str(sample_xlsx), dest_filename="custom_name.xlsx")
        assert Path(dest).name == "custom_name.xlsx"

    def test_save_file_raises_if_source_missing(self, nas: NASHandler):
        with pytest.raises(FileNotFoundError):
            nas.save_file("/nonexistent/path/file.xlsx")

    def test_list_files_returns_saved_files(self, nas: NASHandler, sample_xlsx: Path):
        nas.save_file(str(sample_xlsx))
        files = nas.list_files()
        assert len(files) >= 1, "应能列出已保存的文件"

    def test_list_files_empty_when_no_files(self, nas: NASHandler):
        files = nas.list_files()
        assert files == []

    def test_list_files_by_year_month(self, nas: NASHandler, sample_xlsx: Path):
        from datetime import datetime
        now = datetime.now()
        nas.save_file(str(sample_xlsx))
        files = nas.list_files(year=now.year, month=now.month)
        assert len(files) >= 1


class TestNASHandlerCleanup:
    """文件清理测试"""

    def test_cleanup_old_files_removes_expired(self, nas: NASHandler, tmp_path: Path):
        """创建一个已过期文件（通过修改 mtime），验证 cleanup 删除它"""
        # 先正常保存
        src = tmp_path / "old.xlsx"
        src.write_bytes(b"PK")
        dest_path = nas.save_file(str(src))
        dest = Path(dest_path)

        # 将 mtime 设置为 2 年前
        old_time = time.time() - 365 * 2 * 24 * 3600
        import os
        os.utime(dest_path, (old_time, old_time))

        deleted = nas.cleanup_old_files(days=365)
        assert deleted >= 1, "应删除过期文件"
        assert not dest.exists(), "过期文件应已被删除"

    def test_cleanup_keeps_recent_files(self, nas: NASHandler, sample_xlsx: Path):
        nas.save_file(str(sample_xlsx))
        deleted = nas.cleanup_old_files(days=365)
        assert deleted == 0, "近期文件不应被删除"


class TestNASHandlerDisk:
    """磁盘空间检查测试"""

    def test_check_disk_space_returns_bool(self, nas: NASHandler):
        result = nas.check_disk_space(min_free_mb=1)
        assert isinstance(result, bool)

    def test_get_disk_usage_info_has_keys(self, nas: NASHandler):
        info = nas.get_disk_usage_info()
        assert "total_mb" in info
        assert "used_mb" in info
        assert "free_mb" in info
        assert info["total_mb"] > 0
