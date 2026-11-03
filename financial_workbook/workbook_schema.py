"""Shared, variable-width XLSX review protocol. Indices below are zero based."""
from dataclasses import dataclass


def column_name(index: int) -> str:
    if index < 0:
        raise ValueError('Negative column index')
    result = ''
    while index >= 0:
        index, digit = divmod(index, 26)
        result = chr(65 + digit) + result
        index -= 1
    return result


@dataclass(frozen=True)
class TableLayout:
    count: int

    @property
    def originals(self): return tuple(range(2, 2 + self.count))
    @property
    def page(self): return 2 + self.count
    @property
    def metric(self): return 3 + self.count
    @property
    def identity(self): return 4 + self.count
    @property
    def overrides(self): return tuple(range(5 + self.count, 5 + 2 * self.count))
    @property
    def reason(self): return 5 + 2 * self.count


def table_layout(statement) -> TableLayout:
    if not 2 <= len(statement.columns) <= 8:
        raise ValueError('完整主表需要 2–8 个可验证的年度/比较栏。')
    return TableLayout(len(statement.columns))
