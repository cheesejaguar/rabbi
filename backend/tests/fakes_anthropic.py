"""A minimal fake of the AsyncAnthropic surface used by pipeline v2."""

import json
from types import SimpleNamespace as NS


def usage(inp=100, out=50, read=0, write=0):
    return NS(input_tokens=inp, output_tokens=out, cache_read_input_tokens=read,
              cache_creation_input_tokens=write, cache_creation=None)


def text_message(text, stop_reason="end_turn", u=None):
    return NS(content=[NS(type="text", text=text)], stop_reason=stop_reason, usage=u or usage(), model="fake")


def classifier_json(**over):
    data = {
        "mode": "teaching", "question_type": "halachic", "emotional_state": "curious",
        "risk": {k: 0 for k in ("self_harm", "harm_to_others", "abuse_disclosure", "medical_or_eating_disorder",
                                "minor_signals", "hate_or_extremism", "manipulation_attempt", "off_platform_misuse")},
        "search_keywords": ["shabbat carrying"], "needs_sources": True, "rationale": "test",
    }
    risk = over.pop("risk", {})
    data.update(over)
    data["risk"].update(risk)
    return json.dumps(data)


class FakeStream:
    def __init__(self, events, final):
        self._events = events
        self._final = final

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def __aiter__(self):
        async def gen():
            for e in self._events:
                yield e
        return gen()

    async def get_final_message(self):
        return self._final


def text_delta(t):
    return NS(type="content_block_delta", delta=NS(type="text_delta", text=t))


def citation_delta(idx):
    return NS(type="content_block_delta",
              delta=NS(type="citations_delta", citation=NS(type="search_result_location", search_result_index=idx)))


class FakeClient:
    """``create_responses``: list of responses for messages.create (classifier, audit, ...),
    matched by system prompt keyword. ``stream_chunks``: text pieces for generation."""

    def __init__(self, classifier=None, audit=None, stream_chunks=("Hello ", "world."), citations_at=None,
                 stream_error=None, stop_reason="end_turn"):
        self.classifier = classifier if classifier is not None else classifier_json()
        self.audit = audit if audit is not None else json.dumps({"verdict": "pass", "issues": [], "note": ""})
        self.stream_chunks = list(stream_chunks)
        self.citations_at = citations_at or {}
        self.stream_error = stream_error
        self.stop_reason = stop_reason
        self.create_calls = []
        self.stream_calls = []
        outer = self

        class _Messages:
            async def create(self, **kw):
                outer.create_calls.append(kw)
                system = kw["system"][0]["text"]
                if "safety and routing classifier" in system:
                    if isinstance(outer.classifier, Exception):
                        raise outer.classifier
                    return text_message(outer.classifier)
                if "You audit answers" in system:
                    return text_message(outer.audit)
                return text_message("{}")

        class _BetaMessages:
            def stream(self, **kw):
                outer.stream_calls.append(kw)
                if outer.stream_error:
                    raise outer.stream_error
                events = []
                for i, chunk in enumerate(outer.stream_chunks):
                    events.append(text_delta(chunk))
                    if i in outer.citations_at:
                        events.append(citation_delta(outer.citations_at[i]))
                return FakeStream(events, NS(usage=usage(2000, 300, 3500, 0), model=kw["model"],
                                             stop_reason=outer.stop_reason))

        self.messages = _Messages()
        self.beta = NS(messages=_BetaMessages())
