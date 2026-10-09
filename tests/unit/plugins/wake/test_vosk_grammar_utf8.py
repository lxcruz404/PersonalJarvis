"""Every Vosk grammar must carry accented wake words as UTF-8, never escaped.

libvosk 0.3.44 parses a grammar with a JSON reader that copies a ``\\uXXXX``
escape as literal text (its ``\\u`` branch appends the six characters instead
of decoding them). ``json.dumps`` escapes every non-ASCII letter by default,
so the wake word "darío" reached the decoder as "dar\\u00edo", a word no
lexicon holds. Vosk dropped it with a hidden warning, the grammar kept only
"[unk]", and the live Spanish wake word never produced a single candidate.
"""

from __future__ import annotations

import json
import os
import sys
import unicodedata
from types import SimpleNamespace

import pytest

from jarvis.plugins.wake import vosk_kws_provider
from jarvis.plugins.wake.vosk_kws_provider import (
    VoskKwsProvider,
    vosk_model_supports_phrase,
)

_PHRASES = ("Darío", "Oye Darío", "Hola Begoña")
#: The same phrases as a macOS paste or some input methods deliver them:
#: decomposed accents, and a no-break space between the words.
_DECOMPOSED = unicodedata.normalize("NFD", "Darío")
_NO_BREAK = "Oye\u00a0Darío"


def _libvosk_words(grammar: str) -> list[str]:
    """Read a grammar the way libvosk does: ``\\uXXXX`` stays literal text."""
    return json.loads(grammar.replace("\\u", "\\\\u"))


@pytest.mark.parametrize("phrase", _PHRASES)
def test_the_grammar_recognizer_hears_the_accented_phrase(
    monkeypatch: pytest.MonkeyPatch, phrase: str
) -> None:
    grammars: list[str | None] = []

    def _build(_model: object, _rate: int, grammar: str | None = None) -> object:
        grammars.append(grammar)
        return object()

    monkeypatch.setattr(vosk_kws_provider, "build_recognizer", _build)
    provider = VoskKwsProvider(phrase, model_path="fake")
    monkeypatch.setattr(provider, "_ensure_model", lambda _path=None: object())

    provider._new_grammar_rec()

    assert grammars[0] is not None
    assert _libvosk_words(grammars[0]) == [phrase.lower(), "[unk]"]


@pytest.mark.parametrize(
    ("phrase", "expected"),
    (
        (_DECOMPOSED, "darío"),
        (_NO_BREAK, "oye darío"),
        ("  Darío  ", "darío"),
        ("¡Oye, Darío!", "oye darío"),
        ("Hey Jarvis.", "hey jarvis"),
        ("Don't stop", "don't stop"),
    ),
)
def test_the_grammar_spells_the_phrase_as_the_lexicon_does(
    monkeypatch: pytest.MonkeyPatch, phrase: str, expected: str
) -> None:
    grammars: list[str | None] = []

    def _build(_model: object, _rate: int, grammar: str | None = None) -> object:
        grammars.append(grammar)
        return object()

    monkeypatch.setattr(vosk_kws_provider, "build_recognizer", _build)
    provider = VoskKwsProvider(phrase, model_path="fake")
    monkeypatch.setattr(provider, "_ensure_model", lambda _path=None: object())

    provider._new_grammar_rec()

    assert grammars[0] is not None
    assert _libvosk_words(grammars[0]) == [expected, "[unk]"]


@pytest.mark.parametrize("phrase", ("Oye Darío", "Hey Begoña", _NO_BREAK))
def test_the_competition_grammar_keeps_the_accented_phrase(phrase: str) -> None:
    provider = VoskKwsProvider(phrase, model_path="fake")

    assert provider._competition_grammar is not None
    words = _libvosk_words(provider._competition_grammar)
    spoken = " ".join(phrase.lower().split())
    assert words[0] == spoken
    assert words[1] == f"{spoken.split()[0]} [unk]"


class _Lexicon:
    def __init__(self, words: set[str]) -> None:
        self.words = words


def _fake_vosk(lexicon: set[str]) -> SimpleNamespace:
    """A ``vosk`` module whose recognizer warns on stderr like libvosk does."""

    def _recognizer(model: _Lexicon, _rate: int, grammar: str) -> object:
        for entry in _libvosk_words(grammar):
            for word in entry.split():
                if word != "[unk]" and word not in model.words:
                    os.write(
                        2,
                        f"WARNING Ignoring word missing in vocabulary: '{word}'\n".encode(),
                    )
        return object()

    return SimpleNamespace(
        Model=lambda _path: _Lexicon(lexicon),
        KaldiRecognizer=_recognizer,
        SetLogLevel=lambda _level: None,
    )


@pytest.mark.parametrize("phrase", ("Darío", _DECOMPOSED, "Darío."))
def test_the_vocabulary_probe_finds_an_accented_word(
    monkeypatch: pytest.MonkeyPatch, phrase: str
) -> None:
    monkeypatch.setitem(sys.modules, "vosk", _fake_vosk({"darío"}))

    assert vosk_model_supports_phrase("fake", phrase) is True


def test_the_vocabulary_probe_still_reports_a_missing_word(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "vosk", _fake_vosk({"darío"}))

    assert vosk_model_supports_phrase("fake", "Begoña") is False
