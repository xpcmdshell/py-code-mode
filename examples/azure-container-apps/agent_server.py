"""FastAPI server for py-code-mode agent.

Exposes the AutoGen agent as an HTTP API for Azure Container Apps.
"""

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from autogen_agentchat.agents import AssistantAgent

from py_code_mode import CodeExecutor, ToolRegistry
from py_code_mode.integrations.autogen import create_run_code_tool
from py_code_mode.semantic import create_skill_library
from py_code_mode.skill_store import RedisSkillStore


# Global executor and agent (initialized at startup)
executor = None
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
        from azure.identity import DefaultAzureCredential
        from autogen_ext.models.azure import AzureAIChatCompletionClient

        return AzureAIChatCompletionClient(
            model="claude-sonnet-4-20250514",
            endpoint=azure_endpoint,
            credential=DefaultAzureCredential(),
        )
    else:
        from autogen_ext.models.anthropic import AnthropicChatCompletionClient

        return AnthropicChatCompletionClient(model="claude-sonnet-4-20250514")


async def create_executor():
    """Create executor - Redis mode if REDIS_URL set, file mode otherwise."""
    redis_url = os.environ.get("REDIS_URL")

    # Tools and skills paths (mounted via Azure Files or local)
    tools_path = os.environ.get("TOOLS_PATH", "/workspace/configs/tools")
    skills_path = os.environ.get("SKILLS_PATH", "/workspace/configs/skills")

    if redis_url:
        import redis as redis_lib
        from py_code_mode import RedisArtifactStore

        r = redis_lib.from_url(redis_url)

        # Use Redis store wrapped in skill library for semantic search
        redis_store = RedisSkillStore(r, prefix="agent-skills")
        skill_library = create_skill_library(store=redis_store)
        artifact_store = RedisArtifactStore(r, prefix="agent-artifacts")

        registry = await ToolRegistry.from_dir(Path(tools_path))

        return CodeExecutor(
            registry=registry,
            skill_library=skill_library,
            artifact_store=artifact_store,
        )
    else:
        return await CodeExecutor.create(
            tools=tools_path,
            skills=skills_path,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize executor and agent at startup."""
    global executor, agent

    executor = await create_executor()
    await executor.__aenter__()

    run_code = create_run_code_tool(executor=executor)

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

    await executor.__aexit__(None, None, None)


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
    if executor is None:
        raise HTTPException(status_code=503, detail="Executor not initialized")

    tools = executor._namespace.get("tools")
    skills = executor._namespace.get("skills")

    return {
        "tools": tools.list() if tools else [],
        "skills": skills.list() if skills else [],
    }
