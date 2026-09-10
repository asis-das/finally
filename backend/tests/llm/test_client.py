"""The LiteLLM call wrapper: kwargs, parsing, retry, and the error taxonomy.

Every test patches ``app.llm.client.completion`` — nothing here touches a network.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.llm import client
from app.llm.schemas import ChatResponse

VALID_PAYLOAD = {"message": "Hello.", "trades": [], "watchlist_changes": []}


def fake_completion_response(content: str):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


class RecordingCompletion:
    """Returns queued contents in order, recording the kwargs of each call."""

    def __init__(self, *contents: str) -> None:
        self.contents = list(contents)
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return fake_completion_response(self.contents.pop(0))


class TestParseResponse:
    def test_plain_json(self):
        reply = client.parse_response(json.dumps(VALID_PAYLOAD))
        assert reply.message == "Hello."
        assert reply.trades == []

    def test_json_fence(self):
        reply = client.parse_response(f"```json\n{json.dumps(VALID_PAYLOAD)}\n```")
        assert reply.message == "Hello."

    def test_prose_around_the_object(self):
        raw = f"Sure! {json.dumps(VALID_PAYLOAD)} Hope that helps."
        assert client.parse_response(raw).message == "Hello."

    def test_populated_actions_round_trip(self):
        raw = json.dumps(
            {
                "message": "Done.",
                "trades": [{"ticker": "AAPL", "side": "buy", "quantity": 10}],
                "watchlist_changes": [{"ticker": "PYPL", "action": "add"}],
            }
        )
        reply = client.parse_response(raw)
        assert reply.trades[0].ticker == "AAPL"
        assert reply.trades[0].quantity == 10.0
        assert reply.watchlist_changes[0].action == "add"

    def test_missing_optional_fields_default_to_empty(self):
        reply = client.parse_response('{"message": "Hi."}')
        assert reply.trades == []
        assert reply.watchlist_changes == []

    @pytest.mark.parametrize(
        "raw",
        [
            None,
            "",
            "   ",
            "not json at all",
            "[1, 2, 3]",
            '{"trades": []}',  # no message
            '{"message": "hi", "trades": [{"ticker": "AAPL", "side": "hold", "quantity": 1}]}',
        ],
    )
    def test_malformed_input(self, raw):
        with pytest.raises(client.MalformedResponseError):
            client.parse_response(raw)


class TestCompletionKwargs:
    def test_defaults(self, monkeypatch, live_env):
        recorder = RecordingCompletion(json.dumps(VALID_PAYLOAD))
        monkeypatch.setattr(client, "completion", recorder)

        client.complete([{"role": "user", "content": "hi"}])

        kwargs = recorder.calls[0]
        assert kwargs["model"] == "openrouter/vendor/test-model:free"
        assert kwargs["response_format"] is ChatResponse
        assert kwargs["api_key"] == "test-key"
        assert kwargs["timeout"] == 30.0
        assert kwargs["reasoning_effort"] == "low"
        # Models that reject reasoning_effort or response_format must not error.
        assert kwargs["drop_params"] is True
        # Empty provider order -> no provider block, so any provider may serve it.
        assert "extra_body" not in kwargs

    def test_provider_order_is_sent_when_configured(self, monkeypatch, live_env):
        monkeypatch.setenv("OPENROUTER_PROVIDER_ORDER", "cerebras")
        monkeypatch.setenv("OPENROUTER_TIMEOUT", "5")
        recorder = RecordingCompletion(json.dumps(VALID_PAYLOAD))
        monkeypatch.setattr(client, "completion", recorder)

        client.complete([{"role": "user", "content": "hi"}])

        kwargs = recorder.calls[0]
        assert kwargs["extra_body"] == {"provider": {"order": ["cerebras"]}}
        assert kwargs["timeout"] == 5.0

    def test_reasoning_effort_can_be_omitted(self, monkeypatch, live_env):
        monkeypatch.setenv("OPENROUTER_REASONING_EFFORT", "")
        recorder = RecordingCompletion(json.dumps(VALID_PAYLOAD))
        monkeypatch.setattr(client, "completion", recorder)

        client.complete([{"role": "user", "content": "hi"}])

        assert "reasoning_effort" not in recorder.calls[0]


class TestRetryAndErrors:
    def test_malformed_reply_is_retried_once_and_can_succeed(self, monkeypatch, live_env):
        recorder = RecordingCompletion("sorry, no JSON here", json.dumps(VALID_PAYLOAD))
        monkeypatch.setattr(client, "completion", recorder)

        reply = client.complete([{"role": "user", "content": "hi"}])

        assert reply.message == "Hello."
        assert len(recorder.calls) == 2
        retry_messages = recorder.calls[1]["messages"]
        assert retry_messages[-1]["content"] == client.RETRY_INSTRUCTION

    def test_two_malformed_replies_raise(self, monkeypatch, live_env):
        recorder = RecordingCompletion("nope", "still nope")
        monkeypatch.setattr(client, "completion", recorder)

        with pytest.raises(client.MalformedResponseError):
            client.complete([{"role": "user", "content": "hi"}])
        assert len(recorder.calls) == 2

    def test_provider_error_becomes_llm_error(self, monkeypatch, live_env):
        def boom(**kwargs):
            raise RuntimeError("provider exploded")

        monkeypatch.setattr(client, "completion", boom)

        with pytest.raises(client.LLMError) as excinfo:
            client.complete([{"role": "user", "content": "hi"}])
        assert not isinstance(excinfo.value, client.LLMTimeoutError)

    def test_timeout_is_classified_by_exception_name(self, monkeypatch, live_env):
        class APITimeoutError(Exception):
            pass

        def boom(**kwargs):
            raise APITimeoutError("timed out")

        monkeypatch.setattr(client, "completion", boom)

        with pytest.raises(client.LLMTimeoutError):
            client.complete([{"role": "user", "content": "hi"}])

    def test_timeout_is_classified_through_a_cause(self, monkeypatch, live_env):
        class ReadTimedOutError(Exception):
            pass

        def boom(**kwargs):
            raise RuntimeError("wrapped") from ReadTimedOutError("underlying")

        monkeypatch.setattr(client, "completion", boom)

        with pytest.raises(client.LLMTimeoutError):
            client.complete([{"role": "user", "content": "hi"}])

    def test_unexpected_response_shape(self, monkeypatch, live_env):
        monkeypatch.setattr(client, "completion", lambda **kwargs: SimpleNamespace(choices=[]))

        with pytest.raises(client.MalformedResponseError):
            client.complete([{"role": "user", "content": "hi"}])

    def test_complete_refuses_when_mock_mode_is_active(self, monkeypatch):
        called = []
        monkeypatch.setattr(client, "completion", lambda **kwargs: called.append(kwargs))

        # The autouse fixture leaves LLM_MOCK=true.
        with pytest.raises(client.LLMError):
            client.complete([{"role": "user", "content": "hi"}])
        assert called == []
