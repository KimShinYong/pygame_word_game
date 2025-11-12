# main.py — Single Screen / 3 Stages
# Arrow(배경+단어 내장)만 사용. 기존 WORD/arrow 혼합 그리기 함수 전부 제거.
import os, sys, random, pygame
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, Tuple

# -----------------------------
# 화면/필드 설정
# -----------------------------
WIDTH, HEIGHT = 900, 760
FPS = 60
COLS = 10
CELL_W = 56
FIELD_W = COLS * CELL_W
TOP_MARGIN = 20
GROUND_Y = HEIGHT - 110
MARGIN_X = (WIDTH - FIELD_W) // 2  # 가운데 정렬

ASSET_DIR = os.path.join(os.path.dirname(__file__), "assets")

PLAYER_SIZE = (44, 44)
BLOCK_H = 28
STEP_PX = BLOCK_H

SLOW_FACTOR = 1.0

# 가속(30→25→20→…초마다 1.1배)
ACCEL_RATIO = 1.10
ACCEL_INTERVAL_START_MS = 30_000
ACCEL_INTERVAL_STEP_MS = 5_000
ACCEL_INTERVAL_MIN_MS = 10_000

SPAWN_MS_LOWER_BOUND = 220

LETTERS = "asdfjklghqwertyuiopzxcvbnm1234567890"
FONT_NAME = None

# 스폰 안전장치
MOVES_PER_SEC = 2.8
SAFETY_MARGIN_MS = 400

# -----------------------------
# 중앙 오버레이 레이아웃
# -----------------------------
CENTER_X = MARGIN_X + FIELD_W // 2
CENTER_Y = (TOP_MARGIN + GROUND_Y) // 2 + 20

ARROW_SCALE = 0.70
ARROW_W_BASE, ARROW_H_BASE = 150, 120
ARROW_W, ARROW_H = int(ARROW_W_BASE * ARROW_SCALE), int(ARROW_H_BASE * ARROW_SCALE)

ARROW_X_GAP = 150
ARROW_OUT_OFFSET = 40   # 화살표는 바깥쪽으로
WORD_Y_OFFSET = 2

# 색상 팔레트
ARROW_FILL = (120, 120, 120, 160)   # 반투명 본체
ARROW_BORDER = (60, 60, 60, 220)    # 테두리
ARROW_HILITE = (255, 255, 255, 40)  # 상단 하이라이트
LEFT_WORD_COLOR = (18, 120, 255)
RIGHT_WORD_COLOR = (255, 140, 0)
WORD_OUTLINE = (0, 0, 0)

# -----------------------------
# Stage 정의(3개만)
# -----------------------------
@dataclass(frozen=True)
class StageConf:
    min_len: int
    max_len: int
    steps_per_sec: float
    spawn_ms: int

STAGE_PRESETS: dict[int, StageConf] = {
    1: StageConf(min_len=3, max_len=3, steps_per_sec=1.0, spawn_ms=8000),
    2: StageConf(min_len=4, max_len=4, steps_per_sec=1.8, spawn_ms=5500),
    3: StageConf(min_len=5, max_len=5, steps_per_sec=2.4, spawn_ms=3500),
}

# -----------------------------
# 유틸
# -----------------------------
def load_image(path: str, size: Optional[Tuple[int, int]] = None) -> Optional[pygame.Surface]:
    if not os.path.isfile(path):
        return None
    try:
        img = pygame.image.load(path).convert_alpha()
        return pygame.transform.smoothscale(img, size) if size else img
    except Exception:
        return None

# -----------------------------
# 엔티티
# -----------------------------
class GameState(Enum):
    MENU = auto()
    PLAY = auto()
    OVER = auto()

class Background:
    def __init__(self, screen: pygame.Surface):
        self.screen = screen
        self.img = load_image(os.path.join(ASSET_DIR, "bg.jpg"))
        if self.img:
            self.img = pygame.transform.smoothscale(self.img, (WIDTH, HEIGHT))
        self.scroll_y = 0
        self.scroll_speed = 0.22

    def update(self, dt: int):
        if self.img:
            self.scroll_y = (self.scroll_y + self.scroll_speed * dt) % HEIGHT

    def draw(self):
        if self.img:
            y = int(self.scroll_y)
            self.screen.blit(self.img, (0, y - HEIGHT))
            self.screen.blit(self.img, (0, y))
        else:
            self.screen.fill((235, 245, 255))

class Player:
    def __init__(self, col: int):
        self.col = col
        self.img = load_image(os.path.join(ASSET_DIR, "player.png"), size=PLAYER_SIZE)

    @property
    def rect(self) -> pygame.Rect:
        x = MARGIN_X + self.col * CELL_W + (CELL_W - PLAYER_SIZE[0]) // 2
        y = GROUND_Y - PLAYER_SIZE[1] - 2
        return pygame.Rect(x, y, *PLAYER_SIZE)

    def move(self, d: int):
        self.col = max(0, min(COLS - 1, self.col + d))

    def draw(self, screen: pygame.Surface):
        if self.img:
            screen.blit(self.img, self.rect)
        else:
            pygame.draw.rect(screen, (70, 120, 255), self.rect, border_radius=8)

@dataclass
class Block:
    start_col: int
    length: int
    steps_per_sec_base: float
    y: float = -BLOCK_H
    acc_ms: int = 0
    img: Optional[pygame.Surface] = None

    def __post_init__(self):
        if self.img is None:
            self.img = load_image(os.path.join(ASSET_DIR, "block.png"),
                                  size=(CELL_W * self.length, BLOCK_H))

    def bind_runtime(self, get_steps_per_sec):
        self._get_steps_per_sec = get_steps_per_sec
        self._recompute_step_interval()

    def _recompute_step_interval(self):
        sps = max(0.1, self._get_steps_per_sec())
        self.step_interval_ms = max(60, int(1000 / (sps / SLOW_FACTOR)))

    @property
    def rect(self) -> pygame.Rect:
        return pygame.Rect(MARGIN_X + self.start_col * CELL_W, int(self.y), CELL_W * self.length, BLOCK_H)

    def update(self, dt: int):
        self._recompute_step_interval()
        self.acc_ms += dt
        while self.acc_ms >= self.step_interval_ms:
            self.y += STEP_PX
            self.acc_ms -= self.step_interval_ms

    def hit_ground(self) -> bool:
        return self.y + BLOCK_H >= GROUND_Y

    def time_to_ground_ms(self) -> int:
        remaining_steps = max(0, int((GROUND_Y - (self.y + BLOCK_H)) // BLOCK_H) + 1)
        return remaining_steps * self.step_interval_ms

    def draw(self, screen: pygame.Surface):
        if self.img:
            screen.blit(self.img, (self.rect.x, self.rect.y))
        else:
            pygame.draw.rect(screen, (235, 95, 85), self.rect, border_radius=6)

@dataclass
class Explosion:
    start_col: int
    length: int
    timer: int = 380
    img: Optional[pygame.Surface] = None

    def __post_init__(self):
        if self.img is None:
            self.img = load_image(os.path.join(ASSET_DIR, "explosion.png"),
                                  size=(CELL_W * self.length, CELL_W // 2))

    @property
    def danger_cols(self):
        return self.start_col, self.start_col + self.length - 1

    def update(self, dt: int):
        self.timer -= dt

    def alive(self) -> bool:
        return self.timer > 0

    def draw(self, screen: pygame.Surface):
        x = MARGIN_X + self.start_col * CELL_W
        y = GROUND_Y - (CELL_W // 2)
        if self.img:
            screen.blit(self.img, (x, y))
        else:
            s = pygame.Surface((CELL_W * self.length, CELL_W // 2), pygame.SRCALPHA)
            s.fill((255, 180, 60, 150))
            screen.blit(s, (x, y))
            pygame.draw.rect(screen, (255, 120, 0), (x, y, CELL_W * self.length, CELL_W // 2), width=2, border_radius=6)

# -----------------------------
# Arrow — 단일 객체(배경+단어 포함)
# -----------------------------
class Arrow:
    def __init__(self, pointing: str, center: Tuple[int, int],
                 font: pygame.font.Font, word_color: Tuple[int, int, int]):
        assert pointing in ("left", "right")
        self.pointing = pointing
        self.cx, self.cy = center
        self.font = font
        self.word_color = word_color
        self.word = "word"

    def set_center(self, center: Tuple[int, int]):
        self.cx, self.cy = center

    def set_word(self, word: str):
        self.word = word

    def _poly_and_inner(self):
        cx, cy = self.cx, self.cy
        if self.pointing == "left":
            pts = [(cx, cy), (cx + ARROW_W, cy - ARROW_H // 2), (cx + ARROW_W, cy + ARROW_H // 2)]
            inner = pygame.Rect(cx, cy - ARROW_H // 2, ARROW_W, ARROW_H)
        else:
            pts = [(cx, cy), (cx - ARROW_W, cy - ARROW_H // 2), (cx - ARROW_W, cy + ARROW_H // 2)]
            inner = pygame.Rect(cx - ARROW_W, cy - ARROW_H // 2, ARROW_W, ARROW_H)
        return pts, inner

    def draw(self, surface: pygame.Surface):
        pts, inner = self._poly_and_inner()

        layer = pygame.Surface((surface.get_width(), surface.get_height()), pygame.SRCALPHA)
        pygame.draw.polygon(layer, ARROW_FILL, pts)             # 본체
        pygame.draw.polygon(layer, ARROW_BORDER, pts, 2)        # 테두리
        hilite = pygame.Rect(inner.x + 6, inner.y + 6, inner.w - 12, max(6, ARROW_H // 6))
        pygame.draw.rect(layer, ARROW_HILITE, hilite, border_radius=6)

        # 텍스트(외곽선 2px + 본문) — 별도 배경 없음
        text = self.font.render(self.word, True, self.word_color)
        tw, th = text.get_size()
        tx = inner.centerx - tw // 2
        ty = inner.centery - th // 2 + WORD_Y_OFFSET
        for dx, dy in [(-2, 0), (2, 0), (0, -2), (0, 2)]:
            layer.blit(self.font.render(self.word, True, WORD_OUTLINE), (tx + dx, ty + dy))
        layer.blit(text, (tx, ty))

        surface.blit(layer, (0, 0))

# -----------------------------
# Game
# -----------------------------
class Game:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Typing Dodge — Fixed Stage")
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        self.clock = pygame.time.Clock()

        # 글꼴
        self.font_ui = pygame.font.SysFont(FONT_NAME, 22, bold=False)   # 좌상단
        self.font_big = pygame.font.SysFont(FONT_NAME, 30, bold=True)   # 메뉴
        self.font_h1 = pygame.font.SysFont(FONT_NAME, 40, bold=True)    # 오버
        self.font_word = pygame.font.SysFont(FONT_NAME, 58, bold=True)  # 중앙 단어
        self.font_input = pygame.font.SysFont(FONT_NAME, 28, bold=False)  # 큰 입력창

        self.bg = Background(self.screen)
        self.player = Player(COLS // 2)
        self.blocks: list[Block] = []
        self.explosions: list[Explosion] = []

        self.input_buf = ""
        self.elapsed_ms = 0
        self.state = GameState.MENU
        self.menu_selected = 0

        self.current_stage_id = 1
        self.stage_base = STAGE_PRESETS[self.current_stage_id]

        # 가속
        self.accel_multiplier = 1.0
        self.accel_interval_ms = ACCEL_INTERVAL_START_MS
        self.next_accel_due_ms = ACCEL_INTERVAL_START_MS

        # 파라미터
        self.min_len = self.stage_base.min_len
        self.max_len = self.stage_base.max_len
        self.spawn_ms = max(SPAWN_MS_LOWER_BOUND, int(self.stage_base.spawn_ms))
        self.spawn_acc = 0

        # 단어 & Arrow 객체
        self.left_word = self._make_word()
        self.right_word = self._make_word()

        self.left_arrow = Arrow(
            "left",
            (CENTER_X - (ARROW_X_GAP + ARROW_OUT_OFFSET), CENTER_Y),
            self.font_word, LEFT_WORD_COLOR
        )
        self.right_arrow = Arrow(
            "right",
            (CENTER_X + (ARROW_X_GAP + ARROW_OUT_OFFSET), CENTER_Y),
            self.font_word, RIGHT_WORD_COLOR
        )
        self.left_arrow.set_word(self.left_word)
        self.right_arrow.set_word(self.right_word)

    # ---------- 단어 ----------
    def _make_word(self) -> str:
        L = self.min_len if self.min_len == self.max_len else random.randint(self.min_len, self.max_len)
        return "".join(random.choice(LETTERS) for _ in range(L))

    def _refresh_left(self):
        self.left_word = self._make_word()
        self.left_arrow.set_word(self.left_word)

    def _refresh_right(self):
        self.right_word = self._make_word()
        self.right_arrow.set_word(self.right_word)

    # ---------- 가속 ----------
    def _apply_acceleration(self):
        if self.elapsed_ms >= self.next_accel_due_ms:
            self.accel_multiplier *= ACCEL_RATIO
            self.accel_interval_ms = max(ACCEL_INTERVAL_MIN_MS, self.accel_interval_ms - ACCEL_INTERVAL_STEP_MS)
            self.next_accel_due_ms += self.accel_interval_ms
            self.spawn_ms = max(SPAWN_MS_LOWER_BOUND, int(self.stage_base.spawn_ms / self.accel_multiplier))

    def _effective_steps_per_sec(self) -> float:
        return self.stage_base.steps_per_sec * self.accel_multiplier

    # ---------- 스폰 안전 ----------
    def _nearest_safe_moves(self, player_col: int, start_col: int, length: int) -> int:
        s = start_col
        e = start_col + length - 1
        candidates = []
        if s - 1 >= 0: candidates.append(abs(player_col - (s - 1)))
        if e + 1 <= COLS - 1: candidates.append(abs(player_col - (e + 1)))
        return min(candidates) if candidates else 0

    def _spawn_block_safe(self):
        for _ in range(12):
            length = max(1, min(self.max_len, COLS - 1))
            if self.min_len == self.max_len:
                length = min(length, self.min_len)
            start_col = random.randint(0, COLS - length)

            b = Block(start_col, length, steps_per_sec_base=self.stage_base.steps_per_sec)
            b.bind_runtime(self._effective_steps_per_sec)

            ttg = b.time_to_ground_ms()
            need_moves = self._nearest_safe_moves(self.player.col, start_col, length)
            need_ms = int((need_moves / MOVES_PER_SEC) * 1000) + SAFETY_MARGIN_MS

            if need_ms <= ttg:
                self.blocks.append(b); return True

            alt_start = max(0, min(COLS - length, start_col + random.choice((-1, +1))))
            b2 = Block(alt_start, length, steps_per_sec_base=self.stage_base.steps_per_sec)
            b2.bind_runtime(self._effective_steps_per_sec)
            if int((self._nearest_safe_moves(self.player.col, alt_start, length) / MOVES_PER_SEC) * 1000) + SAFETY_MARGIN_MS <= b2.time_to_ground_ms():
                self.blocks.append(b2); return True

            if length > 1:
                length2 = length - 1
                alt2 = random.randint(0, COLS - length2)
                b3 = Block(alt2, length2, steps_per_sec_base=self.stage_base.steps_per_sec)
                b3.bind_runtime(self._effective_steps_per_sec)
                if int((self._nearest_safe_moves(self.player.col, alt2, length2) / MOVES_PER_SEC) * 1000) + SAFETY_MARGIN_MS <= b3.time_to_ground_ms():
                    self.blocks.append(b3); return True
        return False

    # ---------- 업데이트 ----------
    def update(self, dt: int):
        if self.state != GameState.PLAY: return
        self.elapsed_ms += dt
        self._apply_acceleration()
        self.bg.update(dt)

        self.spawn_acc += dt
        if self.spawn_acc >= self.spawn_ms:
            if self._spawn_block_safe(): self.spawn_acc = 0
            else: self.spawn_acc = self.spawn_ms // 2

        for b in self.blocks: b.update(dt)

        alive_blocks = []
        for b in self.blocks:
            if b.hit_ground(): self.explosions.append(Explosion(b.start_col, b.length))
            else: alive_blocks.append(b)
        self.blocks = alive_blocks

        alive_ex = []
        for ex in self.explosions:
            ex.update(dt)
            if ex.alive():
                s, e = ex.danger_cols
                if s <= self.player.col <= e: self.state = GameState.OVER
                alive_ex.append(ex)
        self.explosions = alive_ex

    # ---------- 입력 ----------
    def type_char(self, ch: str):
        if ch and ch.isprintable() and ch not in ("\r", "\n"):
            self.input_buf += ch

    def commit_input(self):
        buf = self.input_buf
        if not buf: 
            return
        if buf == self.left_word:
            self.player.move(-1)
            self._refresh_left()
        elif buf == self.right_word:
            self.player.move(+1)
            self._refresh_right()
        self.input_buf = ""

    # ---------- 그리기 ----------
    def _draw_grid(self):
        pygame.draw.rect(self.screen, (220, 228, 236),
                         (MARGIN_X - 4, TOP_MARGIN, FIELD_W + 8, GROUND_Y - TOP_MARGIN), width=2, border_radius=6)
        for c in range(COLS):
            x = MARGIN_X + c * CELL_W
            col = (245, 248, 252) if c % 2 == 0 else (235, 242, 250)
            pygame.draw.rect(self.screen, col, (x, TOP_MARGIN, CELL_W, GROUND_Y - TOP_MARGIN))
        for c in range(COLS + 1):
            x = MARGIN_X + c * CELL_W
            pygame.draw.line(self.screen, (208, 216, 224), (x, TOP_MARGIN), (x, GROUND_Y), 1)
        pygame.draw.line(self.screen, (80, 80, 80), (MARGIN_X, GROUND_Y), (MARGIN_X + FIELD_W, GROUND_Y), 3)

    def draw_world(self):
        self._draw_grid()
        for b in self.blocks: b.draw(self.screen)
        for ex in self.explosions: ex.draw(self.screen)
        self.player.draw(self.screen)

    def draw_top_left_hud(self):
        lines = [
            f"Time: {self.elapsed_ms // 1000}s",
            "Enter: 단어 확정",
            "Backspace: 입력 삭제",
            "ESC: 종료, (Game Over) R: 재시작",
        ]
        x0, y0 = 16, 12
        for i, t in enumerate(lines):
            self.screen.blit(self.font_ui.render(t, True, (30, 30, 30)), (x0, y0 + i * 22))

    def draw_bottom_center_input(self):
        buf_text = f"> {self.input_buf}"
        surf = self.font_input.render(buf_text, True, (20, 20, 20))
        pad_x, pad_y = 16, 12
        bg = pygame.Surface((surf.get_width() + pad_x * 2, surf.get_height() + pad_y * 2), pygame.SRCALPHA)
        pygame.draw.rect(bg, (255, 255, 255, 180), bg.get_rect(), border_radius=12)
        shadow = pygame.Surface(bg.get_size(), pygame.SRCALPHA)
        pygame.draw.rect(shadow, (0, 0, 0, 50), shadow.get_rect(), border_radius=14)
        x = (WIDTH - bg.get_width()) // 2
        y = GROUND_Y + 34
        self.screen.blit(shadow, (x + 2, y + 2))
        self.screen.blit(bg, (x, y))
        self.screen.blit(surf, (x + pad_x, y + pad_y))

    def draw_center(self):
        self.left_arrow.draw(self.screen)
        self.right_arrow.draw(self.screen)

    def draw_menu(self):
        title = self.font_h1.render("Stage Select (Fixed Difficulty)", True, (15, 15, 20))
        hint = self.font_ui.render("숫자(1~3) 또는 ←/→, Enter로 시작", True, (30, 30, 30))
        self.screen.blit(title, (MARGIN_X, 40))
        self.screen.blit(hint, (MARGIN_X, 90))
        labels = [
            "Stage 1  — len=3, 1 step/s, spawn=8.0s",
            "Stage 2  — len=4, 1.8 step/s, 5.5s",
            "Stage 3  — len=5, 2.4 step/s, 3.5s",
        ]
        y = 140
        for i, label in enumerate(labels):
            sel = (i == self.menu_selected)
            bullet = "▶ " if sel else "   "
            color = (0, 90, 210) if sel else (40, 40, 40)
            line = self.font_big.render(bullet + label, True, color)
            self.screen.blit(line, (MARGIN_X, y))
            y += 36

    def draw_gameover(self):
        msg1 = self.font_h1.render("GAME OVER", True, (20, 20, 20))
        msg2 = self.font_ui.render("Press R to Restart, ESC to Quit", True, (30, 30, 30))
        cx = MARGIN_X + FIELD_W // 2
        self.screen.blit(msg1, (cx - msg1.get_width() // 2, HEIGHT // 2 - 24))
        self.screen.blit(msg2, (cx - msg2.get_width() // 2, HEIGHT // 2 + 18))

    # ---------- 상태 전환 ----------
    def _start_fixed_stage(self):
        self.blocks.clear(); self.explosions.clear()
        self.player = Player(COLS // 2)
        self.input_buf = ""; self.elapsed_ms = 0
        self.spawn_acc = 0

        self.accel_multiplier = 1.0
        self.accel_interval_ms = ACCEL_INTERVAL_START_MS
        self.next_accel_due_ms = ACCEL_INTERVAL_START_MS

        self.min_len = self.stage_base.min_len
        self.max_len = self.stage_base.max_len
        self.spawn_ms = max(SPAWN_MS_LOWER_BOUND, int(self.stage_base.spawn_ms))

        self.left_word = self._make_word()
        self.right_word = self._make_word()
        self.left_arrow.set_word(self.left_word)
        self.right_arrow.set_word(self.right_word)

        self.state = GameState.PLAY

        if not self._spawn_block_safe():
            self.spawn_acc = self.spawn_ms // 2
        else:
            self.spawn_acc = 0

    # ---------- 루프 ----------
    def run(self):
        running = True
        while running:
            dt = self.clock.tick(FPS)
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    running = False
                elif e.type == pygame.KEYDOWN:
                    if e.key == pygame.K_ESCAPE:
                        running = False

                    if self.state == GameState.MENU:
                        if e.key in (pygame.K_RIGHT, pygame.K_d):
                            self.menu_selected = (self.menu_selected + 1) % 3
                        elif e.key in (pygame.K_LEFT, pygame.K_a):
                            self.menu_selected = (self.menu_selected - 1) % 3
                        elif pygame.K_1 <= e.key <= pygame.K_3:
                            self.menu_selected = e.key - pygame.K_1
                        elif e.key == pygame.K_RETURN:
                            self.current_stage_id = self.menu_selected + 1
                            self.stage_base = STAGE_PRESETS[self.current_stage_id]
                            self._start_fixed_stage()

                    elif self.state == GameState.PLAY:
                        if e.key == pygame.K_BACKSPACE:
                            self.input_buf = self.input_buf[:-1]
                        elif e.key == pygame.K_RETURN:
                            self.commit_input()
                        else:
                            if e.unicode and e.unicode.isprintable():
                                self.type_char(e.unicode.lower())

                    elif self.state == GameState.OVER:
                        if e.key == pygame.K_r:
                            self._start_fixed_stage()

            # draw/update
            self.bg.update(dt); self.bg.draw()
            if self.state == GameState.MENU:
                self._draw_grid(); self.draw_menu()
            elif self.state == GameState.PLAY:
                self.update(dt)
                self.draw_world()
                self.draw_top_left_hud()
                self.draw_center()                 # 오로지 Arrow 객체만 그림
                self.draw_bottom_center_input()    # 확대 입력창
                if self.state == GameState.OVER:
                    self.draw_gameover()
            else:
                self.draw_world()
                self.draw_top_left_hud()
                self.draw_center()
                self.draw_bottom_center_input()
                self.draw_gameover()

            pygame.display.flip()

        pygame.quit(); sys.exit()

# -----------------------------
if __name__ == "__main__":
    Game().run()
