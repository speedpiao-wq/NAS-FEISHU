"""
单元测试：Flask Webhook（main.py）

测试：
- /health 健康检查端点
- /webhook/feishu URL 验证握手
- /api/generate 手动生成（mock bitable + excel gen）
- /api/files 文件列举
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import create_app


@pytest.fixture
def client(tmp_path: Path):
    # Override NAS and Excel output dirs via environment variables
    import os
    os.environ["NAS_OUTPUT_DIR"] = str(tmp_path / "nas")
    # Reload config so updated env vars are picked up
    import importlib
    import config as _cfg
    importlib.reload(_cfg)

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert "nas_disk" in data


class TestWebhookFeishu:
    def test_url_verification_challenge(self, client):
        payload = {"type": "url_verification", "challenge": "test_challenge_abc"}
        resp = client.post(
            "/webhook/feishu",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["challenge"] == "test_challenge_abc"

    def test_unknown_event_returns_ok(self, client):
        payload = {
            "header": {"event_type": "unknown.event.v1"},
            "event": {},
        }
        resp = client.post(
            "/webhook/feishu",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.get_json()["code"] == 0

    def test_bitable_record_created_event(self, client, tmp_path: Path):
        po_data = {
            "_record_id": "rec123",
            "po_number": "PO-TEST-001",
            "contract_date": "2024-01-01",
            "supplier_name": "测试供应商",
            "buyer_name": "测试采购方",
            "currency": "CNY",
            "items": [{"description": "产品X", "qty": 2, "unit_price": 50.0}],
        }

        with patch("main.BitableClient") as MockBitable, \
             patch("main.ExcelGenerator") as MockExcel:

            mock_bitable = MagicMock()
            mock_bitable.get_record.return_value = po_data
            MockBitable.return_value = mock_bitable

            mock_gen = MagicMock()
            mock_gen.generate.return_value = str(tmp_path / "PO_TEST.xlsx")
            MockExcel.return_value = mock_gen

            app = create_app()
            app.config["TESTING"] = True
            with app.test_client() as c:
                payload = {
                    "header": {"event_type": "bitable.record.created.v1"},
                    "event": {"record_id": "rec123"},
                }
                resp = c.post(
                    "/webhook/feishu",
                    data=json.dumps(payload),
                    content_type="application/json",
                )
                assert resp.status_code == 200
                assert resp.get_json()["code"] == 0


class TestGenerateEndpoint:
    def test_missing_record_id_returns_400(self, client):
        resp = client.post(
            "/api/generate",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_generate_with_record_id(self, client, tmp_path: Path):
        po_data = {
            "_record_id": "rec456",
            "po_number": "PO-MANUAL-001",
            "items": [],
        }
        fake_path = str(tmp_path / "contracts" / "PO_MANUAL.xlsx")

        with patch("main.BitableClient") as MockBitable, \
             patch("main.ExcelGenerator") as MockExcel:

            mock_bitable = MagicMock()
            mock_bitable.get_record.return_value = po_data
            MockBitable.return_value = mock_bitable

            mock_gen = MagicMock()
            mock_gen.generate.return_value = fake_path
            MockExcel.return_value = mock_gen

            app = create_app()
            app.config["TESTING"] = True
            with app.test_client() as c:
                resp = c.post(
                    "/api/generate",
                    data=json.dumps({"record_id": "rec456"}),
                    content_type="application/json",
                )
                assert resp.status_code == 200
                data = resp.get_json()
                assert data["code"] == 0
                assert "file" in data


class TestListFilesEndpoint:
    def test_list_files_returns_list(self, client):
        resp = client.get("/api/files")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["code"] == 0
        assert isinstance(data["files"], list)
