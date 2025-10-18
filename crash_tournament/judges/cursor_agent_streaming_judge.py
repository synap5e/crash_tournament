"""
Cursor Agent Streaming judge implementation.

Specialized judge for cursor-agent CLI tool with streaming JSON output format.
Provides real-time progress updates during agent execution.
"""

import json
import subprocess
import time
from typing import Any, cast, override

from pydantic import TypeAdapter, ValidationError as PydanticValidationError
from typing_extensions import TypedDict

from ..exceptions import ValidationError
from ..logging_config import get_logger
from .cursor_agent_judge import CursorAgentJudge, NoJsonFromCursorAgentError

# Module-level logger
logger = get_logger("cursor_agent_streaming_judge")


class TextContent(TypedDict):
    type: str
    text: str


class MessageContent(TypedDict):
    type: str
    text: str


class AssistantMessage(TypedDict):
    content: list[MessageContent]


class AssistantMessageWrapper(TypedDict):
    type: str
    message: AssistantMessage


class ToolCallWrapper(TypedDict):
    type: str
    subtype: str
    tool_call: dict[str, dict[str, object]]  # {toolName}ToolCall: {args/result: ...}


class FilesResult(TypedDict):
    files: list[str]
    totalFiles: int


class ContentResult(TypedDict):
    content: str
    totalLines: int


class SuccessData(TypedDict):
    files: list[str] | None
    totalFiles: int | None
    content: str | None
    totalLines: int | None


class ToolError(TypedDict):
    errorMessage: str


class ToolResult(TypedDict):
    success: SuccessData | None
    error: ToolError | None


class ResultMessage(TypedDict):
    type: str
    subtype: str
    result: str


class CursorAgentStreamingJudge(CursorAgentJudge):
    """
    Cursor Agent Streaming judge implementation.

    Specialized for cursor-agent CLI tool with streaming JSON output.
    Uses cursor-agent's -p flag for inline prompts and --output-format=stream-json
    for real-time progress updates.
    """

    def __init__(self, timeout: float = 300.0, prompt_file: str | None = None):
        """
        Initialize Cursor Agent Streaming judge.

        Args:
            timeout: Timeout in seconds for agent execution
            prompt_file: Path to markdown prompt file (default: ordinal_judge.md)
        """
        super().__init__(timeout, prompt_file)
        self.judge_id: str = "cursor_agent_streaming"

    @override
    def _invoke_cursor_agent(self, prompt: str) -> str:
        """
        Invoke cursor-agent with streaming output format.

        Args:
            prompt: The prompt to send to cursor-agent

        Returns:
            Raw output from cursor-agent result field

        Raises:
            subprocess.TimeoutExpired: If agent times out
            subprocess.CalledProcessError: If agent returns non-zero exit code
        """
        # Build command with streaming output format
        cmd = ["cursor-agent", "--output-format=stream-json", "-p", prompt]

        # Log the command being executed
        prompt_preview = prompt[:100] + "..." if len(prompt) > 100 else prompt
        logger.info(
            f"Running cursor-agent command: cursor-agent --output-format=stream-json -p {repr(prompt_preview)} ({len(prompt)} chars)"
        )
        logger.debug(f"Full prompt: {repr(prompt)}")

        # Start cursor-agent process with streaming output
        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1
        )

        result_message = None
        start_time = time.time()

        try:
            # Process streaming output line by line
            assert process.stdout is not None  # We set stdout=subprocess.PIPE
            for line in process.stdout:
                # Check timeout
                if time.time() - start_time > self.timeout:
                    process.kill()
                    raise subprocess.TimeoutExpired(cmd, self.timeout)

                try:
                    raw_msg: dict[str, Any] = json.loads(line.strip())  # pyright: ignore[reportExplicitAny, reportAny]
                    msg_type = raw_msg.get("type")

                    # Log progress based on message type
                    if msg_type == "assistant":
                        try:
                            msg = TypeAdapter(AssistantMessageWrapper).validate_python(
                                raw_msg
                            )
                            for item in msg["message"]["content"]:
                                if item["type"] == "text":
                                    text = item["text"]
                                    # Log full agent thinking with repr to avoid line breaks
                                    if text:
                                        text_preview = (
                                            text[:100] + "..."
                                            if len(text) > 100
                                            else text
                                        )
                                        logger.info(
                                            f"Agent: {repr(text_preview)} ({len(text)} chars)"
                                        )
                                        logger.debug(
                                            f"Full agent response: {repr(text)}"
                                        )
                        except PydanticValidationError as e:
                            logger.warning(f"Invalid assistant message format: {e}")
                            continue

                    elif msg_type == "tool_call":
                        try:
                            msg = TypeAdapter(ToolCallWrapper).validate_python(raw_msg)
                            tool_call_data = msg["tool_call"]

                            if msg["subtype"] == "started":
                                # Extract tool name (first key that ends with 'ToolCall')
                                tool_name = next(
                                    (
                                        k.replace("ToolCall", "")
                                        for k in tool_call_data.keys()
                                        if k.endswith("ToolCall")
                                    ),
                                    "unknown",
                                )

                                # Extract args - handle dynamic structure
                                tool_info_started = tool_call_data.get(
                                    f"{tool_name}ToolCall", {}
                                )
                                args: object = tool_info_started.get("args", {})
                                if isinstance(args, dict):
                                    # Type narrow args to dict[str, object] after isinstance check
                                    args_dict = cast(dict[str, object], args)
                                    # Create a concise arg summary
                                    arg_summary = ", ".join(
                                        f"{k}={v}"
                                        for k, v in list(args_dict.items())[:3]
                                    )
                                    if len(args_dict) > 3:
                                        arg_summary += "..."
                                    logger.debug(f"Tool: {tool_name}({arg_summary})")
                                else:
                                    logger.debug(f"Tool: {tool_name}(args: {args})")
                            elif msg["subtype"] == "completed":
                                tool_name = next(
                                    (
                                        k.replace("ToolCall", "")
                                        for k in tool_call_data.keys()
                                        if k.endswith("ToolCall")
                                    ),
                                    "unknown",
                                )

                                tool_info_completed = tool_call_data.get(
                                    f"{tool_name}ToolCall", {}
                                )
                                result: object = tool_info_completed.get("result", {})
                                if isinstance(result, dict):
                                    # Summarize result based on type
                                    if "success" in result:
                                        success_data: object = result["success"]  # pyright: ignore[reportUnknownVariableType]
                                        if isinstance(success_data, dict):
                                            # Type narrow success_data to dict[str, object] after isinstance check
                                            success_dict = cast(dict[str, object], success_data)
                                            if "files" in success_dict:
                                                files_result = TypeAdapter(
                                                    FilesResult
                                                ).validate_python(success_dict)
                                                logger.debug(
                                                    f"Tool {tool_name} => found {files_result['totalFiles']} files"
                                                )
                                            elif "content" in success_dict:
                                                content_result = TypeAdapter(
                                                    ContentResult
                                                ).validate_python(success_dict)
                                                lines = content_result["content"].split(
                                                    "\n"
                                                )
                                                self._log_content_preview(
                                                    tool_name,
                                                    lines,
                                                    content_result["totalLines"],
                                                )
                                            else:
                                                logger.debug(
                                                    f"Tool {tool_name} => success"
                                                )
                                    elif "error" in result:
                                        error_data: object = result["error"]  # pyright: ignore[reportUnknownVariableType]
                                        if isinstance(error_data, dict):
                                            # Type narrow error_data to dict[str, object] after isinstance check
                                            error_dict = cast(dict[str, object], error_data)
                                            tool_error = TypeAdapter(
                                                ToolError
                                            ).validate_python(error_dict)
                                            logger.debug(
                                                f"Tool {tool_name} => error: {tool_error['errorMessage']}"
                                            )
                                    else:
                                        logger.debug(f"Tool {tool_name} => completed")
                        except PydanticValidationError as e:
                            logger.warning(f"Invalid tool_call message format: {e}")
                            continue

                    # Capture final result
                    elif msg_type == "result":
                        try:
                            result_message = TypeAdapter(ResultMessage).validate_python(
                                raw_msg
                            )
                            logger.info("Received final result from cursor-agent")
                            break
                        except PydanticValidationError as e:
                            logger.warning(f"Invalid result message format: {e}")
                            continue

                except json.JSONDecodeError:
                    # Log malformed JSON lines - may indicate issues with cursor-agent output
                    logger.warning(
                        f"Skipping malformed JSON line from cursor-agent: {line[:100]}..."
                    )
                    continue

            # Wait for process to complete
            return_code = process.wait()

            # Check if process exited with error
            if return_code != 0:
                stderr_output = ""
                if process.stderr:
                    try:
                        stderr_output = process.stderr.read()
                    except Exception:
                        stderr_output = "Failed to read stderr"

                error_msg = f"cursor-agent exited with code {return_code}"
                if stderr_output:
                    error_msg += f"\nStderr: {stderr_output}"
                raise subprocess.CalledProcessError(return_code, cmd, stderr=error_msg)

            if result_message is None:
                raise ValidationError("No result message found in cursor-agent stream")

            if result_message["subtype"] != "success":
                raise ValidationError(
                    f"cursor-agent failed: {result_message['subtype']}"
                )

            # Extract the result content
            result_content = result_message["result"]
            logger.info(
                f"cursor-agent completed successfully, result length: {len(result_content)} chars"
            )

            # Log the full result content for debugging
            logger.info(f"Full agent result: {result_content}")

            # Extract JSON from the result content (handle markdown code blocks)
            json_result = self._extract_json_from_agent_output(result_content)

            # Return in the format expected by the parent class
            return json.dumps({"result": json_result})

        except subprocess.TimeoutExpired:
            process.kill()
            raise
        except Exception as e:
            process.kill()
            # Capture stderr from the subprocess
            stderr_output = ""
            if process.stderr:
                try:
                    stderr_output = process.stderr.read()
                except Exception:
                    stderr_output = "Failed to read stderr"

            # Combine the exception message with stderr output
            logger.warning(
                f"cursor-agent failed with error: {str(e)} and stderr: {stderr_output}"
            )
            error_msg = f"{str(e)}\nStderr: {stderr_output}"
            raise subprocess.CalledProcessError(1, cmd, stderr=error_msg)

    @override
    def _log_content_preview(
        self, tool_name: str, lines: list[str], total_lines: int
    ) -> None:
        """Log content preview for tool results."""
        # Show content if short (< 10 lines), else first & last 5 lines
        if total_lines <= 10:
            # Truncate super long lines (> 200 chars)
            display_lines = [
                (line[:200] + "..." if len(line) > 200 else line) for line in lines
            ]
            content_preview = "\n".join(display_lines)
            logger.debug(f"Tool {tool_name} => {total_lines} lines:\n{content_preview}")
        else:
            # Show first 5 and last 5 lines with truncation
            first_5 = [
                (line[:200] + "..." if len(line) > 200 else line) for line in lines[:5]
            ]
            last_5 = [
                (line[:200] + "..." if len(line) > 200 else line) for line in lines[-5:]
            ]
            content_preview = "\n".join(first_5) + "\n...\n" + "\n".join(last_5)
            logger.debug(
                f"Tool {tool_name} => {total_lines} lines (showing first & last 5):\n{content_preview}"
            )

    def _extract_json_from_agent_output(self, output: str) -> str:
        """
        Extract JSON from agent output, handling markdown code blocks.

        Args:
            output: Full agent output text

        Returns:
            JSON string ready for parsing

        Raises:
            NoJsonFromCursorAgentError: If no valid JSON found
        """
        # Look for JSON in markdown code blocks
        if "```json" in output:
            # Extract JSON from markdown code block
            start = output.find("```json") + 7
            end = output.find("```", start)
            if end == -1:
                raise NoJsonFromCursorAgentError(
                    "Malformed JSON code block in agent output"
                )
            json_text = output[start:end].strip()
            logger.info(f"Extracted JSON from markdown block: {json_text}")
            return json_text
        else:
            # Try to find JSON in the output (look for { and } patterns)
            start = output.find("{")
            if start == -1:
                raise NoJsonFromCursorAgentError("No JSON found in agent output")

            # Find the matching closing brace
            brace_count = 0
            end = start
            for i, char in enumerate(output[start:], start):
                if char == "{":
                    brace_count += 1
                elif char == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        end = i + 1
                        break

            if brace_count != 0:
                raise NoJsonFromCursorAgentError("Unbalanced braces in JSON")

            json_text = output[start:end].strip()
            logger.info(f"Extracted JSON from output: {json_text}")
            return json_text

    @override
    def get_agent_command(self) -> list[str]:
        """Get the command used to invoke cursor-agent."""
        return ["cursor-agent", "--output-format=stream-json", "-p"]
