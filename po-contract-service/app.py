from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from openpyxl import load_workbook
from openpyxl.drawing.image import Image as OpenpyxlImage
from datetime import datetime, timedelta, timezone
from pathlib import Path
from io import BytesIO
import os
import shutil
import base64
import mimetypes
import tempfile
import requests

app = FastAPI()

API_KEY = os.environ.get("PO_CONTRACT_API_KEY", "")
TEMPLATE_PATH = os.environ.get("PO_TEMPLATE_PATH", "")
OUTPUT_DIR = os.environ.get("PO_OUTPUT_DIR", "")
OUTPUT_DISPLAY_DIR = os.environ.get("PO_OUTPUT_DISPLAY_DIR", "").strip()
TEMPLATE_SHEET = os.environ.get("PO_TEMPLATE_SHEET", "Sheet1")
BEIJING_TZ = timezone(timedelta(hours=8))


def build_display_file_path(out_file: Path):
    display_dir = OUTPUT_DISPLAY_DIR.rstrip("/\\")
    if not display_dir:
        return str(out_file.parent)
    return display_dir

# ===== 上方基础区域 =====
# 这一版按你当前模板截图重新对齐
BASE_MAPPING = {
    "style_no": "B2",           # 款号
    "po_no": "B3",              # PO
    "price": "B4",              # Price
    "order_date": "H2",         # 下单日期
    "ship_date": "H3",          # 出货日期
    "vendor": "H4",             # Vendor

    "top_size": "B11",          # TOP码数
    "top_qty": "H11",           # TOP数量
    "size_pack": "B12",         # 尺码包装
    "inner_ratio": "H12",       # 中包比例
    "carton_thickness": "B13",  # 纸箱箱度
    "tape_color": "H13",        # 封箱胶颜色
}

SIZE_ORDER = ["XS", "S", "M", "L", "XL", "1XL", "2XL", "3XL"]

SIZE_FIELD_MAP = {
    "XS": "xs_qty",
    "S": "s_qty",
    "M": "m_qty",
    "L": "l_qty",
    "XL": "xl_qty",
    "1XL": "x1l_qty",
    "2XL": "x2l_qty",
    "3XL": "x3l_qty",
}

# 方案2：表头只写一次
SIZE_HEADER_COLS = ["D", "E", "F", "G", "H"]
SIZE_HEADER_ROW = 5
FIRST_DATA_ROW = 6
MAX_COLOR_ROWS = 4
IMAGE_CELL_MAP = [
    {"front": "A15", "back": "A23"},
    {"front": "B15", "back": "B23"},
]

class ColorRow(BaseModel):
    color: str | None = ""
    color_en: str | None = ""
    xs_qty: str | int | float | None = ""
    s_qty: str | int | float | None = ""
    m_qty: str | int | float | None = ""
    l_qty: str | int | float | None = ""
    xl_qty: str | int | float | None = ""
    x1l_qty: str | int | float | None = ""
    x2l_qty: str | int | float | None = ""
    x3l_qty: str | int | float | None = ""


class ImageRow(BaseModel):
    color: str | None = ""
    front_images_base64: list[dict] = Field(default_factory=list)
    back_images_base64: list[dict] = Field(default_factory=list)


class ContractPayload(BaseModel):
    record_id: str | None = ""
    po_no: str | None = ""
    style_no: str | None = ""
    price: str | int | float | None = ""
    order_date: str | None = ""
    ship_date: str | None = ""
    vendor: str | None = ""

    top_size: str | None = ""
    top_qty: str | int | float | None = ""
    size_pack: str | None = ""
    inner_ratio: str | None = ""
    carton_thickness: str | None = ""
    tape_color: str | None = ""

    tag_images_base64: list[dict] = Field(default_factory=list)
    image_rows: list[ImageRow] = Field(default_factory=list)
    rows: list[ColorRow] = Field(default_factory=list)


@app.get("/health")
def health():
    return {"ok": True, "version": "scheme2-v1"}


def safe_str(value):
    if value is None:
        return ""
    return str(value).strip()


def format_date_value(value):
    if value in (None, "", " "):
        return ""

    try:
        text = str(value).strip()

        # 13位毫秒时间戳
        if text.isdigit() and len(text) == 13:
            dt = datetime.fromtimestamp(int(text) / 1000)
            return dt.strftime("%Y/%m/%d")

        # 10位秒级时间戳
        if text.isdigit() and len(text) == 10:
            dt = datetime.fromtimestamp(int(text))
            return dt.strftime("%Y/%m/%d")

        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(text, fmt).strftime("%Y/%m/%d")
            except Exception:
                pass

        return text
    except Exception:
        return str(value)


def format_price_value(value):
    if value in (None, "", " "):
        return ""

    try:
        num = float(value)
        return f"¥{num:.2f}"
    except Exception:
        text = str(value).strip()
        return text


def save_base64_image_to_temp(image_obj, prefix="contract_img"):
    if not image_obj:
        return None

    b64 = image_obj.get("base64") or ""
    if not b64:
        return None

    file_type = image_obj.get("mime_type") or image_obj.get("type") or "image/png"
    file_type = str(file_type).lower().strip()

    ext_map = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/webp": ".webp",
        "image/bmp": ".bmp",
    }
    ext = ext_map.get(file_type, ".png")

    # 兼容 data:image/png;base64,xxxx 这种前缀
    if "," in b64 and "base64" in b64[:80].lower():
        b64 = b64.split(",", 1)[1]

    image_bytes = base64.b64decode(b64)

    fd, temp_path = tempfile.mkstemp(prefix=prefix, suffix=ext)
    with os.fdopen(fd, "wb") as f:
        f.write(image_bytes)

    return temp_path


def insert_image_to_cell(ws, image_path, cell, width=180, height=180):
    if not image_path:
        return

    if not os.path.exists(image_path):
        return

    img = OpenpyxlImage(image_path)
    img.width = width
    img.height = height
    img.anchor = cell
    ws.add_image(img)


EXTRA_IMAGE_SLOTS = [
    {
        "payload_field": "tag_images_base64",
        "label": "吊牌",
        "start_col": "A",
        "start_row": 8,
        "direction": "down",
        "width": 72,
        "height": 72,
    }
]


def build_excel_image_from_base64(image_payload: dict):
    if not image_payload:
        return None

    b64_text = image_payload.get("base64", "")
    if not b64_text:
        return None

    try:
        image_bytes = base64.b64decode(b64_text)
        bio = BytesIO(image_bytes)
        img = OpenpyxlImage(bio)
        return img
    except Exception:
        return None

def write_contract_images(ws, payload: ContractPayload, warnings: list[str]):
    temp_paths = []

    image_rows = payload.image_rows or []

    FRONT_START_ROW = 15
    BACK_START_ROW = 23
    START_COL = 1
    COL_STEP = 1

    IMAGE_WIDTH = 105
    IMAGE_HEIGHT = 145

    front_cursor_col = START_COL
    back_cursor_col = START_COL

    def col_letter(col_index: int) -> str:
        result = ""
        while col_index > 0:
            col_index, remainder = divmod(col_index - 1, 26)
            result = chr(65 + remainder) + result
        return result

    try:
        for color_idx, image_row in enumerate(image_rows, start=1):
            color_name = image_row.color or f"color_{color_idx}"
            front_list = image_row.front_images_base64 or []
            back_list = image_row.back_images_base64 or []

            if not front_list and not back_list:
                warnings.append(f"颜色 {color_name} 没有可写入的图片。")
                continue

            for image_idx, image_payload in enumerate(front_list, start=1):
                target_cell = f"{col_letter(front_cursor_col)}{FRONT_START_ROW}"
                front_temp_path = save_base64_image_to_temp(
                    image_payload if isinstance(image_payload, dict) else {},
                    prefix=f"front_img_{color_idx}_{image_idx}_"
                )

                if front_temp_path:
                    insert_image_to_cell(ws, front_temp_path, target_cell, width=IMAGE_WIDTH, height=IMAGE_HEIGHT)
                    temp_paths.append(front_temp_path)
                else:
                    warnings.append(f"颜色 {color_name} 的正面第 {image_idx} 张图片为空或解码失败，未写入 {target_cell}。")

                front_cursor_col += COL_STEP

            for image_idx, image_payload in enumerate(back_list, start=1):
                target_cell = f"{col_letter(back_cursor_col)}{BACK_START_ROW}"
                back_temp_path = save_base64_image_to_temp(
                    image_payload if isinstance(image_payload, dict) else {},
                    prefix=f"back_img_{color_idx}_{image_idx}_"
                )

                if back_temp_path:
                    insert_image_to_cell(ws, back_temp_path, target_cell, width=IMAGE_WIDTH, height=IMAGE_HEIGHT)
                    temp_paths.append(back_temp_path)
                else:
                    warnings.append(f"颜色 {color_name} 的背面第 {image_idx} 张图片为空或解码失败，未写入 {target_cell}。")

                back_cursor_col += COL_STEP

    except Exception as e:
        warnings.append(f"图片写入异常：{repr(e)}")
        print("Image write exception:", repr(e), flush=True)

    return temp_paths


def write_extra_images(ws, payload: ContractPayload, warnings: list[str]):
    temp_paths = []

    def build_slot_cells(slot: dict, image_count: int) -> list[str]:
        explicit_cells = slot.get("cells")
        if explicit_cells:
            return explicit_cells

        start_col = slot.get("start_col", "A")
        start_row = int(slot.get("start_row", 1))
        direction = slot.get("direction", "down")

        def shift_col(col: str, offset: int) -> str:
            value = 0
            for ch in col.upper():
                value = value * 26 + (ord(ch) - 64)
            value += offset

            result = ""
            while value > 0:
                value, remainder = divmod(value - 1, 26)
                result = chr(65 + remainder) + result
            return result

        cells = []
        for idx in range(image_count):
            if direction == "right":
                cells.append(f"{shift_col(start_col, idx)}{start_row}")
            else:
                cells.append(f"{start_col}{start_row + idx}")
        return cells

    try:
        for slot in EXTRA_IMAGE_SLOTS:
            payload_field = slot["payload_field"]
            label = slot["label"]
            width = slot.get("width", 72)
            height = slot.get("height", 72)

            image_list = getattr(payload, payload_field, None) or []
            if not image_list:
                continue

            cells = build_slot_cells(slot, len(image_list))

            if len(image_list) > len(cells):
                warnings.append(f"{label} 图片数量超过当前模板槽位：{len(image_list)} 张，仅写入前 {len(cells)} 张。")

            for idx, cell in enumerate(cells):
                if idx >= len(image_list):
                    break

                image_payload = image_list[idx]
                temp_path = save_base64_image_to_temp(
                    image_payload if isinstance(image_payload, dict) else {},
                    prefix=f"{payload_field}_{idx+1}_"
                )

                if temp_path:
                    insert_image_to_cell(ws, temp_path, cell, width=width, height=height)
                    temp_paths.append(temp_path)
                else:
                    warnings.append(f"{label} 第 {idx+1} 张图片为空或解码失败，未写入 {cell}。")

    except Exception as e:
        warnings.append(f"扩展图片写入异常：{repr(e)}")
        print("Extra image write exception:", repr(e), flush=True)

    return temp_paths

def normalize_qty(value):
    if value in (None, "", " "):
        return None
    try:
        num = float(value)
        if num == 0:
            return None
        if num.is_integer():
            return int(num)
        return num
    except Exception:
        return None


def collect_union_sizes(rows: list[ColorRow]) -> list[str]:
    result = []
    for size_name in SIZE_ORDER:
        field_name = SIZE_FIELD_MAP[size_name]
        for row in rows:
            qty = normalize_qty(getattr(row, field_name, None))
            if qty is not None:
                result.append(size_name)
                break
    return result


def clear_size_area(ws):
    for col in SIZE_HEADER_COLS:
        ws[f"{col}{SIZE_HEADER_ROW}"] = ""

    for r in range(FIRST_DATA_ROW, FIRST_DATA_ROW + MAX_COLOR_ROWS):
        ws[f"B{r}"] = ""
        ws[f"C{r}"] = ""
        for col in SIZE_HEADER_COLS:
            ws[f"{col}{r}"] = ""


def write_base_fields(ws, payload: ContractPayload):
    ws[BASE_MAPPING["style_no"]] = payload.style_no or ""
    ws[BASE_MAPPING["po_no"]] = payload.po_no or ""
    ws[BASE_MAPPING["price"]] = format_price_value(payload.price)
    ws[BASE_MAPPING["order_date"]] = format_date_value(payload.order_date)
    ws[BASE_MAPPING["ship_date"]] = format_date_value(payload.ship_date)
    ws[BASE_MAPPING["vendor"]] = payload.vendor or ""

    ws[BASE_MAPPING["top_size"]] = payload.top_size or ""
    ws[BASE_MAPPING["top_qty"]] = payload.top_qty or ""
    ws[BASE_MAPPING["size_pack"]] = payload.size_pack or ""
    ws[BASE_MAPPING["inner_ratio"]] = payload.inner_ratio or ""
    ws[BASE_MAPPING["carton_thickness"]] = payload.carton_thickness or ""
    ws[BASE_MAPPING["tape_color"]] = payload.tape_color or ""


def write_contract_table(ws, rows: list[ColorRow], warnings: list[str]):
    clear_size_area(ws)

    union_sizes = collect_union_sizes(rows)

    if len(union_sizes) > 5:
        warnings.append(f"有效尺码超过5列，当前识别到：{', '.join(union_sizes)}；仅写入前5个。")
        union_sizes = union_sizes[:5]

    # 表头 D5:H5
    for i, size_name in enumerate(union_sizes):
        ws[f"{SIZE_HEADER_COLS[i]}{SIZE_HEADER_ROW}"] = size_name

    if len(rows) > MAX_COLOR_ROWS:
        warnings.append(f"颜色行数超过模板容量：{len(rows)} 行；仅写入前 {MAX_COLOR_ROWS} 行。")
        rows = rows[:MAX_COLOR_ROWS]

    for row_idx, row in enumerate(rows):
        excel_row = FIRST_DATA_ROW + row_idx

        # B列先不写，C列写英文颜色名
        ws[f"B{excel_row}"] = ""
        ws[f"C{excel_row}"] = row.color or ""

        # 数量
        for i, size_name in enumerate(union_sizes):
            field_name = SIZE_FIELD_MAP[size_name]
            qty = normalize_qty(getattr(row, field_name, None))
            ws[f"{SIZE_HEADER_COLS[i]}{excel_row}"] = qty if qty is not None else ""


@app.post("/generate-po-contract")
def generate_po_contract(
    payload: ContractPayload,
    x_api_key: str = Header(default="")
):
    out_file = None

    try:
        if not API_KEY or x_api_key != API_KEY:
            raise HTTPException(status_code=401, detail="Invalid API key")

        template = Path(TEMPLATE_PATH)
        output_dir = Path(OUTPUT_DIR)

        if not template.exists():
            raise HTTPException(status_code=500, detail=f"Template not found: {template}")

        output_dir.mkdir(parents=True, exist_ok=True)

        beijing_now = datetime.now(BEIJING_TZ)
        ts = beijing_now.strftime("%Y%m%d_%H%M%S")
        safe_po = (payload.po_no or "NO_PO").replace("/", "_").replace("\\", "_")
        out_file = output_dir / f"{safe_po}_{ts}.xlsx"

        shutil.copy(template, out_file)

        wb = load_workbook(out_file)
        if TEMPLATE_SHEET in wb.sheetnames:
            ws = wb[TEMPLATE_SHEET]
        else:
            ws = wb[wb.sheetnames[0]]

        warnings = []
        temp_image_paths = []

        write_base_fields(ws, payload)
        write_contract_table(ws, payload.rows, warnings)
        temp_image_paths.extend(write_extra_images(ws, payload, warnings))
        temp_image_paths.extend(write_contract_images(ws, payload, warnings))

        wb.save(out_file)

        for p in temp_image_paths:
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

        print("Contract warnings:", warnings, flush=True)
        print("Contract output file:", str(out_file), flush=True)

        return {
            "success": True,
            "file_name": out_file.name,
            "file_path": build_display_file_path(out_file),
            "generated_at": beijing_now.isoformat(),
            "warnings": warnings
        }

    except HTTPException:
        if out_file and Path(out_file).exists():
            try:
                Path(out_file).unlink()
            except Exception:
                pass
        raise

    except Exception as e:
        import traceback
        traceback.print_exc()

        if out_file and Path(out_file).exists():
            try:
                Path(out_file).unlink()
            except Exception:
                pass

        raise HTTPException(status_code=500, detail=f"Generate contract failed: {repr(e)}")