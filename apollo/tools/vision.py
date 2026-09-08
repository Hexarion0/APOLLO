"""
apollo/tools/vision.py — Vision and image analysis tools for APOLLO.

Tools:
  - AnalyzeImageTool : Inspect, OCR, analyze UI, and describe images via vision model.
"""

import base64
import logging
import mimetypes
from pathlib import Path
from typing import Any, Dict, Optional

import aiohttp

from apollo.providers.base import BaseLLMProvider
from apollo.tools.base import BaseTool

logger = logging.getLogger("apollo.tools.vision")

SUPPORTED_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}

class AnalyzeImageTool(BaseTool):
    """Tool to inspect, analyze, OCR, and describe images using vision-capable LLM."""

    name = "analyze_image"
    description = (
        "Inspect, OCR, describe, or extract information from an image file on the local filesystem "
        "or from an image URL using a multimodal vision model."
    )
    parameters = {
        "type": "object",
        "properties": {
            "image_path": {
                "type": "string",
                "description": "Path to local image file (e.g. '~/Pictures/Screenshots/error.png') or image URL.",
            },
            "prompt": {
                "type": "string",
                "description": "Optional specific question, OCR request, or instructions for analyzing the image. "
                               "Defaults to detailed analysis.",
            },
        },
        "required": ["image_path"],
    }

    def __init__(self, provider: Optional[BaseLLMProvider] = None):
        self.provider = provider

    async def execute(self, image_path: str, prompt: Optional[str] = None) -> str:
        if not image_path or not str(image_path).strip():
            return "Error: image_path cannot be empty."

        clean_path = str(image_path).strip()
        analysis_prompt = prompt.strip() if prompt and prompt.strip() else (
            "Please analyze and describe this image in detail. Extract any visible text/code, "
            "explain any diagrams/UI elements, and highlight key details."
        )

        image_bytes: bytes = b""
        mime_type = "image/jpeg"

        # Check if remote URL
        if clean_path.startswith("http://") or clean_path.startswith("https://"):
            try:
                timeout = aiohttp.ClientTimeout(total=20)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(clean_path) as resp:
                        if resp.status != 200:
                            return f"Error fetching image from URL: HTTP status {resp.status}"
                        image_bytes = await resp.read()
                        content_type = resp.headers.get("Content-Type", "")
                        if content_type.startswith("image/"):
                            mime_type = content_type.split(";")[0].strip()
                        else:
                            # fallback by extension
                            ext = Path(clean_path.split("?")[0]).suffix.lower()
                            mime_type = SUPPORTED_MIME_TYPES.get(ext, "image/jpeg")
            except Exception as e:
                logger.error(f"Error fetching image URL '{clean_path}': {e}")
                return f"Error fetching remote image URL: {e}"
        else:
            # Local file
            local_path = Path(clean_path).expanduser().resolve()
            if not local_path.exists():
                return f"Error: Image file does not exist at '{local_path}'."
            if not local_path.is_file():
                return f"Error: Path '{local_path}' is not a file."

            ext = local_path.suffix.lower()
            if ext not in SUPPORTED_MIME_TYPES:
                guessed, _ = mimetypes.guess_type(str(local_path))
                if guessed and guessed.startswith("image/"):
                    mime_type = guessed
                else:
                    return f"Error: Unsupported image extension '{ext}'. Supported: {', '.join(SUPPORTED_MIME_TYPES.keys())}"
            else:
                mime_type = SUPPORTED_MIME_TYPES[ext]

            try:
                image_bytes = local_path.read_bytes()
            except Exception as e:
                logger.error(f"Error reading image file '{local_path}': {e}")
                return f"Error reading image file: {e}"

        if not image_bytes:
            return "Error: Image file/content is empty."

        b64_encoded = base64.b64encode(image_bytes).decode("utf-8")
        data_uri = f"data:{mime_type};base64,{b64_encoded}"

        if not self.provider:
            return "Error: No LLM provider configured on AnalyzeImageTool."

        try:
            return await self.provider.analyze_image(
                image_data_uri=data_uri,
                prompt=analysis_prompt,
            )
        except Exception as e:
            logger.error(f"Error analyzing image with vision provider: {e}")
            return f"Error performing vision analysis: {e}"
