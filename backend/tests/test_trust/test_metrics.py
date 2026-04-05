"""Unit tests for backend/eval/metrics.py"""
import pytest
from backend.eval.metrics import exact_match, token_f1, rouge_l


class TestExactMatch:
    def test_identical(self):
        assert exact_match("hello world", "hello world") == 1.0

    def test_case_insensitive(self):
        assert exact_match("Hello World", "hello world") == 1.0

    def test_different(self):
        assert exact_match("foo", "bar") == 0.0

    def test_whitespace_trimmed(self):
        assert exact_match("  hello  ", "hello") == 1.0


class TestTokenF1:
    def test_identical(self):
        assert token_f1("the cat sat", "the cat sat") == 1.0

    def test_partial_overlap(self):
        score = token_f1("the cat sat on mat", "the cat sat on the mat")
        assert 0.8 < score < 1.0

    def test_no_overlap(self):
        assert token_f1("foo bar", "baz qux") == 0.0

    def test_empty_predicted(self):
        assert token_f1("", "expected output") == 0.0

    def test_empty_expected(self):
        assert token_f1("predicted output", "") == 0.0


class TestRougeL:
    def test_identical(self):
        assert rouge_l("the cat sat on the mat", "the cat sat on the mat") == 1.0

    def test_partial(self):
        score = rouge_l("the cat sat", "the cat sat on the mat")
        assert 0.0 < score < 1.0

    def test_no_overlap(self):
        assert rouge_l("foo bar", "baz qux") == 0.0
