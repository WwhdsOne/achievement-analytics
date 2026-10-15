"""Parse Gamer Guides achievement reference values without network or database I/O."""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
import math
import re
from typing import Any
import unicodedata
from urllib.parse import urlsplit


class GuideParseError(ValueError):
    """Indicate an invalid guide URL, blocked page, or ambiguous reference value."""


_VOID_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
)
_NUMBER = r"(?:[0-9]+(?:\.[0-9]+)?)"
_UNIT = r"(?:hours?|hrs?|h|minutes?|mins?|min)"
_TIME_RANGE = re.compile(
    rf"(?P<low>{_NUMBER})\s*(?P<low_unit>{_UNIT})?\s*-\s*"
    rf"(?P<high>{_NUMBER})\s*(?P<high_unit>{_UNIT})",
    re.IGNORECASE,
)
_TIME_LOWER_BOUND = re.compile(rf"(?P<value>{_NUMBER})\s*\+\s*(?P<unit>{_UNIT})", re.IGNORECASE)
_TIME_SINGLE = re.compile(rf"(?P<value>{_NUMBER})\s*(?P<unit>{_UNIT})", re.IGNORECASE)
_TIME_UNITLESS_RANGE = re.compile(rf"(?P<low>{_NUMBER})\s*-\s*(?P<high>{_NUMBER})")
_TIME_UNITLESS_VALUE = re.compile(rf"(?P<value>{_NUMBER})\s*\+?")
_DIFFICULTY = re.compile(rf"(?P<value>{_NUMBER})\s*/\s*10")
_PLATFORM_TITLE = re.compile(r"\b(?:Xbox|PlayStation|PS[1-5])\b", re.IGNORECASE)
_MISSING_VALUES = frozenset({"", "n/a", "unknown"})


def normalize_game_name(value: str) -> str:
    """Normalize name typography and case while retaining edition and version words."""
    if not isinstance(value, str):
        raise GuideParseError("Game name must be a string.")
    # Remove trademarks before NFKC, which otherwise turns the trademark into 'TM'.
    normalized = unicodedata.normalize("NFKC", value.replace("™", "").replace("®", ""))
    return " ".join(normalized.casefold().split())


def validate_guide_url(value: str) -> str:
    """Validate a Steam achievement overview URL and canonicalize its hostname."""
    if not isinstance(value, str) or value != value.strip() or not value:
        raise GuideParseError("Guide URL must be a nonempty URL without surrounding whitespace.")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise GuideParseError("Guide URL contains a control character.")
    try:
        parsed = urlsplit(value)
    except ValueError as error:
        raise GuideParseError("Guide URL is malformed.") from error
    if parsed.scheme != "https" or parsed.netloc.casefold() not in {"gamerguides.com", "www.gamerguides.com"}:
        raise GuideParseError("Guide URL must use HTTPS on gamerguides.com without credentials or a port.")
    if parsed.query or parsed.fragment or "?" in value or "#" in value:
        raise GuideParseError("Guide URL must not contain a query string or fragment.")
    if not re.fullmatch(r"/[a-z0-9]+(?:-[a-z0-9]+)*/steam-achievements/overview", parsed.path):
        raise GuideParseError("Guide URL must point exactly to /{slug}/steam-achievements/overview.")
    return f"https://www.gamerguides.com{parsed.path}"


@dataclass
class _Capture:
    parts: list[str] = field(default_factory=list)
    closed: bool = False

    def text(self) -> str:
        return " ".join("".join(self.parts).split())


@dataclass
class _Chip:
    label: str
    values: list[_Capture] = field(default_factory=list)
    closed: bool = False


@dataclass
class _Element:
    tag: str
    ignored: bool
    capture: _Capture | None = None
    chip: _Chip | None = None


class _GuideHTMLParser(HTMLParser):
    def __init__(self, *, difficulty_only: bool = False) -> None:
        super().__init__(convert_charrefs=True)
        self.elements: list[_Element] = []
        self.headings: list[_Capture] = []
        self.titles: list[_Capture] = []
        self.chips: dict[str, list[_Chip]] = {"Difficulty": []}
        if not difficulty_only:
            self.chips["Time"] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        ignored = tag in {"script", "style"} or bool(self.elements and self.elements[-1].ignored)
        element = _Element(tag=tag, ignored=ignored)
        if not ignored:
            if tag in {"h1", "title"}:
                element.capture = _Capture()
                (self.headings if tag == "h1" else self.titles).append(element.capture)
            if "achv-roadmap-chip" in classes and attributes.get("title") in self.chips:
                if any(ancestor.chip is not None for ancestor in self.elements):
                    raise GuideParseError("Reference chips must not be nested.")
                label = attributes["title"]
                assert label is not None
                element.chip = _Chip(label=label)
                self.chips[label].append(element.chip)
            if "achv-roadmap-chip-value" in classes:
                chip = next((ancestor.chip for ancestor in reversed(self.elements) if ancestor.chip is not None), None)
                if chip is not None:
                    if element.capture is not None:
                        raise GuideParseError("A reference value must not also be a page heading.")
                    element.capture = _Capture()
                    chip.values.append(element.capture)
            if tag in {"br", "p", "div", "li"}:
                for ancestor in self.elements:
                    if ancestor.capture is not None:
                        ancestor.capture.parts.append(" ")
        if tag not in _VOID_TAGS:
            self.elements.append(element)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        matching_index = next(
            (index for index in range(len(self.elements) - 1, -1, -1) if self.elements[index].tag == tag),
            None,
        )
        if matching_index is None:
            return
        removed = self.elements[matching_index:]
        # A parent closing before its captured child is a malformed target node.
        for element in removed[1:]:
            if element.capture is not None or element.chip is not None:
                raise GuideParseError("A captured heading or reference node is not properly closed.")
        matching = self.elements[matching_index]
        if matching.capture is not None:
            matching.capture.closed = True
        if matching.chip is not None:
            matching.chip.closed = True
        del self.elements[matching_index:]

    def handle_data(self, data: str) -> None:
        if self.elements and self.elements[-1].ignored:
            return
        for element in self.elements:
            if element.capture is not None:
                element.capture.parts.append(data)


def _finite_number(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise GuideParseError("Reference numbers must be finite and nonnegative.")
    return number


def _unit_factor(unit: str) -> float:
    return 1 / 60 if unit.casefold().startswith("min") else 1.0


def _parse_time(value: str | None, warnings: list[str] | None = None, *,
                unitless_time_as_hours: bool = True) -> tuple[float | None, float | None]:
    if value is None:
        return None, None
    normalized = " ".join(unicodedata.normalize("NFKC", value).casefold().split())
    if not normalized or (not unitless_time_as_hours and normalized in _MISSING_VALUES):
        return None, None
    normalized = re.sub(r"[\u2010-\u2015\u2212]", "-", normalized)
    if matched := _TIME_RANGE.fullmatch(normalized):
        low_unit = matched.group("low_unit")
        high_factor = _unit_factor(matched.group("high_unit"))
        if low_unit is not None and _unit_factor(low_unit) != high_factor:
            raise GuideParseError(f"Time range has inconsistent units: {value!r}.")
        low = _finite_number(matched.group("low")) * high_factor
        high = _finite_number(matched.group("high")) * high_factor
        if low > high:
            raise GuideParseError(f"Time range is reversed: {value!r}.")
        return low, high
    if matched := _TIME_LOWER_BOUND.fullmatch(normalized):
        return _finite_number(matched.group("value")) * _unit_factor(matched.group("unit")), None
    if matched := _TIME_SINGLE.fullmatch(normalized):
        hours = _finite_number(matched.group("value")) * _unit_factor(matched.group("unit"))
        return hours, hours
    if matched := _TIME_UNITLESS_RANGE.fullmatch(normalized):
        low = _finite_number(matched.group("low"))
        high = _finite_number(matched.group("high"))
        if low > high:
            raise GuideParseError(f"Time range is reversed: {value!r}.")
        hours = (low, high)
    elif matched := _TIME_UNITLESS_VALUE.fullmatch(normalized):
        number = _finite_number(matched.group("value"))
        hours = (number, number)
    else:
        raise GuideParseError(f"Unrecognized reference time: {value!r}.")
    if warnings is not None:
        warnings.append("Unitless Time numbers are treated as hours by the project rule." if unitless_time_as_hours else
                        "Time reference lacks an explicit unit; hour bounds are left NULL.")
    return hours if unitless_time_as_hours else (None, None)


def _parse_difficulty(value: str | None) -> float | None:
    if value is None:
        return None
    normalized = " ".join(unicodedata.normalize("NFKC", value).casefold().split())
    if normalized in _MISSING_VALUES:
        return None
    matched = _DIFFICULTY.fullmatch(normalized)
    if matched is None:
        raise GuideParseError(f"Unrecognized difficulty; an explicit /10 scale is required: {value!r}.")
    difficulty = _finite_number(matched.group("value"))
    if difficulty > 10:
        raise GuideParseError(f"Difficulty is outside 0 to 10: {value!r}.")
    return difficulty


def _chip_text(parser: _GuideHTMLParser, label: str, warnings: list[str]) -> str | None:
    chips = parser.chips[label]
    if len(chips) > 1:
        raise GuideParseError(f"Multiple {label} reference chips were found.")
    if not chips:
        warnings.append(f"{label} reference chip is absent.")
        return None
    chip = chips[0]
    if not chip.closed:
        raise GuideParseError(f"{label} reference chip is not closed.")
    if len(chip.values) > 1:
        raise GuideParseError(f"Multiple values were found inside the {label} reference chip.")
    if not chip.values:
        warnings.append(f"{label} reference chip has no value node.")
        return None
    capture = chip.values[0]
    if not capture.closed:
        raise GuideParseError(f"{label} reference value is not closed.")
    return capture.text()


def parse_guide_html(html: str, source_url: str, *, unitless_time_as_hours: bool = True,
                     difficulty_only: bool = False) -> dict[str, Any]:
    """Extract fixed chips, or only difficulty when HLTB supplies current game times.

    Full time parsing is retained for validating historical receipts by their version.
    Difficulty-only parsing ignores Time nodes and their contents entirely.
    """
    validate_guide_url(source_url)
    if not isinstance(html, str) or not html.strip():
        raise GuideParseError("Guide HTML is empty.")
    lowered = html.casefold()
    if any(marker in lowered for marker in ("cf-chl", "cf-mitigated", "challenge-platform", "cf-browser-verification")):
        raise GuideParseError("The response is a Cloudflare challenge, not a guide page.")
    parser = _GuideHTMLParser(difficulty_only=difficulty_only)
    parser.feed(html)
    parser.close()
    titles = [capture.text() for capture in parser.titles]
    challenge_headings = [capture.text() for capture in parser.headings]
    if any("just a moment" in text.casefold() for text in titles + challenge_headings):
        raise GuideParseError("The response is an access challenge, not a guide page.")
    if len(titles) > 1:
        raise GuideParseError("Multiple HTML page titles were found.")
    if parser.titles and not parser.titles[0].closed:
        raise GuideParseError("The HTML page title is not properly closed.")
    page_title = titles[0] if titles else ""
    if _PLATFORM_TITLE.search(page_title):
        raise GuideParseError("The page title identifies a non-Steam achievement platform.")
    if len(parser.headings) != 1 or not parser.headings[0].closed:
        raise GuideParseError("Exactly one properly closed game heading (h1) is required.")
    heading = parser.headings[0].text()
    game_name = re.sub(r"\s+Achievements\s*$", "", heading, flags=re.IGNORECASE).strip()
    if not game_name:
        raise GuideParseError("The game heading is empty.")
    warnings: list[str] = []
    time_text = None if difficulty_only else _chip_text(parser, "Time", warnings)
    difficulty_text = _chip_text(parser, "Difficulty", warnings)
    minimum, maximum = (None, None) if difficulty_only else _parse_time(
        time_text, warnings, unitless_time_as_hours=unitless_time_as_hours)
    difficulty = _parse_difficulty(difficulty_text)
    values = {"guide_difficulty": difficulty} if difficulty_only else {
        "guide_time_hours_min": minimum, "guide_time_hours_max": maximum,
        "guide_difficulty": difficulty,
    }
    available = sum(value is not None for value in values.values())
    status = "parsed" if available == len(values) else "partial" if available else "missing"
    if time_text is not None and minimum is None and " ".join(
        unicodedata.normalize("NFKC", time_text).casefold().split()
    ) in _MISSING_VALUES:
        warnings.append("Time reference is empty or explicitly unknown.")
    if minimum is not None and maximum is None:
        warnings.append("Time reference supplies a lower bound only.")
    if difficulty_text is not None and difficulty is None:
        warnings.append("Difficulty reference is empty or explicitly unknown.")
    return {
        "page_title": page_title,
        "game_name": game_name,
        "time_text": time_text,
        "difficulty_text": difficulty_text,
        "values": values,
        "status": status,
        "scope": "achievement_difficulty_reference" if difficulty_only else "achievement_overview_reference",
        "warnings": warnings,
    }
