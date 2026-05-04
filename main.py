"""
飞书 PO 合同自动生成服务（主入口）

功能：
1. 提供 HTTP Webhook 端点，接收飞书事件订阅通知。
2. 解析 Bitable 记录新增/更新事件，读取完整 PO 数据。
3. 调用 ExcelGenerator 生成标准格式 PO 合同 Excel 文件。
4. 将文件保存至 NAS 指定目录，并将 Bitable 中的状态字段更新为"已生成"。

启动方式::

    python main.py

    或使用 gunicorn（生产环境）::

    gunicorn -w 2 -b 0.0.0.0:5000 "main:create_app()"
"""
import hashlib
import hmac
import json
import logging
import os
import sys

from flask import Flask, jsonify, request

from config import FeishuConfig, FlaskConfig
from excel.generator import ExcelGenerator
from feishu.bitable import BitableClient
from feishu.client import FeishuClient
from nas.handler import NASHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def create_app() -> Flask:
    """工厂函数：创建并配置 Flask 应用"""
    app = Flask(__name__)

    feishu_client = FeishuClient()
    bitable_client = BitableClient(feishu_client=feishu_client)
    excel_gen = ExcelGenerator()
    nas_handler = NASHandler()

    # ------------------------------------------------------------------
    # 健康检查端点
    # ------------------------------------------------------------------

    @app.get("/health")
    def health():
        disk = nas_handler.get_disk_usage_info()
        return jsonify({"status": "ok", "nas_disk": disk})

    # ------------------------------------------------------------------
    # 飞书事件订阅 Webhook
    # ------------------------------------------------------------------

    @app.post("/webhook/feishu")
    def feishu_webhook():
        """
        飞书事件订阅回调端点。

        支持两类事件：
        - url_verification：飞书验证回调地址
        - bitable_record.created / bitable_record.updated：记录新增/更新
        """
        payload = request.get_json(force=True, silent=True) or {}

        # 1. 验证签名（若配置了 encrypt_key）
        if FeishuConfig.ENCRYPT_KEY:
            signature = request.headers.get("X-Lark-Signature", "")
            if not _verify_signature(request.get_data(), signature):
                logger.warning("飞书 Webhook 签名验证失败")
                return jsonify({"code": 401, "msg": "签名验证失败"}), 401

        # 2. URL 验证握手（飞书开放平台首次配置时调用）
        if payload.get("type") == "url_verification":
            challenge = payload.get("challenge", "")
            logger.info("飞书 URL 验证成功，challenge=%s", challenge)
            return jsonify({"challenge": challenge})

        # 3. 处理事件
        event_type = payload.get("header", {}).get("event_type", "")
        event = payload.get("event", {})

        logger.info("收到飞书事件: %s", event_type)

        if event_type in ("bitable.record.created.v1", "bitable.record.updated.v1"):
            _handle_bitable_event(event, bitable_client, excel_gen, nas_handler)
        else:
            logger.debug("忽略事件类型: %s", event_type)

        return jsonify({"code": 0, "msg": "ok"})

    # ------------------------------------------------------------------
    # 手动触发端点（调试 / 补偿）
    # ------------------------------------------------------------------

    @app.post("/api/generate")
    def generate_by_record_id():
        """
        根据 Bitable record_id 手动触发 PO 合同生成。

        请求体::

            {"record_id": "recXXXXXXX"}
        """
        body = request.get_json(force=True, silent=True) or {}
        record_id = body.get("record_id", "").strip()
        if not record_id:
            return jsonify({"code": 400, "msg": "缺少 record_id 参数"}), 400

        try:
            po_data = bitable_client.get_record(record_id)
            filepath = excel_gen.generate(po_data)
            _update_status(bitable_client, po_data, "已生成", filepath)
            return jsonify({"code": 0, "msg": "生成成功", "file": filepath})
        except Exception as exc:
            logger.exception("手动生成失败: %s", exc)
            return jsonify({"code": 500, "msg": str(exc)}), 500

    @app.get("/api/files")
    def list_files():
        """列出 NAS 目录中已生成的合同文件"""
        files = nas_handler.list_files()
        return jsonify({"code": 0, "count": len(files), "files": files})

    return app


# ---------------------------------------------------------------------------
# 内部辅助函数
# ---------------------------------------------------------------------------

def _handle_bitable_event(
    event: dict,
    bitable_client: BitableClient,
    excel_gen: ExcelGenerator,
    nas_handler: NASHandler,
) -> None:
    """处理 Bitable 记录新增/更新事件，生成并保存 PO 合同 Excel"""
    record_id = event.get("record_id") or event.get("record", {}).get("record_id", "")
    if not record_id:
        logger.warning("事件中未找到 record_id，跳过")
        return

    try:
        po_data = bitable_client.get_record(record_id)
        filepath = excel_gen.generate(po_data)
        nas_handler.check_disk_space()
        _update_status(bitable_client, po_data, "已生成", filepath)
        logger.info("PO 合同生成完毕: record_id=%s, file=%s", record_id, filepath)
    except Exception as exc:
        logger.exception("处理记录 %s 时出错: %s", record_id, exc)
        try:
            bitable_client.update_record(record_id, {"status": "生成失败", "error_msg": str(exc)})
        except Exception:
            pass


def _update_status(
    bitable_client: BitableClient,
    po_data: dict,
    status: str,
    filepath: str,
) -> None:
    """将 Bitable 中的记录状态字段更新为指定值"""
    record_id = po_data.get("_record_id", "")
    if record_id:
        try:
            bitable_client.update_record(
                record_id,
                {"status": status, "generated_file": os.path.basename(filepath)},
            )
        except Exception as exc:
            logger.warning("更新记录状态失败（不影响文件生成）: %s", exc)


def _verify_signature(body: bytes, signature: str) -> bool:
    """校验飞书 Webhook 签名"""
    encrypt_key = FeishuConfig.ENCRYPT_KEY
    if not encrypt_key:
        return True
    expected = hmac.new(
        encrypt_key.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


# ---------------------------------------------------------------------------
# 程序入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app = create_app()
    app.run(
        host=FlaskConfig.HOST,
        port=FlaskConfig.PORT,
        debug=FlaskConfig.DEBUG,
    )
