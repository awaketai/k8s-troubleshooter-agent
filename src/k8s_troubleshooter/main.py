from __future__ import annotations

from k8s_troubleshooter.config import AppConfig


async def run(config: AppConfig) -> None:
    from k8s_troubleshooter.chat.terminal import TerminalUI
    from k8s_troubleshooter.kube.client import KubeClient
    from k8s_troubleshooter.llm.openai_provider import OpenAIProvider
    from k8s_troubleshooter.llm.provider import LLMProvider

    kube_client = KubeClient(config)
    kube_client.verify_connection()

    llm_provider: LLMProvider | None = None
    if config.resolved_api_key and config.resolved_model:
        llm_provider = OpenAIProvider(
            api_key=config.resolved_api_key,
            base_url=config.resolved_base_url,
            model=config.resolved_model,
        )

    ui = TerminalUI(config=config, kube_client=kube_client, llm_provider=llm_provider)
    await ui.run()
