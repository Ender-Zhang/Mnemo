from __future__ import annotations

import unittest

from mnemo.providers import AnthropicProviderAdapter, OpenAIProviderAdapter, ProviderRunInput


class ProviderAdapterTests(unittest.TestCase):
    def test_provider_adapters_are_explicit_placeholders(self) -> None:
        request = ProviderRunInput(messages=[], tools=[])

        with self.assertRaises(NotImplementedError):
            list(OpenAIProviderAdapter().stream(request))
        with self.assertRaises(NotImplementedError):
            list(AnthropicProviderAdapter().stream(request))


if __name__ == "__main__":
    unittest.main()
