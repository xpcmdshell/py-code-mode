"""FastAPI server for py-code-mode agent.

Exposes the AutoGen agent as an HTTP API for Azure Container Apps.
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

import redis as redis_lib
from autogen_agentchat.agents import AssistantAgent
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from py_code_mode import FileStorage, RedisStorage, Session
from py_code_mode.integrations.autogen import create_run_code_tool

# Global session and agent (initialized at startup)
session = None
agent = None


class TaskRequest(BaseModel):
    task: str


class TaskResponse(BaseModel):
    result: str
    error: str | None = None


def get_model_client():
    """Get model client - Azure AI Foundry in cloud, Anthropic API locally."""
    azure_endpoint = os.environ.get("AZURE_AI_ENDPOINT")

    if azure_endpoint:
        from autogen_ext.models.azure import AzureAIChatCompletionClient
        from azure.identity import DefaultAzureCredential

        return AzureAIChatCompletionClient(
            model="claude-sonnet-4-20250514",
            endpoint=azure_endpoint,
            credential=DefaultAzureCredential(),
        )
    else:
        from autogen_ext.models.anthropic import AnthropicChatCompletionClient

        return AnthropicChatCompletionClient(model="claude-sonnet-4-20250514")


def create_storage():
    """Create storage - Redis mode if REDIS_URL set, file mode otherwise."""
    redis_url = os.environ.get("REDIS_URL")

    # Base path for file storage (mounted via Azure Files or local)
    base_path = os.environ.get("STORAGE_PATH", "/workspace/configs")

    if redis_url:
        r = redis_lib.from_url(redis_url)
        return RedisStorage(redis=r, prefix="agent")
    else:
        return FileStorage(base_path=Path(base_path))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize session and agent at startup."""
    global session, agent

    storage = create_storage()
    session = Session(storage=storage)
    await session.start()

    run_code = create_run_code_tool(session=session)

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

    agent = AssistantAgent(
        name="assistant",
        model_client=model,
        tools=[run_code],
        system_message=system_prompt,
        reflect_on_tool_use=True,
        max_tool_iterations=5,
    )

    yield

    await session.close()


app = FastAPI(title="py-code-mode Agent", lifespan=lifespan)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "agent": agent is not None}


@app.post("/task", response_model=TaskResponse)
async def run_task(request: TaskRequest):
    """Run a task with the agent."""
    if agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    try:
        result = await agent.run(task=request.task)
        final_message = result.messages[-1].content
        return TaskResponse(result=final_message)
    except Exception as e:
        return TaskResponse(result="", error=str(e))


@app.get("/info")
async def info():
    """Get available tools and skills."""
    if session is None:
        raise HTTPException(status_code=503, detail="Session not initialized")

    # Get storage info instead
    storage = session.storage

    return {
        "tools": storage.tools.list() if hasattr(storage, "tools") else [],
        "skills": storage.skills.list() if hasattr(storage, "skills") else [],
    }
