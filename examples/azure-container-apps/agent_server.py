"""FastAPI server for py-code-mode agent.

Exposes the AutoGen agent as an HTTP API for Azure Container Apps.
Connects to an external session server for code execution.
"""

import os

from autogen_agentchat.agents import AssistantAgent
from autogen_core.tools import FunctionTool
from fastapi import FastAPI
from pydantic import BaseModel

from py_code_mode import RedisStorage, Session
from py_code_mode.execution import ContainerConfig, ContainerExecutor


class TaskRequest(BaseModel):
    task: str


class TaskResponse(BaseModel):
    result: str
    error: str | None = None


def get_model_client():
    """Get Azure OpenAI model client."""
    from autogen_ext.models.openai import AzureOpenAIChatCompletionClient
    from autogen_core.models import ModelFamily, ModelInfo
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider

    # Use managed identity for Azure OpenAI auth
    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(),
        "https://cognitiveservices.azure.com/.default",
    )

    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

    # Model info for models not yet in autogen's registry
    model_info_map = {
        "gpt-41": ModelInfo(
            vision=True,
            function_calling=True,
            json_output=True,
            family=ModelFamily.GPT_4O,  # GPT-4.1 is similar to GPT-4o
            context_window=128000,
        ),
    }

    return AzureOpenAIChatCompletionClient(
        azure_deployment=deployment,
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        azure_ad_token_provider=token_provider,
        model=deployment,
        api_version="2024-08-01-preview",
        model_info=model_info_map.get(deployment),
    )


app = FastAPI(title="py-code-mode Agent")


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.post("/task", response_model=TaskResponse)
async def run_task(request: TaskRequest):
    """Run a task with the agent."""
    # Create storage pointing to same Redis as session server
    storage = RedisStorage(
        url=os.environ["REDIS_URL"],
        prefix=os.environ.get("REDIS_PREFIX", "pycodemode"),
    )

    # Create executor in remote mode
    config = ContainerConfig(
        remote_url=os.environ.get("SESSION_URL", "http://session-server:8080"),
        auth_token=os.environ.get("SESSION_AUTH_TOKEN"),
    )
    executor = ContainerExecutor(config)

    async with Session(storage=storage, executor=executor) as session:

        async def _run_code(code: str) -> str:
            """Execute Python code via the session server.

            Args:
                code: Python code to execute. Has access to tools, skills,
                      artifacts, and deps namespaces.

            Returns:
                String result of execution, or error message if failed.
            """
            result = await session.run(code)
            if result.error:
                return f"Error: {result.error}"
            parts = []
            if result.stdout:
                parts.append(result.stdout)
            if result.value is not None:
                parts.append(str(result.value))
            return "\n".join(parts) if parts else "OK"

        run_code_tool = FunctionTool(
            func=_run_code,
            name="run_code",
            description="Execute Python code with tools, skills, artifacts, deps.",
        )

        system_prompt = """You are a helpful assistant that writes Python code to accomplish tasks.

You have access to these namespaces in run_code:
- tools.* - CLI tools (curl, jq, etc.)
- skills.* - Reusable Python functions
- artifacts.* - Persistent data storage
- deps.* - Python package management

WORKFLOW:
1. Discover tools: tools.list() or tools.search("keyword")
2. Use tools: tools.curl.get(url="...") or tools.jq.query(filter=".")
3. Save results: artifacts.save("name", data)

Example code:
```python
import json
response = tools.curl.get(url="https://api.github.com/repos/python/cpython")
data = json.loads(response)
print(f"Stars: {data['stargazers_count']}")
```

Always use the run_code tool to execute Python code."""

        agent = AssistantAgent(
            name="assistant",
            model_client=get_model_client(),
            tools=[run_code_tool],
            system_message=system_prompt,
        )

        try:
            result = await agent.run(task=request.task)
            return TaskResponse(result=result.messages[-1].content)
        except Exception as e:
            return TaskResponse(result="", error=str(e))


@app.get("/info")
async def info():
    """Get available tools and skills from session server."""
    # Create storage pointing to same Redis as session server
    storage = RedisStorage(
        url=os.environ["REDIS_URL"],
        prefix=os.environ.get("REDIS_PREFIX", "pycodemode"),
    )

    # Create executor in remote mode
    config = ContainerConfig(
        remote_url=os.environ.get("SESSION_URL", "http://session-server:8080"),
        auth_token=os.environ.get("SESSION_AUTH_TOKEN"),
    )
    executor = ContainerExecutor(config)

    async with Session(storage=storage, executor=executor) as session:
        tools = await session.list_tools()
        skills = await session.list_skills()
        return {
            "tools": tools,
            "skills": skills,
        }
