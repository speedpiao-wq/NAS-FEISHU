"""
PO 合同 Excel 生成器。

输出的 Excel 文件遵循标准采购订单格式：
  - 第一行：公司名称（大标题）
  - 第二行：采购订单（表单标题）
  - 供应商 / 采购方信息区块
  - 商品明细表格
  - 合计金额
  - 付款 / 交货条款
  - 签字确认区域
"""
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from openpyxl import Workbook
from openpyxl.styles import (
    Alignment,
    Border,
    Font,
    PatternFill,
    Side,
)
from openpyxl.utils import get_column_letter

from config import CompanyConfig, NASConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 样式常量
# ---------------------------------------------------------------------------

_THIN = Side(style="thin")
_MEDIUM = Side(style="medium")

_BORDER_ALL_THIN = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_BORDER_ALL_MEDIUM = Border(left=_MEDIUM, right=_MEDIUM, top=_MEDIUM, bottom=_MEDIUM)
_BORDER_BOTTOM_MEDIUM = Border(bottom=_MEDIUM)

_FONT_TITLE = Font(name="微软雅黑", size=18, bold=True)
_FONT_SUBTITLE = Font(name="微软雅黑", size=14, bold=True)
_FONT_HEADER = Font(name="微软雅黑", size=11, bold=True, color="FFFFFF")
_FONT_LABEL = Font(name="微软雅黑", size=10, bold=True)
_FONT_NORMAL = Font(name="微软雅黑", size=10)
_FONT_TOTAL = Font(name="微软雅黑", size=11, bold=True)

_FILL_HEADER = PatternFill(fill_type="solid", fgColor="1F4E79")
_FILL_LABEL = PatternFill(fill_type="solid", fgColor="D6E4F0")
_FILL_SUBTOTAL = PatternFill(fill_type="solid", fgColor="EBF5FB")

_ALIGN_CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
_ALIGN_LEFT = Alignment(horizontal="left", vertical="center", wrap_text=True)
_ALIGN_RIGHT = Alignment(horizontal="right", vertical="center", wrap_text=True)

# 列宽配置（单位：字符宽度）
_COL_WIDTHS = [5, 28, 8, 10, 12, 14, 14]
# 对应列：序号 | 商品描述 | 单位 | 数量 | 单价 | 金额 | 备注


def _apply_cell(
    ws: Any,
    row: int,
    col: int,
    value: Any,
    font: Optional[Font] = None,
    fill: Optional[PatternFill] = None,
    border: Optional[Border] = None,
    alignment: Optional[Alignment] = None,
    number_format: Optional[str] = None,
) -> None:
    """写入单元格并应用样式"""
    cell = ws.cell(row=row, column=col, value=value)
    if font:
        cell.font = font
    if fill:
        cell.fill = fill
    if border:
        cell.border = border
    if alignment:
        cell.alignment = alignment
    if number_format:
        cell.number_format = number_format


def _merge_and_apply(
    ws: Any,
    start_row: int,
    start_col: int,
    end_row: int,
    end_col: int,
    value: Any = None,
    **kwargs: Any,
) -> None:
    """合并单元格区域并设置内容与样式"""
    ws.merge_cells(
        start_row=start_row,
        start_column=start_col,
        end_row=end_row,
        end_column=end_col,
    )
    _apply_cell(ws, start_row, start_col, value, **kwargs)


class ExcelGenerator:
    """
    PO 合同 Excel 文件生成器。

    用法::

        gen = ExcelGenerator()
        path = gen.generate(po_data)
        # path 为生成文件的绝对路径
    """

    # 总列数（A-G，共 7 列）
    TOTAL_COLS = 7

    def __init__(self, output_dir: Optional[str] = None):
        self.output_dir = Path(output_dir or NASConfig.OUTPUT_DIR)

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def generate(self, po_data: Dict[str, Any]) -> str:
        """
        根据 PO 数据生成 Excel 文件并保存到 NAS 目录。

        Args:
            po_data: 字典，字段与 Bitable 规范化字段一致

        Returns:
            生成文件的绝对路径字符串
        """
        wb = Workbook()
        ws = wb.active
        ws.title = "采购订单"

        self._set_column_widths(ws)
        current_row = 1
        current_row = self._write_header(ws, po_data, current_row)
        current_row = self._write_info_section(ws, po_data, current_row)
        current_row = self._write_items_table(ws, po_data, current_row)
        current_row = self._write_terms_section(ws, po_data, current_row)
        current_row = self._write_signature_section(ws, current_row)

        # 冻结前两行（标题行）
        ws.freeze_panes = ws.cell(row=3, column=1)

        # 页面设置（A4 横向打印）
        ws.page_setup.orientation = "landscape"
        ws.page_setup.paperSize = 9  # A4
        ws.print_area = f"A1:{get_column_letter(self.TOTAL_COLS)}{current_row}"

        filepath = self._build_filepath(po_data)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        wb.save(filepath)
        logger.info("PO 合同已保存: %s", filepath)
        return str(filepath)

    # ------------------------------------------------------------------
    # 内部辅助：写入各区块
    # ------------------------------------------------------------------

    def _set_column_widths(self, ws: Any) -> None:
        for idx, width in enumerate(_COL_WIDTHS, start=1):
            ws.column_dimensions[get_column_letter(idx)].width = width
        ws.row_dimensions[1].height = 30
        ws.row_dimensions[2].height = 22

    def _write_header(self, ws: Any, po_data: Dict[str, Any], row: int) -> int:
        """写入公司标题与文档标题"""
        # 公司名称
        _merge_and_apply(
            ws, row, 1, row, self.TOTAL_COLS,
            value=CompanyConfig.NAME,
            font=_FONT_TITLE,
            alignment=_ALIGN_CENTER,
        )
        row += 1

        # "采购订单" 副标题
        _merge_and_apply(
            ws, row, 1, row, self.TOTAL_COLS,
            value="采 购 订 单",
            font=_FONT_SUBTITLE,
            alignment=_ALIGN_CENTER,
        )
        row += 1

        # 分隔线
        for col in range(1, self.TOTAL_COLS + 1):
            ws.cell(row=row, column=col).border = _BORDER_BOTTOM_MEDIUM
        row += 1

        return row

    def _write_info_section(self, ws: Any, po_data: Dict[str, Any], row: int) -> int:
        """写入合同基本信息（供应商 / 采购方 / 合同号等）"""

        def label_value(r: int, lc: int, label: str, vc: int, value: Any, lspan: int = 1, vspan: int = 2) -> None:
            _merge_and_apply(
                ws, r, lc, r, lc + lspan - 1,
                value=label,
                font=_FONT_LABEL,
                fill=_FILL_LABEL,
                border=_BORDER_ALL_THIN,
                alignment=_ALIGN_CENTER,
            )
            _merge_and_apply(
                ws, r, vc, r, vc + vspan - 1,
                value=value,
                font=_FONT_NORMAL,
                border=_BORDER_ALL_THIN,
                alignment=_ALIGN_LEFT,
            )

        # 行：合同编号 | 合同日期
        label_value(row, 1, "合同编号", 2, po_data.get("po_number", ""), lspan=1, vspan=2)
        label_value(row, 4, "合同日期", 5, po_data.get("contract_date", ""), lspan=1, vspan=3)
        row += 1

        # 行：供应商名称 | 采购方名称
        label_value(row, 1, "供应商", 2, po_data.get("supplier_name", ""), lspan=1, vspan=2)
        label_value(row, 4, "采购方", 5, po_data.get("buyer_name", ""), lspan=1, vspan=3)
        row += 1

        # 行：供应商地址 | 采购部门
        label_value(row, 1, "供应商地址", 2, po_data.get("supplier_address", ""), lspan=1, vspan=2)
        label_value(row, 4, "采购部门", 5, po_data.get("buyer_dept", ""), lspan=1, vspan=3)
        row += 1

        # 行：供应商联系人 | 采购联系人
        label_value(row, 1, "联系人", 2, po_data.get("supplier_contact", ""), lspan=1, vspan=2)
        label_value(row, 4, "采购联系人", 5, po_data.get("buyer_contact", ""), lspan=1, vspan=3)
        row += 1

        # 行：供应商电话 | 货币 + 收货地址
        label_value(row, 1, "联系电话", 2, po_data.get("supplier_tel", ""), lspan=1, vspan=2)
        label_value(row, 4, "货币", 5, po_data.get("currency", "CNY"), lspan=1, vspan=1)
        _apply_cell(ws, row, 6, po_data.get("delivery_address", ""),
                    font=_FONT_NORMAL, border=_BORDER_ALL_THIN, alignment=_ALIGN_LEFT)
        ws.merge_cells(start_row=row, start_column=6, end_row=row, end_column=7)
        row += 1

        return row

    def _write_items_table(self, ws: Any, po_data: Dict[str, Any], row: int) -> int:
        """写入商品明细表格"""
        # 表头行
        headers = ["序号", "商品描述", "单位", "数量", "单价", "金额", "备注"]
        for col, header in enumerate(headers, start=1):
            _apply_cell(
                ws, row, col, header,
                font=_FONT_HEADER,
                fill=_FILL_HEADER,
                border=_BORDER_ALL_THIN,
                alignment=_ALIGN_CENTER,
            )
        row += 1

        items: List[Dict[str, Any]] = po_data.get("items") or []
        currency = po_data.get("currency", "CNY")
        number_fmt = '#,##0.00' if currency == "CNY" else '#,##0.00'

        total_amount = 0.0
        for idx, item in enumerate(items, start=1):
            qty = float(item.get("qty") or item.get("quantity") or 0)
            unit_price = float(item.get("unit_price") or item.get("price") or 0)
            amount = qty * unit_price
            total_amount += amount

            row_data = [
                idx,
                item.get("description") or item.get("name") or "",
                item.get("unit") or "个",
                qty,
                unit_price,
                amount,
                item.get("notes") or item.get("remark") or "",
            ]
            for col, value in enumerate(row_data, start=1):
                nfmt = number_fmt if col in (4, 5, 6) else None
                _apply_cell(
                    ws, row, col, value,
                    font=_FONT_NORMAL,
                    border=_BORDER_ALL_THIN,
                    alignment=_ALIGN_RIGHT if col in (4, 5, 6) else _ALIGN_LEFT,
                    number_format=nfmt,
                )
            row += 1

        # 补充空白行（至少 5 行空白）
        min_blank = max(5 - len(items), 0)
        for _ in range(min_blank):
            for col in range(1, self.TOTAL_COLS + 1):
                _apply_cell(ws, row, col, None, border=_BORDER_ALL_THIN, alignment=_ALIGN_LEFT)
            row += 1

        # 合计行
        _merge_and_apply(
            ws, row, 1, row, 5,
            value="合  计",
            font=_FONT_TOTAL,
            fill=_FILL_SUBTOTAL,
            border=_BORDER_ALL_THIN,
            alignment=_ALIGN_RIGHT,
        )
        _apply_cell(
            ws, row, 6, total_amount,
            font=_FONT_TOTAL,
            fill=_FILL_SUBTOTAL,
            border=_BORDER_ALL_THIN,
            alignment=_ALIGN_RIGHT,
            number_format=number_fmt,
        )
        _apply_cell(
            ws, row, 7, None,
            font=_FONT_NORMAL,
            fill=_FILL_SUBTOTAL,
            border=_BORDER_ALL_THIN,
        )
        row += 1

        return row

    def _write_terms_section(self, ws: Any, po_data: Dict[str, Any], row: int) -> int:
        """写入付款条款、交货日期、备注"""
        terms_data = [
            ("付款条款", po_data.get("payment_terms", "")),
            ("交货日期", po_data.get("delivery_date", "")),
            ("收货地址", po_data.get("delivery_address", "")),
            ("备    注", po_data.get("notes", "")),
        ]
        for label, value in terms_data:
            _apply_cell(
                ws, row, 1, label,
                font=_FONT_LABEL,
                fill=_FILL_LABEL,
                border=_BORDER_ALL_THIN,
                alignment=_ALIGN_CENTER,
            )
            _merge_and_apply(
                ws, row, 2, row, self.TOTAL_COLS,
                value=value,
                font=_FONT_NORMAL,
                border=_BORDER_ALL_THIN,
                alignment=_ALIGN_LEFT,
            )
            ws.row_dimensions[row].height = 18
            row += 1

        return row

    def _write_signature_section(self, ws: Any, row: int) -> int:
        """写入签字确认区域"""
        row += 1  # 空行间距

        sig_labels = [
            ("供应商确认签字", 1, 3),
            ("采购方签字", 5, 7),
        ]
        for label, start_col, end_col in sig_labels:
            _merge_and_apply(
                ws, row, start_col, row, end_col,
                value=label,
                font=_FONT_LABEL,
                fill=_FILL_LABEL,
                border=_BORDER_ALL_THIN,
                alignment=_ALIGN_CENTER,
            )
        # 4 列留空（中间间隔列，可根据需要调整）
        ws.cell(row=row, column=4).border = _BORDER_ALL_THIN
        row += 1

        # 签名空白行（3 行高度）
        for _ in range(3):
            ws.row_dimensions[row].height = 20
            for start_col, end_col in [(1, 3), (5, 7)]:
                _merge_and_apply(
                    ws, row, start_col, row, end_col,
                    value=None,
                    border=_BORDER_ALL_THIN,
                    alignment=_ALIGN_CENTER,
                )
            ws.cell(row=row, column=4).border = _BORDER_ALL_THIN
            row += 1

        # 日期行
        for label, start_col, end_col in [("日期：", 1, 3), ("日期：", 5, 7)]:
            _merge_and_apply(
                ws, row, start_col, row, end_col,
                value=label,
                font=_FONT_LABEL,
                border=_BORDER_ALL_THIN,
                alignment=_ALIGN_LEFT,
            )
        ws.cell(row=row, column=4).border = _BORDER_ALL_THIN
        row += 1

        return row

    # ------------------------------------------------------------------
    # 文件命名
    # ------------------------------------------------------------------

    def _build_filepath(self, po_data: Dict[str, Any]) -> Path:
        po_number = str(po_data.get("po_number") or "UNKNOWN").replace("/", "-").replace("\\", "-")
        date_str = datetime.now().strftime("%Y%m%d")
        filename = f"PO_{po_number}_{date_str}.xlsx"
        return self.output_dir / filename
