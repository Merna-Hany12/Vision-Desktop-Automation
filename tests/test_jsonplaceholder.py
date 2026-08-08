from src.api.jsonplaceholder import format_post, get_filename


def test_post_format_matches_assignment_requirement() -> None:
    post = {"id": 7, "title": "A title", "body": "A body"}

    assert format_post(post) == "Title: A title\n\nA body"


def test_filename_uses_post_id() -> None:
    assert get_filename({"id": 10}) == "post_10.txt"
