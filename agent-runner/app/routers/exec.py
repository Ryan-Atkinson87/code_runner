from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import require_token
from app.executor import execute_bash, execute_text_editor
from app.hooks import ToolPermissionError, pre_tool_use_check

router = APIRouter(prefix="/v1", dependencies=[Depends(require_token)])

_workdir = Path("/workspace")


def init_exec_deps(workdir: Path) -> None:
    global _workdir
    _workdir = workdir


class BashRequest(BaseModel):
    command: str = ""
    restart: bool = False


class TextEditorRequest(BaseModel):
    command: str
    path: str
    file_text: str | None = None
    old_str: str | None = None
    new_str: str | None = None
    insert_line: int | None = None
    insert_text: str | None = None
    view_range: list[int] | None = None


class ExecResponse(BaseModel):
    output: str


@router.post("/bash", response_model=ExecResponse)
async def bash_exec(request: BashRequest) -> ExecResponse:
    tool_input = request.model_dump(exclude_none=True)
    try:
        pre_tool_use_check("bash", tool_input, _workdir)
    except ToolPermissionError as exc:
        return ExecResponse(output=f"Permission denied: {exc}")

    try:
        output = await execute_bash(tool_input, _workdir)
    except Exception as exc:
        return ExecResponse(output=f"Error: {exc}")

    return ExecResponse(output=output)


@router.post("/text-editor", response_model=ExecResponse)
async def text_editor_exec(request: TextEditorRequest) -> ExecResponse:
    tool_input = request.model_dump(exclude_none=True)
    try:
        pre_tool_use_check("str_replace_based_edit_tool", tool_input, _workdir)
    except ToolPermissionError as exc:
        return ExecResponse(output=f"Permission denied: {exc}")

    try:
        output = execute_text_editor(tool_input, _workdir)
    except Exception as exc:
        return ExecResponse(output=f"Error: {exc}")

    return ExecResponse(output=output)
