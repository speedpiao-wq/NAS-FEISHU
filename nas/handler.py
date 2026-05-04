"""
NAS 存储处理模块：管理 Excel 合同文件在 NAS 目录中的存储、列举与清理。
"""
import logging
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from config import NASConfig

logger = logging.getLogger(__name__)


class NASHandler:
    """
    NAS 目录操作封装。

    NAS 目录结构::

        <output_dir>/
        └── YYYY/
            └── MM/
                └── PO_<number>_<date>.xlsx
    """

    def __init__(self, output_dir: Optional[str] = None):
        self.output_dir = Path(output_dir or NASConfig.OUTPUT_DIR)

    # ------------------------------------------------------------------
    # 目录管理
    # ------------------------------------------------------------------

    def ensure_dir(self, subpath: Optional[str] = None) -> Path:
        """
        确保目标目录存在（不存在则创建）。

        Args:
            subpath: 相对于 output_dir 的子路径，为 None 时使用当前年月

        Returns:
            已确保存在的目录 Path 对象
        """
        if subpath:
            target = self.output_dir / subpath
        else:
            now = datetime.now()
            target = self.output_dir / str(now.year) / f"{now.month:02d}"
        target.mkdir(parents=True, exist_ok=True)
        return target

    def get_monthly_dir(self, year: Optional[int] = None, month: Optional[int] = None) -> Path:
        """返回指定年月的子目录（自动创建）"""
        now = datetime.now()
        y = year or now.year
        m = month or now.month
        return self.ensure_dir(f"{y}/{m:02d}")

    # ------------------------------------------------------------------
    # 文件操作
    # ------------------------------------------------------------------

    def save_file(self, src_path: str, dest_filename: Optional[str] = None) -> str:
        """
        将文件复制到 NAS 按年月分组的目录中。

        Args:
            src_path:      源文件路径
            dest_filename: 目标文件名，为 None 时保留原文件名

        Returns:
            目标文件的绝对路径字符串
        """
        src = Path(src_path)
        if not src.exists():
            raise FileNotFoundError(f"源文件不存在: {src_path}")

        dest_dir = self.get_monthly_dir()
        dest = dest_dir / (dest_filename or src.name)
        shutil.copy2(src, dest)
        logger.info("文件已保存至 NAS: %s", dest)
        return str(dest)

    def list_files(
        self,
        pattern: str = "*.xlsx",
        year: Optional[int] = None,
        month: Optional[int] = None,
    ) -> List[str]:
        """
        列举 NAS 目录（或指定年月子目录）中符合模式的文件。

        Args:
            pattern: 文件名通配符，默认 *.xlsx
            year:    指定年份，None 表示全部
            month:   指定月份，None 表示全部

        Returns:
            文件绝对路径字符串列表，按修改时间降序排列
        """
        if year and month:
            search_root = self.output_dir / str(year) / f"{month:02d}"
        elif year:
            search_root = self.output_dir / str(year)
        else:
            search_root = self.output_dir

        if not search_root.exists():
            return []

        files = sorted(
            search_root.rglob(pattern),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return [str(f) for f in files]

    def cleanup_old_files(self, days: int = 365) -> int:
        """
        清理超过指定天数的文件（默认 1 年）。

        Args:
            days: 超过此天数的文件将被删除

        Returns:
            删除的文件数量
        """
        cutoff = datetime.now() - timedelta(days=days)
        deleted = 0
        for filepath in self.output_dir.rglob("*.xlsx"):
            mtime = datetime.fromtimestamp(filepath.stat().st_mtime)
            if mtime < cutoff:
                filepath.unlink()
                logger.info("已清理过期文件: %s", filepath)
                deleted += 1
        return deleted

    # ------------------------------------------------------------------
    # 磁盘空间检查
    # ------------------------------------------------------------------

    def check_disk_space(self, min_free_mb: int = 500) -> bool:
        """
        检查 NAS 挂载点剩余空间是否满足最低要求。

        Args:
            min_free_mb: 最低剩余空间 MB

        Returns:
            True 表示空间充足，False 表示不足
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)
        stat = shutil.disk_usage(str(self.output_dir))
        free_mb = stat.free / (1024 * 1024)
        if free_mb < min_free_mb:
            logger.warning("NAS 剩余空间不足: %.1f MB（最低要求 %d MB）", free_mb, min_free_mb)
            return False
        return True

    def get_disk_usage_info(self) -> dict:
        """返回磁盘使用情况（total/used/free，单位 MB）"""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        stat = shutil.disk_usage(str(self.output_dir))
        return {
            "total_mb": round(stat.total / (1024 * 1024), 1),
            "used_mb": round(stat.used / (1024 * 1024), 1),
            "free_mb": round(stat.free / (1024 * 1024), 1),
        }
