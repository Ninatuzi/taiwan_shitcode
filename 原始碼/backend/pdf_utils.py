import re
import pypdf
from collections import Counter

try:
    import os
    import shutil

    import fitz
    import pytesseract
    from PIL import Image

    # 跨平台定位 tesseract：
    # 1) 显式环境变量 TESSERACT_CMD 优先
    # 2) Linux/macOS：依赖 PATH（shutil.which）
    # 3) Windows：回退到默认安装路径
    _tess_env = os.environ.get("TESSERACT_CMD")
    _tess_win = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if _tess_env and os.path.exists(_tess_env):
        pytesseract.pytesseract.tesseract_cmd = _tess_env
    elif shutil.which("tesseract"):
        pass  # 在 PATH 中，pytesseract 默认即可找到
    elif os.path.exists(_tess_win):
        pytesseract.pytesseract.tesseract_cmd = _tess_win
    HAS_OCR = True
except ImportError:
    HAS_OCR = False


def _ocr_pdf_page(pdf_path: str, page_num: int, dpi: int = 200) -> str:
    if not HAS_OCR:
        return ""
    try:
        doc = fitz.open(pdf_path)
        page = doc[page_num]
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        doc.close()
        return pytesseract.image_to_string(img, lang="eng")
    except Exception:
        return ""


def clean_pdf_text(text: str) -> str:
    text = re.sub(r'(\w)-\n(\w)', r'\1\2', text)
    text = re.sub(r'(?m)^\s*[-–—]?\s*\d{1,4}\s*[-–—]?\s*$', '', text)
    text = re.sub(r'(?m)^Page\s+\d+(\s+of\s+\d+)?\s*$', '', text, flags=re.IGNORECASE)
    text = re.sub(r'(?m)^.{3,}[\.·]{4,}\s*\d+\s*$', '', text)
    text = re.sub(r'(?m)^[\s\-=_*#·•▪─━~]{4,}\s*$', '', text)
    text = re.sub(r'[ \t\u3000]+', ' ', text)
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if len(line) <= 2:
            lines.append('')
            continue
        alnum = sum(1 for c in line if c.isalnum())
        if len(line) > 5 and alnum / len(line) < 0.3:
            lines.append('')
            continue
        lines.append(line)
    text = '\n'.join(lines)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def truncate_at_sibling_chapter(text: str, current_title: str) -> str:
    m = re.match(r'^(\d+(?:\.\d+)*)', current_title.strip())
    if not m:
        return text
    current_num = m.group(1)
    current_parts = current_num.split('.')
    current_level = len(current_parts)
    lines = text.split('\n')
    start_search = 0
    for i, line in enumerate(lines[:5]):
        if re.match(r'^' + re.escape(current_num) + r'[\s\.:：]', line.strip()):
            start_search = i + 1
            break
    for i, line in enumerate(lines[start_search:], start=start_search):
        stripped = line.strip()
        m2 = re.match(r'^(\d+(?:\.\d+)*)[\s\.:：]', stripped)
        if not m2:
            continue
        found_num = m2.group(1)
        if found_num == current_num:
            continue
        found_parts = found_num.split('.')
        found_level = len(found_parts)
        if found_level <= current_level and found_parts[:current_level] != current_parts:
            return '\n'.join(lines[:i])
    return text


def remove_repeated_lines(pages: list, reference_pages: list | None = None) -> list:
    ref = reference_pages if reference_pages else pages
    if len(ref) < 3:
        return pages
    line_freq: Counter = Counter()
    for page_text in ref:
        for line in set(page_text.splitlines()):
            s = line.strip()
            if len(s) > 5:
                line_freq[s] += 1
    threshold = max(3, int(len(ref) * 0.35))
    repeated = {line for line, cnt in line_freq.items() if cnt >= threshold}
    if not repeated:
        return pages
    return [
        '\n'.join(l for l in pt.splitlines() if l.strip() not in repeated)
        for pt in pages
    ]


def flatten_outline(outline, reader, level: int = 1) -> list:
    result = []
    for item in outline:
        if isinstance(item, list):
            result.extend(flatten_outline(item, reader, level + 1))
        else:
            try:
                page_num = reader.get_destination_page_number(item) + 1
                result.append((level, str(item.title), page_num))
            except Exception:
                pass
    return result


def extract_chapters(path: str) -> list:
    reader = pypdf.PdfReader(path)
    total = len(reader.pages)
    outline = reader.outline
    if outline:
        flat = flatten_outline(outline, reader)
        chapters = []
        for i, (lvl, title, page_start) in enumerate(flat):
            page_end = total
            for lvl2, _, pg2 in flat[i + 1:]:
                if lvl2 <= lvl:
                    page_end = pg2 - 1
                    break
            chapters.append({
                "title": title.strip(),
                "page_start": page_start,
                "page_end": max(page_end, page_start),
                "level": lvl,
            })
        return chapters

    heading_pattern = re.compile(
        r'^(Chapter\s+\d+[\s:：]+\S.{0,60}'
        r'|\d+\.\d+\.\d+[\s　]+\S.{0,60}'
        r'|\d+\.\d+[\s　]+\S.{0,60}'
        r'|\d+\.[\s　]+\S.{0,60})',
        re.MULTILINE,
    )
    found = []
    for pg_idx in range(total):
        text = reader.pages[pg_idx].extract_text() or ""
        for m in heading_pattern.finditer(text):
            raw = m.group().strip()
            if not (3 < len(raw) < 80):
                continue
            num_part = raw.split()[0]
            dots = num_part.count(".")
            lvl = dots if dots > 0 else 1
            found.append((pg_idx + 1, raw, lvl))

    if found:
        seen, unique = set(), []
        for pg, t, lvl in found:
            key = (pg, t[:20])
            if key not in seen:
                seen.add(key)
                unique.append((pg, t, lvl))
        chapters = []
        for i, (page_start, title, lvl) in enumerate(unique):
            page_end = unique[i + 1][0] - 1 if i + 1 < len(unique) else total
            chapters.append({
                "title": title,
                "page_start": page_start,
                "page_end": max(page_end, page_start),
                "level": lvl,
            })
        return chapters

    return [{"title": "完整規格書", "page_start": 1, "page_end": total, "level": 1}]


def extract_pages_for_chapter(pdf_path: str, chapter: dict, all_pages: list[str]) -> list[str]:
    """Extract raw text pages for a chapter, with OCR fallback for image pages."""
    reader = pypdf.PdfReader(pdf_path)
    pages = []
    start = chapter["page_start"] - 1
    end = chapter["page_end"]
    for pg_idx in range(start, min(end, len(reader.pages))):
        text = reader.pages[pg_idx].extract_text() or ""
        if len(text.strip()) < 80 and HAS_OCR:
            text = _ocr_pdf_page(pdf_path, pg_idx)
        pages.append(text)
    return pages
