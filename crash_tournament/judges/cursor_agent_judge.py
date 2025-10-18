"""
Cursor Agent judge implementation.

Specialized judge for cursor-agent CLI tool with proper JSON format handling.
"""

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import TypedDict, cast

from pydantic import TypeAdapter
from typing_extensions import NotRequired, override

from ..exceptions import JudgeError, ValidationError
from ..interfaces import Judge
from ..logging_config import get_logger
from ..models import Crash, OrdinalResult

# Module-level logger
logger = get_logger("cursor_agent_judge")


class CursorAgentJudgeError(JudgeError):
    """Base exception for cursor-agent judge errors."""

    pass


class NoJsonFromCursorAgentError(CursorAgentJudgeError):
    """Raised when cursor-agent output cannot be parsed as JSON."""

    pass


class InvalidCursorAgentResponseError(CursorAgentJudgeError):
    """Raised when cursor-agent returns invalid/incomplete response."""

    pass


class CursorAgentResponse(TypedDict):
    """Type definition for cursor-agent JSON response."""

    result: str
    activities: NotRequired[
        list[
            dict[
                str,
                str
                | int
                | bool
                | None
                | list[str]
                | dict[str, str | int | bool | None],
            ]
        ]
    ]


class TextContent(TypedDict):
    type: str
    text: str


class MessageContent(TypedDict):
    type: str
    text: str


class AssistantMessage(TypedDict):
    content: list[MessageContent]


class AssistantActivity(TypedDict):
    type: str
    message: AssistantMessage


class ToolCallActivity(TypedDict):
    type: str
    subtype: str
    tool_call: dict[str, dict[str, object]]


class FilesResult(TypedDict):
    files: list[str]
    totalFiles: int


class ContentResult(TypedDict):
    content: str
    totalLines: int


class ToolError(TypedDict):
    errorMessage: str


class JudgeResult(TypedDict):
    """Type definition for judge JSON result."""

    ordered: list[str]


class CursorAgentJudge(Judge):
    """
    Cursor Agent judge implementation.

    Specialized for cursor-agent CLI tool with JSON output.
    Uses cursor-agent's -p flag for inline prompts.
    """

    def __init__(self, timeout: float = 300.0, prompt_file: str | Path | None = None):
        """
        Initialize Cursor Agent judge.

        Args:
            timeout: Timeout in seconds for agent execution
            prompt_file: Path to markdown prompt file (default: ordinal_judge.md)
        """
        self.timeout: float = timeout
        self.judge_id: str = "cursor_agent"

        # Use default prompt file if none specified
        if prompt_file is None:
            prompt_file = Path(__file__).parent.parent / "prompts" / "ordinal_judge.md"
        self.prompt_file: Path = Path(prompt_file)

    @override
    def evaluate_matchup(self, crashes: Sequence[Crash]) -> OrdinalResult:
        """
        Evaluate a group of crashes using cursor-agent.

        Args:
            crashes: List of crashes to evaluate

        Returns:
            OrdinalResult with rankings and rationale

        Raises:
            Exception: If cursor-agent fails or returns invalid output
        """
        if not crashes:
            raise ValidationError("Cannot evaluate empty crash list")

        # Build prompt from markdown file
        prompt = self._build_prompt(crashes)

        # Invoke cursor-agent with inline prompt
        output = self._invoke_cursor_agent(prompt)

        # Parse JSON response
        json_result = self._extract_json_from_output(output)

        # Validate required fields
        if "ordered" not in json_result:
            raise ValueError("cursor-agent response missing 'ordered' field")

        ordered_ids = json_result["ordered"]

        if len(ordered_ids) != len(crashes):
            raise ValueError(
                f"Expected {len(crashes)} ordered IDs, got {len(ordered_ids)}"
            )

        # Validate crash IDs
        crash_ids = {crash.crash_id for crash in crashes}
        for crash_id in ordered_ids:
            if crash_id not in crash_ids:
                logger.error(f"Expected crash IDs: {list(crash_ids)}")
                logger.error(f"Got crash IDs: {ordered_ids}")
                raise ValueError(
                    f"Unknown crash ID in result: {crash_id}. Expected: {list(crash_ids)}"
                )

        # Store entire parsed JSON result
        return OrdinalResult(
            ordered_ids=ordered_ids,
            raw_output=output,
            parsed_result=dict(json_result),
            judge_id=self.judge_id,
        )

    def _build_prompt(self, crashes: Sequence[Crash]) -> str:
        """
        Build prompt from markdown file and crash context.

        Args:
            crashes: List of crashes to evaluate

        Returns:
            Formatted prompt string
        """
        # Read the markdown prompt file
        prompt_template = self.prompt_file.read_text()

        # Format crash context
        context_lines = list[str]()
        for crash in crashes:
            context_lines.append(f"- id: {crash.crash_id} file: @{crash.file_path}")
        context = "\n".join(context_lines)

        # Replace {context} placeholder
        return prompt_template.replace("{context}", context)

    def _invoke_cursor_agent(self, prompt: str) -> str:
        """
        Invoke cursor-agent with inline prompt.

        Args:
            prompt: The prompt to send to cursor-agent

        Returns:
            Raw output from cursor-agent

        Raises:
            subprocess.TimeoutExpired: If agent times out
            subprocess.CalledProcessError: If agent returns non-zero exit code
        """
        # Build command with inline prompt
        cmd = ["cursor-agent", "--output-format=json", "-p", prompt]

        # Log the command being executed (full command for debugging)
        logger.info(f"Running cursor-agent command: {' '.join(cmd)}")
        logger.debug(f"Full prompt: {prompt}")

        # Run cursor-agent
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=self.timeout, check=True
            )
        except subprocess.CalledProcessError as e:
            logger.error(f"cursor-agent failed with exit code {e.returncode}")
            logger.error(f"stderr: {e.stderr}")  # pyright: ignore[reportAny]
            raise CursorAgentJudgeError(
                f"cursor-agent execution failed: {e.stderr}"  # pyright: ignore[reportAny]
            ) from e

        logger.info(
            f"cursor-agent completed successfully, output length: {len(result.stdout)} chars"
        )
        logger.debug(f"Full agent output: {result.stdout}")

        # Parse and log agent activities retroactively for better visibility
        self._log_agent_activities(result.stdout)

        return result.stdout

    def _log_agent_activities(self, output: str) -> None:
        """
        Parse cursor-agent output and log key activities for better visibility.

        Args:
            output: Raw output from cursor-agent
        """
        # Parse the JSON response to extract activities
        response = TypeAdapter(CursorAgentResponse).validate_python(
            json.loads(output.strip())
        )

        # Check if this is a streaming-style response with activities
        if "activities" in response:
            activities = response["activities"]
            for activity in activities:
                activity_type = activity.get("type")

                if activity_type == "assistant":
                    assistant_activity = TypeAdapter(AssistantActivity).validate_python(
                        activity
                    )
                    for item in assistant_activity["message"]["content"]:
                        if item["type"] == "text":
                            text = item["text"]
                            if text:
                                logger.info(
                                    f"Agent: {text[:100]}{'...' if len(text) > 100 else ''}"
                                )

                elif activity_type == "tool_call":
                    tool_activity = TypeAdapter(ToolCallActivity).validate_python(
                        activity
                    )
                    tool_call_data = tool_activity["tool_call"]

                    if tool_activity["subtype"] == "started":
                        tool_name = next(
                            (
                                k.replace("ToolCall", "")
                                for k in tool_call_data.keys()
                                if k.endswith("ToolCall")
                            ),
                            "unknown",
                        )

                        tool_info = tool_call_data.get(f"{tool_name}ToolCall", {})
                        args: object = tool_info.get("args", {})
                        if isinstance(args, dict):
                            # Type narrow args to dict[str, object] after isinstance check
                            args_dict = cast(dict[str, object], args)
                            arg_summary = ", ".join(
                                f"{k}={v}" for k, v in list(args_dict.items())[:3]
                            )
                            if len(args_dict) > 3:
                                arg_summary += "..."
                            logger.info(f"Tool: {tool_name}({arg_summary})")

                    elif tool_activity["subtype"] == "completed":
                        tool_name = next(
                            (
                                k.replace("ToolCall", "")
                                for k in tool_call_data.keys()
                                if k.endswith("ToolCall")
                            ),
                            "unknown",
                        )

                        tool_info = tool_call_data.get(f"{tool_name}ToolCall", {})
                        result: object = tool_info.get("result", {})
                        if isinstance(result, dict):
                            if "success" in result:
                                success_data: object = result["success"]  # pyright: ignore[reportUnknownVariableType]
                                if isinstance(success_data, dict):
                                    # Type narrow success_data to dict[str, object] after isinstance check
                                    success_dict = cast(dict[str, object], success_data)
                                    if "files" in success_dict:
                                        files_result = TypeAdapter(
                                            FilesResult
                                        ).validate_python(success_dict)
                                        logger.info(
                                            f"Tool {tool_name} => found {files_result['totalFiles']} files"
                                        )
                                    elif "content" in success_dict:
                                        content_result = TypeAdapter(
                                            ContentResult
                                        ).validate_python(success_dict)
                                        lines = content_result["content"].split("\n")
                                        self._log_content_preview(
                                            tool_name,
                                            lines,
                                            content_result["totalLines"],
                                        )
                                    else:
                                        logger.info(f"Tool {tool_name} => success")
                            elif "error" in result:
                                error_data: object = result["error"]  # pyright: ignore[reportUnknownVariableType]
                                if isinstance(error_data, dict):
                                    # Type narrow error_data to dict[str, object] after isinstance check
                                    error_dict = cast(dict[str, object], error_data)
                                    tool_error = TypeAdapter(ToolError).validate_python(
                                        error_dict
                                    )
                                    logger.info(
                                        f"Tool {tool_name} => error: {tool_error['errorMessage']}"
                                    )
                            else:
                                logger.info(f"Tool {tool_name} => completed")

    def _log_content_preview(
        self, tool_name: str, lines: list[str], total_lines: int
    ) -> None:
        """Log content preview for tool results."""
        if total_lines <= 10:
            display_lines = [
                (line[:200] + "..." if len(line) > 200 else line) for line in lines
            ]
            content_preview = "\n".join(display_lines)
            logger.info(f"Tool {tool_name} => {total_lines} lines:\n{content_preview}")
        else:
            first_5 = [
                (line[:200] + "..." if len(line) > 200 else line) for line in lines[:5]
            ]
            last_5 = [
                (line[:200] + "..." if len(line) > 200 else line) for line in lines[-5:]
            ]
            content_preview = "\n".join(first_5) + "\n...\n" + "\n".join(last_5)
            logger.info(
                f"Tool {tool_name} => {total_lines} lines (showing first & last 5):\n{content_preview}"
            )

    def _extract_json_from_output(self, output: str) -> JudgeResult:
        """
        Extract JSON from cursor-agent output.

        cursor-agent returns a JSON object with a 'result' field containing the actual response.
        The result may be JSON-in-JSON, so we need to parse it properly.

        Args:
            output: Raw output from cursor-agent

        Returns:
            Parsed JSON dictionary from the result field

        Raises:
            ValueError: If no valid JSON found
        """
        try:
            # Parse cursor-agent's response format
            response = TypeAdapter(CursorAgentResponse).validate_python(
                json.loads(output.strip())
            )
        except json.JSONDecodeError as e:
            raise NoJsonFromCursorAgentError(
                f"Failed to parse JSON from cursor-agent output: {e}"
            )

        # Extract the result field
        result_text: str = response["result"]

        # The result may be JSON-in-JSON (wrapped in ```json``` blocks)
        if "```json" in result_text:
            # Extract JSON from markdown code block
            start = result_text.find("```json") + 7
            end = result_text.find("```", start)
            if end == -1:
                raise InvalidCursorAgentResponseError(
                    "Malformed JSON code block in cursor-agent result"
                )
            json_text: str = result_text[start:end].strip()
        else:
            # Assume the result is direct JSON
            json_text = result_text.strip()

        # Parse the extracted JSON
        try:
            return TypeAdapter(JudgeResult).validate_python(json.loads(json_text))
        except json.JSONDecodeError as e:
            raise NoJsonFromCursorAgentError(
                f"Failed to parse JSON from result field: {e}"
            )

    @override
    def test_connection(self) -> bool:
        """
        Test if cursor-agent is available and working.

        Returns:
            True if cursor-agent is working

        Raises:
            Exception: If cursor-agent is not available or not working
        """
        # Test with a simple prompt
        test_prompt = 'Respond with JSON: {"test": "success"}'
        output = self._invoke_cursor_agent(test_prompt)

        # Try to parse the response
        json_result = self._extract_json_from_output(output)

        # Check if it looks like a valid response
        return "test" in json_result or "success" in str(json_result)

    def get_agent_command(self) -> list[str]:
        """Get the command used to invoke cursor-agent."""
        return ["cursor-agent", "--output-format=json", "-p"]

    def set_timeout(self, timeout: float) -> None:
        """Set timeout for cursor-agent execution."""
        self.timeout = timeout

    def get_timeout(self) -> float:
        """Get current timeout setting."""
        return self.timeout
