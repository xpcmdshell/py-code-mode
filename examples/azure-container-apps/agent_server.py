"""FastAPI server for py-code-mode agent.

Exposes the AutoGen agent as an HTTP API for Azure Container Apps.
Connects to an external session server for code execution.
"""

import os
from contextlib import asynccontextmanager

from autogen_agentchat.agents import AssistantAgent
from autogen_core.tools import FunctionTool
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from py_code_mode.execution.container.client import SessionClient

# Global client and agent (initialized at startup)
_session_client: SessionClient | None = None
_agent: AssistantAgent | None = None


class TaskRequest(BaseModel):
    task: str


class TaskResponse(BaseModel):
    result: str
    error: str | None = None


def get_model_client():
    """Get model client - Azure AI Foundry in cloud, Anthropic API locally."""
    azure_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")

    # Prefer Anthropic API if available (simpler, no Azure AI Foundry setup needed)
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_key and not azure_endpoint:
        from autogen_ext.models.anthropic import AnthropicChatCompletionClient

        return AnthropicChatCompletionClient(model="claude-sonnet-4-20250514")

    if azure_endpoint:
        from autogen_ext.models.azure import AzureAIChatCompletionClient
        from azure.identity import DefaultAzureCredential

        # model_info required for Claude models on Azure AI Foundry
        return AzureAIChatCompletionClient(
            model="claude-sonnet-4-20250514",
            endpoint=azure_endpoint,
            credential=DefaultAzureCredential(),
            model_info={
                "vision": True,
                "function_calling": True,
                "json_output": True,
                "family": "claude",
            },
        )
    else:
        from autogen_ext.models.anthropic import AnthropicChatCompletionClient

        return AnthropicChatCompletionClient(model="claude-sonnet-4-20250514")


async def _run_code(code: str) -> str:
    """Execute Python code via the session server.

    Args:
        code: Python code to execute. Has access to tools, skills,
              artifacts, and deps namespaces.

    Returns:
        String result of execution, or error message if failed.
    """
    if _session_client is None:
        return "Error: Session client not initialized"

    result = await _session_client.execute(code)
    if result.error:
        return f"Error: {result.error}"

    # Include stdout if present
    output_parts = []
    if result.stdout:
        output_parts.append(result.stdout)
    if result.value is not None:
        output_parts.append(str(result.value))

    return "\n".join(output_parts) if output_parts else "OK"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize session client and agent at startup."""
    global _session_client, _agent

    session_url = os.environ.get("SESSION_URL", "http://session-server:8080")
    auth_token = os.environ.get("SESSION_AUTH_TOKEN")

    _session_client = SessionClient(
        base_url=session_url,
        auth_token=auth_token,
        timeout=120.0,
    )

    # Enter the async context manager
    await _session_client.__aenter__()

    # Create AutoGen tool from the run_code function
    run_code_tool = FunctionTool(
        func=_run_code,
        description=(
            "Execute Python code. The code has access to: "
            "tools.* (CLI/HTTP tools), skills.* (reusable solutions), "
            "artifacts.* (persistent storage), deps.* (package management). "
            "Use skills.search() to find existing solutions before writing code."
        ),
        name="run_code",
    )

    system_prompt = """You are a helpful assistant that writes Python code to accomplish tasks.

You have access to `tools` and `skills` namespaces in your code environment.

WORKFLOW:
1. For any nontrivial task, FIRST search skills: skills.search("relevant keywords")
2. If a skill exists, use it: skills.invoke("name", arg=value)
3. If no skill matches, search tools: tools.search("keywords")
4. Script tools together: tools.name(arg=value)

DISCOVERY:
- skills.search("query") / skills.list() - find prebaked solutions
- tools.search("query") / tools.list() - find individual tools

Skills are reusable recipes that combine tools. Prefer them over scripting from scratch.

ARTIFACTS (persistent storage):
- artifacts.save("name", data, description="...") - Save data for later
- artifacts.load("name") - Load previously saved data
- artifacts.list() - List saved artifacts

Always wrap your code in ```python blocks."""

    model = get_model_client()

    _agent = AssistantAgent(
        name="assistant",
        model_client=model,
        tools=[run_code_tool],
        system_message=system_prompt,
        reflect_on_tool_use=True,
        max_tool_iterations=5,
    )

    yield

    # Clean up session client
    await _session_client.__aexit__(None, None, None)
    _session_client = None
    _agent = None


app = FastAPI(title="py-code-mode Agent", lifespan=lifespan)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "agent": _agent is not None}


@app.post("/task", response_model=TaskResponse)
async def run_task(request: TaskRequest):
    """Run a task with the agent."""
    if _agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    try:
        result = await _agent.run(task=request.task)
        final_message = result.messages[-1].content
        return TaskResponse(result=final_message)
    except Exception as e:
        return TaskResponse(result="", error=str(e))


@app.get("/info")
async def info():
    """Get available tools and skills from session server."""
    if _session_client is None:
        raise HTTPException(status_code=503, detail="Session client not initialized")

    info_result = await _session_client.info()
    return {
        "tools": info_result.tools,
        "skills": info_result.skills,
    }
