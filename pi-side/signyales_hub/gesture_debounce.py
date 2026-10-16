"""
Signyales Pi-Side App — Gesture Debouncing

Raw model predictions run several times a second and will naturally
flicker between adjacent gestures, especially mid-transition. This
module only lets a gesture through to text/speech output once it has
been predicted consistently, above a confidence threshold, for a
required number of consecutive inferences — mirroring how the
proposal's evaluation instrument distinguishes a genuine recognition
event from noise.
"""

import logging

log = logging.getLogger("signyales.debounce")


class GestureDebouncer:
    def __init__(self, required_consecutive: int, confidence_threshold: float,
                 silent_labels=()):
        self.required_consecutive = required_consecutive
        self.confidence_threshold = confidence_threshold
        # Labels meaning "no sign" (see HubConfig.silent_labels): never
        # returned, but a confirmed one re-arms repeat detection.
        self.silent_labels = frozenset(silent_labels)
        self._candidate_label = None
        self._candidate_count = 0
        self._last_emitted = None

    def update(self, label: str, confidence: float):
        """
        Feed one raw (label, confidence) prediction in. Returns the
        label string if this update causes a NEW stable gesture to be
        confirmed, otherwise returns None.
        """
        if label is None or confidence < self.confidence_threshold:
            self._candidate_label = None
            self._candidate_count = 0
            return None

        if label == self._candidate_label:
            self._candidate_count += 1
        else:
            self._candidate_label = label
            self._candidate_count = 1

        if self._candidate_count >= self.required_consecutive:
            if label in self.silent_labels:
                # Confirmed rest: say nothing, but allow the next real
                # gesture to be spoken even if it repeats the last one.
                if self._last_emitted is not None:
                    log.debug("Rest label '%s' confirmed; repeat detection re-armed", label)
                self._last_emitted = None
                return None
            if label != self._last_emitted:
                self._last_emitted = label
                log.info("Stable gesture confirmed: %s (confidence=%.2f)", label, confidence)
                return label
            # Already the current held gesture — don't re-emit every
            # window the wearer continues holding the same sign.
        return None

    @property
    def candidate_count(self) -> int:
        """How many consecutive confident predictions the current candidate
        label has (0 if none). Read-only; used by performance_logger to time
        how long debouncing takes."""
        return self._candidate_count

    def reset(self):
        """Call this when the input goes quiet (e.g. both hands stale)
        so a resumed session doesn't inherit stale debounce state."""
        self._candidate_label = None
        self._candidate_count = 0
        self._last_emitted = None
