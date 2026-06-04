import csv
import io
import re


_BMS_ABBREV: dict[str, list[str]] = {
    "CUV":   ["undervoltage", "under voltage", "under-voltage"],
    "COV":   ["overvoltage",  "over voltage",  "over-voltage"],
    "SUV":   ["undervoltage", "stack", "pack voltage"],
    "SOV":   ["overvoltage",  "stack", "pack voltage"],
    "OCC":   ["overcurrent",  "over current",  "charge current"],
    "OCD":   ["overcurrent",  "over current",  "discharge current"],
    "SCC":   ["short circuit", "shortcircuit", "charge"],
    "SCD":   ["short circuit", "shortcircuit", "discharge"],
    "OTC":   ["over temp", "overtemperature", "over temperature", "charge"],
    "OTD":   ["over temp", "overtemperature", "over temperature", "discharge"],
    "UTC":   ["under temp", "undertemperature", "under temperature", "charge"],
    "UTD":   ["under temp", "undertemperature", "under temperature", "discharge"],
    "OTF":   ["fet", "over temp", "overtemperature"],
    "PCHGC": ["precharge", "pre-charge", "pre charge"],
    "CHGV":  ["charge voltage", "charging voltage"],
    "CHGC":  ["charge current", "charging current"],
    "AOLD":  ["overload", "over load"],
    "HWDF":  ["hardware", "discharge fet"],
    "UVAC":  ["undervoltage", "adapter"],
    "OC":    ["overcurrent", "over current"],
}

_MATCH_STOPWORDS = {
    "the", "and", "for", "with", "this", "that", "from", "into",
    "check", "initial", "condition", "function", "mode", "status",
    "table", "list", "register", "bit", "byte", "value",
    "enable", "disable", "set", "get", "read", "write",
}

_EXCLUDE_CATEGORIES: list[tuple[str, str | None]] = [
    ("calibration",   None),
    ("settings",      "afe"),
    ("pf status",     "afe regs"),
    ("system data",   None),
    ("settings",      "sbs configuration"),
    ("gas gauging",   "ra table"),
    ("ra table",      None),
    ("ti cellra data", None),
    ("gas gauging",   "ti cellra data"),
    ("dcir",          None),
    ("gas gauging",   "dcir"),
    ("settings",      "dcir"),
]


def _is_excluded(param: dict) -> bool:
    cls = param.get("class", "").lower().strip()
    sub = param.get("subclass", "").lower().strip()
    for exc_cls, exc_sub in _EXCLUDE_CATEGORIES:
        if cls == exc_cls:
            if exc_sub is None or sub == exc_sub:
                return True
    return False


def parse_csv(path: str) -> tuple:
    with open(path, newline="", encoding="utf-8-sig") as f:
        raw_text = f.read()

    data_lines = [
        ln for ln in raw_text.splitlines()
        if ln.strip() and not ln.strip().startswith("*")
    ]
    if not data_lines:
        return [], "無有效資料行"

    try:
        first_cols = list(csv.reader([data_lines[0]]))[0]
    except Exception:
        first_cols = []

    is_ti = (
        len(first_cols) >= 14
        and not any(k in first_cols[0].lower() for k in ["name", "param", "class", "header", "field"])
        and not any(k in first_cols[2].lower() for k in ["name", "param", "parameter"])
    )

    params = []

    if is_ti:
        reader = csv.reader(io.StringIO("\n".join(data_lines)))
        for row in reader:
            if len(row) < 4:
                continue
            name  = row[2].strip()
            value = row[3].strip()
            if not name or not value:
                continue
            unit    = row[4].strip()  if len(row) > 4  else ""
            default = row[8].strip()  if len(row) > 8  else ""
            min_v   = row[9].strip()  if len(row) > 9  else ""
            max_v   = row[10].strip() if len(row) > 10 else ""
            flags   = row[14].strip() if len(row) > 14 else ""
            params.append({
                "name":     name,
                "value":    value,
                "unit":     "" if unit == "-" else unit,
                "default":  default,
                "min":      min_v,
                "max":      max_v,
                "class":    row[0].strip(),
                "subclass": row[1].strip(),
                "flags":    flags,
            })
        diag = f"TI Data Flash 格式  共 {len(params)} 筆"
    else:
        try:
            dialect = csv.Sniffer().sniff("\n".join(data_lines[:8]), delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        delim_char = getattr(dialect, "delimiter", ",")

        reader   = csv.DictReader(io.StringIO("\n".join(data_lines)), dialect=dialect)
        raw_rows = list(reader)
        if not raw_rows:
            return [], f"分隔符：{repr(delim_char)}  過濾後無資料列"

        headers = list(raw_rows[0].keys())
        norm    = {h: h.lower().replace(" ", "_") for h in headers}

        def _find(keys):
            for h, n in norm.items():
                if any(k in n for k in keys):
                    return h
            return None

        name_col  = _find(["name", "param", "parameter"]) or headers[0]
        value_col = _find(["value", "val", "setting"])    or (headers[1] if len(headers) > 1 else None)
        unit_col  = _find(["unit"])
        min_col   = _find(["min"])
        max_col   = _find(["max"])
        desc_col  = _find(["desc", "description", "remark", "note"])

        for row in raw_rows:
            name  = str(row.get(name_col,  "")).strip()
            value = str(row.get(value_col, "")).strip() if value_col else ""
            if not name or not value:
                continue
            entry = {"name": name, "value": value, "class": "", "subclass": "", "flags": ""}
            for col, key in [(unit_col, "unit"), (min_col, "min"), (max_col, "max"), (desc_col, "desc")]:
                if col:
                    entry[key] = str(row.get(col, "")).strip()
            params.append(entry)
        diag = f"一般 CSV  分隔符：{repr(delim_char)}  共 {len(params)} 筆"

    return params, diag


def match_params_for_chapters(chapters: list, all_params: list) -> list:
    if not all_params:
        return []

    keywords: set[str] = set()
    for ch in chapters:
        title = ch["title"]
        title_lower = title.lower()
        for abbrev, synonyms in _BMS_ABBREV.items():
            pattern = r'\b' + re.escape(abbrev) + r'\b'
            if re.search(pattern, title, re.IGNORECASE):
                keywords.update(synonyms)
                keywords.add(abbrev.lower())
            for syn in synonyms:
                if syn in title_lower:
                    keywords.add(abbrev.lower())
                    keywords.update(synonyms)
        words = re.findall(r'[a-zA-Z]{3,}', title_lower)
        for w in words:
            if w not in _MATCH_STOPWORDS:
                keywords.add(w)

    if not keywords:
        return []

    matched = []
    for p in all_params:
        if _is_excluded(p):
            continue
        searchable = " ".join([
            p.get("name", ""),
            p.get("subclass", ""),
            p.get("flags", ""),
            p.get("desc", ""),
        ]).lower()
        if any(kw in searchable for kw in keywords):
            matched.append(p)

    return matched
