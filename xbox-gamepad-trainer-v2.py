from __future__ import annotations

import random
import statistics
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from pathlib import Path

import pygame

WINDOW_W, WINDOW_H = 900, 520
FPS = 144

RESULTS_FILE = Path("reaction_trainer_results.txt")

# Typical Xbox mapping via SDL on Windows (common, not universal)
DEFAULT_XBOX_FACE = {0: "A", 1: "B", 2: "X", 3: "Y"}
DEFAULT_XBOX_BUMPERS = {4: "LB", 5: "RB"}

# Triggers are usually axes (common mappings; not universal)
TRIGGER_AXES = {4: "LT", 5: "RT"}

ALL_TARGETS = ["A", "B", "X", "Y", "LB", "RB", "LT", "RT"]

BUTTON_COLORS = {
    "A": (0, 200, 0),
    "B": (220, 0, 0),
    "X": (0, 120, 255),
    "Y": (240, 200, 0),
    "LB": (180, 180, 180),
    "RB": (180, 180, 180),
    "LT": (180, 180, 180),
    "RT": (180, 180, 180),
}

BG = (18, 18, 22)
FG = (240, 240, 245)
MUTED = (170, 170, 180)

DELAY_RANGE_S = (0.10, 0.35)

TRIGGER_THRESHOLD = 0.6
TRIGGER_RELEASE = 0.2


@dataclass
class Attempt:
    target: str
    pressed: Optional[str]
    reaction_s: Optional[float]
    correct: bool


@dataclass
class SessionStats:
    attempts: List[Attempt] = field(default_factory=list)

    def add(self, attempt: Attempt) -> None:
        self.attempts.append(attempt)

    def _correct_reactions(self) -> List[float]:
        return [a.reaction_s for a in self.attempts if a.correct and a.reaction_s is not None]

    def summary_text(self) -> str:
        total = len(self.attempts)
        correct = sum(1 for a in self.attempts if a.correct)
        incorrect = total - correct
        acc = (correct / total * 100.0) if total else 0.0

        correct_rts = self._correct_reactions()
        lines: List[str] = []
        lines.append("SESSION SUMMARY")
        lines.append("-" * 60)
        lines.append(f"Total attempts: {total}")
        lines.append(f"Correct:        {correct}")
        lines.append(f"Incorrect:      {incorrect}")
        lines.append(f"Accuracy:       {acc:.1f}%")

        def ms(x: float) -> str:
            return f"{x * 1000.0:.0f} ms"

        if correct_rts:
            lines.append("")
            lines.append("Reaction time (correct only):")
            lines.append(f"  Mean:    {ms(statistics.mean(correct_rts))}")
            lines.append(f"  Median:  {ms(statistics.median(correct_rts))}")
            lines.append(f"  Fastest: {ms(min(correct_rts))}")
            lines.append(f"  Slowest: {ms(max(correct_rts))}")
        else:
            lines.append("")
            lines.append("Reaction time: (no correct attempts recorded)")

        lines.append("")
        lines.append("Per-button breakdown (correct only):")
        for btn in ALL_TARGETS:
            rts = [a.reaction_s for a in self.attempts if a.correct and a.target == btn and a.reaction_s is not None]
            if rts:
                lines.append(
                    f"  {btn}: n={len(rts):3d}  mean={statistics.mean(rts)*1000.0:6.0f} ms  "
                    f"median={statistics.median(rts)*1000.0:6.0f} ms"
                )
            else:
                lines.append(f"  {btn}: n=  0  mean=   -     median=   -")

        conf: Dict[Tuple[str, str], int] = {}
        for a in self.attempts:
            if not a.correct and a.pressed is not None:
                conf[(a.target, a.pressed)] = conf.get((a.target, a.pressed), 0) + 1

        if conf:
            lines.append("")
            lines.append("Most common mistakes (target -> pressed):")
            for (t, p), n in sorted(conf.items(), key=lambda kv: kv[1], reverse=True)[:8]:
                lines.append(f"  {t} -> {p}: {n}")

        lines.append("-" * 60)
        lines.append("Press ESC or close the window to exit.")
        return "\n".join(lines)


def save_session_to_file(summary: str, controller_name: str) -> None:
    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    header = [
        "",
        "=" * 72,
        f"SESSION @ {ts}",
        f"Controller: {controller_name}",
        "=" * 72,
    ]

    with RESULTS_FILE.open("a", encoding="utf-8") as f:
        for line in header:
            f.write(line + "\n")
        f.write(summary + "\n")


def draw_centered_text(surface, font, text, y, color):
    img = font.render(text, True, color)
    rect = img.get_rect(center=(WINDOW_W // 2, y))
    surface.blit(img, rect)


def init_first_gamepad():
    pygame.joystick.init()
    n = pygame.joystick.get_count()
    if n <= 0:
        raise RuntimeError("No gamepad detected.")
    js = pygame.joystick.Joystick(0)
    js.init()
    return js


class ShuffleBag:
    """
    Guarantees each target appears once per cycle, in random order.
    When empty, it refills with a fresh shuffle.
    """

    def __init__(self, items: List[str]) -> None:
        self._items = list(items)
        self._bag: List[str] = []
        self._refill()

    def _refill(self) -> None:
        self._bag = list(self._items)
        random.shuffle(self._bag)

    def next(self) -> str:
        if not self._bag:
            self._refill()
        return self._bag.pop()

    def remaining(self) -> int:
        return len(self._bag)


def main():
    pygame.init()
    pygame.display.set_caption("Gamepad Reaction Trainer")
    screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))
    clock = pygame.time.Clock()

    font_big = pygame.font.SysFont(None, 140)
    font_med = pygame.font.SysFont(None, 38)
    font_small = pygame.font.SysFont(None, 26)
    font_mono = pygame.font.SysFont("consolas", 22) or pygame.font.SysFont(None, 22)

    try:
        js = init_first_gamepad()
        gamepad_name = js.get_name()
    except Exception as e:
        print("Gamepad init failed:", e)
        return

    btn_index_to_label = {}
    btn_index_to_label.update(DEFAULT_XBOX_FACE)
    btn_index_to_label.update(DEFAULT_XBOX_BUMPERS)

    stats = SessionStats()

    phase = "delay"
    delay_until = time.perf_counter() + random.uniform(*DELAY_RANGE_S)

    # Use a shuffle-bag so LB/RB/LT/RT are guaranteed to appear regularly.
    bag = ShuffleBag(ALL_TARGETS)
    target_btn = bag.next()
    prompt_shown_t: Optional[float] = None

    last_feedback = "Press A/B/X/Y/LB/RB/LT/RT. SPACE or START to stop."
    last_feedback_t = time.perf_counter()

    summary_lines: List[str] = []
    trigger_armed = {name: True for name in TRIGGER_AXES.values()}

    def start_summary():
        nonlocal phase, summary_lines
        phase = "summary"
        text = stats.summary_text()
        summary_lines = text.splitlines()
        save_session_to_file(text, gamepad_name)

    def record_press(label: str, now: float):
        nonlocal phase, delay_until, target_btn, prompt_shown_t, last_feedback, last_feedback_t

        rt = now - prompt_shown_t if prompt_shown_t else None
        correct = (label == target_btn)

        stats.add(Attempt(target_btn, label, rt, correct))

        if rt is not None:
            ms = rt * 1000
            last_feedback = f"{'Correct' if correct else 'Wrong'}: {label} | {ms:.0f} ms"
        else:
            last_feedback = "Input received."
        last_feedback_t = now

        if correct:
            phase = "delay"
            delay_until = now + random.uniform(*DELAY_RANGE_S)
            target_btn = bag.next()
            prompt_shown_t = None

    running = True
    while running:
        now = time.perf_counter()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_SPACE and phase != "summary":
                    start_summary()
                if event.key == pygame.K_ESCAPE:
                    running = False

            if event.type == pygame.JOYBUTTONDOWN and phase == "prompt":
                idx = event.button
                if idx == 7:
                    start_summary()
                    continue

                label = btn_index_to_label.get(idx)
                if label:
                    record_press(label, now)

        if phase == "prompt":
            for axis_idx, name in TRIGGER_AXES.items():
                if axis_idx >= js.get_numaxes():
                    continue
                v = js.get_axis(axis_idx)

                if v > TRIGGER_THRESHOLD and trigger_armed[name]:
                    trigger_armed[name] = False
                    record_press(name, now)

                if v < TRIGGER_RELEASE:
                    trigger_armed[name] = True

        if phase == "delay" and now >= delay_until:
            phase = "prompt"
            prompt_shown_t = time.perf_counter()
            for k in trigger_armed:
                trigger_armed[k] = True

        screen.fill(BG)

        if phase in ("delay", "prompt"):
            draw_centered_text(screen, font_med, "Xbox Reaction Trainer", 45, FG)
            draw_centered_text(screen, font_small, f"Controller: {gamepad_name}", 80, MUTED)

            # Debug: show that the shuffle-bag is active and will include everything
            draw_centered_text(
                screen,
                font_small,
                f"Prompt pool: {', '.join(ALL_TARGETS)}  |  bag remaining: {bag.remaining()}",
                110,
                MUTED,
            )

            if phase == "delay":
                draw_centered_text(screen, font_med, "Get ready…", WINDOW_H // 2, MUTED)
            else:
                draw_centered_text(screen, font_big, target_btn, WINDOW_H // 2, BUTTON_COLORS[target_btn])

            total = len(stats.attempts)
            correct_n = sum(a.correct for a in stats.attempts)
            acc = (correct_n / total * 100.0) if total else 0.0

            age = now - last_feedback_t
            feedback_color = FG if age < 1.5 else MUTED
            draw_centered_text(screen, font_small, last_feedback, WINDOW_H - 90, feedback_color)
            draw_centered_text(
                screen,
                font_small,
                f"Attempts: {total}   Correct: {correct_n}   Accuracy: {acc:.1f}%",
                WINDOW_H - 55,
                MUTED,
            )
        else:
            draw_centered_text(screen, font_med, "Results", 40, FG)
            y = 80
            for line in summary_lines[:18]:
                screen.blit(font_mono.render(line, True, FG), (40, y))
                y += 24

        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()


if __name__ == "__main__":
    main()
