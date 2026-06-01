"""Optional physics simulation for moving and colliding word bodies."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Mapping


@dataclass(frozen=True)
class PhysicsConfig:
    """Tuning values for the lightweight word-body simulation."""

    anchor_strength: float = 0.006
    collision_strength: float = 1.0
    damping: float = 0.7
    solver_iterations: int = 24
    collision_padding: float = 18.0


@dataclass(frozen=True)
class WordBodySpec:
    """Initial physics state for one word."""

    word: str
    anchor: tuple[float, float]
    peak_size: tuple[float, float]


@dataclass
class WordBody:
    """Mutable physics state for one word."""

    word: str
    anchor_x: float
    anchor_y: float
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    width: float = 0.0
    height: float = 0.0
    peak_width: float = 0.0
    peak_height: float = 0.0
    active: bool = True


class PhysicsSimulator:
    """A small spring-and-rectangle collision solver for word centers."""

    def __init__(
        self,
        specs: list[WordBodySpec],
        *,
        canvas_size: tuple[int, int],
        config: PhysicsConfig | None = None,
    ) -> None:
        self.config = config or PhysicsConfig()
        self.canvas_width = float(canvas_size[0])
        self.canvas_height = float(canvas_size[1])
        self.bodies = {
            spec.word: WordBody(
                word=spec.word,
                anchor_x=float(spec.anchor[0]),
                anchor_y=float(spec.anchor[1]),
                x=float(spec.anchor[0]),
                y=float(spec.anchor[1]),
                width=float(spec.peak_size[0]),
                height=float(spec.peak_size[1]),
                peak_width=float(spec.peak_size[0]),
                peak_height=float(spec.peak_size[1]),
            )
            for spec in specs
        }

    def step(
        self,
        values: Mapping[str, float],
        peak_values: Mapping[str, float],
    ) -> dict[str, tuple[float, float]]:
        """Advance the simulation and return current word centers."""

        self._update_body_sizes(values, peak_values)
        for _ in range(self.config.solver_iterations):
            self._apply_anchor_forces()
            self._integrate()
            self._resolve_collisions()
            self._clamp_all_to_canvas()

        return self.centers()

    def centers(self) -> dict[str, tuple[float, float]]:
        """Return current centers keyed by word."""

        return {
            word: (body.x, body.y)
            for word, body in self.bodies.items()
        }

    def _update_body_sizes(
        self,
        values: Mapping[str, float],
        peak_values: Mapping[str, float],
    ) -> None:
        for word, body in self.bodies.items():
            current_value = float(values.get(word, 0.0))
            peak_value = float(peak_values.get(word, 0.0))
            if current_value <= 0 or peak_value <= 0:
                body.width = 0.0
                body.height = 0.0
                body.active = False
                continue

            scale = current_value / peak_value
            body.width = max(1.0, body.peak_width * scale) + (
                self.config.collision_padding * 2.0
            )
            body.height = max(1.0, body.peak_height * scale) + (
                self.config.collision_padding * 2.0
            )
            body.active = True

    def _apply_anchor_forces(self) -> None:
        for body in self.bodies.values():
            body.vx += (body.anchor_x - body.x) * self.config.anchor_strength
            body.vy += (body.anchor_y - body.y) * self.config.anchor_strength

    def _resolve_collisions(self) -> None:
        active_bodies = [body for body in self.bodies.values() if body.active]
        for body_a, body_b in combinations(active_bodies, 2):
            dx = body_b.x - body_a.x
            dy = body_b.y - body_a.y
            overlap_x = (body_a.width + body_b.width) / 2.0 - abs(dx)
            overlap_y = (body_a.height + body_b.height) / 2.0 - abs(dy)

            if overlap_x <= 0 or overlap_y <= 0:
                continue

            if overlap_x < overlap_y:
                direction = 1.0 if dx >= 0 else -1.0
                push = overlap_x * self.config.collision_strength / 2.0
                body_a.x -= push * direction
                body_b.x += push * direction
                body_a.vx -= push * direction * 0.05
                body_b.vx += push * direction * 0.05
            else:
                direction = 1.0 if dy >= 0 else -1.0
                push = overlap_y * self.config.collision_strength / 2.0
                body_a.y -= push * direction
                body_b.y += push * direction
                body_a.vy -= push * direction * 0.05
                body_b.vy += push * direction * 0.05

    def _integrate(self) -> None:
        for body in self.bodies.values():
            body.x += body.vx
            body.y += body.vy
            body.vx *= self.config.damping
            body.vy *= self.config.damping
            self._clamp_to_canvas(body)

    def _clamp_all_to_canvas(self) -> None:
        for body in self.bodies.values():
            self._clamp_to_canvas(body)

    def _clamp_to_canvas(self, body: WordBody) -> None:
        if not body.active:
            body.x = min(max(body.x, 0.0), self.canvas_width)
            body.y = min(max(body.y, 0.0), self.canvas_height)
            return

        half_width = body.width / 2.0
        half_height = body.height / 2.0
        min_x = min(half_width, self.canvas_width / 2.0)
        max_x = max(self.canvas_width - half_width, self.canvas_width / 2.0)
        min_y = min(half_height, self.canvas_height / 2.0)
        max_y = max(self.canvas_height - half_height, self.canvas_height / 2.0)

        body.x = min(max(body.x, min_x), max_x)
        body.y = min(max(body.y, min_y), max_y)
