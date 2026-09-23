"""
DeepSeek provider for NEO.

Uses the DeepSeek OpenAI-compatible Chat Completions API.

The Agent communicates only with the generic Provider interface.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any

import requests

from neo_code.logging_config import get_logger
from neo_code.providers.base import (
    Provider,
    ProviderResponse,
    ToolCall,
)

logger = get_logger(__name__)


class DeepSeekProvider(Provider):
    """
    DeepSeek API provider.

    Endpoint:
        https://api.deepseek.com/chat/completions

    Supported models:
        deepseek-chat
        deepseek-reasoner
    """

    id = "deepseek"

    DEFAULT_BASE_URL = "https://api.deepseek.com"

    def __init__(
        self,
        model: str = "deepseek-chat",
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: int = 120,
    ):
        super().__init__(model)

        # API key resolution order:
        # 1. Explicit constructor argument
        # 2. DEEPSEEK_API_KEY
        # 3. DEEPSEEK_KEY
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY") or os.getenv("DEEPSEEK_KEY")

        self.base_url = (
            base_url or os.getenv("DEEPSEEK_BASE_URL") or self.DEFAULT_BASE_URL
        ).rstrip("/")

        self.timeout = timeout

    # =========================================================
    # AVAILABILITY
    # =========================================================

    def is_available(self) -> str | None:
        """
        Return None when the provider is configured.

        IMPORTANT:
        This method only checks configuration.
        It does NOT perform a network request.
        """

        if not self.api_key:
            return (
                "DEEPSEEK_API_KEY is not configured. "
                "Set the environment variable or configure "
                "the provider key."
            )

        return None

    # =========================================================
    # COMPLETE
    # =========================================================

    def complete(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
    ) -> ProviderResponse:

        # -----------------------------------------------------
        # API key check
        # -----------------------------------------------------

        if not self.api_key:
            return ProviderResponse(
                text="DeepSeek API key is not configured.",
                stop_reason="error",
            )

        # -----------------------------------------------------
        # Build messages
        # -----------------------------------------------------

        payload_messages = self._build_messages(
            system_prompt,
            messages,
        )

        # -----------------------------------------------------
        # Base payload
        # -----------------------------------------------------

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": payload_messages,
            "temperature": 0.2,
        }

        # -----------------------------------------------------
        # Tool calling
        # -----------------------------------------------------

        if tool_schemas:

            converted_tools = self._convert_tools(tool_schemas)

            if converted_tools:
                payload["tools"] = converted_tools
                payload["tool_choice"] = "auto"

        # -----------------------------------------------------
        # Headers
        # -----------------------------------------------------

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        # -----------------------------------------------------
        # Endpoint
        # -----------------------------------------------------

        url = f"{self.base_url}/chat/completions"

        # -----------------------------------------------------
        # DEBUG-SAFE request information
        # -----------------------------------------------------
        #
        # NEVER print the API key.
        #
        # This gives us enough information to diagnose
        # HTTP 400 errors without exposing the secret.
        # -----------------------------------------------------

        try:

            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )

        except requests.Timeout as exc:

            return ProviderResponse(
                text=f"DeepSeek API timeout: {exc}",
                stop_reason="error",
            )

        except requests.ConnectionError as exc:

            return ProviderResponse(
                text=f"DeepSeek connection error: {exc}",
                stop_reason="error",
            )

        except requests.RequestException as exc:

            return ProviderResponse(
                text=f"DeepSeek request error: {exc}",
                stop_reason="error",
            )

        # -----------------------------------------------------
        # HTTP error handling (DEBUG)
        # -----------------------------------------------------

        if not response.ok:

            error_body = self._safe_response_text(response)

            # ---------- DEBUG LOGGING ----------
            # Emitted at DEBUG level (set NEO_LOG_LEVEL=DEBUG to see it)
            # instead of unconditional prints, so normal CLI sessions
            # stay clean.
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("DeepSeek HTTP error %s for %s", response.status_code, url)
                logger.debug("Model: %s", payload.get("model"))
                messages = payload.get("messages", [])
                logger.debug("Messages count: %d", len(messages))
                for i, msg in enumerate(messages):
                    content = msg.get("content")
                    if isinstance(content, str):
                        content_desc = f"str len={len(content)}"
                    elif isinstance(content, list):
                        content_desc = f"list len={len(content)}"
                    else:
                        content_desc = f"type={type(content).__name__}"
                    logger.debug(
                        "  msg[%d] role=%s keys=%s content=%s",
                        i,
                        msg.get("role"),
                        list(msg.keys()),
                        content_desc,
                    )
                tools = payload.get("tools", [])
                logger.debug("Tools: %d", len(tools))
                for t in tools:
                    logger.debug("  tool: %s", t.get("function", {}).get("name"))
                safe_payload = dict(payload)
                logger.debug(
                    "Payload (truncated): %s",
                    json.dumps(safe_payload, ensure_ascii=False)[:2000],
                )
            # ------------------------------

            return ProviderResponse(
                text=(f"DeepSeek API error " f"HTTP {response.status_code}: " f"{error_body}"),
                stop_reason="error",
                raw={
                    "status_code": response.status_code,
                    "body": error_body,
                },
            )

        # -----------------------------------------------------
        # JSON response
        # -----------------------------------------------------

        try:

            data = response.json()

        except ValueError as exc:

            return ProviderResponse(
                text=("Invalid DeepSeek JSON response: " f"{exc}"),
                stop_reason="error",
                raw=response.text,
            )

        # -----------------------------------------------------
        # Parse provider response
        # -----------------------------------------------------

        return self._parse_response(data)

    # =========================================================
    # MESSAGE CONVERSION
    # =========================================================

    def _build_messages(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:

        result: list[dict[str, Any]] = []

        # -----------------------------------------------------
        # System message
        # -----------------------------------------------------

        if system_prompt:

            result.append(
                {
                    "role": "system",
                    "content": system_prompt,
                }
            )

        # -----------------------------------------------------
        # Internal messages -> DeepSeek messages
        # -----------------------------------------------------

        for message in messages:

            if not isinstance(message, dict):
                continue

            role = message.get("role")
            content = message.get("content")

            # -------------------------------------------------
            # User / assistant
            # -------------------------------------------------

            if role in ("user", "assistant"):

                # Normal string content
                if isinstance(content, str):

                    item: dict[str, Any] = {
                        "role": role,
                        "content": content,
                    }

                    # Preserve tool_calls if supplied
                    if message.get("tool_calls"):
                        item["tool_calls"] = self._normalize_tool_calls(message["tool_calls"])

                    result.append(item)

                    continue

                # Structured content blocks
                if isinstance(content, list):

                    self._append_content_blocks(
                        result,
                        role,
                        content,
                    )

                    continue

            # -------------------------------------------------
            # Tool result
            # -------------------------------------------------

            elif role == "tool":

                tool_call_id = message.get("tool_call_id") or message.get("tool_use_id") or ""

                tool_content = message.get(
                    "content",
                    "",
                )

                if not isinstance(tool_content, str):

                    tool_content = json.dumps(
                        tool_content,
                        ensure_ascii=False,
                    )

                result.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": tool_content,
                    }
                )

        return result

    # =========================================================
    # CONTENT BLOCK CONVERSION
    # =========================================================

    def _append_content_blocks(
        self,
        output: list[dict[str, Any]],
        role: str,
        blocks: list[dict[str, Any]],
    ):

        text_parts: list[str] = []

        pending_tool_calls: list[dict[str, Any]] = []

        for block in blocks:

            if not isinstance(block, dict):
                continue

            block_type = block.get("type")

            # -------------------------------------------------
            # Text
            # -------------------------------------------------

            if block_type == "text":

                text = block.get(
                    "text",
                    "",
                )

                if text:
                    text_parts.append(str(text))

            # -------------------------------------------------
            # Tool use
            # -------------------------------------------------

            elif block_type == "tool_use":

                tool_id = block.get("id") or str(uuid.uuid4())

                tool_name = block.get("name")

                if not tool_name:
                    continue

                arguments = block.get(
                    "input",
                    {},
                )

                pending_tool_calls.append(
                    {
                        "id": tool_id,
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": self._json_dumps(arguments),
                        },
                    }
                )

            # -------------------------------------------------
            # Tool result
            # -------------------------------------------------

            elif block_type == "tool_result":

                tool_use_id = block.get("tool_use_id") or ""

                content = block.get(
                    "content",
                    "",
                )

                if not isinstance(content, str):

                    content = self._json_dumps(content)

                output.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_use_id,
                        "content": content,
                    }
                )

        # -----------------------------------------------------
        # Emit assistant message
        # -----------------------------------------------------

        if role == "assistant" and pending_tool_calls:

            assistant_message: dict[str, Any] = {
                "role": "assistant",
                "content": ("".join(text_parts) if text_parts else None),
                "tool_calls": pending_tool_calls,
            }

            output.append(assistant_message)

        elif text_parts:

            output.append(
                {
                    "role": role,
                    "content": "".join(text_parts),
                }
            )

    # =========================================================
    # TOOL SCHEMA CONVERSION
    # =========================================================

    def _convert_tools(
        self,
        tool_schemas: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:

        converted: list[dict[str, Any]] = []

        for tool in tool_schemas:

            if not isinstance(tool, dict):
                continue

            name = tool.get("name")

            if not name:
                continue

            description = tool.get(
                "description",
                "",
            )

            parameters = (
                tool.get("input_schema")
                or tool.get("parameters")
                or {
                    "type": "object",
                    "properties": {},
                }
            )

            converted.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": description,
                        "parameters": parameters,
                    },
                }
            )

        return converted

    # =========================================================
    # RESPONSE PARSING
    # =========================================================

    def _parse_response(
        self,
        data: dict[str, Any],
    ) -> ProviderResponse:

        if not isinstance(data, dict):

            return ProviderResponse(
                text="Invalid DeepSeek response structure.",
                stop_reason="error",
                raw=data,
            )

        choices = data.get("choices") or []

        if not choices:

            error = data.get("error")

            if error:

                return ProviderResponse(
                    text=("DeepSeek API error: " + self._format_error(error)),
                    stop_reason="error",
                    raw=data,
                )

            return ProviderResponse(
                text="DeepSeek returned no choices.",
                stop_reason="error",
                raw=data,
            )

        choice = choices[0] or {}

        message = choice.get("message") or {}

        # -----------------------------------------------------
        # Text
        # -----------------------------------------------------

        text = message.get("content") or ""

        if not isinstance(text, str):

            text = str(text)

        # -----------------------------------------------------
        # Tool calls
        # -----------------------------------------------------

        tool_calls: list[ToolCall] = []

        for call in message.get("tool_calls") or []:

            if not isinstance(call, dict):
                continue

            function = call.get("function") or {}

            name = function.get("name")

            if not name:
                continue

            arguments = self._parse_json(
                function.get(
                    "arguments",
                    "{}",
                )
            )

            tool_calls.append(
                ToolCall(
                    id=(call.get("id") or str(uuid.uuid4())),
                    name=name,
                    arguments=arguments,
                )
            )

        # -----------------------------------------------------
        # Finish reason
        # -----------------------------------------------------

        finish_reason = choice.get("finish_reason") or "stop"

        return ProviderResponse(
            text=text,
            tool_calls=tool_calls,
            stop_reason=finish_reason,
            raw=data,
        )

    # =========================================================
    # TOOL CALL NORMALIZATION
    # =========================================================

    @staticmethod
    def _normalize_tool_calls(
        calls: Any,
    ) -> list[dict[str, Any]]:

        if not isinstance(calls, list):
            return []

        normalized = []

        for call in calls:

            if not isinstance(call, dict):
                continue

            function = call.get("function") or {}

            name = function.get("name")

            if not name:
                continue

            arguments = function.get(
                "arguments",
                "{}",
            )

            if isinstance(arguments, dict):

                arguments = json.dumps(
                    arguments,
                    ensure_ascii=False,
                )

            normalized.append(
                {
                    "id": (call.get("id") or str(uuid.uuid4())),
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": arguments,
                    },
                }
            )

        return normalized

    # =========================================================
    # SAFE RESPONSE TEXT
    # =========================================================

    @staticmethod
    def _safe_response_text(
        response: requests.Response,
    ) -> str:

        try:

            data = response.json()

            if isinstance(data, dict):

                error = data.get("error")

                if error:

                    return DeepSeekProvider._format_error(error)

                return json.dumps(
                    data,
                    ensure_ascii=False,
                )

        except ValueError:
            pass

        text = response.text.strip()

        if not text:
            return "<empty response>"

        return text

    # =========================================================
    # ERROR FORMAT
    # =========================================================

    @staticmethod
    def _format_error(
        error: Any,
    ) -> str:

        if isinstance(error, str):
            return error

        if isinstance(error, dict):

            message = error.get("message")

            error_type = error.get("type")

            code = error.get("code")

            parts = []

            if message:
                parts.append(str(message))

            if error_type:
                parts.append(f"type={error_type}")

            if code:
                parts.append(f"code={code}")

            if parts:
                return " | ".join(parts)

        return str(error)

    # =========================================================
    # JSON HELPERS
    # =========================================================

    @staticmethod
    def _json_dumps(
        value: Any,
    ) -> str:

        try:

            return json.dumps(
                value,
                ensure_ascii=False,
            )

        except (
            TypeError,
            ValueError,
        ):

            return "{}"

    @staticmethod
    def _parse_json(
        value: Any,
    ) -> dict[str, Any]:

        if isinstance(value, dict):
            return value

        if not value:
            return {}

        if not isinstance(value, str):
            return {}

        try:

            result = json.loads(value)

            if isinstance(result, dict):
                return result

        except (
            TypeError,
            ValueError,
        ):

            pass

        return {}
