import os
import time
import json
import traceback
import urllib.request
import urllib.error

HUB_BASE_URL = os.environ.get("HUB_BASE_URL", "").rstrip("/")
HUB_API_KEY = os.environ.get("HUB_API_KEY", "")
LOCAL_CONTRACT_API = os.environ.get("LOCAL_CONTRACT_API", "http://127.0.0.1:8000/generate-po-contract")
LOCAL_CONTRACT_API_KEY = os.environ.get("LOCAL_CONTRACT_API_KEY", "")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "10"))


def http_get_json(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_post_json(url, payload, headers=None):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers=headers or {},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def process_one_task():
    headers = {
        "X-Api-Key": HUB_API_KEY
    }

    pending_url = f"{HUB_BASE_URL}/api/contracts/pending"
    result = http_get_json(pending_url, headers=headers)

    task = result.get("task")
    if not task:
        print("No pending task.")
        return

    task_id = task["task_id"]
    payload = task["payload"]

    print(f"Picked task: {task_id}")

    try:
        local_headers = {
            "Content-Type": "application/json",
            "X-Api-Key": LOCAL_CONTRACT_API_KEY
        }

        local_result = http_post_json(
            LOCAL_CONTRACT_API,
            payload,
            headers=local_headers
        )

        callback_payload = {
            "task_id": task_id,
            "status": "done",
            "file_name": local_result.get("file_name", ""),
            "file_path": local_result.get("file_path", ""),
            "error_message": "",
            "generated_at": local_result.get("generated_at", ""),
            "warnings": local_result.get("warnings", [])
        }

        callback_url = f"{HUB_BASE_URL}/api/contracts/result"
        callback_headers = {
            "Content-Type": "application/json",
            "X-Api-Key": HUB_API_KEY
        }

        callback_result = http_post_json(
            callback_url,
            callback_payload,
            headers=callback_headers
        )

        print(f"Task done: {task_id} -> {callback_result}")

    except Exception as e:
        traceback.print_exc()

        callback_payload = {
            "task_id": task_id,
            "status": "failed",
            "file_name": "",
            "file_path": "",
            "error_message": repr(e),
            "generated_at": "",
            "warnings": []
        }

        callback_url = f"{HUB_BASE_URL}/api/contracts/result"
        callback_headers = {
            "Content-Type": "application/json",
            "X-Api-Key": HUB_API_KEY
        }

        try:
            callback_result = http_post_json(
                callback_url,
                callback_payload,
                headers=callback_headers
            )
            print(f"Task failed: {task_id} -> {callback_result}")
        except Exception:
            traceback.print_exc()


def main():
    print("Contract worker started.")
    while True:
        try:
            process_one_task()
        except Exception:
            traceback.print_exc()

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()