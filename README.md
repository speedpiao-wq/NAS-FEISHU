# PO 合同自动生成

这个项目用于从飞书 PO 数据生成合同 Excel 文件。整体链路是：

1. 飞书自动化发送 PO 号到轻量服务器。
2. 轻量服务器的 `contract-hub` 按 PO 号查询飞书记录并创建任务。
3. NAS 上的 `contract-worker` 轮询任务。
4. NAS 上的 `po-contract-service` 写入 Excel 模板并生成合同。
5. 结果回传轻量服务器，再由轻量服务器回写飞书状态。

## 目录

- `轻量服务器/app.py`：轻量服务器上的任务中心 API，默认端口 `9000`。
- `轻量服务器/contract-hub.service`：`contract-hub` 的 systemd 服务文件。
- `轻量服务器/contract-hub.env.example`：轻量服务器环境变量样例。
- `contract-worker/worker.py`：NAS worker，负责轮询轻量服务器并调用本地合同生成服务。
- `contract-worker/docker-compose.yml`：NAS worker 容器配置。
- `contract-worker/.env.example`：worker 环境变量样例。
- `po-contract-service/app.py`：合同 Excel 生成服务，默认端口 `8000`。
- `po-contract-service/docker-compose.yml`：合同生成服务容器配置。
- `po-contract-service/.env.example`：合同生成服务环境变量样例。

## 部署要点

真实密钥不要提交到 Git。部署时把对应的 `.env.example` 复制为 `.env`，再填入真实值。

轻量服务器：

```bash
cd /opt/contract-hub
python3 -m venv .venv
.venv/bin/pip install fastapi uvicorn pydantic requests
cp contract-hub.env.example .env
systemctl restart contract-hub
```

NAS：

```bash
docker compose up -d
docker logs --tail=100 contract-worker
docker logs --tail=100 po-contract-service
```

## 健康检查

轻量服务器：

```bash
curl http://127.0.0.1:9000/health
```

NAS：

```bash
curl http://127.0.0.1:8000/health
```

