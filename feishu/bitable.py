"""
飞书 Bitable（多维表格）读写操作。

Bitable 字段映射（与 Excel 列对应）：
  - po_number        采购订单编号
  - contract_date    合同日期（格式 YYYY-MM-DD）
  - supplier_name    供应商名称
  - supplier_address 供应商地址
  - supplier_contact 供应商联系人
  - supplier_tel     供应商电话
  - buyer_name       采购方名称
  - buyer_dept       采购部门
  - buyer_contact    采购联系人
  - currency         货币（CNY / USD 等）
  - payment_terms    付款条款
  - delivery_date    交货日期
  - delivery_address 收货地址
  - items            行项目列表（JSON 字符串，含 description/qty/unit/unit_price）
  - notes            备注
"""
import json
import logging
from typing import Any, Dict, List, Optional

from config import FeishuConfig
from .client import FeishuClient

logger = logging.getLogger(__name__)

# Bitable field_id → 本地字段名映射（可根据实际表格结构调整）
DEFAULT_FIELD_MAP: Dict[str, str] = {
    "po_number": "po_number",
    "contract_date": "contract_date",
    "supplier_name": "supplier_name",
    "supplier_address": "supplier_address",
    "supplier_contact": "supplier_contact",
    "supplier_tel": "supplier_tel",
    "buyer_name": "buyer_name",
    "buyer_dept": "buyer_dept",
    "buyer_contact": "buyer_contact",
    "currency": "currency",
    "payment_terms": "payment_terms",
    "delivery_date": "delivery_date",
    "delivery_address": "delivery_address",
    "items": "items",
    "notes": "notes",
}


def _extract_cell_value(cell: Any) -> Any:
    """从 Bitable 单元格对象中提取可读值。"""
    if cell is None:
        return ""
    if isinstance(cell, (str, int, float, bool)):
        return cell
    if isinstance(cell, list):
        # 多选 / 人员 / 文本富文本等列表类型取文本
        parts = []
        for item in cell:
            if isinstance(item, dict):
                parts.append(item.get("text") or item.get("name") or item.get("value") or "")
            else:
                parts.append(str(item))
        return ", ".join(parts)
    if isinstance(cell, dict):
        return cell.get("text") or cell.get("value") or str(cell)
    return str(cell)


class BitableClient:
    """飞书 Bitable 数据读取客户端"""

    def __init__(
        self,
        app_token: Optional[str] = None,
        table_id: Optional[str] = None,
        feishu_client: Optional[FeishuClient] = None,
    ):
        self.app_token = app_token or FeishuConfig.BITABLE_APP_TOKEN
        self.table_id = table_id or FeishuConfig.BITABLE_TABLE_ID
        self._client = feishu_client or FeishuClient()

    # ------------------------------------------------------------------
    # 读取记录
    # ------------------------------------------------------------------

    def list_records(
        self,
        filter_expr: Optional[str] = None,
        page_size: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        读取 Bitable 表格中的所有记录，返回规范化后的字典列表。

        Args:
            filter_expr: 可选过滤表达式，例如 'CurrentValue.[status]="待生成"'
            page_size:   每页记录数（最大 100）

        Returns:
            记录列表，每条记录为 {字段名: 值, ...} 格式
        """
        path = (
            f"/bitable/v1/apps/{self.app_token}"
            f"/tables/{self.table_id}/records"
        )
        params: Dict[str, Any] = {"page_size": min(page_size, 100)}
        if filter_expr:
            params["filter"] = filter_expr

        results: List[Dict[str, Any]] = []
        page_token: Optional[str] = None

        while True:
            if page_token:
                params["page_token"] = page_token
            data = self._client.get(path, params=params)
            if data.get("code") != 0:
                raise RuntimeError(f"读取 Bitable 记录失败: {data.get('msg')}")

            items = data.get("data", {}).get("items", [])
            for item in items:
                record = self._normalize_record(item)
                results.append(record)

            has_more = data.get("data", {}).get("has_more", False)
            page_token = data.get("data", {}).get("page_token")
            if not has_more or not page_token:
                break

        logger.info("共读取 %d 条 Bitable 记录", len(results))
        return results

    def get_record(self, record_id: str) -> Dict[str, Any]:
        """读取单条记录"""
        path = (
            f"/bitable/v1/apps/{self.app_token}"
            f"/tables/{self.table_id}/records/{record_id}"
        )
        data = self._client.get(path)
        if data.get("code") != 0:
            raise RuntimeError(f"读取记录 {record_id} 失败: {data.get('msg')}")
        return self._normalize_record(data.get("data", {}).get("record", {}))

    def update_record(self, record_id: str, fields: Dict[str, Any]) -> None:
        """更新记录字段（例如将状态改为"已生成"）"""
        path = (
            f"/bitable/v1/apps/{self.app_token}"
            f"/tables/{self.table_id}/records/{record_id}"
        )
        self._client.post(path, {"fields": fields})

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _normalize_record(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """将 Bitable 原始记录转换为统一字段名格式"""
        fields = raw.get("fields", {})
        record: Dict[str, Any] = {"_record_id": raw.get("record_id", "")}

        for field_key, local_key in DEFAULT_FIELD_MAP.items():
            raw_val = fields.get(field_key)
            value = _extract_cell_value(raw_val)
            # items 字段存储 JSON 字符串
            if local_key == "items" and isinstance(value, str) and value.strip():
                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    logger.warning("items 字段 JSON 解析失败，原始值: %s", value)
                    value = []
            record[local_key] = value

        return record
