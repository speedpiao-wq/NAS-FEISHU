# PO 合同自动生成当前工作流

这份流程图基于目前已经跑通的真实链路整理，覆盖飞书触发、阿里云上游服务、NAS 模板生成、结果回写这 4 段。

## 总览

```mermaid
flowchart TD
	A[PO登记表录入或修改 PO] --> B{是否勾选生成合同}
	B -- 否 --> Z[结束]
	B -- 是 --> C[飞书自动化流程触发]
	C --> D[校验必填字段]
	D --> E{字段是否完整}
	E -- 否 --> E1[返回失败信息给飞书]
	E1 --> Z
	E -- 是 --> F[发送 HTTP 请求到阿里云 contract-hub]
	F --> G[上游服务读取请求 JSON]
	G --> H{请求是否仅传入 po_no}
	H -- 是 --> I[按 po_no 反查飞书记录]
	I --> I1[查 PO登记表 record_id]
	I1 --> I2[查一键合同关联记录]
	I2 --> I3[提取基础字段与尺码行]
	I3 --> I4[提取正面 背面 吊牌图片]
	I4 --> I5[下载图片并转为 BASE64]
	I5 --> J[生成标准合同 payload]
	H -- 否 --> J
	J --> K[写入 tasks 队列 状态 pending]
	K --> L[NAS worker 轮询 pending 任务]
	L --> M[拉取任务 payload]
	M --> N[打开 Excel 模板]
	N --> O[写入基础字段与尺码表]
	O --> P[写入图片区域]
	P --> P1[吊牌图从 A8 向下排]
	P --> P2[正面图从 A15 向右排]
	P --> P3[背面图从 A23 向右排]
	P1 --> Q[生成文件名并保存到 NAS 目录]
	P2 --> Q
	P3 --> Q
	Q --> R[调用上游结果回传接口]
	R --> S[上游更新任务状态 文件路径 警告信息]
	S --> T[飞书读取结果并回写状态 路径 时间]
	T --> Z
```

## 上下游时序图

```mermaid
sequenceDiagram
	participant Feishu as 飞书自动化
	participant Cloud as 阿里云上游服务
	participant DB as SQLite任务队列
	participant NAS as NAS生成服务
	participant Excel as Excel模板

	Feishu->>Cloud: POST /api/contracts/create
	Note over Feishu,Cloud: 可能只传 po_no，也可能直接传完整 payload

	alt 仅传 po_no
		Cloud->>Cloud: 按 po_no 查询飞书记录
		Cloud->>Cloud: 聚合基础字段 / 尺码 / 图片
		Cloud->>Cloud: 图片下载并转 BASE64
	else 已带完整 payload
		Cloud->>Cloud: 直接使用传入数据
	end

	Cloud->>DB: 插入 pending 任务
	NAS->>Cloud: GET /api/contracts/pending
	Cloud->>DB: 取最早 pending 并改为 processing
	Cloud-->>NAS: 返回 task_id + payload

	NAS->>Excel: 打开模板并写入字段
	NAS->>Excel: 写吊牌 / 正面 / 背面图片
	NAS->>Excel: 保存到 NAS 输出目录
	NAS->>Cloud: POST /api/contracts/result
	Cloud->>DB: 更新 completed/failed + 文件信息
	Feishu->>Cloud: GET /api/contracts/status/{task_id}
	Cloud-->>Feishu: 返回状态 / 路径 / warnings
```

## 图片处理逻辑

```mermaid
flowchart LR
	A[飞书图片字段] --> B[提取图片元数据]
	B --> C[按 url 或 tmp_url 下载]
	C --> D[转 BASE64]
	D --> E{图片类型}
	E -->|吊牌| F[聚合并去重]
	E -->|正面| G[按颜色保留到 front_images_base64]
	E -->|背面| H[按颜色保留到 back_images_base64]
	F --> I[写入 A8 A9 A10 ...]
	G --> J[写入 A15 B15 C15 ...]
	H --> K[写入 A23 B23 C23 ...]
```

## 当前落地规则

- 上游服务运行在阿里云，采用 `systemd` 管理，重启命令是 `systemctl restart contract-hub`
- 上游图片逻辑已经改为 `BASE64` 传输，不再依赖 NAS 直接访问飞书图片地址
- 吊牌图支持跨颜色聚合并去重，适合“多数统一吊牌、少数多吊牌”的场景
- NAS 服务负责模板渲染和文件落盘，当前已支持吊牌、正面、背面 3 类图片位
- 结果会回写任务状态、输出路径、警告信息，便于飞书侧追踪

## 建议的后续扩展

- 把主唛、洗水唛、包装图也纳入同一套“聚合 + 去重 + 定位写入”机制
- 给图片区域增加“超出自动换行”规则，避免未来图片数量增加后人工调整模板
- 增加异常分支图：飞书字段缺失、图片下载失败、NAS 保存失败、结果回写失败
- 增加运维发布流程图：本地 `scp` 上传 → `py_compile` → `systemctl restart` → 健康检查
