# main.py (refactored & optimized)
import os, sys, random, pygame, bisect
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, Tuple

# -----------------------------
# Config
# -----------------------------
WIDTH, HEIGHT   = 900, 760
FPS             = 60
COLS            = 10
CELL_W          = 56
FIELD_W         = COLS * CELL_W
MARGIN_X        = 50
TOP_MARGIN      = 20
GROUND_Y        = HEIGHT - 110
UI_PANEL_W      = 260

ASSET_DIR       = os.path.join(os.path.dirname(__file__), "assets")

PLAYER_SIZE     = (44, 44)
BLOCK_H         = 28
STEP_PX         = BLOCK_H
SLOW_FACTOR     = 5.0
SPAWN_MS_MIN    = int(450 * SLOW_FACTOR)

LETTERS         = "asdfjklghqwertyuiopzxcvbnm1234567890"
FONT_NAME       = None  # system default

@dataclass(frozen=True)
class Stage:
    at_sec: int
    min_len: int
    max_len: int
    steps_per_sec: float
    spawn_ms: int

STAGES = [
    Stage(0,   1, 3, 2.0, 1300),
    Stage(10,  1, 5, 2.8, 1100),
    Stage(20,  2, 7, 3.6,  900),
    Stage(30,  3, 9, 4.4,  720),
    Stage(45,  4, 9, 5.2,  580),
    Stage(60,  5, 9, 6.0,  500),
]
STAGE_KEYS = [s.at_sec for s in STAGES]

START_STAGE_OPTIONS = [
    ("Stage 1  (len 1-3, slow)", 0),
    ("Stage 2  (len 1-5)",       10),
    ("Stage 3  (len 2-7)",       20),
    ("Stage 4  (len 3-9)",       30),
    ("Stage 5  (len 4-9, fast)", 45),
    ("Stage 6  (len 5-9, faster)", 60),
]

def load_image(path: str, size: Optional[Tuple[int,int]]=None) -> Optional[pygame.Surface]:
    if not os.path.isfile(path):
        return None
    try:
        img = pygame.image.load(path).convert_alpha()
        return pygame.transform.smoothscale(img, size) if size else img
    except Exception:
        return None

# -----------------------------
# Entities
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
        if self.img: screen.blit(self.img, self.rect)
        else: pygame.draw.rect(screen, (70,120,255), self.rect, border_radius=8)

@dataclass
class Block:
    start_col: int
    length: int
    steps_per_sec: float
    y: float = -BLOCK_H
    acc_ms: int = 0
    img: Optional[pygame.Surface] = None

    def __post_init__(self):
        # 전체 느리게: 속도 보정
        sps = max(0.1, self.steps_per_sec / SLOW_FACTOR)
        self.step_interval_ms = max(60, int(1000 / sps))
        if self.img is None:
            self.img = load_image(os.path.join(ASSET_DIR, "block.png"),
                                  size=(CELL_W*self.length, BLOCK_H))

    @property
    def rect(self) -> pygame.Rect:
        return pygame.Rect(MARGIN_X + self.start_col * CELL_W, int(self.y), CELL_W*self.length, BLOCK_H)

    def update(self, dt: int):
        self.acc_ms += dt
        while self.acc_ms >= self.step_interval_ms:
            self.y += STEP_PX
            self.acc_ms -= self.step_interval_ms

    def hit_ground(self) -> bool:
        return self.y + BLOCK_H >= GROUND_Y

    def draw(self, screen: pygame.Surface):
        if self.img: screen.blit(self.img, (self.rect.x, self.rect.y))
        else: pygame.draw.rect(screen, (235,95,85), self.rect, border_radius=6)

@dataclass
class Explosion:
    start_col: int
    length: int
    timer: int = 380
    img: Optional[pygame.Surface] = None

    def __post_init__(self):
        if self.img is None:
            self.img = load_image(os.path.join(ASSET_DIR, "explosion.png"),
                                  size=(CELL_W*self.length, CELL_W//2))

    @property
    def danger_cols(self):  # (start, end)
        return self.start_col, self.start_col + self.length - 1

    def update(self, dt: int):
        self.timer -= dt

    def alive(self) -> bool:
        return self.timer > 0

    def draw(self, screen: pygame.Surface):
        x = MARGIN_X + self.start_col * CELL_W
        y = GROUND_Y - (CELL_W // 2)
        if self.img: screen.blit(self.img, (x, y))
        else:
            s = pygame.Surface((CELL_W*self.length, CELL_W//2), pygame.SRCALPHA)
            s.fill((255, 180, 60, 150)); screen.blit(s, (x, y))
            pygame.draw.rect(screen, (255,120,0), (x,y,CELL_W*self.length,CELL_W//2), width=2, border_radius=6)

# -----------------------------
# Game
# -----------------------------
class Game:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("비 피하기 + 타자 연습")
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        self.clock  = pygame.time.Clock()

        self.font_ui  = pygame.font.SysFont(FONT_NAME, 24, bold=True)
        self.font_big = pygame.font.SysFont(FONT_NAME, 30, bold=True)
        self.font_h1  = pygame.font.SysFont(FONT_NAME, 40, bold=True)

        self.bg = Background(self.screen)
        self.player = Player(COLS//2)
        self.blocks: list[Block] = []
        self.explosions: list[Explosion] = []

        self.input_buf = ""
        self.elapsed_ms = 0
        self.state = GameState.MENU
        self.menu_selected = 0
        self.stage_shift = 0

        self.spawn_ms = int(1300 * SLOW_FACTOR)
        self.spawn_acc = 0

        # cached UI surfaces (render only when text changes)
        self.cache = {
            "time": None, "len": None,
            "left_word": None, "right_word": None,
            "input": None, "menu_lines": None, "title": None, "menu_hint": None
        }

        # word lengths set by stage
        self.min_len, self.max_len = 1, 3
        self.left_word  = self._make_word()
        self.right_word = self._make_word()

    # ---------- Stage / Words ----------
    def _current_stage(self) -> Stage:
        sec = self.elapsed_ms // 1000 + self.stage_shift
        i = bisect.bisect_right(STAGE_KEYS, sec) - 1
        i = max(0, min(i, len(STAGES)-1))
        return STAGES[i]

    def _apply_stage(self):
        st = self._current_stage()
        self.min_len, self.max_len = st.min_len, st.max_len
        self.spawn_ms = max(SPAWN_MS_MIN, int(st.spawn_ms * SLOW_FACTOR))

    def _make_word(self) -> str:
        L = random.randint(self.min_len, self.max_len)
        return "".join(random.choice(LETTERS) for _ in range(L))

    def _refresh_left(self):
        self.left_word = self._make_word(); self.cache["left_word"] = None

    def _refresh_right(self):
        self.right_word = self._make_word(); self.cache["right_word"] = None

    # ---------- Spawning ----------
    def _spawn_block(self):
        st = self._current_stage()
        length = max(1, min(9, random.randint(self.min_len, self.max_len)))
        start_col = random.randint(0, COLS - length)
        self.blocks.append(Block(start_col, length, st.steps_per_sec))

    # ---------- Update ----------
    def update(self, dt: int):
        if self.state != GameState.PLAY: return
        self.elapsed_ms += dt
        self._apply_stage()
        self.bg.update(dt)

        self.spawn_acc += dt
        if self.spawn_acc >= self.spawn_ms:
            self._spawn_block()
            self.spawn_acc = 0

        for b in self.blocks: b.update(dt)

        # block -> explosion
        alive_blocks = []
        for b in self.blocks:
            if b.hit_ground():
                self.explosions.append(Explosion(b.start_col, b.length))
            else:
                alive_blocks.append(b)
        self.blocks = alive_blocks

        # explosions + collision
        alive_ex = []
        for ex in self.explosions:
            ex.update(dt)
            if ex.alive():
                s, e = ex.danger_cols
                if s <= self.player.col <= e:
                    self.state = GameState.OVER
                alive_ex.append(ex)
        self.explosions = alive_ex

    # ---------- Input ----------
    def type_char(self, ch: str):
        if ch and ch.isprintable() and ch not in ("\r", "\n"):
            self.input_buf += ch
            self.cache["input"] = None

    def commit_input(self):
        buf = self.input_buf
        if not buf: return
        if buf == self.left_word:
            self.player.move(-1); self._refresh_left()
        elif buf == self.right_word:
            self.player.move(+1); self._refresh_right()
        self.input_buf = ""; self.cache["input"] = None

    # ---------- Draw ----------
    def _draw_grid(self):
        pygame.draw.rect(self.screen, (220,228,236),
                         (MARGIN_X-4, TOP_MARGIN, FIELD_W+8, GROUND_Y-TOP_MARGIN), width=2, border_radius=6)
        for c in range(COLS):
            x = MARGIN_X + c*CELL_W
            col = (245,248,252) if c%2==0 else (235,242,250)
            pygame.draw.rect(self.screen, col, (x, TOP_MARGIN, CELL_W, GROUND_Y-TOP_MARGIN))
        for c in range(COLS+1):
            x = MARGIN_X + c*CELL_W
            pygame.draw.line(self.screen, (208,216,224), (x, TOP_MARGIN), (x, GROUND_Y), 1)
        pygame.draw.line(self.screen, (80,80,80), (MARGIN_X, GROUND_Y), (MARGIN_X+FIELD_W, GROUND_Y), 3)

    def _surf(self, key: str, maker):
        if self.cache[key] is None:
            self.cache[key] = maker()
        return self.cache[key]

    def draw_world(self):
        self._draw_grid()
        for b in self.blocks: b.draw(self.screen)
        for ex in self.explosions: ex.draw(self.screen)
        self.player.draw(self.screen)

    def draw_ui(self):
        panel_x = MARGIN_X + FIELD_W + 20
        rect = (panel_x, TOP_MARGIN, UI_PANEL_W, HEIGHT - TOP_MARGIN*2)
        pygame.draw.rect(self.screen, (245,248,252), rect, border_radius=8)
        pygame.draw.rect(self.screen, (215,222,230), rect, width=2, border_radius=8)

        sec_text = self._surf("time", lambda: self.font_ui.render(f"Time: {self.elapsed_ms//1000}s", True, (20,20,20)))
        self.screen.blit(sec_text, (panel_x+16, TOP_MARGIN+8))

        len_text = self._surf("len", lambda: self.font_ui.render(f"Len: {self.min_len}-{self.max_len}", True, (40,40,40)))
        self.screen.blit(len_text, (panel_x+16, TOP_MARGIN+36))

        row_y = TOP_MARGIN + 80
        left_label  = self.font_big.render("←", True, (30,30,30))
        right_label = self.font_big.render("→", True, (30,30,30))
        lw = self._surf("left_word",  lambda: self.font_big.render(self.left_word,  True, (0,110,230)))
        rw = self._surf("right_word", lambda: self.font_big.render(self.right_word, True, (230,120,0)))

        self.screen.blit(left_label, (panel_x+16, row_y))
        self.screen.blit(lw, (panel_x+50, row_y))
        rx = panel_x + UI_PANEL_W - rw.get_width() - 50
        self.screen.blit(rw, (rx, row_y))
        self.screen.blit(right_label, (rx + rw.get_width() + 8, row_y))

        buf = self._surf("input", lambda: self.font_ui.render(f"> {self.input_buf}", True, (0,0,0)))
        self.screen.blit(buf, (panel_x+16, row_y+46))

        for i, g in enumerate(("Enter: 단어 확정 후 이동","Backspace: 입력 삭제","ESC: 종료, R: 재시작")):
            self.screen.blit(self.font_ui.render(g, True, (60,60,60)), (panel_x+16, row_y+84+24*i))

    def draw_menu(self):
        title = self._surf("title", lambda: self.font_h1.render("Typing Dodge — Stage Select", True, (15,15,20)))
        hint  = self._surf("menu_hint", lambda: self.font_ui.render("숫자(1~6) 또는 ←/→, Enter로 시작", True, (30,30,30)))
        self.screen.blit(title, (MARGIN_X, 40))
        self.screen.blit(hint,  (MARGIN_X, 90))

        y = 140
        for i, (label, _) in enumerate(START_STAGE_OPTIONS):
            sel = (i == self.menu_selected)
            bullet = "▶ " if sel else "   "
            color = (0, 90, 210) if sel else (40, 40, 40)
            line = self.font_big.render(bullet + label, True, color)
            self.screen.blit(line, (MARGIN_X, y))
            y += 36

    def draw_gameover(self):
        msg1 = self.font_h1.render("GAME OVER", True, (20,20,20))
        msg2 = self.font_ui.render("Press R to Restart, ESC to Quit", True, (30,30,30))
        cx = MARGIN_X + FIELD_W // 2
        self.screen.blit(msg1, (cx - msg1.get_width()//2, HEIGHT//2 - 24))
        self.screen.blit(msg2, (cx - msg2.get_width()//2, HEIGHT//2 + 18))

    # ---------- State ----------
    def reset_play(self):
        self.blocks.clear(); self.explosions.clear()
        self.player = Player(COLS//2)
        self.input_buf = ""; self.elapsed_ms = 0
        self.spawn_acc = 0
        self.min_len, self.max_len = 1, 3
        self.left_word  = self._make_word()
        self.right_word = self._make_word()
        for k in ("time","len","left_word","right_word","input"):
            self.cache[k] = None
        self.state = GameState.PLAY

    # ---------- Main Loop ----------
    def run(self):
        running = True
        while running:
            dt = self.clock.tick(FPS)
            for e in pygame.event.get():
                if e.type == pygame.QUIT: running = False
                elif e.type == pygame.KEYDOWN:
                    if e.key == pygame.K_ESCAPE: running = False

                    if self.state == GameState.MENU:
                        if e.key in (pygame.K_RIGHT, pygame.K_d):
                            self.menu_selected = (self.menu_selected + 1) % len(START_STAGE_OPTIONS)
                        elif e.key in (pygame.K_LEFT, pygame.K_a):
                            self.menu_selected = (self.menu_selected - 1) % len(START_STAGE_OPTIONS)
                        elif pygame.K_1 <= e.key <= pygame.K_6:
                            self.menu_selected = e.key - pygame.K_1
                        elif e.key == pygame.K_RETURN:
                            _, shift = START_STAGE_OPTIONS[self.menu_selected]
                            self.stage_shift = shift
                            self.reset_play()

                    elif self.state == GameState.PLAY:
                        if e.key == pygame.K_BACKSPACE:
                            self.input_buf = self.input_buf[:-1]; self.cache["input"] = None
                        elif e.key == pygame.K_RETURN:
                            self.commit_input()
                        else:
                            if e.unicode and e.unicode.isprintable():
                                self.type_char(e.unicode.lower())

                    elif self.state == GameState.OVER:
                        if e.key == pygame.K_r: self.reset_play()

            # draw
            self.bg.update(dt); self.bg.draw()
            if self.state == GameState.MENU:
                self._draw_grid(); self.draw_menu()
            elif self.state == GameState.PLAY:
                self.update(dt); self.draw_world(); self.draw_ui()
                if self.state == GameState.OVER: self.draw_gameover()
            else:
                self.draw_world(); self.draw_ui(); self.draw_gameover()

            pygame.display.flip()

        pygame.quit(); sys.exit()

if __name__ == "__main__":
    Game().run()
