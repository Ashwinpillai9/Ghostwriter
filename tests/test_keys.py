"""Key codes and the Win32 input ABI.

The struct-size tests look pedantic but guard a bug that unit tests otherwise cannot reach: an
undersized INPUT union made every SendInput call fail with ERROR_INVALID_PARAMETER, which is
silent — paste simply did nothing, and nothing raised.
"""

import ctypes
import struct

import pytest

from ghostwriter import keys
from ghostwriter.keys import codes


# --- Win32 ABI ---------------------------------------------------------------


@pytest.mark.skipif(struct.calcsize("P") != 8, reason="sizes below are the x64 ABI")
def test_input_structs_match_the_win32_abi():
    from ghostwriter.keys import windows as win

    # SendInput validates cbSize against its own sizeof(INPUT) and rejects anything else.
    assert ctypes.sizeof(win.KEYBDINPUT) == 24
    assert ctypes.sizeof(win.MOUSEINPUT) == 32
    assert ctypes.sizeof(win.INPUT) == 40


def test_input_union_is_sized_by_its_largest_arm():
    from ghostwriter.keys import windows as win

    # KEYBDINPUT is the only arm used, but MOUSEINPUT is what sets the union's size.
    assert ctypes.sizeof(win._INPUTUNION) == ctypes.sizeof(win.MOUSEINPUT)
    assert ctypes.sizeof(win.MOUSEINPUT) > ctypes.sizeof(win.KEYBDINPUT)


def test_extended_keys_include_the_sided_right_modifiers():
    from ghostwriter.keys import windows as win

    # Sent without the extended flag, these arrive as their left-hand or numpad twin.
    assert codes.VK_RCONTROL in win._EXTENDED
    assert codes.VK_RMENU in win._EXTENDED
    assert codes.VK_LCONTROL not in win._EXTENDED


def test_utf16_units_handles_astral_characters():
    from ghostwriter.keys import windows as win

    assert win._utf16_units("a") == [ord("a")]
    assert len(win._utf16_units("\U0001f600")) == 2, "astral chars need a surrogate pair"


# --- key codes ---------------------------------------------------------------


def test_names_are_case_and_space_insensitive():
    assert keys.vk("Right Ctrl") == keys.vk("right ctrl") == keys.vk("RIGHT   CTRL")


def test_letters_and_digits_and_function_keys():
    assert keys.vk("a") == ord("A")
    assert keys.vk("7") == ord("7")
    assert keys.vk("f1") == 0x70
    assert keys.vk("f24") == 0x87


def test_altgr_is_right_alt():
    assert keys.vk("alt gr") == keys.vk("right alt") == codes.VK_RMENU


def test_generic_modifier_matches_both_sides():
    for side in ("left shift", "right shift"):
        assert keys.matches(keys.vk(side), "shift")
    assert not keys.matches(keys.vk("left shift"), "right shift")


def test_non_modifier_matching_is_exact():
    assert keys.matches(keys.vk("d"), "d")
    assert not keys.matches(keys.vk("d"), "f")


def test_covered_modifiers_of_a_plain_chord():
    assert codes.covered_modifiers("ctrl+shift+d") == {"ctrl", "shift"}
    assert codes.covered_modifiers("d") == set()


def test_chord_parts_ignores_stray_separators():
    assert codes.chord_parts("ctrl++d") == ("ctrl", "d")
    assert codes.chord_parts("  ctrl + d  ") == ("ctrl", "d")


def test_trigger_of_an_empty_chord_raises():
    with pytest.raises(codes.UnknownKey):
        codes.trigger("")


def test_is_pressed_is_false_for_an_unknown_name():
    # Called from exclusively_pressed on every keystroke; a raise there would kill the hook.
    assert keys.is_pressed("not a real key") is False
