# -*- coding: utf-8 -*-
"""Phase 3 Step 1 纯逻辑单测：Numerical 确定性检查 + 契约加权判定。

零 LLM、零 DB、零网络。
"""
from __future__ import annotations

from app.tools.grounding import check_numerical_consistency, check_report_grounding
from app.agents.reflection_agent import _contract_verdict


def test_numerical_all_matched():
    report = '门店A销售额为 1,234,567.89 元，订单数 432 单。客单价 2857.80 元。'
    ds = [{'id': 1, 'raw_data': [{'store_name': 'A', 'sales': 1234567.89, 'orders': 432, 'unit_price': 2857.80}]}]
    r = check_numerical_consistency(report, ds)
    assert r.score >= 99
    assert r.total_report_numbers == 3
    assert r.matched_numbers == 3
    assert r.unmatched == []


def test_numerical_partial_fabricated():
    report = '门店A销售额为 1,234,567.89 元，神秘指标 999.99 元（编造）。'
    ds = [{'id': 1, 'raw_data': [{'store_name': 'A', 'sales': 1234567.89, 'orders': 432}]}]
    r = check_numerical_consistency(report, ds)
    assert r.total_report_numbers == 2
    assert r.matched_numbers == 1
    assert r.score == 50
    assert any('999.99' in u['original'].strip() for u in r.unmatched)


def test_numerical_cn_units_and_percent():
    report = '市场份额 12.5%，新增会员 88 万。'
    ds = [{'id': 1, 'raw_data': [{'share': 0.125, 'new_members': 880_000}]}]
    r = check_numerical_consistency(report, ds)
    assert r.score == 100
    assert r.unmatched == []


def test_numerical_empty_report_returns_100():
    r = check_numerical_consistency('', None)
    assert r.score == 100
    assert r.coverage == 1.0


def test_numerical_zero_match():
    r = check_numerical_consistency('本月销售额 5,000,000 元', [{'id': 1, 'raw_data': []}])
    assert r.score == 0
    assert r.total_report_numbers == 1
    assert len(r.unmatched) == 1


def test_contract_high_sev_veto_numerical():
    """加权综合 > 70 但 Numerical=40(<50) → 一票否决 → 不通过。"""
    passed, w, th = _contract_verdict(40, 80, 80, 80)
    # 40*0.30 + 80*0.35 + 80*0.15 + 80*0.20 = 12 + 28 + 12 + 16 = 68
    assert abs(w - 68.0) < 1e-6
    assert passed is False
    assert th['numerical_high_sev_breach'] is True
    assert th['grounding_high_sev_breach'] is False


def test_contract_high_sev_veto_grounding():
    """加权够但 Grounding=40(<50) → 一票否决。"""
    passed, w, th = _contract_verdict(80, 40, 100, 100)
    # 80*0.30 + 40*0.35 + 100*0.15 + 100*0.20 = 24 + 14 + 15 + 20 = 73
    assert abs(w - 73.0) < 1e-6
    assert passed is False
    assert th['grounding_high_sev_breach'] is True
    assert th['numerical_high_sev_breach'] is False


def test_contract_normal_pass():
    passed, w, _th = _contract_verdict(85, 85, 85, 85)
    # 85 * 1.0 = 85
    assert abs(w - 85.0) < 1e-6
    assert passed is True


def test_contract_edge_barely_pass():
    """加权 exactly 70.0 且无 high-sev → 通过。"""
    # 70 = 70*0.3 + 70*0.35 + 70*0.15 + 70*0.20
    passed, w, th = _contract_verdict(70, 70, 70, 70)
    assert abs(w - 70.0) < 1e-6
    assert passed is True
    assert th['numerical_high_sev_breach'] is False
    assert th['grounding_high_sev_breach'] is False


def test_contract_edge_barely_fail():
    """加权 69 → 失败。"""
    passed, w, _th = _contract_verdict(69, 69, 69, 69)
    assert abs(w - 69.0) < 1e-6
    assert passed is False


def test_hallucination_pressure_dual_low():
    """幻觉样本（报告编造多值 + 基准只有门店数）。
    Numerical + Grounding 双低分 → 契约肯定 fail（双重保障）。
    """
    halluc_report = (
        '本月销售额增长至 99,999,999.99 元，会员新注册 88,888 人，'
        '市场份额飙升至 77.77%，复购率 99.99%，全行业第一。'
        '实际门店数 100 家。'
    )
    ds_real = [{'id': 1, 'raw_data': [{'stores': 100}]}]
    nr = check_numerical_consistency(halluc_report, ds_real)
    gr = check_report_grounding(halluc_report, ds_real)
    # 只有 100 命中，报告总数字远大于 1 → 双低分
    assert nr.score < 40, f'numerical 期望 <40，实际 {nr.score}'
    gr_score = int(round(gr.evidence_coverage * 100))
    assert gr_score <= 50, f'grounding coverage 期望 <=50%（幻觉边界），实际 {gr.evidence_coverage:.0%}'
    # Reasoning / Alignment 用 85 代替（LLM 不调用，假设它们全对齐）
    passed, w, th = _contract_verdict(nr.score, gr_score, 85, 85)
    assert passed is False
    assert th['numerical_high_sev_breach'] or th['grounding_high_sev_breach']
