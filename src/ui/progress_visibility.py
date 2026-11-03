# -*- coding: utf-8 -*-
"""Shared hold/fade/collapse lifecycle for a transient progress strip."""


class ProgressVisibility:
    """Keep animation plumbing separate from progress values and run status."""

    def _setup_visibility(self, *, timer_type, opacity_type, variant_factory, animation_allowed):
        self._visibility_animation_allowed = animation_allowed
        self._hide_timer = timer_type(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._start_fade_out)
        self._opacity = opacity_type(self._bar)
        self._opacity.setOpacity(1.0)
        self._opacity.setEnabled(False)
        self._bar.setGraphicsEffect(self._opacity)
        self._fade_anim = variant_factory("base", self, self._on_fade)
        self._fade_anim.finished.connect(self._hide)

    def _cancel_fade(self) -> None:
        self._hide_timer.stop()
        self._fade_anim.stop()
        self._opacity.setOpacity(1.0)
        self._opacity.setEnabled(False)

    def _show_bar(self) -> None:
        self._cancel_fade()
        if self.height() != self.VISIBLE_HEIGHT:
            self.setFixedHeight(self.VISIBLE_HEIGHT)

    def _start_fade_out(self) -> None:
        if not self._visibility_animation_allowed():
            self._hide()
            return
        self._opacity.setEnabled(True)
        self._opacity.setOpacity(1.0)
        self._fade_anim.stop()
        self._fade_anim.start()

    def _on_fade(self, t: float) -> None:
        self._opacity.setOpacity(1.0 - t)

    def _hide(self) -> None:
        self.setFixedHeight(self.HIDDEN_HEIGHT)
        self._opacity.setOpacity(1.0)
        self._opacity.setEnabled(False)
