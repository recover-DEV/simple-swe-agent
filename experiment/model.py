"""Model adapter using the project's existing LLM environment variables."""

import os
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, BaseMessage
from langchain_openai import ChatOpenAI

from .aci import RepositoryACI


def create_model(aci: RepositoryACI, env_file: Path, *, edit_only: bool = False) -> Callable[[list[BaseMessage]], AIMessage]:
    """Bind ACI tools on first use, keeping status and checkpoint inspection local."""
    bound = None

    def invoke(messages: list[BaseMessage]) -> AIMessage:
        nonlocal bound
        if bound is None:
            load_dotenv(env_file)
            model_name = os.getenv('LLM_MODEL')
            api_key = os.getenv('LLM_API_KEY')
            if not model_name or not api_key:
                raise ValueError('Set LLM_MODEL and LLM_API_KEY in .env or the process environment.')
            base_url = os.getenv('LLM_BASE_URL') or None
            extra_body = None
            if base_url and urlsplit(base_url).hostname == 'api.deepseek.com':
                extra_body = {'thinking': {'type': 'disabled'}}
            client = ChatOpenAI(model=model_name, api_key=api_key, base_url=base_url,
                                temperature=0, timeout=45, max_retries=1, use_responses_api=False,
                                extra_body=extra_body)
            tools = aci.model_tools()
            if edit_only:
                tools = [tool for tool in tools if tool.name == 'replace_text']
            bound = client.bind_tools(tools)
        response = bound.invoke(messages)
        if not isinstance(response, AIMessage):
            raise TypeError('Expected an AIMessage from the configured chat model.')
        return response

    return invoke
