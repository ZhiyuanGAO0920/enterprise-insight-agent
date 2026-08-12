"""T-03 PII 脱敏工具测试 —— masker.py 纯函数单测。

验证口径：
- 标准 11 位手机号 → 前 3 后 4 保留、中间 4 位掩码
- 带分隔符变体（138 1234 5678 / 138-1234-5678）同样脱敏
- 数字边界：非手机号 11 位数字串不误伤
- sql_runner 结果表格场景：phone 列脱敏
"""

import pytest

from app.services.masker import mask_phone, mask_pii


class TestMaskPhone:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("13812345678", "138****5678"),
            ("18600001234", "186****1234"),
            ("13912345678", "139****5678"),
        ],
    )
    def test_standard_11_digit(self, raw, expected):
        assert mask_phone(raw) == expected

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("138-1234-5678", "138****5678"),
            ("138 1234 5678", "138****5678"),
        ],
    )
    def test_separator_variants(self, raw, expected):
        assert mask_phone(raw) == expected

    def test_in_text(self):
        assert mask_phone("联系电话 13812345678 请查收") == "联系电话 138****5678 请查收"

    @pytest.mark.parametrize(
        "raw",
        [
            "12345678901",      # 不以 1[3-9] 开头
            "11234567890",      # 第二位是 1
            "138123456789",     # 12 位
            "1381234567",       # 10 位
            "23812345678",      # 前导非 1
        ],
    )
    def test_not_a_phone(self, raw):
        assert mask_phone(raw) == raw

    def test_long_number_inside_no_match(self):
        # 13 位数字串（如订单号）中间夹手机号形态也不应误伤整体
        assert mask_phone("1001381234567800") == "1001381234567800"

    def test_empty_and_none(self):
        assert mask_phone("") == ""
        assert mask_phone(None) is None

    def test_non_string(self):
        assert mask_phone(13812345678) == 13812345678  # 数字类型原样返回


class TestMaskPii:
    def test_sql_result_table_pipe_format(self):
        # run_sql 返回的管道分隔表格：phone 列脱敏
        table = (
            "supplier_name | phone | status\n"
            "-------------------------------\n"
            "供应商-生鲜-01 | 13812345678 | active\n"
            "供应商-日用品-02 | 13900001111 | active"
        )
        masked = mask_pii(table)
        assert "138****5678" in masked
        assert "139****1111" in masked
        assert "13812345678" not in masked

    def test_query_params_audit_scene(self):
        # 审计日志场景：URL query string 携带手机号
        qs = "phone=13812345678&page=1"
        assert mask_pii(qs) == "phone=138****5678&page=1"

    def test_plain_text_unchanged(self):
        assert mask_pii("销售总额 128,000 元，环比 +12%") == "销售总额 128,000 元，环比 +12%"

    def test_decimal_amount_unchanged(self):
        # 金额列 128.50 不受影响
        assert mask_pii("amount | 128.50") == "amount | 128.50"
