"""
Cursor Agent judge implementation.

Specialized judge for cursor-agent CLI tool with proper JSON format handling.
"""

import json
import subprocess
import tempfile
from pathlib import Path
from typing import List, Sequence, Any

from ..interfaces import Judge, JudgeError
from ..models import Crash, OrdinalResult
from ..logging_config import get_logger

class CursorAgentJudgeError(JudgeError):
    """Base exception for cursor-agent judge errors."""
    pass


class NoJsonFromCursorAgentError(CursorAgentJudgeError):
    """Raised when cursor-agent output cannot be parsed as JSON."""
    pass


class InvalidCursorAgentResponseError(CursorAgentJudgeError):
    """Raised when cursor-agent returns invalid/incomplete response."""
    pass


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
        self.timeout = timeout
        self.judge_id = "cursor_agent"
        self.logger = get_logger("cursor_agent_judge")
        
        # Use default prompt file if none specified
        if prompt_file is None:
            prompt_file = Path(__file__).parent.parent / "prompts" / "ordinal_judge.md"
        self.prompt_file = Path(prompt_file)
    
    def evaluate_group(self, crashes: Sequence[Crash], *, grading: bool = False) -> OrdinalResult:
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
            raise ValueError("Cannot evaluate empty crash list")
        
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
        if not isinstance(ordered_ids, list):
            raise ValueError("'ordered' field must be a list")
        
        if len(ordered_ids) != len(crashes):
            raise ValueError(f"Expected {len(crashes)} ordered IDs, got {len(ordered_ids)}")
        
        # Validate crash IDs
        crash_ids = {crash.crash_id for crash in crashes}
        for crash_id in ordered_ids:
            if crash_id not in crash_ids:
                self.logger.error(f"Expected crash IDs: {list(crash_ids)}")
                self.logger.error(f"Got crash IDs: {ordered_ids}")
                raise ValueError(f"Unknown crash ID in result: {crash_id}. Expected: {list(crash_ids)}")
        
        # Store entire parsed JSON result
        return OrdinalResult(
            ordered_ids=ordered_ids,
            raw_output=output,
            parsed_result=json_result,
            judge_id=self.judge_id,
            group_size=len(crashes),
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
        context_lines = []
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
        cmd = [
            "cursor-agent",
            "--output-format=json",
            "-p", prompt
        ]
        
        # Log the command being executed (full command for debugging)
        self.logger.info(f"Running cursor-agent command: {' '.join(cmd)}")
        self.logger.debug(f"Full prompt: {prompt}")
        
        # Run cursor-agent
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=self.timeout,
            check=True
        )
        
        self.logger.info(f"cursor-agent completed successfully, output length: {len(result.stdout)} chars")
        self.logger.info(f"Full agent output: {result.stdout}")
        
        # Parse and log agent activities retroactively for better visibility
        self._log_agent_activities(result.stdout)
        
        return result.stdout
    
    def _log_agent_activities(self, output: str) -> None:
        """
        Parse cursor-agent output and log key activities for better visibility.
        
        Args:
            output: Raw output from cursor-agent
        """
        try:
            # Parse the JSON response to extract activities
            response = json.loads(output.strip())
            
            # Check if this is a streaming-style response with activities
            if "activities" in response:
                activities = response["activities"]
                for activity in activities:
                    if activity.get("type") == "assistant":
                        content = activity.get("message", {}).get("content", [])
                        for item in content:
                            if item.get("type") == "text":
                                text = item.get("text", "")
                                if text:
                                    self.logger.info(f"Agent: {text[:100]}{'...' if len(text) > 100 else ''}")
                    
                    elif activity.get("type") == "tool_call":
                        if activity.get("subtype") == "started":
                            tool_call_data = activity.get("tool_call", {})
                            tool_name = next((k.replace('ToolCall', '') for k in tool_call_data.keys() 
                                             if k.endswith('ToolCall')), "unknown")
                            
                            tool_info = tool_call_data.get(f"{tool_name}ToolCall", {})
                            args = tool_info.get("args", {})
                            
                            arg_summary = ", ".join(f"{k}={v}" for k, v in list(args.items())[:3])
                            if len(args) > 3:
                                arg_summary += "..."
                                
                            self.logger.info(f"Tool: {tool_name}({arg_summary})")
                        elif activity.get("subtype") == "completed":
                            tool_call_data = activity.get("tool_call", {})
                            tool_name = next((k.replace('ToolCall', '') for k in tool_call_data.keys() 
                                             if k.endswith('ToolCall')), "unknown")
                            
                            tool_info = tool_call_data.get(f"{tool_name}ToolCall", {})
                            result = tool_info.get("result", {})
                            
                            if isinstance(result, dict):
                                if "success" in result:
                                    success_data = result["success"]
                                    if "files" in success_data:
                                        file_count = success_data.get('totalFiles', len(success_data.get('files', [])))
                                        self.logger.info(f"Tool {tool_name} => found {file_count} files")
                                    elif "content" in success_data:
                                        content = success_data.get("content", "")
                                        lines = content.split('\n')
                                        total_lines = success_data.get("totalLines", len(lines))
                                        
                                        if total_lines <= 10:
                                            display_lines = [line[:200] + "..." if len(line) > 200 else line 
                                                           for line in lines]
                                            content_preview = '\n'.join(display_lines)
                                            self.logger.info(f"Tool {tool_name} => {total_lines} lines:\n{content_preview}")
                                        else:
                                            first_5 = [line[:200] + "..." if len(line) > 200 else line 
                                                      for line in lines[:5]]
                                            last_5 = [line[:200] + "..." if len(line) > 200 else line 
                                                     for line in lines[-5:]]
                                            content_preview = '\n'.join(first_5) + '\n...\n' + '\n'.join(last_5)
                                            self.logger.info(f"Tool {tool_name} => {total_lines} lines (showing first & last 5):\n{content_preview}")
                                    else:
                                        self.logger.info(f"Tool {tool_name} => success")
                                elif "error" in result:
                                    error_msg = result['error'].get('errorMessage', 'unknown')
                                    self.logger.info(f"Tool {tool_name} => error: {error_msg}")
                                else:
                                    self.logger.info(f"Tool {tool_name} => completed")
                            else:
                                self.logger.info(f"Tool {tool_name} => completed")
                                
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            # If we can't parse the activities, just log a warning and continue
            self.logger.debug(f"Could not parse agent activities from output: {e}")
    
    def _extract_json_from_output(self, output: str) -> dict[str, Any]:
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
            response = json.loads(output.strip())
        except json.JSONDecodeError as e:
            raise NoJsonFromCursorAgentError(f"Failed to parse JSON from cursor-agent output: {e}")
        
        # Extract the result field
        if "result" not in response:
            raise InvalidCursorAgentResponseError("cursor-agent response missing 'result' field")
        
        result_text = response["result"]
        
        # The result may be JSON-in-JSON (wrapped in ```json``` blocks)
        if "```json" in result_text:
            # Extract JSON from markdown code block
            start = result_text.find("```json") + 7
            end = result_text.find("```", start)
            if end == -1:
                raise InvalidCursorAgentResponseError("Malformed JSON code block in cursor-agent result")
            json_text = result_text[start:end].strip()
        else:
            # Assume the result is direct JSON
            json_text = result_text.strip()
        
        # Parse the extracted JSON
        try:
            return json.loads(json_text)
        except json.JSONDecodeError as e:
            raise NoJsonFromCursorAgentError(f"Failed to parse JSON from result field: {e}")
    
    def test_connection(self) -> bool:
        """
        Test if cursor-agent is available and working.
        
        Returns:
            True if cursor-agent is working
            
        Raises:
            Exception: If cursor-agent is not available or not working
        """
        # Test with a simple prompt
        test_prompt = "Respond with JSON: {\"test\": \"success\"}"
        output = self._invoke_cursor_agent(test_prompt)
        
        # Try to parse the response
        json_result = self._extract_json_from_output(output)
        
        # Check if it looks like a valid response
        return "test" in json_result or "success" in str(json_result)
    
    def get_agent_command(self) -> List[str]:
        """Get the command used to invoke cursor-agent."""
        return ["cursor-agent", "--output-format=json", "-p"]
    
    def set_timeout(self, timeout: float) -> None:
        """Set timeout for cursor-agent execution."""
        self.timeout = timeout
    
    def get_timeout(self) -> float:
        """Get current timeout setting."""
        return self.timeout
