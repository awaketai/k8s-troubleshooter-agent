from __future__ import annotations

import asyncio

from rich.console import Console
from rich.markdown import Markdown
from rich.status import Status

from k8s_troubleshooter.config import AppConfig
from k8s_troubleshooter.harness.context import SessionContext
from k8s_troubleshooter.harness.executor import ToolExecutor
from k8s_troubleshooter.harness.policy import PolicyGuard
from k8s_troubleshooter.harness.tools import ToolRegistry
from k8s_troubleshooter.harness.trace import TraceLogger
from k8s_troubleshooter.agent.orchestrator import DiagnosisOrchestrator
from k8s_troubleshooter.chat.session import ChatSession
from k8s_troubleshooter.harness.tool_setup import register_m1_tools
from k8s_troubleshooter.kube.client import KubeClient
from k8s_troubleshooter.llm.provider import LLMProvider


class TerminalUI:
    def __init__(
        self,
        config: AppConfig,
        kube_client: KubeClient,
        llm_provider: LLMProvider | None,
    ) -> None:
        self._config = config
        self._kube_client = kube_client
        self._llm_provider = llm_provider
        self._console = Console()

    async def run(self) -> None:
        context_name = self._config.context or "current-context"
        self._console.print(f"\nConnected to cluster: [bold]{context_name}[/bold]")

        if self._config.namespace:
            self._console.print(f"Default namespace: [bold]{self._config.namespace}[/bold]")

        llm_status = "enabled" if self._llm_provider else "not configured (rule-based only)"
        self._console.print(f"LLM: {llm_status}\n")

        session_context = SessionContext(
            cluster_context=context_name,
            active_namespace=self._config.namespace or "default",
        )

        registry = ToolRegistry()
        register_m1_tools(registry, self._kube_client, self._config)

        policy_guard = PolicyGuard(self._config)
        trace_logger = TraceLogger()
        tool_executor = ToolExecutor(registry, policy_guard, trace_logger)
        orchestrator = DiagnosisOrchestrator(tool_executor, self._llm_provider, self._config, policy_guard)
        chat_session = ChatSession(
            orchestrator=orchestrator,
            tool_executor=tool_executor,
            llm_provider=self._llm_provider,
            trace_logger=trace_logger,
            session_context=session_context,
            policy_guard=policy_guard,
        )

        self._console.print("Type your question or /quit to exit.\n")

        try:
            from prompt_toolkit import PromptSession

            prompt_session = PromptSession()
            while True:
                try:
                    user_input = await asyncio.to_thread(
                        prompt_session.prompt, "> "
                    )
                except (EOFError, KeyboardInterrupt):
                    break

                user_input = user_input.strip()
                if not user_input:
                    continue

                if user_input.lower() in ("/quit", "/exit"):
                    break

                if user_input.lower() == "/context":
                    ctx = chat_session.session_context
                    self._console.print(f"Session: {ctx.session_id or 'N/A'}")
                    self._console.print(f"Namespace: {ctx.active_namespace}")
                    self._console.print(f"Last resources: {[str(r) for r in ctx.last_diagnosed_resources[-3:]]}")
                    self._console.print(f"Active findings: {len(ctx.active_findings)}")
                    continue

                if user_input.lower() == "/help":
                    self._console.print("Commands:")
                    self._console.print("  /quit, /exit  - Exit")
                    self._console.print("  /context      - Show session context")
                    self._console.print("  /help         - Show this help")
                    self._console.print("")
                    self._console.print("Examples:")
                    self._console.print('  看看 default namespace 有什么异常的 pod')
                    self._console.print('  排查 default/demo-pod 为什么起不来')
                    self._console.print('  详细看看那个 OOM 的')
                    continue

                try:
                    chunks: list[str] = []
                    with self._console.status("[bold green]正在分析...[/bold green]", spinner="dots"):
                        async for chunk in chat_session.handle_input(user_input):
                            chunks.append(chunk)
                    self._console.print(Markdown("".join(chunks)))
                    self._console.print("")
                except KeyboardInterrupt:
                    self._console.print("\n[interrupted]\n")
                except Exception as e:
                    self._console.print(f"[red]Error: {e}[/red]\n")

        except ImportError:
            self._console.print("[yellow]prompt_toolkit not available, using basic input[/yellow]")
            while True:
                try:
                    user_input = input("> ").strip()
                except (EOFError, KeyboardInterrupt):
                    break

                if not user_input:
                    continue
                if user_input.lower() in ("/quit", "/exit"):
                    break

                try:
                    chunks: list[str] = []
                    with self._console.status("[bold green]正在分析...[/bold green]", spinner="dots"):
                        async for chunk in chat_session.handle_input(user_input):
                            chunks.append(chunk)
                    self._console.print(Markdown("".join(chunks)))
                except Exception as e:
                    self._console.print(f"[red]Error: {e}[/red]")

        self._console.print("\nGoodbye!")
