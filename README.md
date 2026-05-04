# NAS-FEISHU

**飞书 PO 合同自动生成服务** — 从飞书多维表格（Bitable）读取采购订单数据，自动生成标准格式的 Excel 合同文件并保存到 NAS 指定目录。

---

## 功能概览

| 功能 | 说明 |
|---|---|
| 飞书 Bitable 集成 | 通过事件订阅 Webhook 或手动触发，读取多维表格中的 PO 数据 |
| Excel 合同生成 | 自动生成带格式的采购订单 Excel（含表头、行项目、合计、签字区域） |
| NAS 文件保存 | 按年/月自动分目录保存，支持磁盘空间监控 |
| 状态回写 | 生成完毕后自动将 Bitable 记录状态更新为"已生成" |
| REST API | 提供手动触发、文件列举、健康检查端点 |

---

## 目录结构

```
NAS-FEISHU/
├── main.py                 # Flask 应用入口（Webhook 服务器）
├── config.py               # 配置（读取环境变量）
├── requirements.txt        # Python 依赖
├── .env.example            # 环境变量示例
├── feishu/
│   ├── client.py           # 飞书 API 基础客户端（Token 管理）
│   └── bitable.py          # Bitable 读写操作
├── excel/
│   └── generator.py        # PO 合同 Excel 生成器
├── nas/
│   └── handler.py          # NAS 目录管理
└── tests/
    ├── test_excel_generator.py
    ├── test_nas_handler.py
    └── test_webhook.py
```

---

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env` 并填写实际值：

```bash
cp .env.example .env
```

主要配置项：

| 变量 | 说明 |
|---|---|
| `FEISHU_APP_ID` | 飞书应用 App ID |
| `FEISHU_APP_SECRET` | 飞书应用 App Secret |
| `FEISHU_BITABLE_APP_TOKEN` | 多维表格 App Token（从表格 URL 中获取） |
| `FEISHU_BITABLE_TABLE_ID` | 数据表 ID |
| `NAS_OUTPUT_DIR` | NAS 挂载路径（Excel 文件存储目录） |
| `COMPANY_NAME` | 公司名称（出现在合同头部） |

### 3. 启动服务

**开发模式：**
```bash
python main.py
```

**生产模式（gunicorn）：**
```bash
pip install gunicorn
gunicorn -w 2 -b 0.0.0.0:5000 "main:create_app()"
```

---

## 飞书配置

### 多维表格字段映射

Bitable 数据表中需要包含以下字段（字段名即为 field_id）：

| 字段名 | 类型 | 说明 |
|---|---|---|
| `po_number` | 文本 | 采购订单编号 |
| `contract_date` | 日期/文本 | 合同日期（YYYY-MM-DD） |
| `supplier_name` | 文本 | 供应商名称 |
| `supplier_address` | 文本 | 供应商地址 |
| `supplier_contact` | 文本 | 供应商联系人 |
| `supplier_tel` | 文本 | 供应商电话 |
| `buyer_name` | 文本 | 采购方名称 |
| `buyer_dept` | 文本 | 采购部门 |
| `buyer_contact` | 文本 | 采购联系人 |
| `currency` | 文本 | 货币（CNY / USD 等） |
| `payment_terms` | 文本 | 付款条款 |
| `delivery_date` | 文本 | 交货日期 |
| `delivery_address` | 文本 | 收货地址 |
| `items` | 文本（JSON） | 行项目（见下方格式说明） |
| `notes` | 文本 | 备注 |
| `status` | 单选 | 状态（系统回写：已生成 / 生成失败） |

**`items` 字段 JSON 格式示例：**

```json
[
  {"description": "产品名称", "unit": "个", "qty": 10, "unit_price": 100.00},
  {"description": "另一产品", "unit": "套", "qty": 5,  "unit_price": 250.00}
]
```

### 事件订阅配置

在飞书开放平台「事件订阅」中添加以下事件，并将回调地址设为：

```
https://<your-server>/webhook/feishu
```

推荐订阅事件：
- `bitable.record.created.v1` — 记录新增时自动生成
- `bitable.record.updated.v1` — 记录更新时重新生成

---

## API 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 健康检查（返回 NAS 磁盘状态） |
| POST | `/webhook/feishu` | 飞书事件订阅回调端点 |
| POST | `/api/generate` | 根据 record_id 手动触发生成 |
| GET | `/api/files` | 列出已生成的合同文件 |

**手动触发示例：**

```bash
curl -X POST http://localhost:5000/api/generate \
  -H "Content-Type: application/json" \
  -d '{"record_id": "recXXXXXXX"}'
```

---

## 生成的 Excel 格式

```
┌─────────────────────────────────────────────────────┐
│                    贵公司名称                         │  ← 公司标题
│                  采  购  订  单                       │  ← 文档标题
├──────────┬──────────────┬──────────┬────────────────┤
│  合同编号 │ PO-2024-001  │  合同日期 │  2024-01-15    │
│  供应商   │ XX科技有限公司 │  采购方   │  XX采购集团    │
│  ...      │ ...          │  ...      │  ...           │
├────┬─────────────────┬──┬────┬──────┬────────┬──────┤
│序号│ 商品描述         │单位│数量│ 单价  │  金额  │ 备注 │  ← 行项目表头
│ 1  │ 产品A            │个  │ 10 │100.00│1000.00│      │
│ 2  │ 产品B            │套  │  5 │250.00│1250.00│      │
├────┴─────────────────┴──┴────┴──────┼────────┴──────┤
│                    合  计            │   2250.00      │
├──────────┬──────────────────────────┴───────────────┤
│  付款条款 │ 月结30天                                  │
│  交货日期 │ 2024-02-01                               │
│  备  注   │ 请确保按时交货                             │
├──────────┴──────────────────────────────────────────┤
│  供应商确认签字        │     采购方签字                │
│                        │                              │
│  日期：                │     日期：                    │
└────────────────────────┴─────────────────────────────┘
```

---

## 运行测试

```bash
python -m pytest tests/ -v
```

---

## NAS 目录结构

生成的文件按年/月自动归档：

```
<NAS_OUTPUT_DIR>/
├── 2024/
│   ├── 01/
│   │   ├── PO_PO-2024-001_20240115.xlsx
│   │   └── PO_PO-2024-002_20240120.xlsx
│   └── 02/
│       └── PO_PO-2024-003_20240201.xlsx
└── 2025/
    └── ...
```

