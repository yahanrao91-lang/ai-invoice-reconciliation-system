"""商品别名映射：支持人工维护，用于商品编号缺失时的辅助匹配。"""
from __future__ import annotations

from dataclasses import dataclass, field

from .standardize import normalize_item_no, normalize_name


@dataclass
class AliasRegistry:
    """别名注册表：canonical 为规范键（优先商品编号），aliases 为其别名集合。"""

    canonical_to_aliases: dict[str, set[str]] = field(default_factory=dict)
    alias_to_canonical: dict[str, str] = field(default_factory=dict)

    def add_alias(self, canonical: str, alias: str) -> None:
        c = normalize_item_no(canonical) or canonical
        a = normalize_name(alias)
        if not c or not a:
            return
        self.canonical_to_aliases.setdefault(c, set()).add(a)
        self.alias_to_canonical.setdefault(a, c)

    def resolve(self, key: str | None) -> str | None:
        """返回别名对应的规范键；无映射返回规范化后的原始值。"""
        if not key:
            return None
        k = normalize_name(key)
        if not k:
            return None
        return self.alias_to_canonical.get(k, k)

    def keys_for(self, canonical: str | None) -> set[str]:
        """返回某规范键的所有等价键（含别名），用于匹配。"""
        if not canonical:
            return set()
        c = self.resolve(canonical)
        out = {c}
        out |= self.canonical_to_aliases.get(c, set())
        return out

    def to_rows(self) -> list[tuple[str, str]]:
        rows = []
        for c, aliases in self.canonical_to_aliases.items():
            for a in aliases:
                rows.append((c, a))
        return rows

    @classmethod
    def from_rows(cls, rows: list[tuple[str, str]]) -> "AliasRegistry":
        reg = cls()
        for c, a in rows:
            reg.add_alias(c, a)
        return reg
