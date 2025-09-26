from __future__ import annotations
import re

__all__ = ["normalize_number"]

def normalize_number(text: str) -> float:
    """
    Приводит строку-число к float, поддерживая и запятую, и точку, и любые пробелы/неразрывные пробелы:
    '2.123' → 2.123, '2,123' → 2.123, '1 234,56' → 1234.56,
    '1 234,56' → 1234.56, '1,234.56' → 1234.56, '1.234,56' → 1234.56
    """
    if text is None:
        raise ValueError("normalize_number: empty input")

    t = str(text).strip()
    # убрать все виды юникод-пробелов (включая NBSP/THIN/NNBSP и т.д.)
    t = re.sub(r"\s+", "", t)

    # Если есть и ',' и '.', определяем десятичный разделитель по последнему из них
    if "," in t and "." in t:
        if t.rfind(",") > t.rfind("."):
            # формат: 1.234,56  →  1234.56
            t = t.replace(".", "").replace(",", ".")
        else:
            # формат: 1,234.56  →  1234.56
            t = t.replace(",", "")
    else:
        # Только один разделитель: меняем запятую на точку
        t = t.replace(",", ".")

    # Разрешаем только цифры, точку и минус
    t = re.sub(r"[^0-9.\-]", "", t)

    if t in {"", "-", ".", "-.", ".-"}:
        raise ValueError(f"normalize_number: bad numeric string: {text!r}")

    return float(t)
