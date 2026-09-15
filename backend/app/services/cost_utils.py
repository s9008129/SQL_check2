"""COST normalization (PRD §8.3 / §17.1 / §17.2).

The user provides the original Oracle COST value exactly once, either as a
plain integer string ("68420") or with thousands separators ("68,420").
Backend responsibility is limited to normalizing that text into a
non-negative integer; SQLCheck never queries a database for COST and never
asks the user to enter it a second time (PRD §17.2, §18.1).
"""

from __future__ import annotations

COST_FRIENDLY_ERROR = "COST 請輸入大於等於 0 的數字，可包含千分位逗號（例如 68,420）。"


def normalize_cost(raw: str | int | float) -> int:
    """Normalize a raw COST value to a non-negative integer.

    Raises:
        ValueError: with a Traditional-Chinese, user-facing message when the
            value is blank, non-numeric, negative, or a non-whole number.
    """
    if isinstance(raw, bool):  # bool is an int subclass; never a valid COST
        raise ValueError(COST_FRIENDLY_ERROR)

    if isinstance(raw, int):
        value = raw
    elif isinstance(raw, float):
        if not raw.is_integer():
            raise ValueError(COST_FRIENDLY_ERROR)
        value = int(raw)
    else:
        text = str(raw).replace(",", "").replace(" ", "").strip()
        if text == "":
            raise ValueError(COST_FRIENDLY_ERROR)
        try:
            value = int(text)
        except ValueError as exc:
            raise ValueError(COST_FRIENDLY_ERROR) from exc

    if value < 0:
        raise ValueError(COST_FRIENDLY_ERROR)
    return value
