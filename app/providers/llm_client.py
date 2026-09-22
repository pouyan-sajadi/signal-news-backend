from openai import AsyncOpenAI

from app.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL


class AsyncLLMClient:
    """Small async adapter for OpenAI-compatible LLM gateways."""

    def __init__(self, api_key: str, base_url: str, model: str):
        if not api_key:
            raise ValueError("LLM_API_KEY must be configured")
        if not base_url:
            raise ValueError("LLM_BASE_URL must be configured")
        if not model:
            raise ValueError("LLM_MODEL must be configured")

        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    async def chat(self, system_prompt: str, user_message: str) -> str:
        """Send one chat request and return the assistant's text response."""
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        )
        content = response.choices[0].message.content
        if content is None:
            raise ValueError("LLM returned an empty response")
        return content


llm_client = AsyncLLMClient(
    api_key=LLM_API_KEY,
    base_url=LLM_BASE_URL,
    model=LLM_MODEL,
)
