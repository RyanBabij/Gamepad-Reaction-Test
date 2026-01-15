from __future__ import annotations

import random
import statistics
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pygame

WINDOW_W, WINDOW_H = 900, 520
FPS = 144

# Typical Xbox mapping via SDL on Windows (common, not universal)
DEFAULT_XBOX_FACE = {0: "A", 1: "B", 2: "X", 3: "Y"}

BUTTON_COLORS = {
    "A": (0, 200, 0),
    "B": (220, 0, 0),
    "X": (0, 120, 255),
    "Y": (240, 200, 0),
}

BG = (18, 18, 22)
FG = (240, 240, 245)
MUTED = (170, 170, 180)

# Shorter delay between prompts
DELAY_RANGE_S = (0.10, 0.35)


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
        for btn in ["A", "B", "X", "Y"]:
            rts = [a.reaction_s for a in self.attempts if a.correct and a.target == btn and a.reaction_s is not None]
            if rts:
                lines.append(
                    f"  {btn}: n={len(rts):3d}  mean={statistics.mean(rts)*1000.0:6.0f} ms  "
                    f"median={statistics.median(rts)*1000.0:6.0f} ms"
                )
            else:
                lines.append(f"  {btn}: n=  0  mean=   -     median=   -")

        # Mistakes
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


def draw_centered_text(surface: pygame.Surface, font: pygame.font.Font, text: str, y: int, color: Tuple[int, int, int]) -> None:
    img = font.render(text, True, color)
    rect = img.get_rect(center=(WINDOW_W // 2, y))
    surface.blit(img, rect)


def init_first_gamepad() -> pygame.joystick.Joystick:
    pygame.joystick.init()
    n = pygame.joystick.get_count()
    if n <= 0:
        raise RuntimeError("No gamepad detected. Plug it in, then restart.")
    js = pygame.joystick.Joystick(0)
    js.init()
    return js


def main() -> None:
    pygame.init()
    pygame.display.set_caption("Gamepad Reaction Trainer (SPACE/START to stop)")
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

    print(f"[trainer] Gamepad detected: {gamepad_name!r}")
    print(f"[trainer] Buttons: {js.get_numbuttons()}, Axes: {js.get_numaxes()}, Hats: {js.get_numhats()}")

    btn_index_to_face: Dict[int, str] = dict(DEFAULT_XBOX_FACE)

    stats = SessionStats()

    phase = "delay"  # delay | prompt | summary
    delay_until = time.perf_counter() + random.uniform(*DELAY_RANGE_S)

    target_btn = random.choice(["A", "B", "X", "Y"])
    prompt_shown_t: Optional[float] = None

    last_feedback = "Press A/B/X/Y on your controller. SPACE or START to stop."
    last_feedback_t = time.perf_counter()

    summary_lines: List[str] = []

    running = True
    while running:
        now = time.perf_counter()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                break

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_SPACE and phase != "summary":
                    phase = "summary"
                    summary_lines = stats.summary_text().splitlines()
                    continue
                if event.key == pygame.K_ESCAPE:
                    running = False
                    break

            if event.type == pygame.JOYBUTTONDOWN and event.joy == js.get_id():
                idx = int(event.button)

                # Start button commonly 7 (not guaranteed). Keep as convenience stop.
                if idx == 7 and phase != "summary":
                    phase = "summary"
                    summary_lines = stats.summary_text().splitlines()
                    continue

                if phase == "prompt":
                    pressed_face = btn_index_to_face.get(idx)

                    # Ignore non-face buttons (bumper, etc.)
                    if pressed_face is None:
                        last_feedback = f"Ignored non-face button index {idx}."
                        last_feedback_t = now
                        continue

                    rt = None
                    if prompt_shown_t is not None:
                        rt = now - prompt_shown_t

                    correct = (pressed_face == target_btn)

                    stats.add(Attempt(
                        target=target_btn,
                        pressed=pressed_face,
                        reaction_s=rt,
                        correct=correct,
                    ))

                    if rt is not None:
                        rt_ms = rt * 1000.0
                        if correct:
                            last_feedback = f"Correct: {pressed_face}  |  {rt_ms:.0f} ms"
                        else:
                            last_feedback = f"Wrong: {pressed_face} (wanted {target_btn})  |  {rt_ms:.0f} ms"
                    else:
                        last_feedback = "Input received."
                    last_feedback_t = now

                    # Only proceed when correct
                    if correct:
                        phase = "delay"
                        delay_until = now + random.uniform(*DELAY_RANGE_S)
                        target_btn = random.choice(["A", "B", "X", "Y"])
                        prompt_shown_t = None
                    else:
                        # Stay in prompt phase; do NOT reset the timer
                        # (timer remains anchored to when the prompt first appeared)
                        pass

        # Phase progression
        if phase == "delay" and now >= delay_until:
            phase = "prompt"
            prompt_shown_t = time.perf_counter()

        # Draw
        screen.fill(BG)

        if phase in ("delay", "prompt"):
            draw_centered_text(screen, font_med, "Xbox Face Button Reaction Trainer", 45, FG)
            draw_centered_text(screen, font_small, f"Controller: {gamepad_name}", 80, MUTED)
            draw_centered_text(screen, font_small, "Press SPACE (keyboard) or START (controller) to stop", 110, MUTED)

            if phase == "delay":
                draw_centered_text(screen, font_med, "Get ready…", WINDOW_H // 2, MUTED)
            else:
                color = BUTTON_COLORS[target_btn]
                draw_centered_text(screen, font_big, target_btn, WINDOW_H // 2, color)
                draw_centered_text(screen, font_small, f"Press {target_btn} (won't advance until correct)", WINDOW_H // 2 + 95, FG)

            total = len(stats.attempts)
            correct_n = sum(1 for a in stats.attempts if a.correct)
            acc = (correct_n / total * 100.0) if total else 0.0

            age = now - last_feedback_t
            feedback_color = FG if age < 1.5 else MUTED
            draw_centered_text(screen, font_small, last_feedback, WINDOW_H - 90, feedback_color)
            draw_centered_text(screen, font_small, f"Attempts: {total}   Correct: {correct_n}   Accuracy: {acc:.1f}%", WINDOW_H - 55, MUTED)

        else:
            draw_centered_text(screen, font_med, "Results", 40, FG)
            y = 80
            for line in summary_lines[:18]:
                img = font_mono.render(line, True, FG)
                screen.blit(img, (40, y))
                y += 24

            if len(summary_lines) > 18:
                img = font_small.render(f"(Showing first 18 lines of {len(summary_lines)}.)", True, MUTED)
                screen.blit(img, (40, WINDOW_H - 40))

        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()


if __name__ == "__main__":
    main()
