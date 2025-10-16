"""
Cursor Agent Streaming judge implementation.

Specialized judge for cursor-agent CLI tool with streaming JSON output format.
Provides real-time progress updates during agent execution.
"""

import json
import subprocess
import time
from pathlib import Path
from typing import List, Sequence

from ..models import Crash, OrdinalResult
from .cursor_agent_judge import (
    CursorAgentJudge,
    CursorAgentJudgeError,
    NoJsonFromCursorAgentError,
    InvalidCursorAgentResponseError
)



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
        self.judge_id = "cursor_agent_streaming"
    
    
    
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
        cmd = [
            "cursor-agent",
            "--output-format=stream-json",
            "-p", prompt
        ]
        
        # Log the command being executed
        prompt_preview = prompt[:100] + "..." if len(prompt) > 100 else prompt
        self.logger.info(f"Running cursor-agent command: cursor-agent --output-format=stream-json -p {repr(prompt_preview)} ({len(prompt)} chars)")
        self.logger.debug(f"Full prompt: {repr(prompt)}")
        
        # Start cursor-agent process with streaming output
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
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
                    msg = json.loads(line.strip())
                    
                    # Log progress based on message type
                    if msg.get("type") == "assistant":
                        content = msg.get("message", {}).get("content", [])
                        for item in content:
                            if item.get("type") == "text":
                                text = item.get("text", "")
                                # Log full agent thinking with repr to avoid line breaks
                                if text:
                                    text_preview = text[:100] + "..." if len(text) > 100 else text
                                    self.logger.info(f"Agent: {repr(text_preview)} ({len(text)} chars)")
                                    self.logger.debug(f"Full agent response: {repr(text)}")
                    
                    elif msg.get("type") == "tool_call":
                        if msg.get("subtype") == "started":
                            tool_call_data = msg.get("tool_call", {})
                            # Extract tool name (first key that ends with 'ToolCall')
                            tool_name = next((k.replace('ToolCall', '') for k in tool_call_data.keys() 
                                             if k.endswith('ToolCall')), "unknown")
                            
                            # Extract args
                            tool_info = tool_call_data.get(f"{tool_name}ToolCall", {})
                            args = tool_info.get("args", {})
                            
                            # Create a concise arg summary
                            arg_summary = ", ".join(f"{k}={v}" for k, v in list(args.items())[:3])
                            if len(args) > 3:
                                arg_summary += "..."
                                
                            self.logger.debug(f"Tool: {tool_name}({arg_summary})")
                        elif msg.get("subtype") == "completed":
                            tool_call_data = msg.get("tool_call", {})
                            tool_name = next((k.replace('ToolCall', '') for k in tool_call_data.keys() 
                                             if k.endswith('ToolCall')), "unknown")
                            
                            tool_info = tool_call_data.get(f"{tool_name}ToolCall", {})
                            result = tool_info.get("result", {})
                            
                            # Summarize result based on type
                            if isinstance(result, dict):
                                if "success" in result:
                                    success_data = result["success"]
                                    if "files" in success_data:
                                        file_count = success_data.get('totalFiles', len(success_data.get('files', [])))
                                        self.logger.debug(f"Tool {tool_name} => found {file_count} files")
                                    elif "content" in success_data:
                                        content = success_data.get("content", "")
                                        lines = content.split('\n')
                                        total_lines = success_data.get("totalLines", len(lines))
                                        
                                        # Show content if short (< 10 lines), else first & last 5 lines
                                        if total_lines <= 10:
                                            # Truncate super long lines (> 200 chars)
                                            display_lines = [line[:200] + "..." if len(line) > 200 else line 
                                                           for line in lines]
                                            content_preview = '\n'.join(display_lines)
                                            self.logger.debug(f"Tool {tool_name} => {total_lines} lines:\n{content_preview}")
                                        else:
                                            # Show first 5 and last 5 lines with truncation
                                            first_5 = [line[:200] + "..." if len(line) > 200 else line 
                                                      for line in lines[:5]]
                                            last_5 = [line[:200] + "..." if len(line) > 200 else line 
                                                     for line in lines[-5:]]
                                            content_preview = '\n'.join(first_5) + '\n...\n' + '\n'.join(last_5)
                                            self.logger.debug(f"Tool {tool_name} => {total_lines} lines (showing first & last 5):\n{content_preview}")
                                    else:
                                        self.logger.debug(f"Tool {tool_name} => success")
                                elif "error" in result:
                                    error_msg = result['error'].get('errorMessage', 'unknown')
                                    self.logger.debug(f"Tool {tool_name} => error: {error_msg}")
                                else:
                                    self.logger.debug(f"Tool {tool_name} => completed")
                            else:
                                self.logger.debug(f"Tool {tool_name} => completed")
                    
                    # Capture final result
                    elif msg.get("type") == "result":
                        result_message = msg
                        self.logger.info("Received final result from cursor-agent")
                        break
                
                except json.JSONDecodeError as e:
                    # Log malformed JSON lines - may indicate issues with cursor-agent output
                    self.logger.warning(f"Skipping malformed JSON line from cursor-agent: {line[:100]}...")
                    continue
            
            # Wait for process to complete
            process.wait()
            
            if result_message is None:
                raise ValueError("No result message found in cursor-agent stream")
            
            if result_message.get("subtype") != "success":
                raise ValueError(f"cursor-agent failed: {result_message.get('subtype')}")
            
            # Extract the result content
            result_content = result_message.get("result", "")
            self.logger.info(f"cursor-agent completed successfully, result length: {len(result_content)} chars")
            
            # Log the full result content for debugging
            self.logger.info(f"Full agent result: {result_content}")
            
            # Extract JSON from the result content (handle markdown code blocks)
            json_result = self._extract_json_from_agent_output(result_content)
            
            # Return in the format expected by the parent class
            return json.dumps({"result": json_result})
            
        except subprocess.TimeoutExpired:
            process.kill()
            raise
        except Exception as e:
            process.kill()
            raise subprocess.CalledProcessError(1, cmd, stderr=str(e))
    
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
                raise NoJsonFromCursorAgentError("Malformed JSON code block in agent output")
            json_text = output[start:end].strip()
            self.logger.info(f"Extracted JSON from markdown block: {json_text}")
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
            self.logger.info(f"Extracted JSON from output: {json_text}")
            return json_text
    
    def get_agent_command(self) -> List[str]:
        """Get the command used to invoke cursor-agent."""
        return ["cursor-agent", "--output-format=stream-json", "-p"]
    
