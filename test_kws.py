#!/usr/bin/env python3
"""
Tests for KWS-based Dota2 Invoker Voice Control.
Validates skill mapping, key sequences, debouncing, and casting logic
without requiring audio hardware or KWS model files.
"""

import sys
import time
from unittest.mock import MagicMock

from main import (
    KEYMAP,
    SKILLS,
    Debouncer,
    InvokerCaster,
    VoiceInvoker,
    format_key_sequence,
)


def test_skill_mapping():
    """Verify all 7 skills have correct element combos and key sequences."""
    expected = {
        "天火": ("CCC", "c c c v d"),
        "陨石": ("CCX", "c c x v d"),
        "吹风": ("ZXX", "z x x v d"),
        "磁暴": ("XXX", "x x x v d"),
        "隐身": ("ZZX", "z z x v d"),
        "冰墙": ("ZZC", "z z c v d"),
        "推波": ("ZXC", "z x c v d"),
    }
    assert len(SKILLS) == 7, f"Expected 7 skills, got {len(SKILLS)}"
    for name, (combo, seq) in expected.items():
        skill = SKILLS[name]
        assert skill.keys == combo, f"{name}: expected keys={combo}, got {skill.keys}"
        assert format_key_sequence(skill) == seq, f"{name}: wrong key sequence"
    print("[PASS] test_skill_mapping")


def test_keymap():
    """Verify QWER→ZXCV mapping."""
    assert KEYMAP == {"Z": "z", "X": "x", "C": "c", "V": "v", "D": "d"}
    print("[PASS] test_keymap")


def test_debouncer_allows_first():
    """First trigger should always pass."""
    d = Debouncer(window_ms=350)
    assert d.should_trigger("天火") is True
    print("[PASS] test_debouncer_allows_first")


def test_debouncer_blocks_rapid():
    """Same keyword within 350ms should be blocked."""
    d = Debouncer(window_ms=350)
    assert d.should_trigger("天火") is True
    assert d.should_trigger("天火") is False  # immediate retry blocked
    print("[PASS] test_debouncer_blocks_rapid")


def test_debouncer_allows_after_window():
    """Same keyword after window expires should pass."""
    d = Debouncer(window_ms=50)  # short window for test speed
    assert d.should_trigger("陨石") is True
    time.sleep(0.06)
    assert d.should_trigger("陨石") is True
    print("[PASS] test_debouncer_allows_after_window")


def test_debouncer_independent_keywords():
    """Different keywords should not block each other."""
    d = Debouncer(window_ms=350)
    assert d.should_trigger("天火") is True
    assert d.should_trigger("陨石") is True  # different keyword, not blocked
    assert d.should_trigger("天火") is False  # same keyword, blocked
    print("[PASS] test_debouncer_independent_keywords")


def test_caster_key_sequence():
    """Verify InvokerCaster sends correct key sequence via mock keyboard."""
    mock_kbd = MagicMock()
    caster = InvokerCaster(keyboard=mock_kbd)

    for name, skill in SKILLS.items():
        mock_kbd.reset_mock()
        keys = caster.cast_skill(skill)

        # keys should be: element0 element1 element2 v d
        expected_keys = [KEYMAP[k] for k in skill.keys] + ["v", "d"]
        assert keys == expected_keys, f"{name}: expected {expected_keys}, got {keys}"

        # Verify press/release called for each key
        assert mock_kbd.press.call_count == len(expected_keys)
        assert mock_kbd.release.call_count == len(expected_keys)

    print("[PASS] test_caster_key_sequence")


def test_on_keyword_integration():
    """Test full _on_keyword path with mock caster."""
    mock_kbd = MagicMock()
    caster = InvokerCaster(keyboard=mock_kbd)
    app = VoiceInvoker(kws=MagicMock(), caster=caster)

    # Trigger each skill
    for name in SKILLS:
        mock_kbd.reset_mock()
        app._on_keyword(name)
        assert mock_kbd.press.call_count == 5, f"{name}: expected 5 key presses"

    print("[PASS] test_on_keyword_integration")


def test_on_keyword_debounce():
    """Verify debounce works in the integrated path."""
    mock_kbd = MagicMock()
    caster = InvokerCaster(keyboard=mock_kbd)
    app = VoiceInvoker(kws=MagicMock(), caster=caster)

    # Increase debounce window for test to account for casting delays (~600-800ms)
    app.debouncer = Debouncer(window_ms=2000)

    app._on_keyword("天火")
    first_count = mock_kbd.press.call_count
    assert first_count == 5

    # Immediate retry should be debounced — no additional presses
    app._on_keyword("天火")
    assert mock_kbd.press.call_count == first_count  # unchanged

    print("[PASS] test_on_keyword_debounce")


def test_no_asr_imports():
    """Verify old ASR dependencies are not imported in the active pipeline."""
    import main
    # requests should not be imported
    assert not hasattr(main, "requests"), "requests module should not be imported (ASR removed)"
    # SenseVoiceClient should not exist as active class
    assert not hasattr(main, "SenseVoiceClient"), "SenseVoiceClient should not exist"
    assert not hasattr(main, "SkillMatcher"), "SkillMatcher should not exist"
    print("[PASS] test_no_asr_imports")


def test_deprecated_classes_raise():
    """Verify deprecated classes raise NotImplementedError."""
    from main import _DeprecatedSenseVoiceClient, _DeprecatedSkillMatcher

    try:
        _DeprecatedSenseVoiceClient()
        assert False, "Should have raised"
    except NotImplementedError:
        pass

    try:
        _DeprecatedSkillMatcher()
        assert False, "Should have raised"
    except NotImplementedError:
        pass

    print("[PASS] test_deprecated_classes_raise")


if __name__ == "__main__":
    tests = [
        test_skill_mapping,
        test_keymap,
        test_debouncer_allows_first,
        test_debouncer_blocks_rapid,
        test_debouncer_allows_after_window,
        test_debouncer_independent_keywords,
        test_caster_key_sequence,
        test_on_keyword_integration,
        test_on_keyword_debounce,
        test_no_asr_imports,
        test_deprecated_classes_raise,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"[FAIL] {t.__name__}: {e}")
            failed += 1

    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")
    if failed == 0:
        print("All tests passed!")
    else:
        sys.exit(1)
