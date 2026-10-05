"""Secret scrubbing for prompts and generated output."""

from ticket2test.security.scrubber import ScrubResult, scrub, scrub_text

__all__ = ["ScrubResult", "scrub", "scrub_text"]
