# main.py — Fixed-Stage + Progressive Accel + Safe Spawn (Patched)
# 요구사항:
# 1) 스테이지 고정(시간이 지나도 스테이지 자체는 바뀌지 않음)
# 2) Stage 1: 초당 1칸 낙하, 8초 마다 1개 생성
# 3) 글자 길이는 스테이지별 "고정" (min_len == max_len)
# 4) 시간이 지날수록 조금 어려워짐: 30초 → 25초 → 20초 → … 간격으로
#    매번 1.1배씩 낙하/스폰 모두 빨라짐
# 5) 입력 폭주 방지: 플레이어가 물리적으로 불가능한 상황이 되지 않도록 스폰 안전장치
# 6) 패치: 플레이 중 'r' 입력으로 초기화되는 문제 제거, 타이머 실시간 갱신, 시작 즉시 스폰

import os, sys, random, pygame
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, Tuple

# -----------------------------
# 화면/필드 설정
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

# 전체 배율은 고정(가속은 아래 스케줄로 반영)
SLOW_FACTOR     = 1.0

# 가속 파라미터: 30→25→20→… 초마다 1.1배
ACCEL_RATIO = 1.10
ACCEL_INTERVAL_START_MS = 30_000
ACCEL_INTERVAL_STEP_MS  = 5_000   # 간격을 5초씩 단축
ACCEL_INTERVAL_MIN_MS   = 10_000  # 최소 10초

# 스폰 최소 하한(너무 과도한 스폰 방지)
SPAWN_MS_LOWER_BOUND = 220  # 0.22s 밑으론 금지(튜닝 가능)

# 단어 생성 관련
LETTERS   = "asdfjklghqwertyuiopzxcvbnm1234567890"
FONT_NAME = None  # 시스템 폰트 기본

# 타이핑 처리량 가정(스폰 안전장치)
# 2~3 단어/초 정도가 현실적 — 상황에 따라 조정 가능
MOVES_PER_SEC     = 2.8
SAFETY_MARGIN_MS  = 400  # 여유 시간(밀리초)

# -----------------------------
# Stage 정의(고정 난이도)
# -----------------------------
@dataclass(frozen=True)
class StageConf:
    min_len: int         # 단어 최소 길이 == 최대 길이 (고정)
    max_len: int
    steps_per_sec: float # 기본 낙하 속도(초당 칸 수)
    spawn_ms: int        # 기본 생성 간격(ms)

# 글자 길이를 스테이지마다 '고정'하려면 min_len == max_len 로 둔다.
# Stage 1: 낙하 1칸/초, 8000ms(=8초) 생성 — 필수 요구사항 반영
STAGE_PRESETS: dict[int, StageConf] = {
    1: StageConf(min_len=3, max_len=3, steps_per_sec=1.0, spawn_ms=8000),
    2: StageConf(min_len=4, max_len=4, steps_per_sec=1.8, spawn_ms=5500),
    3: StageConf(min_len=5, max_len=5, steps_per_sec=2.4, spawn_ms=3500),
    4: StageConf(min_len=6, max_len=6, steps_per_sec=3.2, spawn_ms=2200),
    5: StageConf(min_len=7, max_len=7, steps_per_sec=4.2, spawn_ms=1500),
    6: StageConf(min_len=8, max_len=8, steps_per_sec=5.0, spawn_ms=1100),
}

# -----------------------------
# 유틸
# -----------------------------
def load_image(path: str, size: Optional[Tuple[int,int]]=None) -> Optional[pygame.Surface]:
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
        if self.img: screen.blit(self.img, self.rect)
        else: pygame.draw.rect(screen, (70,120,255), self.rect, border_radius=8)

@dataclass
class Block:
    start_col: int
    length: int
    steps_per_sec_base: float  # 생성 시점 기준 기본 속도(가속 전)
    y: float = -BLOCK_H
    acc_ms: int = 0
    img: Optional[pygame.Surface] = None

    def __post_init__(self):
        if self.img is None:
            self.img = load_image(os.path.join(ASSET_DIR, "block.png"),
                                  size=(CELL_W*self.length, BLOCK_H))

    def bind_runtime(self, get_steps_per_sec):
        # 현재 가속 배율을 반영하기 위한 콜백(게임에서 주입)
        self._get_steps_per_sec = get_steps_per_sec
        self._recompute_step_interval()

    def _recompute_step_interval(self):
        # 현재 가속이 반영된 sps 사용
        sps = max(0.1, self._get_steps_per_sec())  # 초당 칸 수
        # 전체 SLOW_FACTOR 고려
        self.step_interval_ms = max(60, int(1000 / (sps / SLOW_FACTOR)))

    @property
    def rect(self) -> pygame.Rect:
        return pygame.Rect(MARGIN_X + self.start_col * CELL_W, int(self.y), CELL_W*self.length, BLOCK_H)

    def update(self, dt: int):
        # 가속 변화에 맞춰 step_interval 재계산
        self._recompute_step_interval()
        self.acc_ms += dt
        while self.acc_ms >= self.step_interval_ms:
            self.y += STEP_PX
            self.acc_ms -= self.step_interval_ms

    def hit_ground(self) -> bool:
        return self.y + BLOCK_H >= GROUND_Y

    def time_to_ground_ms(self) -> int:
        # 남은 스텝 수 * 현재 step_interval
        remaining_steps = max(0, int((GROUND_Y - (self.y + BLOCK_H)) // BLOCK_H) + 1)
        return remaining_steps * self.step_interval_ms

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
        pygame.display.set_caption("Typing Dodge — Fixed Stage")
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

        # 고정 스테이지
        self.current_stage_id = 1
        self.stage_base = STAGE_PRESETS[self.current_stage_id]

        # 가속 스케줄
        self.accel_multiplier = 1.0
        self.accel_interval_ms = ACCEL_INTERVAL_START_MS
        self.next_accel_due_ms = ACCEL_INTERVAL_START_MS

        # 가속 적용 후 현재 파라미터
        self.min_len = self.stage_base.min_len
        self.max_len = self.stage_base.max_len
        self.spawn_ms = int(self.stage_base.spawn_ms / self.accel_multiplier)
        self.spawn_ms = max(self.spawn_ms, SPAWN_MS_LOWER_BOUND)
        self.spawn_acc = 0

        # 캐시된 UI 렌더링
        self.cache = {
            "left_word": None, "right_word": None,
            "input": None, "title": None, "menu_hint": None
        }

        # 단어(좌/우 이동용)
        self.left_word  = self._make_word()
        self.right_word = self._make_word()

    # ---------- 단어/스테이지 ----------
    def _make_word(self) -> str:
        # 글자 길이 고정(min_len == max_len)
        L = self.min_len if self.min_len == self.max_len else random.randint(self.min_len, self.max_len)
        return "".join(random.choice(LETTERS) for _ in range(L))

    def _refresh_left(self):
        self.left_word = self._make_word(); self.cache["left_word"] = None

    def _refresh_right(self):
        self.right_word = self._make_word(); self.cache["right_word"] = None

    # ---------- 가속 ----------
    def _apply_acceleration(self):
        if self.elapsed_ms >= self.next_accel_due_ms:
            self.accel_multiplier *= ACCEL_RATIO
            # 가속 간격 줄이되 아래 한계 유지
            self.accel_interval_ms = max(ACCEL_INTERVAL_MIN_MS, self.accel_interval_ms - ACCEL_INTERVAL_STEP_MS)
            self.next_accel_due_ms += self.accel_interval_ms

            # 스폰: 빨라져야 하므로 "나누기" 반영
            new_spawn = int(self.stage_base.spawn_ms / self.accel_multiplier)
            self.spawn_ms = max(SPAWN_MS_LOWER_BOUND, new_spawn)

    def _effective_steps_per_sec(self) -> float:
        # 낙하: 빨라짐 → "곱하기" 반영
        return self.stage_base.steps_per_sec * self.accel_multiplier

    # ---------- 스폰 안전장치 ----------
    def _nearest_safe_moves(self, player_col: int, start_col: int, length: int) -> int:
        s = start_col
        e = start_col + length - 1
        # 안전 구간: [0..s-1], [e+1..COLS-1]
        candidates = []
        if s - 1 >= 0:
            candidates.append(abs(player_col - (s - 1)))
        if e + 1 <= COLS - 1:
            candidates.append(abs(player_col - (e + 1)))
        if not candidates:
            return 0
        return min(candidates)

    def _spawn_block_safe(self):
        max_attempts = 12

        for _ in range(max_attempts):
            # 전체 덮는 10칸은 금지(회피 불가)
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
                self.blocks.append(b)
                return True

            # 완화 1: 시작 위치 한 칸 이동
            alt_start = max(0, min(COLS - length, start_col + random.choice((-1, +1))))
            b2 = Block(alt_start, length, steps_per_sec_base=self.stage_base.steps_per_sec)
            b2.bind_runtime(self._effective_steps_per_sec)
            if int((self._nearest_safe_moves(self.player.col, alt_start, length) / MOVES_PER_SEC) * 1000) + SAFETY_MARGIN_MS <= b2.time_to_ground_ms():
                self.blocks.append(b2)
                return True

            # 완화 2: 길이를 1 줄여 재시도
            if length > 1:
                length2 = length - 1
                alt_start2 = random.randint(0, COLS - length2)
                b3 = Block(alt_start2, length2, steps_per_sec_base=self.stage_base.steps_per_sec)
                b3.bind_runtime(self._effective_steps_per_sec)
                if int((self._nearest_safe_moves(self.player.col, alt_start2, length2) / MOVES_PER_SEC) * 1000) + SAFETY_MARGIN_MS <= b3.time_to_ground_ms():
                    self.blocks.append(b3)
                    return True

        # 이번 틱에서는 스폰을 지연
        return False

    # ---------- 업데이트 ----------
    def update(self, dt: int):
        if self.state != GameState.PLAY: return
        self.elapsed_ms += dt

        # 가속 적용
        self._apply_acceleration()

        self.bg.update(dt)

        # 스폰
        self.spawn_acc += dt
        if self.spawn_acc >= self.spawn_ms:
            if self._spawn_block_safe():
                self.spawn_acc = 0
            else:
                # 물리적으로 불가능한 상황이면 반주기 뒤로 미룸
                self.spawn_acc = self.spawn_ms // 2

        # 블록 낙하
        for b in self.blocks: b.update(dt)

        # 바닥 도달 → 폭발 전환
        alive_blocks = []
        for b in self.blocks:
            if b.hit_ground():
                self.explosions.append(Explosion(b.start_col, b.length))
            else:
                alive_blocks.append(b)
        self.blocks = alive_blocks

        # 폭발 & 충돌
        alive_ex = []
        for ex in self.explosions:
            ex.update(dt)
            if ex.alive():
                s, e = ex.danger_cols
                if s <= self.player.col <= e:
                    self.state = GameState.OVER
                alive_ex.append(ex)
        self.explosions = alive_ex

    # ---------- 입력 ----------
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

    # ---------- 그리기 ----------
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
        if self.cache.get(key) is None:
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

        # ✅ 매 프레임 실시간 갱신(캐시 X)
        sec_text = self.font_ui.render(f"Time: {self.elapsed_ms//1000}s", True, (20,20,20))
        self.screen.blit(sec_text, (panel_x+16, TOP_MARGIN+8))

        len_text = self.font_ui.render(f"Len: {self.min_len}-{self.max_len}", True, (40,40,40))
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

        buf = self.font_ui.render(f"> {self.input_buf}", True, (0,0,0))
        self.screen.blit(buf, (panel_x+16, row_y+46))

        for i, g in enumerate(("Enter: 단어 확정 후 이동","Backspace: 입력 삭제","ESC: 종료, R: 재시작(게임 오버에서)")):
            self.screen.blit(self.font_ui.render(g, True, (60,60,60)), (panel_x+16, row_y+84+24*i))

    def draw_menu(self):
        title = self._surf("title", lambda: self.font_h1.render("Stage Select (Fixed Difficulty)", True, (15,15,20)))
        hint  = self._surf("menu_hint", lambda: self.font_ui.render("숫자(1~6) 또는 ←/→, Enter로 시작", True, (30,30,30)))
        self.screen.blit(title, (MARGIN_X, 40))
        self.screen.blit(hint,  (MARGIN_X, 90))

        labels = [
            "Stage 1  — len=3, 1 step/s, spawn=8.0s",
            "Stage 2  — len=4, 1.8 step/s, 5.5s",
            "Stage 3  — len=5, 2.4 step/s, 3.5s",
            "Stage 4  — len=6, 3.2 step/s, 2.2s",
            "Stage 5  — len=7, 4.2 step/s, 1.5s",
            "Stage 6  — len=8, 5.0 step/s, 1.1s",
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
        msg1 = self.font_h1.render("GAME OVER", True, (20,20,20))
        msg2 = self.font_ui.render("Press R to Restart, ESC to Quit", True, (30,30,30))
        cx = MARGIN_X + FIELD_W // 2
        self.screen.blit(msg1, (cx - msg1.get_width()//2, HEIGHT//2 - 24))
        self.screen.blit(msg2, (cx - msg2.get_width()//2, HEIGHT//2 + 18))

    # ---------- 상태 전환 ----------
    def _start_fixed_stage(self):
        self.blocks.clear(); self.explosions.clear()
        self.player = Player(COLS//2)
        self.input_buf = ""; self.elapsed_ms = 0
        self.spawn_acc = 0

        # 가속 스케줄 리셋
        self.accel_multiplier = 1.0
        self.accel_interval_ms = ACCEL_INTERVAL_START_MS
        self.next_accel_due_ms = ACCEL_INTERVAL_START_MS

        # 스테이지 고정 파라미터
        self.min_len = self.stage_base.min_len
        self.max_len = self.stage_base.max_len
        self.spawn_ms = max(SPAWN_MS_LOWER_BOUND, int(self.stage_base.spawn_ms / self.accel_multiplier))

        # 단어 리셋
        self.left_word  = self._make_word()
        self.right_word = self._make_word()
        for k in ("left_word","right_word","input"):
            self.cache[k] = None

        self.state = GameState.PLAY

        # ✅ 시작 즉시 1개 스폰(안전장치 통과 못하면 반주기 뒤 재시도)
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
                            self.menu_selected = (self.menu_selected + 1) % 6
                        elif e.key in (pygame.K_LEFT, pygame.K_a):
                            self.menu_selected = (self.menu_selected - 1) % 6
                        elif pygame.K_1 <= e.key <= pygame.K_6:
                            self.menu_selected = e.key - pygame.K_1
                        elif e.key == pygame.K_RETURN:
                            self.current_stage_id = self.menu_selected + 1
                            self.stage_base = STAGE_PRESETS[self.current_stage_id]
                            self._start_fixed_stage()

                    elif self.state == GameState.PLAY:
                        if e.key == pygame.K_BACKSPACE:
                            self.input_buf = self.input_buf[:-1]; self.cache["input"] = None
                        elif e.key == pygame.K_RETURN:
                            self.commit_input()
                        else:
                            # ✅ 플레이 중 r 입력은 단순 타이핑으로 처리(초기화 금지)
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
                self.update(dt); self.draw_world(); self.draw_ui()
                if self.state == GameState.OVER: self.draw_gameover()
            else:
                self.draw_world(); self.draw_ui(); self.draw_gameover()

            pygame.display.flip()

        pygame.quit(); sys.exit()

# -----------------------------
if __name__ == "__main__":
    Game().run()
