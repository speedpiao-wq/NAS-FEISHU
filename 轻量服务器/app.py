from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from typing import Optional
import sqlite3
from datetime import datetime, timedelta, timezone
import os
import json
import requests
from pathlib import Path
from urllib.parse import quote
app = FastAPI()



API_KEY = os.environ.get("HUB_API_KEY", "change-me")
DB_PATH = os.environ.get("HUB_DB_PATH", "/opt/contract-hub/tasks.db")

FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "")
FEISHU_APP_TOKEN = os.environ.get("FEISHU_APP_TOKEN", "")
FEISHU_TABLE_ID = os.environ.get("FEISHU_TABLE_ID", "")
FEISHU_AUTH_MODE = os.environ.get("FEISHU_AUTH_MODE", "tenant").strip().lower()
FEISHU_USER_ACCESS_TOKEN = os.environ.get("FEISHU_USER_ACCESS_TOKEN", "").strip()
FEISHU_USER_REFRESH_TOKEN = os.environ.get("FEISHU_USER_REFRESH_TOKEN", "").strip()
FEISHU_USER_ACCESS_TOKEN_EXPIRES_AT = os.environ.get("FEISHU_USER_ACCESS_TOKEN_EXPIRES_AT", "").strip()
FEISHU_USER_REFRESH_TOKEN_EXPIRES_AT = os.environ.get("FEISHU_USER_REFRESH_TOKEN_EXPIRES_AT", "").strip()
FEISHU_USER_TOKEN_STORE = os.environ.get("FEISHU_USER_TOKEN_STORE", "/opt/contract-hub/feishu_user_token.json").strip()

_feishu_user_token_cache = {
    "loaded": False,
    "access_token": "",
    "access_expires_at": None,
    "refresh_token": "",
    "refresh_expires_at": None,
}

_feishu_table_field_map_cache = {}
BEIJING_TZ = timezone(timedelta(hours=8))

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT UNIQUE,
        status TEXT,
        payload TEXT,
        file_name TEXT,
        file_path TEXT,
        error_message TEXT,
        warnings TEXT,
        created_at TEXT,
        updated_at TEXT
    )
    """)
    conn.commit()
    conn.close()

init_db()

class CreateTaskPayload(BaseModel):
    task_id: str
    payload: dict

class ResultPayload(BaseModel):
    task_id: str
    status: str
    file_name: Optional[str] = ""
    file_path: Optional[str] = ""
    error_message: Optional[str] = ""
    generated_at: Optional[str] = ""
    warnings: Optional[list] = []


def get_beijing_now():
    return datetime.now(BEIJING_TZ)


def get_beijing_isoformat():
    return get_beijing_now().isoformat()


def parse_datetime_text(value: str):
    text = str(value or "").strip()
    if not text:
        return None

    try:
        normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=BEIJING_TZ)
        return dt
    except Exception:
        return None


def to_bitable_datetime_value(value: str):
    dt = parse_datetime_text(value)
    if dt is None:
        dt = get_beijing_now()
    return int(dt.timestamp() * 1000)

def get_tenant_access_token():
    if not FEISHU_APP_ID or not FEISHU_APP_SECRET:
        raise HTTPException(status_code=500, detail="Feishu app credentials not configured")

    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    resp = requests.post(
        url,
        json={
            "app_id": FEISHU_APP_ID,
            "app_secret": FEISHU_APP_SECRET
        },
        timeout=30
    )
    data = resp.json()
    if data.get("code") != 0:
        raise HTTPException(status_code=500, detail=f"Feishu token error: {data}")
    return data["tenant_access_token"]


def _parse_datetime_value(value: str):
    text = str(value or "").strip()
    if not text:
        return None

    try:
        if text.endswith("Z"):
            text = text[:-1]
        return datetime.fromisoformat(text)
    except Exception:
        return None


def _load_user_token_cache_once():
    if _feishu_user_token_cache["loaded"]:
        return

    _feishu_user_token_cache["loaded"] = True
    _feishu_user_token_cache["access_token"] = FEISHU_USER_ACCESS_TOKEN
    _feishu_user_token_cache["refresh_token"] = FEISHU_USER_REFRESH_TOKEN
    _feishu_user_token_cache["access_expires_at"] = _parse_datetime_value(FEISHU_USER_ACCESS_TOKEN_EXPIRES_AT)
    _feishu_user_token_cache["refresh_expires_at"] = _parse_datetime_value(FEISHU_USER_REFRESH_TOKEN_EXPIRES_AT)

    token_store_path = Path(FEISHU_USER_TOKEN_STORE)
    if not token_store_path.exists():
        return

    try:
        data = json.loads(token_store_path.read_text(encoding="utf-8"))
    except Exception as e:
        print("Feishu user token store load failed:", repr(e))
        return

    _feishu_user_token_cache["access_token"] = str(data.get("access_token") or _feishu_user_token_cache["access_token"] or "").strip()
    _feishu_user_token_cache["refresh_token"] = str(data.get("refresh_token") or _feishu_user_token_cache["refresh_token"] or "").strip()

    access_expires_at = _parse_datetime_value(data.get("access_expires_at", ""))
    refresh_expires_at = _parse_datetime_value(data.get("refresh_expires_at", ""))
    if access_expires_at is not None:
        _feishu_user_token_cache["access_expires_at"] = access_expires_at
    if refresh_expires_at is not None:
        _feishu_user_token_cache["refresh_expires_at"] = refresh_expires_at


def _save_user_token_cache(access_token: str, expires_in: int, refresh_token: str = "", refresh_expires_in: int | None = None):
    now = datetime.utcnow()
    access_expires_at = now + timedelta(seconds=max(int(expires_in) - 120, 0))

    _feishu_user_token_cache["access_token"] = access_token.strip()
    _feishu_user_token_cache["access_expires_at"] = access_expires_at

    if refresh_token:
        _feishu_user_token_cache["refresh_token"] = refresh_token.strip()

    if refresh_expires_in is not None:
        _feishu_user_token_cache["refresh_expires_at"] = now + timedelta(seconds=max(int(refresh_expires_in) - 3600, 0))

    payload = {
        "access_token": _feishu_user_token_cache["access_token"],
        "access_expires_at": _feishu_user_token_cache["access_expires_at"].isoformat() if _feishu_user_token_cache["access_expires_at"] else "",
        "refresh_token": _feishu_user_token_cache["refresh_token"],
        "refresh_expires_at": _feishu_user_token_cache["refresh_expires_at"].isoformat() if _feishu_user_token_cache["refresh_expires_at"] else "",
        "updated_at": now.isoformat(),
    }

    try:
        token_store_path = Path(FEISHU_USER_TOKEN_STORE)
        token_store_path.parent.mkdir(parents=True, exist_ok=True)
        token_store_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print("Feishu user token store save failed:", repr(e))


def refresh_user_access_token(refresh_token: str):
    if not FEISHU_APP_ID or not FEISHU_APP_SECRET:
        raise HTTPException(status_code=500, detail="Feishu app credentials not configured")

    if not refresh_token:
        raise HTTPException(status_code=500, detail="Feishu user refresh token not configured")

    url = "https://open.feishu.cn/open-apis/authen/v2/oauth/token"
    resp = requests.post(
        url,
        headers={"Content-Type": "application/json; charset=utf-8"},
        json={
            "grant_type": "refresh_token",
            "client_id": FEISHU_APP_ID,
            "client_secret": FEISHU_APP_SECRET,
            "refresh_token": refresh_token,
        },
        timeout=30,
    )
    data = resp.json()

    if data.get("code") != 0:
        raise HTTPException(status_code=500, detail=f"Feishu user token refresh error: {data}")

    access_token = str(data.get("access_token") or "").strip()
    new_refresh_token = str(data.get("refresh_token") or refresh_token).strip()
    expires_in = int(data.get("expires_in") or 7200)
    refresh_expires_in = data.get("refresh_token_expires_in")

    _save_user_token_cache(access_token, expires_in, new_refresh_token, refresh_expires_in)
    return access_token


def get_user_access_token():
    _load_user_token_cache_once()

    now = datetime.utcnow()
    access_token = str(_feishu_user_token_cache.get("access_token") or "").strip()
    access_expires_at = _feishu_user_token_cache.get("access_expires_at")
    refresh_token = str(_feishu_user_token_cache.get("refresh_token") or "").strip()
    refresh_expires_at = _feishu_user_token_cache.get("refresh_expires_at")

    if access_token and access_expires_at and access_expires_at > now:
        return access_token

    if refresh_token and (refresh_expires_at is None or refresh_expires_at > now):
        return refresh_user_access_token(refresh_token)

    if access_token:
        print("Feishu user access token is missing expiry metadata; using configured raw token.")
        return access_token

    raise HTTPException(
        status_code=500,
        detail=(
            "Feishu user access token unavailable. Configure FEISHU_USER_REFRESH_TOKEN "
            "or FEISHU_USER_ACCESS_TOKEN, or set FEISHU_AUTH_MODE=tenant to use app identity."
        ),
    )


def get_feishu_access_token():
    mode = FEISHU_AUTH_MODE or "tenant"

    if mode == "user":
        return get_user_access_token()

    if mode == "auto":
        if FEISHU_USER_ACCESS_TOKEN or FEISHU_USER_REFRESH_TOKEN or Path(FEISHU_USER_TOKEN_STORE).exists():
            return get_user_access_token()
        return get_tenant_access_token()

    return get_tenant_access_token()


def get_bitable_field_name_id_map(table_id: str):
    table_id = str(table_id or "").strip()
    if not table_id:
        return {}

    cached = _feishu_table_field_map_cache.get(table_id)
    if cached:
        return cached

    token = get_feishu_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{FEISHU_APP_TOKEN}/tables/{table_id}/fields"

    page_token = None
    result = {}

    while True:
        params = {"page_size": 500}
        if page_token:
            params["page_token"] = page_token

        resp = requests.get(url, headers=headers, params=params, timeout=30)
        data = resp.json()

        if data.get("code") != 0:
            print("Feishu field metadata fetch failed:", data)
            break

        items = data.get("data", {}).get("items", [])
        for item in items:
            field_name = str(item.get("field_name") or "").strip()
            field_id = str(item.get("field_id") or "").strip()
            if field_name and field_id:
                result[field_name] = field_id

        if not data.get("data", {}).get("has_more"):
            break

        page_token = data.get("data", {}).get("page_token")

    _feishu_table_field_map_cache[table_id] = result
    return result


def build_bitable_attachment_download_urls(table_id: str, field_id: str, record_id: str, file_token: str):
    table_id = str(table_id or "").strip()
    field_id = str(field_id or "").strip()
    record_id = str(record_id or "").strip()
    file_token = str(file_token or "").strip()

    if not table_id or not field_id or not record_id or not file_token:
        return "", "", ""

    extra_obj = {
        "bitablePerm": {
            "tableId": table_id,
            "attachments": {
                field_id: {
                    record_id: [file_token]
                }
            }
        }
    }
    extra_str = json.dumps(extra_obj, ensure_ascii=False, separators=(",", ":"))
    extra_encoded = quote(extra_str, safe="")

    download_url = f"https://open.feishu.cn/open-apis/drive/v1/medias/{file_token}/download?extra={extra_encoded}"
    tmp_url = f"https://open.feishu.cn/open-apis/drive/v1/medias/batch_get_tmp_download_url?file_tokens={file_token}&extra={extra_encoded}"
    return download_url, tmp_url, extra_str

def normalize_value(value):
    if value is None:
        return ""

    if isinstance(value, str):
        return value.strip()

    if isinstance(value, (int, float)):
        return str(value).strip()

    if isinstance(value, dict):
        if "link_record_ids" in value and value["link_record_ids"]:
            return " | ".join(str(x).strip() for x in value["link_record_ids"] if x)

        if "value" in value:
            return normalize_value(value["value"])

        for key in ["text", "name", "id", "record_id"]:
            if key in value and value[key] is not None:
                return normalize_value(value[key])

        parts = []
        for v in value.values():
            s = normalize_value(v)
            if s:
                parts.append(s)
        return " ".join(parts).strip()

    if isinstance(value, list):
        parts = []
        for item in value:
            s = normalize_value(item)
            if s:
                parts.append(s)
        return " | ".join(parts).strip()

    return str(value).strip()

def extract_link_record_ids(value):
    result = []

    if value is None:
        return result

    if isinstance(value, dict):
        ids = value.get("link_record_ids")
        if isinstance(ids, list):
            for x in ids:
                if x:
                    result.append(str(x).strip())
            return result

        if "value" in value:
            return extract_link_record_ids(value["value"])

        return result

    if isinstance(value, list):
        for item in value:
            result.extend(extract_link_record_ids(item))
        return result

    return result

def find_po_record_ids(po_no: str):
    """
    去 PO登记表 里查指定 PO 文本对应的所有 record_id
    适配：同一个 PO号 在 PO登记表 中有多条颜色记录
    """
    po_no = (po_no or "").strip()
    if not po_no:
        return []

    if not FEISHU_APP_TOKEN:
        raise HTTPException(status_code=500, detail="Feishu app token not set")

    token = get_feishu_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # PO登记表 table_id
    po_table_id = "tbllR17Z5yRQ8qTS"
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{FEISHU_APP_TOKEN}/tables/{po_table_id}/records/search"

    matched_record_ids = []
    page_token = None

    while True:
        payload = {
            "page_size": 500
        }
        if page_token:
            payload["page_token"] = page_token

        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        data = resp.json()

        if data.get("code") != 0:
            raise HTTPException(status_code=500, detail=f"Feishu PO table search error: {data}")

        items = data.get("data", {}).get("items", [])
        for item in items:
            fields = item.get("fields", {})

            # 只匹配 PO号 / ✍PO# 这种真正的 PO 文本字段
            po_text = ""
            if "PO号" in fields:
                po_text = normalize_value(fields.get("PO号"))
            elif "✍PO#" in fields:
                po_text = normalize_value(fields.get("✍PO#"))
            elif "PO#" in fields:
                po_text = normalize_value(fields.get("PO#"))

            po_text = str(po_text).strip().rstrip(",，")

            if po_text == po_no:
                rid = item.get("record_id")
                if rid:
                    matched_record_ids.append(rid)

        has_more = data.get("data", {}).get("has_more", False)
        if not has_more:
            break

        page_token = data.get("data", {}).get("page_token")

    return matched_record_ids

def search_records_by_po(po_no: str):
    """
    在 一键合同 表中，按 PO# 关联字段查找所有属于同一个 PO 的记录
    适配：一个 PO号 在 PO登记表 中对应多条颜色唯一记录
    """
    if not FEISHU_APP_TOKEN or not FEISHU_TABLE_ID:
        raise HTTPException(status_code=500, detail="Feishu base config not set")

    po_no = str(po_no or "").strip().rstrip(",，")
    if not po_no:
        return []

    # 第1步：先去 PO登记表 找到这个 PO 对应的所有 record_id
    target_po_record_ids = find_po_record_ids(po_no)

    if not target_po_record_ids:
        return []

    target_po_record_ids_set = set(target_po_record_ids)

    # 第2步：在 一键合同 表中找所有 PO# 关联到这些 record_id 的记录
    token = get_feishu_access_token()
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{FEISHU_APP_TOKEN}/tables/{FEISHU_TABLE_ID}/records/search"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    matched_items = []
    page_token = None

    while True:
        payload = {
            "page_size": 500
        }
        if page_token:
            payload["page_token"] = page_token

        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        data = resp.json()

        if data.get("code") != 0:
            raise HTTPException(status_code=500, detail=f"Feishu search error: {data}")

        items = data.get("data", {}).get("items", [])
        for item in items:
            fields = item.get("fields", {})
            po_link_ids = extract_link_record_ids(fields.get("PO#"))

            if any(rid in target_po_record_ids_set for rid in po_link_ids):
                matched_items.append(item)

        has_more = data.get("data", {}).get("has_more", False)
        if not has_more:
            break

        page_token = data.get("data", {}).get("page_token")

    return matched_items

def build_contract_payload_from_records(po_no: str):
    items = search_records_by_po(po_no)

    if not items:
        raise HTTPException(status_code=404, detail=f"No Feishu records found for PO#: {po_no}")

    first_fields = items[0].get("fields", {})
    field_id_map = get_bitable_field_name_id_map(FEISHU_TABLE_ID)

    def f(name, default=""):
        return normalize_value(first_fields.get(name, default))

    def extract_images_from_field(item, field_name):
        fields = item.get("fields", {})
        record_id = str(item.get("record_id") or "").strip()
        field_id = str(field_id_map.get(field_name) or "").strip()
        raw = fields.get(field_name, {})
        images = []

        def append_image(item):
            if not isinstance(item, dict):
                return
            file_token = str(item.get("file_token") or "").strip()
            generated_url, generated_tmp_url, generated_extra = build_bitable_attachment_download_urls(
                FEISHU_TABLE_ID,
                field_id,
                record_id,
                file_token,
            )
            images.append({
                "file_token": file_token,
                "name": item.get("name", ""),
                "url": generated_url or item.get("url", ""),
                "tmp_url": generated_tmp_url or item.get("tmp_url", ""),
                "type": item.get("type", ""),
                "record_id": record_id,
                "field_name": field_name,
                "field_id": field_id,
                "extra": generated_extra,
                "raw_url": item.get("url", ""),
                "raw_tmp_url": item.get("tmp_url", ""),
            })

        if isinstance(raw, dict):
            values = raw.get("value", [])
            if isinstance(values, list):
                for item in values:
                    append_image(item)
            else:
                append_image(raw)

        elif isinstance(raw, list):
            for item in raw:
                append_image(item)

        return images

    def image_to_base64(image_info):
        import base64

        if not image_info:
            return {}

        direct_url = str(image_info.get("url") or "").strip()
        tmp_api_url = str(image_info.get("tmp_url") or "").strip()

        if not direct_url and not tmp_api_url:
            print("Feishu image download skipped: missing download URL.")
            return {}

        token_candidates = []
        preferred_mode = FEISHU_AUTH_MODE or "tenant"

        def add_token_candidate(mode_name, token_getter):
            try:
                token_value = str(token_getter() or "").strip()
                if token_value and token_value not in [item[1] for item in token_candidates]:
                    token_candidates.append((mode_name, token_value))
            except Exception as exc:
                print(f"Feishu image download token acquisition failed ({mode_name}):", repr(exc))

        if preferred_mode == "user":
            add_token_candidate("user", get_user_access_token)
            add_token_candidate("tenant", get_tenant_access_token)
        elif preferred_mode == "auto":
            add_token_candidate("user", get_user_access_token)
            add_token_candidate("tenant", get_tenant_access_token)
        else:
            add_token_candidate("tenant", get_tenant_access_token)
            add_token_candidate("user", get_user_access_token)

        for token_mode, token in token_candidates:
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8",
            }

            try:
                download_url = direct_url

                if tmp_api_url:
                    tmp_resp = requests.get(tmp_api_url, headers=headers, timeout=60)
                    if not tmp_resp.ok:
                        print(
                            f"Feishu tmp download URL request failed ({token_mode}): "
                            f"status={tmp_resp.status_code}, body={tmp_resp.text[:500]}"
                        )
                    tmp_resp.raise_for_status()

                    content_type = str(tmp_resp.headers.get("Content-Type") or "").lower()

                    if "application/json" in content_type:
                        tmp_data = tmp_resp.json()
                        if tmp_data.get("code") != 0:
                            print(
                                f"Feishu tmp download URL API returned error ({token_mode}): "
                                f"code={tmp_data.get('code')}, msg={tmp_data.get('msg')}"
                            )
                        tmp_urls = tmp_data.get("data", {}).get("tmp_download_urls", [])
                        if tmp_urls:
                            first_tmp_url = tmp_urls[0] or {}
                            download_url = (
                                first_tmp_url.get("tmp_download_url")
                                or first_tmp_url.get("download_url")
                                or download_url
                            )

                if not download_url:
                    print("Feishu image download skipped: failed to resolve a download URL.")
                    continue

                download_headers = headers
                if "internal-api-drive-stream.feishu.cn" in download_url:
                    download_headers = {}

                resp = requests.get(download_url, headers=download_headers, timeout=60, allow_redirects=True)
                if not resp.ok:
                    print(
                        f"Feishu image download failed ({token_mode}): "
                        f"status={resp.status_code}, file_token={image_info.get('file_token', '')}, "
                        f"field={image_info.get('field_name', '')}, record_id={image_info.get('record_id', '')}, "
                        f"body={resp.text[:500]}"
                    )
                resp.raise_for_status()

                content_type = image_info.get("type") or resp.headers.get("Content-Type", "image/png")
                file_name = image_info.get("name", "image.png")
                b64_text = base64.b64encode(resp.content).decode("utf-8")

                return {
                    "name": file_name,
                    "type": content_type,
                    "base64": b64_text
                }
            except Exception as e:
                print(
                    f"Feishu image conversion failed ({token_mode}): "
                    f"file_token={image_info.get('file_token', '')}, error={str(e)}"
                )

        return {}

    def images_to_base64_list(image_list):
        result = []
        for image_info in image_list:
            converted = image_to_base64(image_info)
            if converted and converted.get("base64"):
                result.append(converted)
        return result

    def merge_unique_images(existing_images, new_images):
        merged = list(existing_images)
        seen = set()

        for image_info in merged:
            image_key = (
                str(image_info.get("file_token", "")).strip(),
                str(image_info.get("url", "")).strip(),
                str(image_info.get("tmp_url", "")).strip(),
                str(image_info.get("name", "")).strip(),
            )
            seen.add(image_key)

        for image_info in new_images:
            image_key = (
                str(image_info.get("file_token", "")).strip(),
                str(image_info.get("url", "")).strip(),
                str(image_info.get("tmp_url", "")).strip(),
                str(image_info.get("name", "")).strip(),
            )
            if image_key in seen:
                continue
            seen.add(image_key)
            merged.append(image_info)

        return merged

    def split_multi_value_text(value):
        text = normalize_value(value)
        if not text:
            return []

        normalized = text.replace("，", ",").replace("/", ",").replace("|", ",").replace("、", ",")
        return [part.strip() for part in normalized.split(",") if part and part.strip()]

    def aggregate_top_sizes(records):
        ordered_sizes = []
        seen = set()

        for item in records:
            fields = item.get("fields", {})
            for size_text in split_multi_value_text(fields.get("TOP码数", "")):
                size_key = size_text.upper()
                if size_key in seen:
                    continue
                seen.add(size_key)
                ordered_sizes.append(size_text)

        return ",".join(ordered_sizes)

    def aggregate_top_qty(records):
        total_qty = 0.0
        has_numeric = False
        raw_texts = []
        seen_texts = set()

        for item in records:
            fields = item.get("fields", {})
            raw_value = fields.get("TOP数量", "")
            text = normalize_value(raw_value)
            if not text:
                continue

            try:
                numeric_value = float(text)
                total_qty += numeric_value
                has_numeric = True
            except Exception:
                if text not in seen_texts:
                    seen_texts.add(text)
                    raw_texts.append(text)

        if has_numeric:
            if total_qty.is_integer():
                return str(int(total_qty))
            return str(total_qty)

        return ",".join(raw_texts)

    rows = []
    image_rows = []
    tag_images = []

    for item in items:
        fields = item.get("fields", {})

        color_value = normalize_value(fields.get("颜色", ""))

        row = {
            "color": color_value,
            "xs_qty": normalize_value(fields.get("XS", "")),
            "s_qty": normalize_value(fields.get("S", "")),
            "m_qty": normalize_value(fields.get("M", "")),
            "l_qty": normalize_value(fields.get("L", "")),
            "xl_qty": normalize_value(fields.get("XL", "")),
            "x1l_qty": normalize_value(fields.get("1XL", "")),
            "x2l_qty": normalize_value(fields.get("2XL", "")),
            "x3l_qty": normalize_value(fields.get("3XL", "")),
        }
        rows.append(row)

        front_images = extract_images_from_field(item, "正面")
        back_images = extract_images_from_field(item, "背面")
        current_tag_images = extract_images_from_field(item, "吊牌")

        front_images_base64 = images_to_base64_list(front_images)
        back_images_base64 = images_to_base64_list(back_images)
        tag_images = merge_unique_images(tag_images, current_tag_images)

        image_rows.append({
            "color": color_value,
            "front_images_base64": front_images_base64,
            "back_images_base64": back_images_base64,
        })

    tag_images_base64 = images_to_base64_list(tag_images)
    aggregated_top_size = aggregate_top_sizes(items)
    aggregated_top_qty = aggregate_top_qty(items)
    source_record_ids = [str(item.get("record_id") or "").strip() for item in items if item.get("record_id")]

    payload = {
        "record_id": source_record_ids[0] if source_record_ids else "",
        "source_record_ids": source_record_ids,
        "po_no": po_no,
        "style_no": f("款号"),
        "price": f("价格"),
        "order_date": f("下单日期"),
        "ship_date": f("出货日期"),
        "vendor": f("Vendor"),
        "top_size": aggregated_top_size,
        "top_qty": aggregated_top_qty,
        "size_pack": f("尺码包装"),
        "inner_ratio": f("中包比例"),
        "carton_thickness": f("纸箱箱度"),
        "tape_color": f("封箱胶颜色"),
        "tag_images_base64": tag_images_base64,
        "image_rows": image_rows,
        "rows": rows
    }
    return payload


def update_contract_result_to_feishu(record_ids, file_name: str, file_path: str, generated_at: str, error_message: str, contract_status: str = ""):
    cleaned_record_ids = []
    seen = set()
    for record_id in record_ids or []:
        rid = str(record_id or "").strip()
        if not rid or rid in seen:
            continue
        seen.add(rid)
        cleaned_record_ids.append(rid)

    if not cleaned_record_ids:
        return {"success": False, "message": "No record_id available for Feishu update"}

    token = get_feishu_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }

    fields = {
        "合同文件名": str(file_name or ""),
        "合同文件路径": str(file_path or ""),
        "合同生成时间": to_bitable_datetime_value(generated_at),
        "合同错误信息": str(error_message or ""),
    }
    if contract_status:
        fields["合同生成状态"] = str(contract_status)

    updated_record_ids = []
    failed_updates = []

    for record_id in cleaned_record_ids:
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{FEISHU_APP_TOKEN}/tables/{FEISHU_TABLE_ID}/records/{record_id}"
        resp = requests.put(
            url,
            headers=headers,
            params={"ignore_consistency_check": "true"},
            json={"fields": fields},
            timeout=30,
        )
        data = resp.json()

        if data.get("code") == 0:
            updated_record_ids.append(record_id)
            continue

        failed_updates.append({
            "record_id": record_id,
            "code": data.get("code"),
            "msg": data.get("msg"),
        })

    if failed_updates:
        print("Feishu contract result update partial failure:", failed_updates)

    return {
        "success": len(failed_updates) == 0,
        "updated_record_ids": updated_record_ids,
        "failed_updates": failed_updates,
    }

@app.get("/health")
def health():
    return {"ok": True, "service": "contract-hub"}

@app.get("/debug/feishu/by-po")
def debug_feishu_by_po(po_no: str, x_api_key: str = Header(default="")):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    payload = build_contract_payload_from_records(po_no)
    return {"success": True, "payload": payload}


@app.get("/debug/feishu/auth-mode")
def debug_feishu_auth_mode(x_api_key: str = Header(default="")):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

    _load_user_token_cache_once()

    return {
        "success": True,
        "auth_mode": FEISHU_AUTH_MODE,
        "using_user_token_config": bool(
            FEISHU_USER_ACCESS_TOKEN
            or FEISHU_USER_REFRESH_TOKEN
            or Path(FEISHU_USER_TOKEN_STORE).exists()
        ),
        "user_token_store": FEISHU_USER_TOKEN_STORE,
        "has_cached_user_access_token": bool(_feishu_user_token_cache.get("access_token")),
        "has_cached_user_refresh_token": bool(_feishu_user_token_cache.get("refresh_token")),
        "user_access_expires_at": _feishu_user_token_cache.get("access_expires_at").isoformat() if _feishu_user_token_cache.get("access_expires_at") else "",
        "user_refresh_expires_at": _feishu_user_token_cache.get("refresh_expires_at").isoformat() if _feishu_user_token_cache.get("refresh_expires_at") else "",
    }


@app.get("/debug/feishu/raw-images-by-po")
def debug_feishu_raw_images_by_po(po_no: str, x_api_key: str = Header(default="")):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

    items = search_records_by_po(po_no)
    result = []

    for item in items:
        fields = item.get("fields", {})
        result.append({
            "record_id": item.get("record_id", ""),
            "color": normalize_value(fields.get("颜色", "")),
            "front_raw": fields.get("正面"),
            "back_raw": fields.get("背面"),
            "tag_raw": fields.get("吊牌"),
            "field_keys": sorted(list(fields.keys())),
        })

    return {
        "success": True,
        "count": len(result),
        "records": result,
    }


@app.get("/debug/feishu/sample")
def debug_feishu_sample(x_api_key: str = Header(default="")):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

    token = get_feishu_access_token()
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{FEISHU_APP_TOKEN}/tables/{FEISHU_TABLE_ID}/records?page_size=3"     

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    resp = requests.get(url, headers=headers, timeout=30)
    data = resp.json()
    return data

@app.post("/api/contracts/create")
def create_task(data: CreateTaskPayload, x_api_key: str = Header(default="")):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

    incoming_payload = data.payload or {}
    po_no = str(incoming_payload.get("po_no", "")).strip().rstrip(",，")

    if po_no and ("rows" not in incoming_payload or not incoming_payload.get("rows")):
        final_payload = build_contract_payload_from_records(po_no)
    else:
        final_payload = incoming_payload

    now = get_beijing_isoformat()
    base_po_no = str(po_no or final_payload.get("po_no", "") or "contract").strip().rstrip(",，")
    unique_task_id = f"{base_po_no}__{get_beijing_now().strftime('%Y%m%d%H%M%S%f')}"

    conn = get_conn()
    conn.execute("""
        INSERT INTO tasks (task_id, status, payload, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
    """, (
        unique_task_id,
        "pending",
        json.dumps(final_payload, ensure_ascii=False),
        now,
        now
    ))
    conn.commit()
    conn.close()

    print(f"Queued contract task: task_id={unique_task_id}, po_no={base_po_no}")

    return {"success": True, "task_id": unique_task_id, "status": "pending"}

@app.get("/api/contracts/pending")
def get_pending(x_api_key: str = Header(default="")):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

    conn = get_conn()
    row = conn.execute("""
        SELECT * FROM tasks
        WHERE status = 'pending'
        ORDER BY id ASC
        LIMIT 1
    """).fetchone()

    if not row:
        conn.close()
        return {"success": True, "task": None}

    conn.execute("""
        UPDATE tasks SET status = ?, updated_at = ?
        WHERE task_id = ?
    """, ("processing", datetime.utcnow().isoformat(), row["task_id"]))
    conn.commit()

    payload = json.loads(row["payload"])
    task_id = row["task_id"]
    conn.close()

    return {
        "success": True,
        "task": {
            "task_id": task_id,
            "payload": payload
        }
    }

@app.post("/api/contracts/result")
def post_result(data: ResultPayload, x_api_key: str = Header(default="")):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

    conn = get_conn()
    task_row = conn.execute("SELECT payload FROM tasks WHERE task_id = ?", (data.task_id,)).fetchone()
    conn.execute("""
        UPDATE tasks
        SET status = ?, file_name = ?, file_path = ?, error_message = ?, warnings = ?, updated_at = ?
        WHERE task_id = ?
    """, (
        data.status,
        data.file_name or "",
        data.file_path or "",
        data.error_message or "",
        json.dumps(data.warnings or [], ensure_ascii=False),
        get_beijing_isoformat(),
        data.task_id
    ))
    conn.commit()
    conn.close()

    task_payload = json.loads(task_row["payload"] or "{}") if task_row else {}
    record_ids = task_payload.get("source_record_ids") or []
    if not record_ids and task_payload.get("record_id"):
        record_ids = [task_payload.get("record_id")]

    error_text = str(data.error_message or "").strip()
    if not error_text and data.warnings:
        error_text = "；".join(str(item).strip() for item in data.warnings if str(item).strip())

    contract_status = ""
    if data.status == "done":
        contract_status = "已生成"
    elif data.status == "failed":
        contract_status = "失败"

    feishu_update_result = {"success": False, "message": "Skipped"}
    try:
        feishu_update_result = update_contract_result_to_feishu(
            record_ids=record_ids,
            file_name=data.file_name or "",
            file_path=data.file_path or "",
            generated_at=data.generated_at or get_beijing_isoformat(),
            error_message=error_text,
            contract_status=contract_status,
        )
    except Exception as exc:
        feishu_update_result = {"success": False, "message": repr(exc)}
        print("Feishu contract result update failed:", repr(exc))

    return {
        "success": True,
        "task_id": data.task_id,
        "status": data.status,
        "feishu_update": feishu_update_result,
    }

@app.get("/api/contracts/status/{task_id}")
def get_status(task_id: str, x_api_key: str = Header(default="")):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

    conn = get_conn()
    row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Task not found")

    return {
        "success": True,
        "task_id": row["task_id"],
        "status": row["status"],
        "file_name": row["file_name"],
        "file_path": row["file_path"],
        "error_message": row["error_message"],
        "warnings": json.loads(row["warnings"] or "[]")
    }