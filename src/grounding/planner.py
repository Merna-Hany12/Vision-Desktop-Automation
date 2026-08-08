"""
Stage 1: Planner — LLM-powered spatial inference.

Takes a full desktop screenshot and a natural language description of a target UI element.
Returns a ranked list of candidate screen regions where the target is likely located.

This implements Stage 1 of the ScreenSeekeR framework (arXiv 2504.07981):
  "The planner proposes the most possible areas to search within based on the screenshot."

Supports two backends:
  - "gemini"  : Google Gemini API (free tier)
"""

import json
import re
import base64
from dataclasses import dataclass

from tenacity import retry, stop_after_attempt, wait_exponential

from src.utils.config import (
    GEMINI_API_KEY,
    GEMINI_PLANNER_MODEL,
    PLANNER_BACKEND,
    NUM_CANDIDATES,
    GROQ_PLANNER_MODEL,
)
from src.utils.logger import logger
from src.grounding.prompts import PLANNER_SYSTEM_PROMPT, PLANNER_USER_PROMPT_TEMPLATE
from src.capturer.screen_capture import Screenshot, image_to_base64_compressed


@dataclass
class CandidateRegion:
    """A candidate screen region proposed by the planner."""
    bbox: list[float]        # [x1, y1, x2, y2] normalized 0.0-1.0
    confidence: float        # Planner's confidence (0.0-1.0)
    reasoning: str           # Planner's spatial reasoning for this region
    score: float = 0.0       # Updated by candidate_scorer after grounder runs


class Planner:
    """
    LLM-powered spatial planner (Stage 1 of ScreenSeekeR).

    Uses an LLM's visual understanding to identify probable regions in a screenshot
    where a described UI element might be located — without any template image.
    """

    def __init__(self) -> None:
        self._backend = PLANNER_BACKEND

        self._groq_failed = False
        self._sbg_failed = False
        logger.info(f"Planner backend: {self._backend}")

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
        self._gemini_model = GEMINI_PLANNER_MODEL
        logger.info(f"Planner initialized with Gemini model: {self._gemini_model}")

    def _init_groq(self) -> None:
        self._groq_model = GROQ_PLANNER_MODEL
        logger.info(f"Groq planner initialized: {self._groq_model}")

    def _init_sbg(self) -> None:
        from src.utils.config import SBG_BASE_URL, SBG_API_KEY, SBG_PLANNER_MODEL
        self._sbg_url = SBG_BASE_URL.rstrip("/")
        if not self._sbg_url.endswith("/student/chat"):
            self._sbg_url += "/student/chat"
        self._sbg_key = SBG_API_KEY
        self._sbg_model = SBG_PLANNER_MODEL
        logger.info(f"Planner initialized with SBG Gateway model: {self._sbg_model}")

    @retry(
        stop=stop_after_attempt(6),
        wait=wait_exponential(multiplier=2, min=5, max=30),
        reraise=True,
    )
    def infer_positions(
        self,
        target_description: str,
        screenshot: Screenshot,
        num_candidates: int = NUM_CANDIDATES,
    ) -> list[CandidateRegion]:
        """
        Analyze the screenshot and return candidate regions for the target.

        Args:
            target_description: Natural language description (e.g., "Notepad icon")
            screenshot: Full desktop screenshot
            num_candidates: How many candidate regions to request

        Returns:
            List of CandidateRegion, ordered by confidence (highest first)
        """
        logger.info(f"Planner: inferring positions for '{target_description}'")

        prompt = PLANNER_USER_PROMPT_TEMPLATE.format(
            target_description=target_description,
            num_candidates=num_candidates,
        )

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
                    logger.info("Calling Planner backend: groq...")
                    raw_text = self._call_groq(prompt, screenshot)
                elif b == "sbg":
                    logger.info("Calling Planner backend: sbg...")
                    raw_text = self._call_sbg(prompt, screenshot)
                else:
                    logger.info("Calling Planner backend: gemini...")
                    raw_text = self._call_gemini(prompt, screenshot)
                
                candidates = self._parse_response(raw_text, target_description)
                if candidates:
                    return candidates
            except Exception as e:
                err_str = str(e)
                if b == "groq":
                    if "429" in err_str or "rate limit" in err_str.lower() or "too many" in err_str.lower():
                        logger.warning("Groq Planner rate limited. Disabling Groq fallback.")
                    else:
                        logger.warning(f"Groq Planner error: {e}. Disabling Groq fallback.")
                    self._groq_failed = True
                elif b == "sbg":
                    if "403" in err_str or "429" in err_str or "daily limit" in err_str.lower() or "too many" in err_str.lower():
                        logger.warning("SBG Planner rate/auth limited. Disabling SBG fallback.")
                    else:
                        logger.warning(f"SBG Planner error: {e}. Disabling SBG fallback.")
                    self._sbg_failed = True
                else:
                    logger.warning(f"Gemini Planner error: {e}")
                
                logger.info(f"Planner backend '{b}' failed, falling back to next...")
                last_error = e
                continue

        logger.error(f"All Planner backends failed. Last error: {last_error}")
        return self._fallback_candidates()

    def _call_sbg(self, prompt: str, screenshot: Screenshot) -> str:
        """Call custom SBG API with image."""
        import requests

        # Compress screenshot for SBG API
        compressed_b64 = image_to_base64_compressed(screenshot.image, max_width=1024, quality=80)

        payload = {
            "model_id": self._sbg_model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "system_prompt": PLANNER_SYSTEM_PROMPT,
            "image": compressed_b64,
            "max_tokens": 2048,
        }

        endpoint = self._sbg_url
        response = requests.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {self._sbg_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60,
        )
        response.raise_for_status()

        data = response.json()

        # Handle the SBG Gateway response format (output_text) same as catalog_order_agent
        if "output_text" in data:
            return data["output_text"]
        elif "choices" in data and len(data["choices"]) > 0:
            return data["choices"][0].get("message", {}).get("content", "")
        elif "content" in data:
            return data["content"]
        else:
            return str(data)

    def _call_gemini_with_retry(self, prompt: str, screenshot, max_wait: int = 60) -> str:
        """Call Gemini, handling 429 rate limit by waiting and retrying."""
        import time
        for attempt in range(4):
            try:
                return self._call_gemini(prompt, screenshot)
            except Exception as e:
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    wait = min(30 * (attempt + 1), max_wait)
                    logger.warning(f"Gemini rate limited (429). Waiting {wait}s before retry {attempt+1}/3...")
                    time.sleep(wait)
                else:
                    raise
        return self._call_gemini(prompt, screenshot)

    def _call_groq(self, prompt: str, screenshot: Screenshot) -> str:
        """Call Groq API with vision support, with automatic key rotation on 429s."""
        import groq
        from src.utils.config import get_next_groq_key, GROQ_API_KEYS

        compressed_b64 = image_to_base64_compressed(screenshot.image, max_width=1024, quality=80)
        
        max_attempts = len(GROQ_API_KEYS) if GROQ_API_KEYS else 1
        
        for attempt in range(max_attempts):
            client = groq.Groq(api_key=get_next_groq_key())
            try:
                response = client.chat.completions.create(
                    model=self._groq_model,
                    messages=[
                        {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/jpeg;base64,{compressed_b64}"},
                                },
                                {"type": "text", "text": prompt},
                            ],
                        },
                    ],
                    max_tokens=1024,
                    temperature=0.0,
                )
                return response.choices[0].message.content or ""
            except Exception as e:
                if "429" in str(e) and attempt < max_attempts - 1:
                    logger.warning(f"Groq API rate limited. Rotating to next key (attempt {attempt+1}/{max_attempts})...")
                    continue
                raise

    def _call_gemini(self, prompt: str, screenshot) -> str:
        """Call Gemini API with image."""
        from google.genai import types

        image_part = types.Part.from_bytes(
            data=base64.b64decode(screenshot.base64_png),
            mime_type="image/png",
        )

        response = self._client.models.generate_content(
            model=self._gemini_model,
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_text(text=PLANNER_SYSTEM_PROMPT + "\n\n" + prompt),
                        image_part,
                    ],
                )
            ],
            config=types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=1024,
            ),
        )
        return response.text

    def _parse_response(
        self, raw_text: str, target_description: str
    ) -> list[CandidateRegion]:
        """Parse the planner's JSON response into CandidateRegion objects."""
        try:
            json_str = _extract_json(raw_text)
            data = json.loads(json_str)

            if data.get("target_found") is False:
                logger.info("Planner reported target_found=False. Bypassing LLM guesses and using deterministic grid search.")
                return self._fallback_candidates()

            candidates = []
            for item in data.get("candidates", []):
                bbox = item.get("bbox", [])
                if len(bbox) != 4:
                    continue

                # Validate normalized coordinates
                bbox = [max(0.0, min(1.0, float(v))) for v in bbox]

                # Ensure x2 > x1 and y2 > y1
                if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
                    logger.warning(f"Skipping invalid bbox: {bbox}")
                    continue

                candidates.append(CandidateRegion(
                    bbox=bbox,
                    confidence=float(item.get("confidence", 0.5)),
                    reasoning=item.get("reasoning", ""),
                ))

            # Sort by confidence descending
            candidates.sort(key=lambda c: c.confidence, reverse=True)
            return candidates

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(f"Planner parse error: {e}. Attempting fallback.")
            return self._fallback_candidates()

    def _fallback_candidates(self) -> list[CandidateRegion]:
        """
        Fallback: return a robust grid of regions covering the left and right edges.
        When the LLM cannot see a tiny icon in the 1920x1080 global view, 
        blind guessing is unreliable. This deterministic grid ensures we scan
        the common desktop icon areas systematically.
        """
        logger.warning("Using fallback grid search regions (target not found by Planner)")
        return [
            CandidateRegion([0.0, 0.0, 0.33, 1.0], 0.9, "Left Third"),
            CandidateRegion([0.33, 0.0, 0.66, 1.0], 0.8, "Middle Third"),
            CandidateRegion([0.66, 0.0, 1.0, 1.0], 0.7, "Right Third"),
        ]


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
        # Return the last valid-looking block
        return matches[-1]
    return text.strip()
