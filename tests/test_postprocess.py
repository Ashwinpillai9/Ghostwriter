from ghostwriter.postprocess import clean

DEFAULTS: dict = {}


def test_voice_commands_become_punctuation():
    assert clean("run the tests comma then commit period", DEFAULTS) == (
        "Run the tests, then commit."
    )


def test_double_punctuation_is_collapsed():
    # Whisper often punctuates the spoken command itself, e.g. "...changes period."
    assert clean("commit the changes period.", DEFAULTS) == "Commit the changes."


def test_fillers_are_removed():
    assert clean("um so uh push the branch", DEFAULTS) == "So push the branch."


def test_new_line_command():
    assert clean("first item new line second item", DEFAULTS) == "First item\nsecond item."


def test_brackets_hug_their_contents():
    # No space before "(" — dictating code should yield call(x), not call (x).
    assert clean("call open paren x close paren", DEFAULTS) == "Call(x)."


def test_replacements_are_applied():
    settings = {"replacements": {"get hub": "GitHub"}}
    assert clean("push to get hub", settings) == "Push to GitHub."


def test_empty_input():
    assert clean("   ", DEFAULTS) == ""


def test_disabled_rules_pass_text_through():
    settings = {"remove_fillers": False, "voice_commands": False, "tidy_sentences": False}
    assert clean("um comma test", settings) == "um comma test"
