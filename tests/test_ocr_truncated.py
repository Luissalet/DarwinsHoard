"""Repository links that a post cut short are completed from the owner's repositories, or not taken as links."""

from darwin_hoard import ocr

REPOS = {"addyosmani": ["agent-skills", "web-vitals"], "mattpocock": ["skills", "ts-reset", "skillful"], "ghost": None}


def lookup(owner):
    return REPOS.get(owner)


def test_single_match_is_completed():
    text, done = ocr.complete_truncated("2. Addy's skills github.com/addyosmani/age... more", lookup)
    assert "https://github.com/addyosmani/agent-skills" in text and done == ["addyosmani/agent-skills"]


def test_ambiguous_or_unknown_owner_is_not_a_link():
    text, done = ocr.complete_truncated("github.com/mattpocock/ski… and github.com/ghost/thing...", lookup)
    assert done == []
    assert "github.com/mattpocock" not in text and "github.com/ghost" not in text
    assert "mattpocock/ski" in text


def test_whole_links_are_left_alone():
    text, done = ocr.complete_truncated("see github.com/addyosmani/web-vitals today", lookup)
    assert text == "see github.com/addyosmani/web-vitals today" and done == []
