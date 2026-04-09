from trace_llm.providers import MockProvider


def test_mock_provider() -> None:
    provider = MockProvider()
    assert provider.complete("hello").startswith("mock-response")
