import pytest

from jtalm.data.human_eval import is_negated_request, parse_request


def look(direction: str, amount: str = "normal") -> dict:
    return {"name": "look", "arguments": {"direction": direction, "amount": amount}}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("右を向いてください。", [look("right")]),
        ("ほら、こっちを見て", [look("center")]),
        ("少し左を向いて", [look("left", "slight")]),
        ("顔を上げて", [look("up")]),
        ("2回うなずいて", [{"name": "nod", "arguments": {"count": 2}}]),
        (
            "こっち向いて笑って",
            [look("center"), {"name": "set_expression", "arguments": {"expression": "happy"}}],
        ),
    ],
)
def test_whole_sentence_requests_are_labelled(text: str, expected: list) -> None:
    assert parse_request(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "彼は笑って答えた",
        "笑顔で迎えてくれました。",
        "笑ってる",
        "前を見てろ",
        "上を向け、上を向くんだよ",
    ],
)
def test_other_sentences_are_not_requests(text: str) -> None:
    assert parse_request(text) is None


def test_negated_requests() -> None:
    assert is_negated_request("こっち見ないで")
    assert is_negated_request("笑わないでよ")
    assert not is_negated_request("見ないで済むように準備した")


def test_transcript_markup_is_removed() -> None:
    from jtalm.data.human_eval import clean_transcript

    assert clean_transcript("(F えっと)(R うん)それ取って。(P)<H>") == "えっとうんそれ取って。"
