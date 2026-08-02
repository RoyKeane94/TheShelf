"""Riso spine palette.

The colour is assigned by a stable hash of the essay id and follows the essay
everywhere it appears: the hero shelf, shelf strips, row markers, the essay page.
Stability matters more than distribution — a spine that changes colour between two
pages stops being a recognisable object.
"""

INKS = [
    {"bg": "#E8471E", "fg": "#FFFFFF", "light": False},
    {"bg": "#FBF9F3", "fg": "#0B1226", "light": True},
    {"bg": "#17B14B", "fg": "#062B12", "light": False},
    {"bg": "#071A63", "fg": "#FFFFFF", "light": False},
    {"bg": "#FF9E45", "fg": "#3A1A00", "light": False},
    {"bg": "#FFFFFF", "fg": "#0B1226", "light": True},
    {"bg": "#0A2AA0", "fg": "#FFFFFF", "light": False},
    {"bg": "#F5C542", "fg": "#3A2A00", "light": False},
]


def _scatter(n: int) -> int:
    """A fixed 32-bit integer mix, so neighbouring ids do not land in palette order."""
    n = (n ^ 61) ^ (n >> 16)
    n = (n + (n << 3)) & 0xFFFFFFFF
    n = n ^ (n >> 4)
    n = (n * 0x27D4EB2D) & 0xFFFFFFFF
    n = n ^ (n >> 15)
    return n


def ink_for(essay_id):
    """Return the ink dict for an essay id. Unsaved rows fall back to the first ink."""
    if not essay_id:
        return INKS[0]
    return INKS[_scatter(int(essay_id)) % len(INKS)]
