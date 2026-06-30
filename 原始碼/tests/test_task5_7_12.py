"""Task 5(队列+并发闸)/ 7(SSE)/ 12(队列状态)自测。

后台调度器在测试中禁用(BMS_NO_DISPATCHER=1),由测试直接调用 process_task,确保确定性。
"""
from __future__ import annotations

import uuid

import pytest

import backend.app.llm as llm
from backend.app import taskqueue
from backend.app.redis_client import client as redis_client

from .conftest import make_pdf_bytes, make_ti_csv_bytes


@pytest.fixture(autouse=True)
def _clear_queue():
    # 每个用例前后清掉队列相关键,避免互相干扰
    for k in redis_client.keys("bms:*"):
        redis_client.delete(k)
    yield
    for k in redis_client.keys("bms:*"):
        redis_client.delete(k)


def _new_case(client) -> tuple[str, str]:
    pdf = make_pdf_bytes(["1. CUV Protection"])
    rc = client.post("/api/cases/upload-pdf", files={"file": ("s.pdf", pdf, "application/pdf")})
    d = rc.json()
    cid, title = d["case_id"], d["chapters"][0]["title"]
    client.post(f"/api/cases/{cid}/upload-csv", files={"file": ("f.csv", make_ti_csv_bytes(), "text/csv")})
    return cid, title


# ── Task 5:并发闸(running2/queued2/满4拒绝)──
def test_enqueue_gate_rejects_when_full(client):
    cid, title = _new_case(client)
    accepted = 0
    for _ in range(4):  # capacity = max_running(2)+max_queued(2) = 4
        r = client.post(f"/api/cases/{cid}/generate", json={"selected_titles": [title], "queued": True})
        assert r.status_code == 202, r.text
        accepted += 1
    assert accepted == 4
    # 第 5 个应被拒绝
    r5 = client.post(f"/api/cases/{cid}/generate", json={"selected_titles": [title], "queued": True})
    assert r5.status_code == 429
    assert "排队已满" in r5.json()["detail"]


def test_queue_status_and_position(client):
    cid, title = _new_case(client)
    r = client.post(f"/api/cases/{cid}/generate", json={"selected_titles": [title], "queued": True})
    task_id = r.json()["task_id"]
    assert r.json()["queue_position"] == 1

    st = client.get("/api/queue/status").json()
    assert st["queued"] == 1
    assert st["max_running"] == 2 and st["max_queued"] == 2 and st["capacity"] == 4

    ts = client.get(f"/api/tasks/{task_id}").json()
    assert ts["status"] == "queued"
    assert ts["queue_position"] == 1


def test_cancel_queued_task(client):
    cid, title = _new_case(client)
    r = client.post(f"/api/cases/{cid}/generate", json={"selected_titles": [title], "queued": True})
    task_id = r.json()["task_id"]

    rc = client.post(f"/api/tasks/{task_id}/cancel")
    assert rc.status_code == 200
    # 取消后从队列移除,状态 canceled
    assert taskqueue.position(task_id) is None
    assert client.get(f"/api/tasks/{task_id}").json()["status"] == "canceled"


# ── worker 端到端 + Task 7 SSE ──
def test_process_task_end_to_end_and_sse(client, monkeypatch):
    cid, title = _new_case(client)
    r = client.post(f"/api/cases/{cid}/generate", json={"selected_titles": [title], "queued": True, "mode": "engine"})
    task_id = r.json()["task_id"]

    card = '<div class="tc-card"><div class="tc-header"><span class="tc-id">TC-01</span></div></div>'
    monkeypatch.setattr(llm, "stream_chat", lambda prompt: iter([card]))

    # 直接处理(模拟 worker)
    taskqueue.process_task(task_id)

    # 任务完成、落库
    ts = client.get(f"/api/tasks/{task_id}").json()
    assert ts["status"] == "done"
    assert ts["tc_count"] == 1

    # SSE 流:已完成任务应回放出 progress/done 事件后结束
    sr = client.get(f"/api/tasks/{task_id}/stream")
    assert sr.status_code == 200
    assert "text/event-stream" in sr.headers["content-type"]
    body = sr.text
    assert '"type": "progress"' in body or '"type":"progress"' in body
    assert '"type": "done"' in body or '"type":"done"' in body


def test_cancel_before_process_skips(client, monkeypatch):
    cid, title = _new_case(client)
    r = client.post(f"/api/cases/{cid}/generate", json={"selected_titles": [title], "queued": True})
    task_id = r.json()["task_id"]

    taskqueue.request_cancel(task_id)
    # 模型不该被调用
    def boom(prompt):
        raise AssertionError("已取消的任务不应调用模型")
        yield
    monkeypatch.setattr(llm, "stream_chat", boom)
    taskqueue.process_task(task_id)
    assert client.get(f"/api/tasks/{task_id}").json()["status"] == "canceled"
