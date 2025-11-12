# main.py — Single Screen / 3 Stages with Random Word API
# 변경점
# 1) 배경: 항상 검정색
# 2) 단어 자동 글자 크기 조절(좌/우 겹침 방지)
# 3) 게임 종료 시 생존 시간 기반 점수 표시 (Score = SurvivedSeconds * 100)

import os, sys, random, pygame, requests
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, Tuple, List

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
MARGIN_X = (WIDTH - FIELD_W) // 2

IMAGE_DIR = os.path.join(os.path.dirname(__file__), "images")

PLAYER_SIZE = (44, 44)
BLOCK_H = 28
STEP_PX = BLOCK_H

SLOW_FACTOR = 1.0

ACCEL_RATIO = 1.10
ACCEL_INTERVAL_START_MS = 30_000
ACCEL_INTERVAL_STEP_MS = 5_000
ACCEL_INTERVAL_MIN_MS = 10_000

SPAWN_MS_LOWER_BOUND = 220

# API 설정 - Random Word API
API_BASE_URL = "https://random-word-api.herokuapp.com/word"
WORD_CACHE: List[str] = []

LETTERS = "asdfjklghqwertyuiopzxcvbnm1234567890"
FONT_NAME = "malgungothic"

MOVES_PER_SEC = 2.8
SAFETY_MARGIN_MS = 400

# -----------------------------
# 중앙 오버레이 레이아웃
# -----------------------------
CENTER_X = MARGIN_X + FIELD_W // 2
CENTER_Y = (TOP_MARGIN + GROUND_Y) // 2 + 20

ARROW_X_GAP = 150

LEFT_WORD_COLOR = (18, 120, 255)
RIGHT_WORD_COLOR = (255, 140, 0)
WORD_OUTLINE = (0, 0, 0)

CENTER_SAFE_GAP = 24
MAX_TEXT_WIDTH_PER_SIDE = 2 * (ARROW_X_GAP - CENTER_SAFE_GAP)

WORD_FONT_MAX = 58
WORD_FONT_MIN = 18

# -----------------------------
# Stage 정의
# -----------------------------
@dataclass(frozen=True)
class StageConf:
    steps_per_sec: float
    spawn_ms: int

STAGE_PRESETS: dict[int, StageConf] = {
    1: StageConf(steps_per_sec=1.0, spawn_ms=8000),
    2: StageConf(steps_per_sec=1.8, spawn_ms=5500),
    3: StageConf(steps_per_sec=2.4, spawn_ms=3500),
}

# -----------------------------
# 유틸
# -----------------------------
def load_image(path: str, size: Optional[Tuple[int, int]] = None) -> Optional[pygame.Surface]:
    if not os.path.isfile(path):
        print(f"Warning: Image not found - {path}")
        return None
    try:
        img = pygame.image.load(path).convert_alpha()
        return pygame.transform.smoothscale(img, size) if size else img
    except Exception as e:
        print(f"Error loading image {path}: {e}")
        return None

def fetch_words_from_api(count: int = 100) -> List[str]:
    words = []
    try:
        params = {'number': count}
        response = requests.get(API_BASE_URL, params=params, timeout=5)
        if response.status_code == 200:
            word_list = response.json()
            for word in word_list:
                if isinstance(word, str) and word.isalpha():
                    words.append(word.lower())
            print(f"✅ API에서 {len(words)}개 단어 로딩 성공")
        else:
            print(f"❌ API 응답 오류: {response.status_code}")
    except Exception as e:
        print(f"❌ API 호출 실패: {e}")
        print("기본 단어 목록을 사용합니다.")
        fallback_words = [
            "cat","dog","run","jump","play","book","tree","sun","moon","star",
            "bird","fish","love","hope","time","word","good","best","fast","slow",
            "apple","water","house","happy","friend","music","smile","peace","dream","light",
            "strong","bright","quiet","travel","beauty","nature","winter","spring","summer","autumn",
            "mountain","river","forest","garden","flower","butterfly","rainbow","thunder","ocean","desert"
        ]
        words = fallback_words[:count]
    return words

def get_random_word() -> str:
    global WORD_CACHE
    if len(WORD_CACHE) < 20:
        new_words = fetch_words_from_api(100)
        WORD_CACHE.extend(new_words)
    if WORD_CACHE:
        word = random.choice(WORD_CACHE)
        WORD_CACHE.remove(word)
        return word
    else:
        length = random.randint(3, 12)
        return "".join(random.choice(LETTERS) for _ in range(length))

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
    def update(self, dt: int):
        pass
    def draw(self):
        self.screen.fill((0, 0, 0))  # 항상 검정색

class Player:
    def __init__(self, col: int):
        self.col = col
        self.img = load_image(os.path.join(IMAGE_DIR, "chunsik.png"), size=PLAYER_SIZE)

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
    fish_img: Optional[pygame.Surface] = None

    def __post_init__(self):
        if self.fish_img is None:
            base_fish = load_image(os.path.join(IMAGE_DIR, "fish.png"))
            if base_fish:
                self.fish_img = pygame.transform.smoothscale(base_fish, (CELL_W, CELL_W))

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
        if self.fish_img:
            for i in range(self.length):
                x = MARGIN_X + (self.start_col + i) * CELL_W
                fish_rect = pygame.Rect(x, int(self.y) + (BLOCK_H - CELL_W) // 2, CELL_W, CELL_W)
                screen.blit(self.fish_img, fish_rect)
        else:
            pygame.draw.rect(screen, (235, 95, 85), self.rect, border_radius=6)

@dataclass
class Explosion:
    start_col: int
    length: int
    timer: int = 380
    img: Optional[pygame.Surface] = None

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

class Arrow:
    def __init__(self, pointing: str, center: Tuple[int, int],
                 word_color: Tuple[int, int, int],
                 font_name: str,
                 max_width: int,
                 size_min: int = WORD_FONT_MIN,
                 size_max: int = WORD_FONT_MAX):
        assert pointing in ("left", "right")
        self.pointing = pointing
        self.cx, self.cy = center
        self.word_color = word_color
        self.word = "word"
        self.font_name = font_name
        self.max_width = max_width
        self.size_min = size_min
        self.size_max = size_max
        self._cache: dict[str, Tuple[pygame.font.Font, Tuple[int, int]]] = {}

    def set_center(self, center: Tuple[int, int]):
        self.cx, self.cy = center

    def set_word(self, word: str):
        self.word = word

    def _font_fit(self, text: str) -> Tuple[pygame.font.Font, Tuple[int, int]]:
        if text in self._cache:
            return self._cache[text]
        lo, hi = self.size_min, self.size_max
        best_font = pygame.font.SysFont(self.font_name, lo, bold=True)
        best_size = best_font.size(text)
        while lo <= hi:
            mid = (lo + hi) // 2
            f = pygame.font.SysFont(self.font_name, mid, bold=True)
            w, h = f.size(text)
            if w <= self.max_width:
                best_font, best_size = f, (w, h)
                lo = mid + 1
            else:
                hi = mid - 1
        self._cache[text] = (best_font, best_size)
        return best_font, best_size

    def draw(self, surface: pygame.Surface):
        font, (tw, th) = self._font_fit(self.word)
        tx = self.cx - tw // 2
        ty = self.cy - th // 2
        for dx, dy in [(-3, 0), (3, 0), (0, -3), (0, 3), (-2, -2), (2, -2), (-2, 2), (2, 2)]:
            outline = font.render(self.word, True, WORD_OUTLINE)
            surface.blit(outline, (tx + dx, ty + dy))
        text = font.render(self.word, True, self.word_color)
        surface.blit(text, (tx, ty))

# -----------------------------
# Game
# -----------------------------
class Game:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Typing Dodge — Random Word API")
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        self.clock = pygame.time.Clock()

        self.font_ui = pygame.font.SysFont(FONT_NAME, 22, bold=False)
        self.font_big = pygame.font.SysFont(FONT_NAME, 30, bold=True)
        self.font_h1 = pygame.font.SysFont(FONT_NAME, 40, bold=True)
        self.font_input = pygame.font.SysFont(FONT_NAME, 28, bold=False)

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

        self.accel_multiplier = 1.0
        self.accel_interval_ms = ACCEL_INTERVAL_START_MS
        self.next_accel_due_ms = ACCEL_INTERVAL_START_MS

        self.spawn_ms = max(SPAWN_MS_LOWER_BOUND, int(self.stage_base.spawn_ms))
        self.spawn_acc = 0

        self.left_word = self._make_word()
        self.right_word = self._make_word()

        self.left_arrow = Arrow(
            "left",
            (CENTER_X - ARROW_X_GAP, CENTER_Y),
            LEFT_WORD_COLOR,
            FONT_NAME,
            MAX_TEXT_WIDTH_PER_SIDE,
            WORD_FONT_MIN,
            WORD_FONT_MAX,
        )
        self.right_arrow = Arrow(
            "right",
            (CENTER_X + ARROW_X_GAP, CENTER_Y),
            RIGHT_WORD_COLOR,
            FONT_NAME,
            MAX_TEXT_WIDTH_PER_SIDE,
            WORD_FONT_MIN,
            WORD_FONT_MAX,
        )
        self.left_arrow.set_word(self.left_word)
        self.right_arrow.set_word(self.right_word)

        # 점수 관련 상태
        self.gameover_processed = False
        self.final_time_s = 0
        self.final_score = 0
        self.best_score = 0  # 세션 내 최고점

        print(f"🎮 Stage {self.current_stage_id} 단어 캐시 로딩 중...")
        fetch_words_from_api(100)
        print(f"✅ 로딩 완료: {len(WORD_CACHE)}개 단어")

    def _make_word(self) -> str:
        return get_random_word()

    def _refresh_left(self):
        self.left_word = self._make_word()
        self.left_arrow.set_word(self.left_word)

    def _refresh_right(self):
        self.right_word = self._make_word()
        self.right_arrow.set_word(self.right_word)

    def _apply_acceleration(self):
        if self.elapsed_ms >= self.next_accel_due_ms:
            self.accel_multiplier *= ACCEL_RATIO
            self.accel_interval_ms = max(ACCEL_INTERVAL_MIN_MS, self.accel_interval_ms - ACCEL_INTERVAL_STEP_MS)
            self.next_accel_due_ms += self.accel_interval_ms
            self.spawn_ms = max(SPAWN_MS_LOWER_BOUND, int(self.stage_base.spawn_ms / self.accel_multiplier))

    def _effective_steps_per_sec(self) -> float:
        return self.stage_base.steps_per_sec * self.accel_multiplier

    def _nearest_safe_moves(self, player_col: int, start_col: int, length: int) -> int:
        s = start_col
        e = start_col + length - 1
        candidates = []
        if s - 1 >= 0: candidates.append(abs(player_col - (s - 1)))
        if e + 1 <= COLS - 1: candidates.append(abs(player_col - (e + 1)))
        return min(candidates) if candidates else 0

    def _spawn_block_safe(self):
        for _ in range(12):
            length = random.randint(2, min(4, COLS - 1))
            start_col = random.randint(0, COLS - length)

            b = Block(start_col, length, steps_per_sec_base=self.stage_base.steps_per_sec)
            b.bind_runtime(self._effective_steps_per_sec)

            ttg = b.time_to_ground_ms()
            need_moves = self._nearest_safe_moves(self.player.col, start_col, length)
            need_ms = int((need_moves / MOVES_PER_SEC) * 1000) + SAFETY_MARGIN_MS

            if need_ms <= ttg:
                self.blocks.append(b)
                return True

            alt_start = max(0, min(COLS - length, start_col + random.choice((-1, +1))))
            b2 = Block(alt_start, length, steps_per_sec_base=self.stage_base.steps_per_sec)
            b2.bind_runtime(self._effective_steps_per_sec)
            if int((self._nearest_safe_moves(self.player.col, alt_start, length) / MOVES_PER_SEC) * 1000) + SAFETY_MARGIN_MS <= b2.time_to_ground_ms():
                self.blocks.append(b2)
                return True

            if length > 1:
                length2 = length - 1
                alt2 = random.randint(0, COLS - length2)
                b3 = Block(alt2, length2, steps_per_sec_base=self.stage_base.steps_per_sec)
                b3.bind_runtime(self._effective_steps_per_sec)
                if int((self._nearest_safe_moves(self.player.col, alt2, length2) / MOVES_PER_SEC) * 1000) + SAFETY_MARGIN_MS <= b3.time_to_ground_ms():
                    self.blocks.append(b3)
                    return True
        return False

    def update(self, dt: int):
        if self.state != GameState.PLAY:
            return
        self.elapsed_ms += dt
        self._apply_acceleration()
        self.bg.update(dt)

        self.spawn_acc += dt
        if self.spawn_acc >= self.spawn_ms:
            if self._spawn_block_safe():
                self.spawn_acc = 0
            else:
                self.spawn_acc = self.spawn_ms // 2

        for b in self.blocks:
            b.update(dt)

        alive_blocks = []
        for b in self.blocks:
            if b.hit_ground():
                self.explosions.append(Explosion(b.start_col, b.length))
            else:
                alive_blocks.append(b)
        self.blocks = alive_blocks

        alive_ex = []
        for ex in self.explosions:
            ex.update(dt)
            if ex.alive():
                s, e = ex.danger_cols
                if s <= self.player.col <= e:
                    self.state = GameState.OVER
            if ex.alive():
                alive_ex.append(ex)
        self.explosions = alive_ex

        # 게임오버 확정 시 점수 계산(한 번만)
        if self.state == GameState.OVER and not self.gameover_processed:
            self.final_time_s = self.elapsed_ms // 1000
            self.final_score = int(self.final_time_s * 100)  # 시간 기반 점수
            if self.final_score > self.best_score:
                self.best_score = self.final_score
            self.gameover_processed = True
            print(f"🧮 Score 계산: Survived {self.final_time_s}s → Score {self.final_score}")

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

    def _draw_grid(self):
        for c in range(COLS + 1):
            x = MARGIN_X + c * CELL_W
            for y in range(TOP_MARGIN, GROUND_Y, 20):
                pygame.draw.line(self.screen, (255, 250, 235, 100),
                                 (x, y), (x, y + 10), 1)
        pygame.draw.line(self.screen, (160, 130, 100),
                         (MARGIN_X, GROUND_Y),
                         (MARGIN_X + FIELD_W, GROUND_Y), 4)

    def draw_world(self):
        self._draw_grid()
        for b in self.blocks:
            b.draw(self.screen)
        for ex in self.explosions:
            ex.draw(self.screen)
        self.player.draw(self.screen)

    def draw_top_left_hud(self):
        lines = [
            f"Time: {self.elapsed_ms // 1000}s",
            "Enter: confirm word",
            "Backspace: delete input",
            "ESC: quit, (Game Over) R: restart",
        ]
        x0, y0 = 16, 12
        for i, t in enumerate(lines):
            self.screen.blit(self.font_ui.render(t, True, (220, 220, 220)), (x0, y0 + i * 22))

    def draw_bottom_center_input(self):
        buf_text = f"> {self.input_buf}"
        surf = self.font_input.render(buf_text, True, (230, 230, 230))
        pad_x, pad_y = 16, 12
        bg = pygame.Surface((surf.get_width() + pad_x * 2, surf.get_height() + pad_y * 2), pygame.SRCALPHA)
        pygame.draw.rect(bg, (30, 30, 30, 220), bg.get_rect(), border_radius=12)
        shadow = pygame.Surface(bg.get_size(), pygame.SRCALPHA)
        pygame.draw.rect(shadow, (0, 0, 0, 80), shadow.get_rect(), border_radius=14)
        x = (WIDTH - bg.get_width()) // 2
        y = GROUND_Y + 34
        self.screen.blit(shadow, (x + 2, y + 2))
        self.screen.blit(bg, (x, y))
        self.screen.blit(surf, (x + pad_x, y + pad_y))

    def draw_center(self):
        self.left_arrow.draw(self.screen)
        self.right_arrow.draw(self.screen)

    def draw_menu(self):
        title = self.font_h1.render("Stage Select", True, (230, 230, 230))
        hint = self.font_ui.render("숫자(1~3) 또는 ←/→, Enter로 시작", True, (220, 220, 220))
        self.screen.blit(title, (MARGIN_X, 40))
        self.screen.blit(hint, (MARGIN_X, 90))
        labels = [
            "Stage 1  — 쉬움, 1 step/s, spawn=8.0s",
            "Stage 2  — 보통, 1.8 step/s, 5.5s",
            "Stage 3  — 어려움, 2.4 step/s, 3.5s",
        ]
        y = 140
        for i, label in enumerate(labels):
            sel = (i == self.menu_selected)
            bullet = "▶ " if sel else "   "
            color = (120, 180, 255) if sel else (200, 200, 200)
            line = self.font_big.render(bullet + label, True, color)
            self.screen.blit(line, (MARGIN_X, y))
            y += 36

    def draw_gameover(self):
        # 어둡게 덮는 반투명 오버레이
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 150))
        self.screen.blit(overlay, (0, 0))

        # 중앙 카드(하얀 창) 크기/위치
        card_w = min(560, WIDTH - 80)
        card_h = 280
        card_x = (WIDTH - card_w) // 2
        card_y = (HEIGHT - card_h) // 2

        # 그림자
        shadow = pygame.Surface((card_w, card_h), pygame.SRCALPHA)
        pygame.draw.rect(shadow, (0, 0, 0, 70), shadow.get_rect(), border_radius=18)
        self.screen.blit(shadow, (card_x + 4, card_y + 6))

        # 카드 본체(하얀색)
        card = pygame.Surface((card_w, card_h), pygame.SRCALPHA)
        pygame.draw.rect(card, (255, 255, 255, 245), card.get_rect(), border_radius=16)
        self.screen.blit(card, (card_x, card_y))

        # 카드 내부 텍스트 (검정색)
        pad_x, pad_y = 24, 20
        cx = card_x + card_w // 2

        title = self.font_h1.render("GAME OVER", True, (15, 15, 15))
        self.screen.blit(title, (cx - title.get_width() // 2, card_y + pad_y))

        # 구분선
        line_y = card_y + pad_y + title.get_height() + 10
        pygame.draw.line(self.screen, (220, 220, 220),
                        (card_x + pad_x, line_y),
                        (card_x + card_w - pad_x, line_y), 2)

        # 점수/시간/베스트
        info_y = line_y + 18
        score_line = self.font_big.render(f"Score : {self.final_score}", True, (20, 20, 20))
        time_line  = self.font_ui.render (f"Time   : {self.final_time_s}s", True, (35, 35, 35))
        best_line  = self.font_ui.render (f"Best   : {self.best_score}", True, (35, 35, 35))

        self.screen.blit(score_line, (cx - score_line.get_width() // 2, info_y))
        self.screen.blit(time_line,  (cx - time_line.get_width()  // 2, info_y + 36))
        self.screen.blit(best_line,  (cx - best_line.get_width()  // 2, info_y + 62))

        # 안내 문구
        hint_text = self.font_ui.render("Press R to Restart, ESC to Quit", True, (55, 55, 55))
        self.screen.blit(hint_text, (cx - hint_text.get_width() // 2, card_y + card_h - pad_y - hint_text.get_height()))


    def _start_fixed_stage(self):
        global WORD_CACHE
        WORD_CACHE.clear()

        self.blocks.clear()
        self.explosions.clear()
        self.player = Player(COLS // 2)
        self.input_buf = ""
        self.elapsed_ms = 0
        self.spawn_acc = 0

        self.accel_multiplier = 1.0
        self.accel_interval_ms = ACCEL_INTERVAL_START_MS
        self.next_accel_due_ms = ACCEL_INTERVAL_START_MS

        self.spawn_ms = max(SPAWN_MS_LOWER_BOUND, int(self.stage_base.spawn_ms))

        # 점수 상태 초기화 (best_score는 유지)
        self.gameover_processed = False
        self.final_time_s = 0
        self.final_score = 0

        print(f"🎮 Stage {self.current_stage_id} 시작 - 단어 로딩 중...")
        fetch_words_from_api(100)
        print(f"✅ 로딩 완료: {len(WORD_CACHE)}개 단어")

        self.left_word = self._make_word()
        self.right_word = self._make_word()
        self.left_arrow.set_word(self.left_word)
        self.right_arrow.set_word(self.right_word)

        self.state = GameState.PLAY

        if not self._spawn_block_safe():
            self.spawn_acc = self.spawn_ms // 2
        else:
            self.spawn_acc = 0

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

            self.bg.update(dt)
            self.bg.draw()

            if self.state == GameState.MENU:
                self.draw_menu()
            elif self.state == GameState.PLAY:
                self.update(dt)
                self.draw_world()
                self.draw_top_left_hud()
                self.draw_center()
                self.draw_bottom_center_input()
                if self.state == GameState.OVER:
                    self.draw_gameover()
            else:
                self.draw_world()
                self.draw_top_left_hud()
                self.draw_center()
                self.draw_bottom_center_input()
                self.draw_gameover()

            pygame.display.flip()

        pygame.quit()
        sys.exit()

if __name__ == "__main__":
    Game().run()
