"""覆盖最大化引擎 — Task 8(确定性枚举层)。

在调用模型之前,由程序决定"测哪些点":
- BVA(边界值分析):每个有 min/max 的参数生成 下界-误差/下界/下界+误差/正常值/上界-误差/上界/上界+误差;
  误差按参数类型(电压/电流/温度)走配置。
- pairwise(成对覆盖):用 allpairspy 对多参数的边界点做成对组合,覆盖两两交互。
- 约束过滤:排除非法组合(min>max、空值等)。
全程本地离线,绝不调用在线 API。
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from allpairspy import AllPairs

from .config import get_settings
from backend.csv_utils import match_params_for_chapters

_settings = get_settings()

_NUM_RE = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")


def parse_number(s) -> float | None:
    """从字符串里抽第一个数值(容忍带单位/符号)。"""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    m = _NUM_RE.search(str(s).replace(",", ""))
    return float(m.group()) if m else None


def classify(param: dict) -> str:
    """按单位/名称判定参数类型:voltage / current / temperature / generic。"""
    unit = (param.get("unit") or "").strip().lower()
    name = (param.get("name") or "").lower()
    if unit in ("mv", "v") or "voltage" in name or "volt" in name:
        return "voltage"
    if unit in ("ma", "a") or "current" in name or "curr" in name:
        return "current"
    if unit in ("°c", "c", "degc", "℃", "deg") or "temp" in name:
        return "temperature"
    return "generic"


def tolerance_for(param: dict) -> float:
    """返回该参数在其单位下的 BVA 误差值。"""
    cat = classify(param)
    unit = (param.get("unit") or "").strip().lower()
    if cat == "voltage":
        tol = _settings.bva_tolerance_voltage_static_mv  # 默认静态阈值 ±10mV
        return tol / 1000.0 if unit == "v" else tol
    if cat == "current":
        tol = _settings.bva_tolerance_current_ma
        return tol / 1000.0 if unit == "a" else tol
    if cat == "temperature":
        return _settings.bva_tolerance_temperature_c
    return 0.0  # generic:无误差,仅取 min/typical/max


def _fmt(v: float) -> str:
    """数值格式化:整数去掉 .0,其余保留有效小数。"""
    if v == int(v):
        return str(int(v))
    return f"{v:.4f}".rstrip("0").rstrip(".")


@dataclass
class BoundaryPoint:
    value: str
    label: str


def boundary_points(param: dict) -> list[BoundaryPoint]:
    """对单个参数生成 BVA 边界点(去重)。无 min/max 数值则返回空。"""
    lo = parse_number(param.get("min"))
    hi = parse_number(param.get("max"))
    if lo is None or hi is None:
        return []
    if lo > hi:  # 约束:min>max 视为非法,交换以容错
        lo, hi = hi, lo
    tol = tolerance_for(param)
    mid = (lo + hi) / 2.0
    raw = [
        (lo - tol, "下界-误差"),
        (lo, "下界"),
        (lo + tol, "下界+误差"),
        (mid, "正常值"),
        (hi - tol, "上界-误差"),
        (hi, "上界"),
        (hi + tol, "上界+误差"),
    ]
    seen: set[str] = set()
    pts: list[BoundaryPoint] = []
    for v, label in raw:
        key = _fmt(v)
        if key in seen:
            continue
        seen.add(key)
        pts.append(BoundaryPoint(value=key, label=label))
    return pts


def build_plan(params: list[dict], strength: str | None = None) -> dict:
    """对一组参数生成覆盖计划:每参数边界点 + 跨参数 pairwise 组合。

    返回:
      {
        params: [{name, unit, category, min, max, points:[{value,label}]}],
        skipped: [无 min/max 无法做 BVA 的参数名],
        strength, combination_count, combinations:[{param: value}]
      }
    """
    strength = (strength or _settings.combination_strength or "pairwise").lower()

    bva_params: list[dict] = []
    skipped: list[str] = []
    for p in params:
        pts = boundary_points(p)
        if not pts:
            skipped.append(p.get("name", ""))
            continue
        bva_params.append(
            {
                "name": p.get("name", ""),
                "unit": p.get("unit"),
                "category": classify(p),
                "min": p.get("min"),
                "max": p.get("max"),
                "points": [asdict(pt) for pt in pts],
            }
        )

    names = [p["name"] for p in bva_params]
    value_lists = [[pt["value"] for pt in p["points"]] for p in bva_params]

    combinations: list[dict] = []
    if len(names) == 0:
        pass
    elif len(names) == 1:
        # 单参数:就是该参数的全部边界点(纯 BVA)
        combinations = [{names[0]: v} for v in value_lists[0]]
    else:
        def _valid(row) -> bool:
            return all(v is not None for v in row)

        if strength == "full":
            from itertools import product

            for combo in product(*value_lists):
                if _valid(combo):
                    combinations.append(dict(zip(names, combo)))
        else:  # pairwise(默认)
            for row in AllPairs(value_lists, filter_func=_valid):
                combinations.append(dict(zip(names, list(row))))

    return {
        "params": bva_params,
        "skipped": skipped,
        "strength": strength,
        "combination_count": len(combinations),
        "combinations": combinations,
    }



def coverage_for_case(case, selected_titles: list[str], strength: str | None = None) -> list[dict]:
    """对所选章节,各自匹配参数并生成覆盖计划。

    返回 [{title, matched_count, plan}, ...]。
    """
    all_chapters = case.chapters or []
    selected = [ch for ch in all_chapters if ch.get("title") in selected_titles]
    csv_params = [p.raw for p in case.params] if case.params else []

    out: list[dict] = []
    for ch in selected:
        matched = match_params_for_chapters([ch], csv_params) if csv_params else []
        plan = build_plan(matched, strength)
        out.append(
            {"title": ch["title"], "matched_count": len(matched), "plan": plan}
        )
    return out
