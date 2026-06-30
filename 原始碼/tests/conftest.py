"""测试夹具：建表 + 提供 TestClient + 生成样例 PDF/CSV。"""
from __future__ import annotations

import io
import os

# 测试中禁用后台队列调度器,改由测试直接调用 process_task(确定性)
os.environ.setdefault("BMS_NO_DISPATCHER", "1")

import fitz  # PyMuPDF
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session", autouse=True)
def _init_schema():
    # 建扩展 + 建表（幂等）
    from backend.app.schema import init_db

    init_db(drop=True)
    yield


@pytest.fixture()
def client():
    from backend.app.main import app

    with TestClient(app) as c:
        yield c


def make_pdf_bytes(headings: list[str]) -> bytes:
    """生成一个每页一个章节标题的 PDF（无书签，走标题正则解析）。"""
    doc = fitz.open()
    for h in headings:
        page = doc.new_page()
        page.insert_text((72, 72), h, fontsize=14)
        page.insert_text(
            (72, 110),
            "Threshold and protection behavior description for testing. "
            "The device shall trigger when the measured value exceeds the limit.",
            fontsize=10,
        )
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


def make_ti_csv_bytes() -> bytes:
    """生成 TI Data Flash 风格 CSV（>=14 列、无表头、列定位）。"""
    rows = [
        # 0Class,1Subclass,2Name,3Value,4Unit,5,6,7,8Default,9Min,10Max,11,12,13,14Flags
        ["Protections", "CUV", "CUV Threshold", "2500", "mV", "", "", "", "2500", "2000", "3000", "", "", "", "F8"],
        ["Protections", "COV", "COV Threshold", "4300", "mV", "", "", "", "4300", "4000", "4500", "", "", "", "F8"],
        ["Protections", "OCD", "OCD1 Threshold", "60", "mV", "", "", "", "60", "10", "100", "", "", "", "F8"],
    ]
    out = io.StringIO()
    import csv

    w = csv.writer(out)
    for r in rows:
        w.writerow(r)
    return out.getvalue().encode("utf-8")


def make_generic_csv_bytes() -> bytes:
    return (
        "Name,Value,Unit,Min,Max,Description\n"
        "Overvoltage,4300,mV,4000,4500,over voltage threshold\n"
        "Undervoltage,2500,mV,2000,3000,under voltage threshold\n"
    ).encode("utf-8")
