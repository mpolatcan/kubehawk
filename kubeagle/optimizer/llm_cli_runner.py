"""Non-interactive runners for Codex CLI and Claude Agent SDK."""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

_AGENT_SDK_MAX_TURNS = 10


class LLMProvider(str, Enum):
    """Supported non-interactive CLI providers."""

    CODEX = "codex"
    CLAUDE = "claude"


@dataclass(slots=True)
class LLMDirectEditResult:
    """Result of provider-driven direct file edits in an existing workspace."""

    ok: bool
    provider: LLMProvider
    command: list[str] = field(default_factory=list)
    log_text: str = ""
    attempts: int = 1
    changed_rel_paths: list[str] = field(default_factory=list)
    error_message: str = ""
    stdout_tail: str = ""
    stderr_tail: str = ""


# Environment variables that must be cleared before launching a nested Claude
# Code process through the Agent SDK, otherwise the subprocess refuses to start
# with "Claude Code cannot be launched inside another Claude Code session."
_CLAUDE_SESSION_ENV_VARS: tuple[str, ...] = (
    "CLAUDECODE",
    "CLAUDE_CODE_SESSION",
    "CLAUDE_CODE_ENTRY",
)


_CLAUDE_SDK_CHECKED: bool = False
_CLAUDE_SDK_OK: bool = False


def _claude_agent_sdk_available() -> bool:
    """Return True if the claude-agent-sdk package is importable.

    The result is cached after the first successful probe so that Textual
    terminal takeover or other runtime environment changes cannot flip
    a previously-working import to False.
    """
    global _CLAUDE_SDK_CHECKED, _CLAUDE_SDK_OK
    if _CLAUDE_SDK_CHECKED:
        return _CLAUDE_SDK_OK
    try:
        from claude_agent_sdk import query as _q

        _CLAUDE_SDK_OK = True
    except Exception:
        _CLAUDE_SDK_OK = False
    _CLAUDE_SDK_CHECKED = True
    return _CLAUDE_SDK_OK


def detect_llm_cli_capabilities() -> dict[LLMProvider, bool]:
    """Detect whether each provider backend is available."""
    return {
        LLMProvider.CODEX: shutil.which("codex") is not None,
        LLMProvider.CLAUDE: _claude_agent_sdk_available(),
    }


def provider_supports_direct_edit(provider: LLMProvider) -> bool:
    """Return whether provider appears available for direct-edit execution."""
    return detect_llm_cli_capabilities().get(provider, False)


def run_llm_direct_edit(
    *,
    provider: LLMProvider,
    prompt: str,
    cwd: Path,
    timeout_seconds: int = 180,
    model: str | None = None,
    attempts: int = 1,
) -> LLMDirectEditResult:
    """Run provider against workspace and detect file changes done in place."""
    working_dir = cwd.expanduser().resolve()
    if not working_dir.exists() or not working_dir.is_dir():
        return LLMDirectEditResult(
            ok=False,
            provider=provider,
            attempts=max(1, int(attempts)),
            error_message=f"Direct-edit working directory not found: {working_dir}",
            log_text=f"Direct-edit working directory not found: {working_dir}",
        )

    if provider == LLMProvider.CODEX:
        command = [
            "codex",
            "exec",
            "--ephemeral",
            "--color",
            "never",
            "--skip-git-repo-check",
            "--full-auto",
        ]
        if model:
            command.extend(["--model", model])
        command.extend(["--cd", str(working_dir), "-"])
        return _run_direct_edit_subprocess(
            provider=provider,
            command=command,
            prompt=prompt,
            working_dir=working_dir,
            timeout_seconds=timeout_seconds,
            attempts=attempts,
        )

    if provider == LLMProvider.CLAUDE:
        before_snapshot = _snapshot_tree_hashes(working_dir)
        result = _run_claude_agent_sdk_direct_edit(
            prompt=prompt,
            working_dir=working_dir,
            model=model,
            max_turns=_AGENT_SDK_MAX_TURNS,
            timeout_seconds=timeout_seconds,
        )
        if not result.ok:
            return result
        after_snapshot = _snapshot_tree_hashes(working_dir)
        result.changed_rel_paths = _collect_changed_paths(before_snapshot, after_snapshot)
        result.attempts = max(1, int(attempts))
        return result

    return LLMDirectEditResult(
        ok=False,
        provider=provider,
        attempts=max(1, int(attempts)),
        error_message=f"Unsupported provider: {provider}",
        log_text=f"Unsupported provider: {provider}",
    )


def _run_direct_edit_subprocess(
    *,
    provider: LLMProvider,
    command: list[str],
    prompt: str,
    working_dir: Path,
    timeout_seconds: int,
    attempts: int,
) -> LLMDirectEditResult:
    """Execute a direct-edit CLI command via subprocess with snapshot diffing."""
    before_snapshot = _snapshot_tree_hashes(working_dir)
    try:
        process = subprocess.run(
            command,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=max(1, int(timeout_seconds)),
            check=False,
            cwd=str(working_dir),
            env=_non_interactive_env(),
        )
    except FileNotFoundError as exc:
        return LLMDirectEditResult(
            ok=False,
            provider=provider,
            command=command,
            attempts=max(1, int(attempts)),
            error_message=str(exc),
            log_text=f"Binary not found: {exc!s}",
        )
    except subprocess.TimeoutExpired as exc:
        stdout_tail = _tail_text(_safe_text(exc.stdout))
        stderr_tail = _tail_text(_safe_text(exc.stderr))
        return LLMDirectEditResult(
            ok=False,
            provider=provider,
            command=command,
            attempts=max(1, int(attempts)),
            error_message=f"{provider.value} timed out after {timeout_seconds}s",
            stdout_tail=stdout_tail,
            stderr_tail=stderr_tail,
            log_text=_build_direct_edit_log(
                provider=provider,
                command=command,
                cwd=working_dir,
                exit_code=124,
                changed_rel_paths=[],
                stdout_tail=stdout_tail,
                stderr_tail=stderr_tail,
                error_message=f"{provider.value} timed out after {timeout_seconds}s",
                attempts=max(1, int(attempts)),
            ),
        )

    after_snapshot = _snapshot_tree_hashes(working_dir)
    changed_rel_paths = _collect_changed_paths(before_snapshot, after_snapshot)
    stdout_tail = _tail_text(process.stdout or "")
    stderr_tail = _tail_text(process.stderr or "")
    error_message = ""
    if process.returncode != 0:
        error_message = (
            (process.stderr or process.stdout or "").strip()
            or f"{provider.value} exited with code {process.returncode}"
        )
    return LLMDirectEditResult(
        ok=process.returncode == 0,
        provider=provider,
        command=command,
        attempts=max(1, int(attempts)),
        changed_rel_paths=changed_rel_paths,
        error_message=error_message,
        stdout_tail=stdout_tail,
        stderr_tail=stderr_tail,
        log_text=_build_direct_edit_log(
            provider=provider,
            command=command,
            cwd=working_dir,
            exit_code=int(process.returncode),
            changed_rel_paths=changed_rel_paths,
            stdout_tail=stdout_tail,
            stderr_tail=stderr_tail,
            error_message=error_message,
            attempts=max(1, int(attempts)),
        ),
    )


def _patch_sdk_message_parser() -> None:
    """Patch the Agent SDK message parser to skip unknown message types.

    The Anthropic streaming API may send event types (e.g.
    ``rate_limit_event``) that the SDK does not recognise.  The SDK's
    ``parse_message`` raises ``MessageParseError`` on these, which kills
    the async generator — Python cannot resume iteration after an
    exception.  This patch replaces the parser so that unrecognised
    types return ``None`` instead of raising, allowing the stream to
    continue.
    """
    try:
        from claude_agent_sdk._internal import client as _sdk_client_mod
        from claude_agent_sdk._internal import message_parser as _mp

        _original_parse = _mp.parse_message

        def _safe_parse_message(data: dict) -> object:
            try:
                return _original_parse(data)
            except Exception:
                # Unknown / unrecognised message type — skip silently.
                return None

        # Patch the module-level reference so InternalClient.process_query
        # picks up the safe version.
        _sdk_client_mod.parse_message = _safe_parse_message  # type: ignore[assignment]
    except Exception:
        # If the internal SDK layout changes, silently ignore and let
        # the original behaviour remain.
        pass


def _run_claude_agent_sdk_direct_edit(
    *,
    prompt: str,
    working_dir: Path,
    model: str | None,
    max_turns: int = _AGENT_SDK_MAX_TURNS,
    timeout_seconds: int = 180,
) -> LLMDirectEditResult:
    """Run Claude Agent SDK with Read/Write/Edit tools for direct file edits.

    Non-fatal stream events (e.g. ``rate_limit_event``) that the SDK does
    not recognise are silently ignored so the stream can complete normally.
    """
    try:
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            ResultMessage,
            TextBlock,
            ToolUseBlock,
            query,
        )
    except ImportError:
        return LLMDirectEditResult(
            ok=False,
            provider=LLMProvider.CLAUDE,
            error_message="claude-agent-sdk not installed.",
        )

    _EDIT_TOOLS = {"Write", "Edit", "MultiEdit"}

    effective_timeout = max(10, int(timeout_seconds))
    options = ClaudeAgentOptions(
        model=model,
        cwd=str(working_dir),
        allowed_tools=["Read", "Write", "Edit"],
        permission_mode="bypassPermissions",
        max_turns=max(1, max_turns),
    )

    log_lines: list[str] = [
        "Provider: claude (Agent SDK)",
        f"Model: {model or 'default'}",
        f"CWD: {working_dir}",
    ]
    final_text: list[str] = []
    result_msg: ResultMessage | None = None
    stream_error: str = ""
    got_edit_tool_calls: bool = False

    async def _run() -> None:
        nonlocal result_msg, stream_error, got_edit_tool_calls
        try:
            async for message in query(prompt=prompt, options=options):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            final_text.append(block.text)
                        elif isinstance(block, ToolUseBlock):
                            if block.name in _EDIT_TOOLS:
                                got_edit_tool_calls = True
                            log_lines.append(f"  Tool: {block.name}({_summarize_tool_input(block.input)})")
                elif isinstance(message, ResultMessage):
                    result_msg = message
        except Exception as exc:
            stream_error = str(exc)
            log_lines.append(f"  Stream interrupted: {stream_error}")

    saved_env = _clear_claude_session_env()
    try:
        asyncio.run(asyncio.wait_for(_run(), timeout=float(effective_timeout)))
    except asyncio.TimeoutError:
        return LLMDirectEditResult(
            ok=False,
            provider=LLMProvider.CLAUDE,
            error_message=f"Agent SDK timed out after {effective_timeout}s",
            log_text="\n".join(log_lines),
        )
    except Exception as exc:
        return LLMDirectEditResult(
            ok=False,
            provider=LLMProvider.CLAUDE,
            error_message=str(exc),
            log_text="\n".join(log_lines),
        )
    finally:
        _restore_claude_session_env(saved_env)

    if result_msg is not None:
        cost = getattr(result_msg, "total_cost_usd", None) or 0
        turns = getattr(result_msg, "num_turns", "?")
        log_lines.append(f"Turns: {turns}, Cost: ${cost:.4f}")
        is_error = getattr(result_msg, "is_error", False)
        if is_error:
            error_text = getattr(result_msg, "result", "") or "Agent SDK error"
            return LLMDirectEditResult(
                ok=False,
                provider=LLMProvider.CLAUDE,
                error_message=str(error_text),
                log_text="\n".join(log_lines),
            )

    # If the stream broke but the agent already made edit tool calls,
    # treat as success so the caller inspects the workspace for changes.
    if stream_error and got_edit_tool_calls:
        return LLMDirectEditResult(
            ok=True,
            provider=LLMProvider.CLAUDE,
            command=[f"claude-agent-sdk:{model or 'default'}"],
            log_text="\n".join(log_lines),
            stdout_tail=_tail_text("\n".join(final_text)),
        )

    if stream_error:
        return LLMDirectEditResult(
            ok=False,
            provider=LLMProvider.CLAUDE,
            error_message=stream_error,
            log_text="\n".join(log_lines),
        )

    # Clean completion.
    return LLMDirectEditResult(
        ok=True,
        provider=LLMProvider.CLAUDE,
        command=[f"claude-agent-sdk:{model or 'default'}"],
        log_text="\n".join(log_lines),
        stdout_tail=_tail_text("\n".join(final_text)),
    )


def _summarize_tool_input(tool_input: dict | str | None) -> str:
    """Format tool input for log display."""
    if not tool_input:
        return ""
    if isinstance(tool_input, str):
        return tool_input[:80]
    if isinstance(tool_input, dict):
        if "file_path" in tool_input:
            return str(tool_input["file_path"])
        if "command" in tool_input:
            cmd = tool_input["command"]
            return cmd[:80] if isinstance(cmd, str) else str(cmd)[:80]
        return str(tool_input)[:80]
    return str(tool_input)[:80]


def _clear_claude_session_env() -> dict[str, str]:
    """Remove Claude Code session env vars; return saved values for restore."""
    saved: dict[str, str] = {}
    for key in _CLAUDE_SESSION_ENV_VARS:
        value = os.environ.pop(key, None)
        if value is not None:
            saved[key] = value
    return saved


def _restore_claude_session_env(saved: dict[str, str]) -> None:
    """Restore previously cleared Claude Code session env vars."""
    for key, value in saved.items():
        os.environ[key] = value


def _non_interactive_env() -> dict[str, str]:
    env = dict(os.environ)
    env["CI"] = "1"
    env["TERM"] = "dumb"
    env["NO_COLOR"] = "1"
    for key in _CLAUDE_SESSION_ENV_VARS:
        env.pop(key, None)
    return env


def _safe_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _snapshot_tree_hashes(root: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel_path = path.relative_to(root).as_posix()
        with contextlib.suppress(OSError):
            snapshot[rel_path] = _hash_path(path)
    return snapshot


def _hash_path(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _collect_changed_paths(
    before: dict[str, str],
    after: dict[str, str],
) -> list[str]:
    keys = sorted(set(before) | set(after))
    return [key for key in keys if before.get(key) != after.get(key)]


def _tail_text(
    text: str,
    *,
    max_chars: int = 5000,
    max_lines: int = 120,
) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    lines = normalized.splitlines()
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
    tail = "\n".join(lines)
    if len(tail) > max_chars:
        tail = tail[-max_chars:]
    return tail.strip()


def _build_direct_edit_log(
    *,
    provider: LLMProvider,
    command: list[str],
    cwd: Path,
    exit_code: int,
    changed_rel_paths: list[str],
    stdout_tail: str,
    stderr_tail: str,
    error_message: str,
    attempts: int,
) -> str:
    lines = [
        f"Provider: {provider.value}",
        f"Attempt: {attempts}",
        f"Command: {' '.join(command)}",
        f"CWD: {cwd}",
        f"Exit Code: {exit_code}",
    ]
    if changed_rel_paths:
        lines.append(f"Changed Files ({len(changed_rel_paths)}):")
        lines.extend(f"- {path}" for path in changed_rel_paths)
    else:
        lines.append("Changed Files (0):")
    if error_message:
        lines.append(f"Error: {error_message}")
    if stdout_tail:
        lines.extend(["", "STDOUT (tail):", stdout_tail])
    if stderr_tail:
        lines.extend(["", "STDERR (tail):", stderr_tail])
    return "\n".join(lines).strip()


# Warm the SDK availability cache at import time, before Textual takes over
# the terminal and potentially interferes with lazy imports.
_claude_agent_sdk_available()

# Patch the SDK message parser to tolerate unknown streaming event types
# (e.g. rate_limit_event) that would otherwise kill the async generator.
_patch_sdk_message_parser()

