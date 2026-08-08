"""
Stage 2: Grounder — precise coordinate prediction within a candidate region.

Takes a cropped image patch and returns the exact pixel coordinates of the target element.

This implements Stage 2 of the ScreenSeekeR framework (arXiv 2504.07981):
  "The grounder model is invoked if the patch size is sufficiently small,
   and the planner verifies the correctness of the bounding box."

Backend is configurable via GROUNDER_BACKEND env variable:
  - "gemini"  : Uses Gemini API (default, CPU-friendly, no local model)
  - "ollama"  : Uses Qwen2.5-VL via Ollama (CPU-friendly local model)
  - "osatlas" : Uses OS-Atlas-7B via HuggingFace (needs GPU)
"""

import json
import re
import io
from dataclasses import dataclass

from PIL import Image
from tenacity import retry, stop_after_attempt, wait_exponential

from src.utils.config import (
    GEMINI_API_KEY,
    GEMINI_GROUNDER_MODEL,
    GROUNDER_BACKEND,
    GROQ_GROUNDER_MODEL,
    SBG_GROUNDER_MODEL,
)
from src.utils.logger import logger
from src.grounding.prompts import GROUNDER_SYSTEM_PROMPT, GROUNDER_USER_PROMPT_TEMPLATE
from src.capturer.screen_capture import image_to_base64_compressed


@dataclass
class GroundingResult:
    """Result from the grounder for a single image patch."""
    found: bool
    confidence: float
    center_x: float        # Normalized 0.0-1.0 within the patch
    center_y: float        # Normalized 0.0-1.0 within the patch
    bbox: list[float]      # [x1, y1, x2, y2] normalized within the patch
    reasoning: str


class Grounder:
    """
    Precise GUI element locator (Stage 2 of ScreenSeekeR).

    Accepts a small cropped image patch and returns exact coordinates
    of the target element within that patch.

    Uses the configured backend (Gemini by default for CPU-only systems).
    """

    def __init__(self) -> None:
        self._backend = GROUNDER_BACKEND
        self._sbg_model = SBG_GROUNDER_MODEL

        self._groq_failed = False
        self._sbg_failed = False
        self._sambanova_failed = False
        logger.info(f"Grounder initialized with backend: {self._backend}")

        if self._backend == "gemini":
            self._init_gemini()
        elif self._backend == "sbg":
            self._init_sbg()
            self._init_groq()   # Groq as fallback for SBG
        elif self._backend == "groq":
            self._init_groq()
            self._init_sbg()    # SBG as fallback for Groq
        else:
            logger.warning(f"Unknown backend '{self._backend}', falling back to gemini")
            self._backend = "gemini"
            self._init_gemini()

        # Always initialize Gemini as last-resort fallback
        if self._backend != "gemini":
            self._init_gemini()

    def _init_gemini(self) -> None:
        from google import genai
        self._client = genai.Client(api_key=GEMINI_API_KEY)
        self._gemini_model = GEMINI_GROUNDER_MODEL

    def _init_groq(self) -> None:
        self._groq_model = GROQ_GROUNDER_MODEL
        logger.info(f"Groq grounder initialized: {self._groq_model}")

    def _init_sbg(self) -> None:
        from src.utils.config import SBG_BASE_URL, SBG_API_KEY, SBG_GROUNDER_MODEL
        self._sbg_url = SBG_BASE_URL.rstrip("/")
        if not self._sbg_url.endswith("/student/chat"):
            self._sbg_url += "/student/chat"
        self._sbg_key = SBG_API_KEY
        self._sbg_model = SBG_GROUNDER_MODEL
        logger.info(f"SBG grounder initialized: {self._sbg_model}")

    @retry(
        stop=stop_after_attempt(6),
        wait=wait_exponential(multiplier=2, min=5, max=30),
        reraise=True,
    )
    def ground(
        self,
        target_description: str,
        patch: Image.Image,
    ) -> GroundingResult:
        """
        Find the exact location of the target within a cropped image patch.

        Args:
            target_description: Natural language description of the target
            patch: Cropped PIL Image (a candidate region from the planner)

        Returns:
            GroundingResult with normalized coordinates within the patch
        """
        logger.debug(f"Grounder: locating '{target_description}' in {patch.width}x{patch.height} patch")

        # Determine order of backends to try based on primary backend
        if self._backend == "groq":
            backends_to_try = ["groq", "sbg", "gemini"]
        elif self._backend == "sbg":
            backends_to_try = ["sbg", "groq", "gemini"]
        else:
            backends_to_try = ["gemini"]

        last_error = None
        for b in backends_to_try:
            if b == "groq" and self._groq_failed:
                continue
            if b == "sbg" and self._sbg_failed:
                continue

            try:
                if b == "groq":
                    logger.debug("Calling Grounder backend: groq...")
                    result = self._ground_groq(target_description, patch)
                elif b == "sbg":
                    logger.debug("Calling Grounder backend: sbg...")
                    result = self._ground_sbg(target_description, patch)
                else:
                    logger.debug("Calling Grounder backend: gemini...")
                    result = self._ground_gemini_with_retry(target_description, patch)
                return result
            except Exception as e:
                err_str = str(e)
                if b == "groq":
                    if "429" in err_str or "rate_limit" in err_str.lower() or "too many" in err_str.lower():
                        logger.warning("Groq Grounder rate limited. Disabling Groq fallback.")
                    else:
                        logger.warning(f"Groq Grounder error: {e}. Disabling Groq fallback.")
                    self._groq_failed = True
                elif b == "sbg":
                    if "403" in err_str or "429" in err_str or "daily limit" in err_str.lower() or "too many" in err_str.lower():
                        logger.warning("SBG Grounder rate/auth limited. Disabling SBG fallback.")
                    else:
                        logger.warning(f"SBG Grounder error: {e}. Disabling SBG fallback.")
                    self._sbg_failed = True
                else:
                    logger.warning(f"Gemini Grounder error: {e}")
                
                logger.info(f"Grounder backend '{b}' failed, falling back to next...")
                last_error = e
                continue
        
        logger.error(f"All Grounder backends failed. Last error: {last_error}")
        return _not_found_result()

    def _ground_sbg(self, target_description: str, patch: Image.Image) -> GroundingResult:
        """Ground using custom SBG Gateway API."""
        import requests

        # The Qwen-VL model hallucinates that cropped patches are blank if they are small or have irregular aspect ratios.
        # We resize the patch proportionally so its longest edge is 1024 pixels. 
        # This keeps the image large enough to prevent the Qwen-VL blank hallucination bug,
        # avoids adding black borders, and prevents distortion!
        # Because we only scale the image, the relative coordinates (0.0-1.0) remain identical.
        orig_w, orig_h = patch.size
        scale = 1024.0 / max(orig_w, orig_h)
        new_w = int(orig_w * scale)
        new_h = int(orig_h * scale)
        scaled_img = patch.resize((new_w, new_h), Image.LANCZOS)
        
        # Create a JPEG-compressed version for SBG
        sbg_img_b64 = image_to_base64_compressed(scaled_img, max_width=1024, quality=85)

        prompt = GROUNDER_USER_PROMPT_TEMPLATE.format(target_description=target_description)

        # Payload format matches catalog_order_agent's sbg_model.py
        payload = {
            "model_id": self._sbg_model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "system_prompt": GROUNDER_SYSTEM_PROMPT,
            "image": sbg_img_b64,
            "max_tokens": 2048,
        }

        response = requests.post(
            self._sbg_url,
            headers={
                "Authorization": f"Bearer {self._sbg_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60,
        )
        response.raise_for_status()

        data = response.json()

        result_text = ""
        if "output_text" in data:
            result_text = data["output_text"]
        elif "choices" in data and len(data["choices"]) > 0:
            result_text = data["choices"][0].get("message", {}).get("content", "")
        elif "content" in data:
            result_text = data["content"]
        else:
            result_text = str(data)

        return self._parse_response(result_text, target_description)

    def _ground_groq(self, target_description: str, patch: Image.Image) -> GroundingResult:
        """Ground using Groq API with vision support, with automatic key rotation on 429s."""
        import groq
        from src.utils.config import get_next_groq_key, GROQ_API_KEYS

        prompt = GROUNDER_USER_PROMPT_TEMPLATE.format(target_description=target_description)
        sbg_img_b64 = image_to_base64_compressed(patch, max_width=1280, quality=85)

        max_attempts = len(GROQ_API_KEYS) if GROQ_API_KEYS else 1
        
        for attempt in range(max_attempts):
            client = groq.Groq(api_key=get_next_groq_key())
            try:
                response = client.chat.completions.create(
                    model=self._groq_model,
                    messages=[
                        {"role": "system", "content": GROUNDER_SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/jpeg;base64,{sbg_img_b64}"},
                                },
                                {"type": "text", "text": prompt},
                            ],
                        },
                    ],
                    max_tokens=1536,
                    temperature=0.0,
                )
                raw_text = response.choices[0].message.content or ""
                return self._parse_response(raw_text, target_description)
            except Exception as e:
                if "429" in str(e) and attempt < max_attempts - 1:
                    logger.warning(f"Groq API rate limited. Rotating to next key (attempt {attempt+1}/{max_attempts})...")
                    continue
                raise

    def _ground_gemini_with_retry(self, target_description: str, patch, max_wait: int = 60):
        """Call Gemini grounder, handling 429 rate limit by waiting and retrying."""
        import time
        for attempt in range(4):
            try:
                return self._ground_gemini(target_description, patch)
            except Exception as e:
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    wait = min(30 * (attempt + 1), max_wait)
                    logger.warning(f"Gemini rate limited (429). Waiting {wait}s before retry {attempt+1}/3...")
                    time.sleep(wait)
                else:
                    raise
        return self._ground_gemini(target_description, patch)

    def _ground_gemini(self, target_description: str, patch: Image.Image) -> GroundingResult:
        """Ground using Gemini API."""
        from google.genai import types

        prompt = GROUNDER_USER_PROMPT_TEMPLATE.format(target_description=target_description)

        # Encode patch as base64
        buf = io.BytesIO()
        patch.save(buf, format="PNG")
        img_bytes = buf.getvalue()

        image_part = types.Part.from_bytes(data=img_bytes, mime_type="image/png")

        response = self._client.models.generate_content(
            model=self._gemini_model,
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_text(
                            text=GROUNDER_SYSTEM_PROMPT + "\n\n" + prompt
                        ),
                        image_part,
                    ],
                )
            ],
            config=types.GenerateContentConfig(
                temperature=0.1,      # Very low — we want precise, deterministic coords
                max_output_tokens=512,
            ),
        )

        return self._parse_response(response.text, target_description)

    def _parse_response(self, raw_text: str, target_description: str) -> GroundingResult:
        """Parse the grounder's JSON response."""
        logger.debug(f"Grounder raw response:\n{raw_text}")
        try:
            json_str = _extract_json(raw_text)
            data = json.loads(json_str)

            found = bool(data.get("found", False))
            confidence = float(data.get("confidence", 0.0))

            if not found or confidence < 0.1:
                logger.debug("Grounder: element not found in this patch")
                return _not_found_result()

            cx = float(data.get("center_x", 0.5))
            cy = float(data.get("center_y", 0.5))
            bbox = data.get("bbox", [max(0, cx-0.1), max(0, cy-0.1),
                                      min(1, cx+0.1), min(1, cy+0.1)])

            # Clamp coordinates
            cx = max(0.0, min(1.0, cx))
            cy = max(0.0, min(1.0, cy))

            result = GroundingResult(
                found=True,
                confidence=confidence,
                center_x=cx,
                center_y=cy,
                bbox=[max(0.0, min(1.0, v)) for v in bbox],
                reasoning=data.get("reasoning", ""),
            )
            logger.debug(
                f"Grounder: found=True conf={confidence:.2f} "
                f"center=({cx:.3f},{cy:.3f})"
            )
            return result

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(f"Grounder JSON parse error: {e}. Attempting regex fallback...")
            
            # If Qwen truncates before outputting JSON, we can often extract the last mentioned coordinates!
            match = re.search(r"x:\s*~?0\.(\d+)[,\s\n]+y:\s*~?0\.(\d+)", raw_text, re.IGNORECASE)
            if not match:
                match = re.search(r"x\s*=\s*~?0\.(\d+)[,\s\n]+y\s*=\s*~?0\.(\d+)", raw_text, re.IGNORECASE)
            if not match:
                match = re.search(r"Center:\s*~?0\.(\d+)[,\s]+~?0\.(\d+)", raw_text, re.IGNORECASE)
                
            if match:
                cx = float(f"0.{match.group(1)}")
                cy = float(f"0.{match.group(2)}")
                logger.info(f"Regex extracted center: ({cx}, {cy})")
                return GroundingResult(
                    found=True, confidence=0.85,
                    center_x=cx, center_y=cy,
                    bbox=[max(0.0, cx-0.05), max(0.0, cy-0.05), min(1.0, cx+0.05), min(1.0, cy+0.05)],
                    reasoning="Regex fallback extraction"
                )
                
            return _not_found_result()


def _not_found_result() -> GroundingResult:
    return GroundingResult(
        found=False, confidence=0.0,
        center_x=0.5, center_y=0.5,
        bbox=[0.0, 0.0, 1.0, 1.0],
        reasoning="Element not found in patch",
    )


def _extract_json(text: str) -> str:
    """Extract JSON from text, stripping <think> blocks and markdown fences."""
    # Strip <think>...</think> blocks from reasoning models
    text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE).strip()
    # If there's an unclosed <think> tag, strip it and everything after it
    text = re.sub(r"<think>[\s\S]*$", "", text, flags=re.IGNORECASE).strip()
    
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if match:
        return match.group(1).strip()
        
    # Non-greedy search for all {...} blocks
    matches = re.findall(r"\{[\s\S]*?\}", text)
    if matches:
        # Return the last valid-looking block (often the final JSON output after reasoning)
        return matches[-1]
    return text.strip()
