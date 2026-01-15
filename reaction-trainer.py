from __future__ import annotations

import random
import statistics
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pygame

# =========================
# Config
# =========================

WINDOW_W, WINDOW_H = 900, 520
FPS = 144

DELAY_RANGE_S = (1.0, 3.0)  # random "get ready" delay before showing target
TARGET_BUTTONS = ["A"]      # keep as ["A"] for simple A-only test; or ["A","B","X","Y"]

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

# Start button index convenience (common, not guaranteed)
START_BUTTON_INDEX = 7


# =========================
# Data model
# =========================

@dataclass
class Trial:
    target: str
    reaction_s: float


@dataclass
class Session:
    trials: List[Trial] = field(default_factory=list)
    false_starts: int = 0  # premature presses during delay window (any face button, including A)

    def add_trial(self, target: str, reaction_s: float) -> None:
        self.trials.append(Trial(target=target, reaction_s=reaction_s))

    def record_false_start(self) -> None:
        self.false_starts += 1

    def reaction_times(self) -> List[float]:
        return [t.reaction_s for t in self.trials]

    def per_button_times(self) -> Dict[str, List[float]]:
        out: Dict[str, List[float]] = {b: [] for b in TARGET_BUTTONS}
        for t in self.trials:
            if t.target in out:
                out[t.target].append(t.reaction_s)
        return out

    def summary_lines(self) -> List[str]:
        rts = self.reaction_times()
        n = len(rts)

        def ms(x: float) -> str:
            return f"{x * 1000.0:.0f} ms"

        lines: List[str] = []
        lines.append("SESSION SUMMARY")
        lines.append("-" * 60)
        lines.append(f"Trials completed: {n}")
        lines.append(f"False starts:     {self.false_starts}")

        if n:
            lines.append("")
            lines.append("Reaction time:")
            lines.append(f"  Mean:    {ms(statistics.mean(rts))}")
            lines.append(f"  Median:  {ms(statistics.median(rts))}")
            lines.append(f"  Fastest: {ms(min(rts))}")
            lines.append(f"  Slowest: {ms(max(rts))}")

            # Per-button breakdown only if multiple targets
            if len(TARGET_BUTTONS) > 1:
                lines.append("")
                lines.append("Per-button breakdown:")
                per = self.per_button_times()
                for b in TARGET_BUTTONS:
                    xs = per.get(b, [])
                    if xs:
                        lines.append(
                            f"  {b}: n={len(xs):3d}  mean={statistics.mean(xs)*1000.0:6.0f} ms  "
                            f"median={statistics.median(xs)*1000.0:6.0f} ms"
                        )
                    else:
                        lines.append(f"  {b}: n=  0  mean=   -     median=   -")
        else:
            lines.append("")
            lines.append("Reaction time: (no trials completed)")

        lines.append("-" * 60)
        lines.append("Press ESC or close the window to exit.")
        return lines


# =========================
# UI helpers
# =========================

def draw_centered_text(
    surface: pygame.Surface,
    font: pygame.font.Font,
    text: str,
    y: int,
    color: Tuple[int, int, int],
) -> None:
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


def rand_delay_s() -> float:
    return random.uniform(*DELAY_RANGE_S)


# =========================
# State machine
# =========================

class Phase:
    READY = "ready"      # waiting random delay; premature presses are false starts and reset timer
    GO = "go"            # target displayed; first correct press records RT and moves back to READY
    SUMMARY = "summary"  # display results


@dataclass
class AppState:
    phase: str = Phase.READY
    target: str = "A"
    delay_until: float = 0.0
    go_shown_t: Optional[float] = None

    last_feedback: str = "Press SPACE (keyboard) or START (controller) to stop."
    last_feedback_t: float = 0.0

    def set_feedback(self, msg: str) -> None:
        self.last_feedback = msg
        self.last_feedback_t = time.perf_counter()

    def schedule_ready(self) -> None:
        self.phase = Phase.READY
        self.go_shown_t = None
        self.delay_until = time.perf_counter() + rand_delay_s()

    def show_go(self) -> None:
        self.phase = Phase.GO
        self.go_shown_t = time.perf_counter()


# =========================
# Main
# =========================

def main() -> None:
    pygame.init()
    pygame.display.set_caption("Reaction Test (SPACE/START to stop)")
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

    btn_index_to_face: Dict[int, str] = dict(DEFAULT_XBOX_FACE)

    session = Session()
    state = AppState()
    state.last_feedback_t = time.perf_counter()

    # initial target + delay
    state.target = random.choice(TARGET_BUTTONS)
    state.schedule_ready()

    summary_lines: List[str] = []
    running = True

    while running:
        now = time.perf_counter()

        # Events
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                break

            # Keyboard
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                    break
                if event.key == pygame.K_SPACE and state.phase != Phase.SUMMARY:
                    state.phase = Phase.SUMMARY
                    summary_lines = session.summary_lines()
                    continue

            # Controller
            if event.type == pygame.JOYBUTTONDOWN and event.joy == js.get_id():
                idx = int(event.button)

                # START to stop
                if idx == START_BUTTON_INDEX and state.phase != Phase.SUMMARY:
                    state.phase = Phase.SUMMARY
                    summary_lines = session.summary_lines()
                    continue

                pressed_face = btn_index_to_face.get(idx)
                if pressed_face is None:
                    # ignore non-face buttons
                    state.set_feedback(f"Ignored non-face button index {idx}.")
                    continue

                # READY phase: any face press is a false start (timer resets)
                if state.phase == Phase.READY:
                    session.record_false_start()
                    state.schedule_ready()
                    state.set_feedback(f"False start: {pressed_face}. Timer reset.")
                    continue

                # GO phase: only correct press records; wrong press ignored (no penalty)
                if state.phase == Phase.GO:
                    if pressed_face != state.target:
                        state.set_feedback(f"Wrong: {pressed_face} (want {state.target}).")
                        continue

                    if state.go_shown_t is None:
                        # should not happen, but stay safe
                        state.set_feedback("Recorded input, but timing was unavailable.")
                        state.schedule_ready()
                        state.target = random.choice(TARGET_BUTTONS)
                        continue

                    rt = now - state.go_shown_t
                    session.add_trial(state.target, rt)
                    state.set_feedback(f"Correct: {pressed_face} | {rt*1000.0:.0f} ms")

                    # Next trial
                    state.target = random.choice(TARGET_BUTTONS)
                    state.schedule_ready()
                    continue

        # Phase progression
        if state.phase == Phase.READY and now >= state.delay_until:
            state.show_go()

        # Draw
        screen.fill(BG)

        if state.phase != Phase.SUMMARY:
            draw_centered_text(screen, font_med, "Gamepad Reaction Test", 45, FG)
            draw_centered_text(screen, font_small, f"Controller: {gamepad_name}", 80, MUTED)
            draw_centered_text(screen, font_small, "Press SPACE (keyboard) or START (controller) to stop", 110, MUTED)

            if state.phase == Phase.READY:
                draw_centered_text(screen, font_med, "Get ready…", WINDOW_H // 2, MUTED)
                draw_centered_text(screen, font_small, "Any face-button press now counts as a false start.", WINDOW_H // 2 + 70, MUTED)
            else:
                color = BUTTON_COLORS.get(state.target, FG)
                draw_centered_text(screen, font_big, state.target, WINDOW_H // 2, color)
                draw_centered_text(screen, font_small, f"Press {state.target} now", WINDOW_H // 2 + 95, FG)

            # HUD
            n = len(session.trials)
            fs = session.false_starts
            age = now - state.last_feedback_t
            feedback_color = FG if age < 1.5 else MUTED

            draw_centered_text(screen, font_small, state.last_feedback, WINDOW_H - 95, feedback_color)
            draw_centered_text(screen, font_small, f"Trials: {n}   False starts: {fs}", WINDOW_H - 60, MUTED)

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
