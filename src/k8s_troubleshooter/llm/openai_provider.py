from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from k8s_troubleshooter.llm.provider import LLMProvider

logger = logging.getLogger(__name__)


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model

    async def chat(self, messages: list[dict], **kwargs) -> str:
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                stream=False,
                **kwargs,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.error("OpenAI chat error: %s", e)
            raise

    async def chat_stream(self, messages: list[dict], **kwargs) -> AsyncIterator[str]:
        try:
            stream = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                stream=True,
                **kwargs,
            )
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            logger.error("OpenAI stream error: %s", e)
            raise
