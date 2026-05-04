"""
飞书 API 基础客户端：管理 tenant_access_token 并提供通用 HTTP 请求封装。
"""
import logging
import time
from typing import Any, Dict, Optional

import requests

from config import FeishuConfig

logger = logging.getLogger(__name__)

_TOKEN_CACHE: Dict[str, Any] = {"token": None, "expires_at": 0}


class FeishuClient:
    """飞书开放平台 API 客户端"""

    def __init__(self, app_id: Optional[str] = None, app_secret: Optional[str] = None):
        self.app_id = app_id or FeishuConfig.APP_ID
        self.app_secret = app_secret or FeishuConfig.APP_SECRET
        self.base_url = FeishuConfig.API_BASE_URL
        self._session = requests.Session()

    # ------------------------------------------------------------------
    # Token 管理
    # ------------------------------------------------------------------

    def get_access_token(self) -> str:
        """获取 tenant_access_token，自动处理缓存与刷新。"""
        global _TOKEN_CACHE
        now = time.time()
        if _TOKEN_CACHE["token"] and now < _TOKEN_CACHE["expires_at"] - 60:
            return _TOKEN_CACHE["token"]

        url = f"{self.base_url}/auth/v3/tenant_access_token/internal"
        payload = {"app_id": self.app_id, "app_secret": self.app_secret}
        resp = self._session.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"获取飞书 token 失败: {data.get('msg')}")

        token = data["tenant_access_token"]
        expires_in = int(data.get("expire", 7200))
        _TOKEN_CACHE = {"token": token, "expires_at": now + expires_in}
        logger.debug("飞书 token 已刷新，有效期 %s 秒", expires_in)
        return token

    def _auth_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.get_access_token()}",
            "Content-Type": "application/json; charset=utf-8",
        }

    # ------------------------------------------------------------------
    # 通用请求
    # ------------------------------------------------------------------

    def get(self, path: str, params: Optional[Dict] = None) -> Dict:
        url = f"{self.base_url}{path}"
        resp = self._session.get(url, headers=self._auth_headers(), params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def post(self, path: str, payload: Optional[Dict] = None) -> Dict:
        url = f"{self.base_url}{path}"
        resp = self._session.post(url, headers=self._auth_headers(), json=payload, timeout=15)
        resp.raise_for_status()
        return resp.json()
