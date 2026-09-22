"""tests.test_repair_mapping — 成就名映射修复的对齐逻辑测试

背景见 cleaning/repair_mapping.py 模块 docstring：两源顺序不一致时按位 zip
会张冠李戴，修复靠 percent 量化对齐。这里测纯函数，不发网络请求。
"""

from __future__ import annotations

from cleaning.repair_mapping import (
    ALIGNED,
    AMBIGUOUS,
    INCOMPATIBLE,
    align_by_percent,
)
from cleaning.writers import write_achievement_pairs


def _valve(*pairs: tuple[str, float]) -> list[dict]:
    """构造全局接口数据：[(内部名, percent), ...]"""
    return [{"name": n, "percent": p} for n, p in pairs]


def _community(*pairs: tuple[str, float], desc: str | None = None) -> list[dict]:
    """构造社区页数据：[(展示名, percent), ...]"""
    return [
        {"display_name": n, "percent": p, "description": desc} for n, p in pairs
    ]


class TestAlignByPercent:
    def test_identical_order_keeps_pairing(self) -> None:
        """两源本来就同序 → ALIGNED，配对原样保留。"""
        valve = _valve(("ACH1", 10.0), ("ACH2", 50.0))
        community = _community(("击败boss", 10.0), ("通关", 50.0))
        pairs, status = align_by_percent(valve, community)
        assert status == ALIGNED
        assert [p["api_name"] for p in pairs] == ["ACH1", "ACH2"]
        assert [p["display_name"] for p in pairs] == ["击败boss", "通关"]

    def test_permutation_is_repaired(self) -> None:
        """两源乱序（多重集相同）→ 确定性重对齐到正确配对。"""
        valve = _valve(("ACH_A", 10.0), ("ACH_B", 50.0))
        community = _community(("通关", 50.0), ("击败boss", 10.0))  # 顺序颠倒
        pairs, status = align_by_percent(valve, community)
        assert status == ALIGNED
        by_name = {p["api_name"]: p["display_name"] for p in pairs}
        assert by_name == {"ACH_A": "击败boss", "ACH_B": "通关"}
        # percent 始终取 valve 侧
        assert [p["percent"] for p in pairs] == [10.0, 50.0]

    def test_duplicate_percents_are_ambiguous(self) -> None:
        """同分成就（两个 100.0）→ 组内配对不可证，标 AMBIGUOUS。"""
        valve = _valve(("ACH1", 100.0), ("ACH2", 100.0))
        community = _community(("成就乙", 100.0), ("成就甲", 100.0))
        pairs, status = align_by_percent(valve, community)
        assert status == AMBIGUOUS
        assert pairs is not None and len(pairs) == 2  # 仍给出尽力配对，但不可信

    def test_length_mismatch_incompatible(self) -> None:
        valve = _valve(("ACH1", 10.0))
        community = _community(("击败boss", 10.0), ("通关", 50.0))
        pairs, status = align_by_percent(valve, community)
        assert status == INCOMPATIBLE
        assert pairs is None

    def test_multiset_mismatch_incompatible(self) -> None:
        """percent 多重集对不上 → 不可自动修复。"""
        valve = _valve(("ACH1", 10.0), ("ACH2", 50.0))
        community = _community(("击败boss", 10.2), ("通关", 60.0))
        pairs, status = align_by_percent(valve, community)
        assert status == INCOMPATIBLE
        assert pairs is None

    def test_float_noise_is_tolerated(self) -> None:
        """浮点噪声（84.30000001 vs 84.3）量化后被吸收。"""
        valve = _valve(("ACH1", 84.30000001), ("ACH2", 15.7))
        community = _community(("击败boss", 84.3), ("通关", 15.7))
        pairs, status = align_by_percent(valve, community)
        assert status == ALIGNED
        assert pairs[0]["api_name"] == "ACH1"


class TestWriteAchievementPairs:
    def test_positions_are_renumbered_from_one(self) -> None:
        """先删后插，position 从 1 连续编号（不管传入顺序如何）。"""
        executed: list[tuple[str, list | dict]] = []

        class StubResult:
            def __init__(self, payload: list | dict) -> None:
                self._payload = payload

        class StubConn:
            def execute(self, sql, params=None):
                executed.append((str(sql), params))
                return StubResult(params or {})

        pairs = [
            {"api_name": "ACH_B", "display_name": "通关", "description": None,
             "percent": 50.0},
            {"api_name": "ACH_A", "display_name": "击败boss", "description": "d",
             "percent": 10.0},
        ]
        write_achievement_pairs(StubConn(), 367520, pairs)

        assert "DELETE FROM achievements" in executed[0][0]
        insert_params = executed[1][1]
        assert [p["position"] for p in insert_params] == [1, 2]
        assert all(p["appid"] == 367520 for p in insert_params)


class TestJudgeAndWrite:
    """judge_and_write 的分诊逻辑：容差内销账、可对齐修复、不可修复落台账。"""

    def _make_stub_conn(self) -> tuple:
        executed: list[tuple[str, Any]] = []

        class StubConn:
            def execute(self, sql, params=None):
                executed.append((str(sql), params))
                return self

        return StubConn(), executed

    def _valve(self, *pairs):
        return [{"name": n, "percent": p} for n, p in pairs]

    def _community(self, *pairs):
        return [{"display_name": n, "percent": p, "description": None}
                for n, p in pairs]

    def test_within_tolerance_resolves_without_touching_data(self) -> None:
        """逐位差 ≤0.5 → 原映射正确：销账、不重写 achievements。"""
        from cleaning.repair_mapping import judge_and_write

        conn, executed = self._make_stub_conn()
        valve = self._valve(("ACH1", 84.3), ("ACH2", 15.7))
        community = self._community(("击败boss", 84.4), ("通关", 15.7))  # 0.1 舍入差
        status = judge_and_write(conn, 300, valve, community, dry_run=False)
        assert status == "ok"
        assert any("mapping_issues" in sql and "resolved = true" in sql
                   for sql, _ in executed)
        assert not any("DELETE FROM achievements" in sql for sql, _ in executed)

    def test_beyond_tolerance_with_same_multiset_repairs(self) -> None:
        """真乱序（多重集相同）→ 重对齐回写并销账。"""
        from cleaning.repair_mapping import judge_and_write

        conn, executed = self._make_stub_conn()
        valve = self._valve(("ACH1", 5.0), ("ACH2", 90.0))
        community = self._community(("通关", 90.0), ("击败boss", 5.0))  # 位置差 85
        status = judge_and_write(conn, 300, valve, community, dry_run=False)
        assert status == "repaired"
        assert any("DELETE FROM achievements" in sql for sql, _ in executed)
        assert any("resolved = true" in sql for sql, _ in executed)

    def test_beyond_tolerance_multiset_mismatch_flags_issue(self) -> None:
        """容差外且多重集不匹配 → 保持原状，落台账 unresolved。"""
        from cleaning.repair_mapping import judge_and_write

        conn, executed = self._make_stub_conn()
        valve = self._valve(("ACH1", 10.0), ("ACH2", 50.0))
        community = self._community(("击败boss", 10.2), ("通关", 60.0))
        status = judge_and_write(conn, 300, valve, community, dry_run=False)
        assert status == "incompatible"
        upserts = [p for sql, p in executed
                   if "mapping_issues" in sql and "INSERT INTO" in sql]
        assert upserts and upserts[0]["appid"] == 300
        assert not any("DELETE FROM achievements" in sql for sql, _ in executed)
