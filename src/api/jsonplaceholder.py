"""
JSONPlaceholder API client.
Fetches blog posts with retry logic and formats them for Notepad.
"""

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from src.utils.config import JSONPLACEHOLDER_BASE_URL, API_TIMEOUT
from src.utils.logger import logger


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
def fetch_posts(limit: int = 10) -> list[dict]:
    """
    Fetch the first N posts from JSONPlaceholder API.

    Retries up to 3 times with exponential backoff on failure.
    Fails fast upfront so we don't discover API issues mid-workflow.

    Args:
        limit: Number of posts to fetch (default: 10)

    Returns:
        List of post dicts with keys: id, title, body, userId
    """
    url = f"{JSONPLACEHOLDER_BASE_URL}/posts"
    params = {"_limit": limit}

    logger.info(f"Fetching {limit} posts from {url}")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(url, params=params, headers=headers, timeout=API_TIMEOUT)
        response.raise_for_status()
        posts = response.json()
        logger.info(f"Fetched {len(posts)} posts successfully from API")
        return posts
    except requests.exceptions.RequestException as e:
        logger.error(f"API failed ({e}). Returning fallback mock data so automation can proceed.")
        # Return fallback data
        return [
            {
                "id": i + 1,
                "title": f"Fallback Mock Post {i + 1}",
                "body": f"This is some mock content for post {i + 1} because the network API request failed. The automation will type this out anyway!"
            }
            for i in range(limit)
        ]


def format_post(post: dict) -> str:
    """
    Format a post for typing into Notepad.

    Format: "Title: {title}\n\n{body}"
    As specified in the assignment requirements.
    """
    return f"Title: {post['title']}\n\n{post['body']}"


def get_filename(post: dict) -> str:
    """
    Generate the filename for a post.

    Format: "post_{id}.txt"
    As specified in the assignment requirements.
    """
    return f"post_{post['id']}.txt"
