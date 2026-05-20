import pygame
import threading
import re
import time


BG_COLOR = (30, 32, 36)
TEXT_COLOR = (190, 190, 185)
INPUT_BG = (40, 42, 48)
INPUT_BORDER = (70, 72, 78)
INPUT_TEXT = (210, 210, 205)
INPUT_SELECTION_BG = (72, 92, 130)
MENU_OVERLAY = (10, 12, 16, 170)
MENU_PANEL_BG = (28, 31, 36)
MENU_PANEL_BORDER = (82, 86, 96)
MENU_BUTTON_BG = (54, 58, 68)
MENU_BUTTON_HOVER = (74, 80, 94)
MENU_BUTTON_TEXT = (220, 224, 232)
PROMPT_COLOR = (130, 135, 120)
HIGHLIGHT_NAME = (180, 160, 100)
HIGHLIGHT_LOCATION = (100, 160, 180)
HIGHLIGHT_ITEM = (140, 180, 120)
HIGHLIGHT_DESCRIPTOR = (120, 150, 135)
HIGHLIGHT_NPC = (200, 145, 115)
HIGHLIGHT_TIME = (155, 135, 185)
HIGHLIGHT_DANGER = (205, 110, 110)
HIGHLIGHT_INTERACT = (120, 175, 170)
HIGHLIGHT_COMBAT = (190, 100, 100)
SYSTEM_COLOR = (120, 120, 115)
CURSOR_COLOR = (190, 190, 185)
PARAGRAPH_GAP = 10


class TextBlock:
    def __init__(self, text: str, color=None, is_player=False, highlights=None):
        self.text = text
        self.color = color or TEXT_COLOR
        self.is_player = is_player
        self.highlights = highlights or {}
        self.chars_shown = 0
        self.fully_revealed = False

    def reveal_all(self):
        self.chars_shown = len(self.text)
        self.fully_revealed = True


class GameUI:
    def __init__(self, width=900, height=600):
        pygame.init()
        self.base_width = width
        self.base_height = height

        self.screen = pygame.display.set_mode(
            (width, height),
            pygame.RESIZABLE
        )
        pygame.display.set_caption("The Game")
        pygame.key.set_repeat(600, 50)
        self._clipboard_fallback = ""
        try:
            pygame.scrap.init()
        except Exception:
            pass

        self.width = width
        self.height = height

        self.font = pygame.font.SysFont("Menlo", 17)
        if not self.font:
            self.font = pygame.font.SysFont("Consolas", 17)
        if not self.font:
            self.font = pygame.font.SysFont("Courier", 17)

        self.line_height = self.font.get_linesize() + 3
        self.margin_left = 24
        self.margin_right = 24
        self.margin_top = 18
        self.input_height = 44
        self.text_area_height = height - self.input_height - self.margin_top - 14
        self.max_text_width = width - self.margin_left - self.margin_right

        self.lock = threading.RLock()
        self.blocks: list[TextBlock] = []
        self.input_text = ""
        self.input_cursor_pos = 0
        self.input_selection_anchor: int | None = None
        self.input_view_start = 0
        self.input_view_end = 0
        self.input_bar_rect = pygame.Rect(0, 0, 0, 0)
        self.input_text_x = 0
        self.input_text_y = 0
        self.cursor_visible = True
        self.cursor_timer = 0
        self.scroll_offset = 0
        self.typewriter_speed = 120
        self.typewriter_timer = 0
        self.running = True
        self.pending_input = None
        self.input_ready = threading.Event()
        self.clock = pygame.time.Clock()
        self.awaiting_input = False
        self.allow_empty_submit = False
        self.menu_active = False
        self.menu_title = ""
        self.menu_subtitle = ""
        self.menu_options: list[tuple[str, str]] = []
        self.menu_choice = ""
        self.menu_ready = threading.Event()
        self.menu_button_rects: list[tuple[pygame.Rect, str]] = []
        self.menu_hover_choice = ""
        self.menu_layout = "vertical"
        self.menu_scroll = 0
        self.window_focused = True

        self.combat_intro_active = False
        self.combat_intro_title = ""
        self.combat_intro_visible = True
        self.combat_intro_timer = 0.0
        self.combat_intro_interval = 0.12
        self.combat_intro_flips_left = 0
        self.combat_intro_ready = threading.Event()

        self.combat_active = False
        self.combat_title = ""
        self.combat_status_lines: list[tuple[str, int | None]] = []
        self.combat_options: list[tuple[str, str]] = []
        self.combat_choice = ""
        self.combat_ready = threading.Event()
        self.combat_button_rects: list[tuple[pygame.Rect, str]] = []
        self.combat_hover_choice = ""
        self.combat_panel_height = 148
        self.combat_layout = "horizontal"
        self.combat_scroll = 0

        self.player_name = ""
        self.known_locations: list[str] = []
        self.known_items: list[str] = []
        self.known_descriptors: list[str] = []
        self.known_npcs: list[str] = []

    # ── context ──────────────────────────────────────────────────────────────

    def set_context(self, player_name: str, locations: list[str], items: list[str], npcs: list[str] | None = None):
        with self.lock:
            self.player_name = player_name
            self.known_locations = locations
            self.known_items = items
            self.known_descriptors = self._extract_location_descriptors(locations)
            self.known_npcs = npcs or []

    def _extract_location_descriptors(self, locations: list[str]) -> list[str]:
        stopwords = {
            "the", "a", "an", "and", "or", "of", "to", "at", "in", "on", "by", "for", "with", "from",
            "near", "toward", "towards", "above", "below", "off", "into", "over", "under", "through", "across",
            "edge", "road", "path"
        }
        words = set()
        for loc in locations:
            for token in re.findall(r"[a-zA-Z]+", loc.lower()):
                if len(token) < 4:
                    continue
                if token in stopwords:
                    continue
                words.add(token)
        return sorted(words, key=len, reverse=True)

    # ── public block adders ───────────────────────────────────────────────────

    def add_narrative(self, text: str):
        with self.lock:
            highlights = self._build_highlights(text)
            block = TextBlock(text, TEXT_COLOR, is_player=False, highlights=highlights)
            self.blocks.append(block)
            self._scroll_to_bottom()  # always scroll for new narrative

    def add_player_input(self, text: str):
        with self.lock:
            block = TextBlock(f">> {text}", PROMPT_COLOR, is_player=True)
            block.reveal_all()
            self.blocks.append(block)
            self._scroll_to_bottom()

    def add_system(self, text: str):
        with self.lock:
            block = TextBlock(text, SYSTEM_COLOR, is_player=False)
            block.reveal_all()
            self.blocks.append(block)
            if self._is_at_bottom():  # only scroll if already at bottom
                self._scroll_to_bottom()

    def add_combat_text(self, text: str, animate: bool = False):
        with self.lock:
            block = TextBlock(text, HIGHLIGHT_COMBAT, is_player=False)
            if not animate:
                block.reveal_all()
            self.blocks.append(block)
            if self._is_at_bottom():  # only scroll if already at bottom
                self._scroll_to_bottom()

    def remove_loading_indicator(self):
        with self.lock:
            if self.blocks and self.blocks[-1].text == "...":
                self.blocks.pop()

    # ── input / menu / combat hud ─────────────────────────────────────────────

    def get_input(self, prompt="", allow_empty=False) -> str:
        self.input_text = ""
        self.input_cursor_pos = 0
        self.input_selection_anchor = None
        self.pending_input = None
        self.allow_empty_submit = allow_empty
        self.input_ready.clear()
        self.awaiting_input = True
        self.input_ready.wait()
        self.awaiting_input = False
        return self.pending_input or ""

    def show_menu(self, title: str, options: list[tuple[str, str]], subtitle: str = "", layout: str = "vertical") -> str:
        with self.lock:
            self.menu_title = title
            self.menu_subtitle = subtitle
            self.menu_options = options
            self.menu_layout = layout
            self.menu_choice = ""
            self.menu_hover_choice = ""
            self.menu_button_rects = []
            self.menu_scroll = 0
            self.menu_active = True
            self.awaiting_input = False
        self.menu_ready.clear()
        self.menu_ready.wait()
        with self.lock:
            choice = self.menu_choice
            self.menu_active = False
            self.menu_button_rects = []
        return choice

    def begin_combat_intro(self, title: str, flashes: int = 3, interval: float = 0.12):
        with self.lock:
            self.combat_intro_title = title
            self.combat_intro_visible = True
            self.combat_intro_timer = 0.0
            self.combat_intro_interval = interval
            self.combat_intro_flips_left = max(1, flashes * 2)
            self.combat_intro_active = True
        self.combat_intro_ready.clear()

    def wait_for_combat_intro(self):
        self.combat_intro_ready.wait()

    def show_combat_hud(self, title: str, status_lines: list[tuple[str, int | None]], options: list[tuple[str, str]], layout: str = "horizontal") -> str:
        with self.lock:
            self.combat_title = title
            self.combat_status_lines = status_lines
            self.combat_options = options
            self.combat_layout = layout
            self.combat_scroll = 0
            self.combat_choice = ""
            self.combat_hover_choice = ""
            self.combat_button_rects = []
            self.combat_panel_height = 220 if layout == "horizontal" else 340
            self.combat_active = True
            self.awaiting_input = False
        self._scroll_to_bottom()  # recalculate with panel height set
        self.combat_ready.clear()
        self.combat_ready.wait()
        with self.lock:
            choice = self.combat_choice
            self.combat_active = False
            self.combat_button_rects = []
        return choice

    def end_combat_hud(self):
        self.combat_active = False
        self.combat_button_rects = []

    def wait_for_text_output(self):
        while True:
            with self.lock:
                done = all(b.fully_revealed for b in self.blocks)
            if done:
                break
            time.sleep(0.01)

    # ── clipboard ─────────────────────────────────────────────────────────────

    def _set_clipboard_text(self, text: str):
        self._clipboard_fallback = text
        try:
            pygame.scrap.put(pygame.SCRAP_TEXT, text.encode("utf-8"))
        except Exception:
            pass

    def _get_clipboard_text(self) -> str:
        try:
            raw = pygame.scrap.get(pygame.SCRAP_TEXT)
            if raw:
                return raw.decode("utf-8", errors="ignore").replace("\x00", "")
        except Exception:
            pass
        return self._clipboard_fallback

    # ── input editing helpers ─────────────────────────────────────────────────

    def _selection_bounds(self) -> tuple[int, int] | None:
        if self.input_selection_anchor is None or self.input_selection_anchor == self.input_cursor_pos:
            return None
        return tuple(sorted((self.input_selection_anchor, self.input_cursor_pos)))

    def _clear_selection(self):
        self.input_selection_anchor = None

    def _delete_selection_if_any(self) -> bool:
        bounds = self._selection_bounds()
        if not bounds:
            return False
        start, end = bounds
        self.input_text = self.input_text[:start] + self.input_text[end:]
        self.input_cursor_pos = start
        self._clear_selection()
        return True

    def _insert_text_at_cursor(self, text: str):
        self._delete_selection_if_any()
        pos = self.input_cursor_pos
        self.input_text = self.input_text[:pos] + text + self.input_text[pos:]
        self.input_cursor_pos = pos + len(text)

    def _move_cursor(self, new_pos: int, selecting: bool):
        new_pos = max(0, min(len(self.input_text), new_pos))
        if selecting:
            if self.input_selection_anchor is None:
                self.input_selection_anchor = self.input_cursor_pos
        else:
            self._clear_selection()
        self.input_cursor_pos = new_pos

    def _delete_prev_word(self):
        if self._delete_selection_if_any():
            return
        if self.input_cursor_pos <= 0:
            return
        i = self.input_cursor_pos
        while i > 0 and self.input_text[i - 1].isspace():
            i -= 1
        while i > 0 and not self.input_text[i - 1].isspace():
            i -= 1
        self.input_text = self.input_text[:i] + self.input_text[self.input_cursor_pos:]
        self.input_cursor_pos = i

    def _delete_next_word(self):
        if self._delete_selection_if_any():
            return
        i = self.input_cursor_pos
        n = len(self.input_text)
        while i < n and self.input_text[i].isspace():
            i += 1
        while i < n and not self.input_text[i].isspace():
            i += 1
        self.input_text = self.input_text[:self.input_cursor_pos] + self.input_text[i:]

    def _measure_text_width(self, text: str) -> int:
        return self.font.size(text)[0]

    def _compute_input_view_window(self, available_width: int) -> tuple[int, int]:
        text = self.input_text
        n = len(text)
        cursor = max(0, min(self.input_cursor_pos, n))
        if not text:
            return 0, 0

        start = cursor
        while start > 0 and self._measure_text_width(text[start - 1:cursor]) <= max(10, available_width // 2):
            start -= 1

        end = cursor
        while end < n and self._measure_text_width(text[start:end + 1]) <= available_width:
            end += 1

        while start > 0 and self._measure_text_width(text[start - 1:end]) <= available_width:
            start -= 1

        while end > start and self._measure_text_width(text[start:end]) > available_width:
            end -= 1

        if end <= start:
            end = min(n, start + 1)

        return start, end

    # ── highlighting ──────────────────────────────────────────────────────────

    def _build_highlights(self, text: str) -> dict:
        highlights = {}
        if self.player_name:
            for m in re.finditer(re.escape(self.player_name), text, re.IGNORECASE):
                for i in range(m.start(), m.end()):
                    highlights[i] = HIGHLIGHT_NAME
        for loc in self.known_locations:
            if len(loc) < 3:
                continue
            for m in re.finditer(re.escape(loc), text, re.IGNORECASE):
                for i in range(m.start(), m.end()):
                    if i not in highlights:
                        highlights[i] = HIGHLIGHT_LOCATION
        for item in self.known_items:
            if len(item) < 3:
                continue
            for m in re.finditer(re.escape(item), text, re.IGNORECASE):
                for i in range(m.start(), m.end()):
                    if i not in highlights:
                        highlights[i] = HIGHLIGHT_ITEM
        for descriptor in self.known_descriptors:
            for m in re.finditer(rf"\b{re.escape(descriptor)}\b", text, re.IGNORECASE):
                for i in range(m.start(), m.end()):
                    if i not in highlights:
                        highlights[i] = HIGHLIGHT_DESCRIPTOR
        for npc in self.known_npcs:
            if len(npc) < 3:
                continue
            for m in re.finditer(re.escape(npc), text, re.IGNORECASE):
                for i in range(m.start(), m.end()):
                    if i not in highlights:
                        highlights[i] = HIGHLIGHT_NPC
        keyword_groups = [
            (HIGHLIGHT_TIME, ["dawn", "morning", "midday", "afternoon", "evening", "night", "midnight"]),
            (HIGHLIGHT_DANGER, ["blood", "wound", "wounded", "danger", "threat", "ambush", "attack", "hostile", "deadly"]),
            (HIGHLIGHT_INTERACT, ["door", "gate", "lever", "switch", "altar", "statue", "chest", "bridge", "path"]),
        ]
        for color, words in keyword_groups:
            for keyword in words:
                for m in re.finditer(rf"\b{re.escape(keyword)}\b", text, re.IGNORECASE):
                    for i in range(m.start(), m.end()):
                        if i not in highlights:
                            highlights[i] = color
        return highlights

    # ── text layout ───────────────────────────────────────────────────────────

    def _wrap_text(self, text: str) -> list[tuple[str, bool, int]]:
        all_lines = []
        n = len(text)
        i = 0

        while i < n:
            while i < n and text[i].isspace():
                i += 1
            if i >= n:
                break

            paragraph_start = i
            sep = text.find("\n\n", i)
            paragraph_end = sep if sep != -1 else n

            paragraph_text = text[paragraph_start:paragraph_end].replace('\n', ' ')
            if paragraph_text.strip():
                words = paragraph_text.split(' ')
                current = ""
                current_start = -1
                paragraph_lines = []
                local_idx = 0

                for word in words:
                    while local_idx < len(paragraph_text) and paragraph_text[local_idx] == ' ':
                        local_idx += 1
                    if not word:
                        continue
                    word_start_local = local_idx
                    test = current + (" " if current else "") + word
                    w, _ = self.font.size(test)
                    if w > self.max_text_width and current:
                        paragraph_lines.append((current, current_start))
                        current = word
                        current_start = paragraph_start + word_start_local
                    else:
                        if not current:
                            current_start = paragraph_start + word_start_local
                        current = test
                    local_idx = word_start_local + len(word)

                if current:
                    paragraph_lines.append((current, current_start))

                for l_idx, (line, src_start) in enumerate(paragraph_lines):
                    is_last_line = (l_idx == len(paragraph_lines) - 1)
                    add_gap = is_last_line and sep != -1
                    all_lines.append((line, add_gap, src_start))

            if sep == -1:
                break
            i = sep + 2

        return all_lines if all_lines else [("", False, 0)]

    def _get_block_lines(self, block: TextBlock) -> list[tuple[str, bool, int]]:
        visible_text = block.text[:block.chars_shown]
        return self._wrap_text(visible_text)

    def _total_content_height(self) -> int:
        with self.lock:
            total = 0
            for block in self.blocks:
                text = block.text if block.fully_revealed else block.text[:block.chars_shown]
                lines = self._wrap_text(text)
                for _, has_gap, _ in lines:
                    total += self.line_height
                    if has_gap:
                        total += PARAGRAPH_GAP
                total += 12
            return total

    def _effective_visible_height(self) -> int:
        if self.combat_active:
            return max(100, self.height - self.margin_top - self.combat_panel_height - 14)
        return self.text_area_height

    def _scroll_to_bottom(self):
        with self.lock:
            content_h = self._total_content_height()
            visible_h = self._effective_visible_height()
            if content_h > visible_h:
                self.scroll_offset = content_h - visible_h

    def _is_at_bottom(self) -> bool:
        with self.lock:
            content_h = self._total_content_height()
            visible_h = self._effective_visible_height()
            max_scroll = max(0, content_h - visible_h)
            return self.scroll_offset >= max_scroll - self.line_height * 2

    def _skip_typewriter(self):
        with self.lock:
            for block in self.blocks:
                if not block.fully_revealed:
                    block.reveal_all()

    def _update_typewriter(self, dt: float):
        with self.lock:
            for block in self.blocks:
                if block.fully_revealed:
                    continue
                self.typewriter_timer += dt
                chars_to_add = int(self.typewriter_timer * self.typewriter_speed)
                if chars_to_add > 0:
                    block.chars_shown = min(len(block.text), block.chars_shown + chars_to_add)
                    self.typewriter_timer = 0
                    if block.chars_shown >= len(block.text):
                        block.fully_revealed = True
                    self._scroll_to_bottom()
                break

    # ── rendering ─────────────────────────────────────────────────────────────

    def _render_text_area(self):
        effective_height = self._effective_visible_height()
        clip_rect = pygame.Rect(0, self.margin_top, self.width, effective_height)
        self.screen.set_clip(clip_rect)

        y = self.margin_top - self.scroll_offset

        with self.lock:
            for block in self.blocks:
                lines = self._get_block_lines(block)
                for line_text, has_gap, char_offset in lines:
                    if y + self.line_height < self.margin_top:
                        y += self.line_height
                        if has_gap:
                            y += PARAGRAPH_GAP
                        continue
                    if y > self.margin_top + effective_height:
                        break

                    if block.is_player or not block.highlights:
                        surf = self.font.render(line_text, True, block.color)
                        self.screen.blit(surf, (self.margin_left, y))
                    else:
                        self._blit_highlighted_line(line_text, char_offset, block, y)

                    y += self.line_height
                    if has_gap:
                        y += PARAGRAPH_GAP

                y += 12

        # scrollbar
        self.screen.set_clip(None)
        content_h = self._total_content_height()
        if content_h > effective_height:
            track_x = self.width - 8
            track_y = self.margin_top
            track_h = effective_height

            thumb_ratio = effective_height / content_h
            thumb_h = max(20, int(track_h * thumb_ratio))

            max_scroll = content_h - effective_height
            scroll_ratio = (self.scroll_offset / max_scroll) if max_scroll > 0 else 0
            thumb_y = track_y + int((track_h - thumb_h) * scroll_ratio)

            pygame.draw.rect(self.screen, (45, 47, 52),
                             pygame.Rect(track_x, track_y, 6, track_h), border_radius=3)
            pygame.draw.rect(self.screen, (80, 82, 88),
                             pygame.Rect(track_x, thumb_y, 6, thumb_h), border_radius=3)

        self.screen.set_clip(None)

    def _blit_highlighted_line(self, line_text: str, char_offset: int, block: TextBlock, y: int):
        x = self.margin_left
        if not line_text:
            return

        run_chars = []
        run_color = None
        for i, ch in enumerate(line_text):
            global_idx = char_offset + i
            color = block.highlights.get(global_idx, block.color)
            if run_color is None:
                run_color = color
                run_chars.append(ch)
                continue
            if color != run_color:
                run_surf = self.font.render("".join(run_chars), True, run_color)
                self.screen.blit(run_surf, (x, y))
                x += run_surf.get_width()
                run_chars = [ch]
                run_color = color
            else:
                run_chars.append(ch)

        if run_chars:
            run_surf = self.font.render("".join(run_chars), True, run_color)
            self.screen.blit(run_surf, (x, y))

    def _render_input_bar(self):
        bar_y = self.height - self.input_height - 5
        bar_rect = pygame.Rect(
            self.margin_left - 5, bar_y,
            self.width - self.margin_left * 2 + 10, self.input_height
        )
        pygame.draw.rect(self.screen, INPUT_BG, bar_rect, border_radius=4)
        pygame.draw.rect(self.screen, INPUT_BORDER, bar_rect, 1, border_radius=4)

        prompt = ">> "
        prompt_surf = self.font.render(prompt, True, PROMPT_COLOR)
        text_y = bar_y + (self.input_height - prompt_surf.get_height()) // 2
        self.screen.blit(prompt_surf, (self.margin_left, text_y))

        input_x = self.margin_left + prompt_surf.get_width()
        available_width = max(24, bar_rect.right - 10 - input_x)

        view_start, view_end = self._compute_input_view_window(available_width)
        render_text = self.input_text[view_start:view_end]
        self.input_view_start = view_start
        self.input_view_end = view_end

        if self.awaiting_input and not self.input_text:
            hint_render = "What do you do?"
            while hint_render and self._measure_text_width(hint_render) > available_width:
                hint_render = hint_render[1:]
            hint_surf = self.font.render(hint_render, True, SYSTEM_COLOR)
            self.screen.blit(hint_surf, (input_x, text_y))

        bounds = self._selection_bounds()
        if bounds and render_text:
            sel_start, sel_end = bounds
            vis_sel_start = max(sel_start, view_start)
            vis_sel_end = min(sel_end, view_end)
            if vis_sel_end > vis_sel_start:
                before = self.input_text[view_start:vis_sel_start]
                selected = self.input_text[vis_sel_start:vis_sel_end]
                sel_x = input_x + self._measure_text_width(before)
                sel_w = self._measure_text_width(selected)
                sel_h = self.font.get_height()
                sel_rect = pygame.Rect(sel_x - 1, text_y + 1, sel_w + 2, max(1, sel_h - 2))
                pygame.draw.rect(self.screen, INPUT_SELECTION_BG, sel_rect, border_radius=2)

        self.screen.blit(self.font.render(render_text, True, INPUT_TEXT), (input_x, text_y))

        self.input_bar_rect = bar_rect
        self.input_text_x = input_x
        self.input_text_y = text_y

        if self.cursor_visible:
            cursor_slice = self.input_text[view_start:self.input_cursor_pos]
            cursor_x = input_x + self._measure_text_width(cursor_slice) + 1
            pygame.draw.line(self.screen, CURSOR_COLOR,
                             (cursor_x, text_y + 2),
                             (cursor_x, text_y + prompt_surf.get_height() - 2), 1)

    def _render_menu_overlay(self):
        overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        overlay.fill(MENU_OVERLAY)
        self.screen.blit(overlay, (0, 0))

        panel_w = min(520, self.width - 40)
        panel_h = min(360, self.height - 60)
        panel_x = (self.width - panel_w) // 2
        panel_y = (self.height - panel_h) // 2
        panel_rect = pygame.Rect(panel_x, panel_y, panel_w, panel_h)

        pygame.draw.rect(self.screen, MENU_PANEL_BG, panel_rect, border_radius=8)
        pygame.draw.rect(self.screen, MENU_PANEL_BORDER, panel_rect, 1, border_radius=8)

        self.screen.blit(self.font.render(self.menu_title, True, INPUT_TEXT),
                         (panel_x + 22, panel_y + 20))

        y = panel_y + 54
        if self.menu_subtitle:
            for line in self._wrap_ui_text(self.menu_subtitle, panel_w - 44):
                self.screen.blit(self.font.render(line, True, SYSTEM_COLOR), (panel_x + 22, y))
                y += self.line_height
            y += 8

        self.menu_button_rects = []
        button_h = 44
        button_gap = 10

        if self.menu_layout == "horizontal" and self.menu_options:
            available_w = panel_w - 44
            count = len(self.menu_options)
            button_w = max(90, (available_w - button_gap * (count - 1)) // count)
            total_w = button_w * count + button_gap * (count - 1)
            start_x = panel_x + 22 + max(0, (available_w - total_w) // 2)

            for idx, (label, choice) in enumerate(self.menu_options):
                button_rect = pygame.Rect(start_x + idx * (button_w + button_gap), y, button_w, button_h)
                hovered = self.menu_hover_choice == choice
                pygame.draw.rect(self.screen, MENU_BUTTON_HOVER if hovered else MENU_BUTTON_BG, button_rect, border_radius=6)
                pygame.draw.rect(self.screen, MENU_PANEL_BORDER, button_rect, 1, border_radius=6)
                label_surf = self.font.render(f"{idx + 1}) {label}", True, MENU_BUTTON_TEXT)
                lx = button_rect.x + max(8, (button_rect.width - label_surf.get_width()) // 2)
                ly = button_rect.y + (button_h - label_surf.get_height()) // 2
                self.screen.blit(label_surf, (lx, ly))
                self.menu_button_rects.append((button_rect, choice))
        else:
            max_bottom = panel_y + panel_h - 20
            available_h = max(44, max_bottom - y)
            visible_count = max(1, (available_h + button_gap) // (button_h + button_gap))
            max_scroll = max(0, len(self.menu_options) - visible_count)
            self.menu_scroll = max(0, min(self.menu_scroll, max_scroll))

            for local_idx, (label, choice) in enumerate(self.menu_options[self.menu_scroll:self.menu_scroll + visible_count]):
                idx = self.menu_scroll + local_idx
                button_rect = pygame.Rect(panel_x + 22, y, panel_w - 44, button_h)
                hovered = self.menu_hover_choice == choice
                pygame.draw.rect(self.screen, MENU_BUTTON_HOVER if hovered else MENU_BUTTON_BG, button_rect, border_radius=6)
                pygame.draw.rect(self.screen, MENU_PANEL_BORDER, button_rect, 1, border_radius=6)
                label_surf = self.font.render(f"{idx + 1}) {label}", True, MENU_BUTTON_TEXT)
                self.screen.blit(label_surf, (button_rect.x + 14, button_rect.y + (button_h - label_surf.get_height()) // 2))
                self.menu_button_rects.append((button_rect, choice))
                y += button_h + button_gap

            if max_scroll > 0:
                hint = f"Scroll {self.menu_scroll + 1}-{min(len(self.menu_options), self.menu_scroll + visible_count)} of {len(self.menu_options)}"
                hint_surf = self.font.render(hint, True, SYSTEM_COLOR)
                self.screen.blit(hint_surf, (panel_x + panel_w - 22 - hint_surf.get_width(),
                                             panel_y + panel_h - 16 - hint_surf.get_height()))

    def _wrap_ui_text(self, text: str, max_width: int) -> list[str]:
        words = text.split()
        if not words:
            return [""]
        lines = []
        current = ""
        for word in words:
            test = current + (" " if current else "") + word
            w, _ = self.font.size(test)
            if w > max_width and current:
                lines.append(current)
                current = word
            else:
                current = test
        if current:
            lines.append(current)
        return lines

    def _render_combat_intro(self):
        if not self.combat_intro_active:
            return
        overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 0))
        self.screen.blit(overlay, (0, 0))
        if self.combat_intro_visible:
            title_surf = self.font.render(self.combat_intro_title, True, (245, 220, 220))
            self.screen.blit(title_surf, (
                (self.width - title_surf.get_width()) // 2,
                (self.height - title_surf.get_height()) // 2
            ))

    def _render_combat_hud(self):
        if not self.combat_active:
            return

        panel_h = self.combat_panel_height
        panel_y = self.height - panel_h - 5
        panel_rect = pygame.Rect(self.margin_left - 5, panel_y,
                                 self.width - self.margin_left * 2 + 10, panel_h)
        pygame.draw.rect(self.screen, (24, 26, 30), panel_rect, border_radius=6)
        pygame.draw.rect(self.screen, INPUT_BORDER, panel_rect, 1, border_radius=6)

        y = panel_y + 10
        self.screen.blit(self.font.render(self.combat_title, True, HIGHLIGHT_COMBAT),
                         (self.margin_left + 8, y))
        y += self.line_height

        button_strip_h = 62 if self.combat_layout == "horizontal" else 54
        status_bottom = panel_rect.bottom - button_strip_h - 14

        for line, color in self.combat_status_lines:
            if y > status_bottom:
                break
            surf = self.font.render(line, True, color if color is not None else INPUT_TEXT)
            self.screen.blit(surf, (self.margin_left + 8, y))
            y += self.line_height

        if y <= status_bottom - self.line_height:
            divider_y = y + 2
            pygame.draw.line(self.screen, INPUT_BORDER,
                             (panel_rect.x + 10, divider_y), (panel_rect.right - 10, divider_y), 1)
            y = divider_y + 8

        self.combat_button_rects = []
        if self.combat_layout == "horizontal":
            button_h = 40
            button_gap = 10
            available_w = panel_rect.width - 40
            count = max(1, len(self.combat_options))
            button_w = max(100, (available_w - button_gap * (count - 1)) // count)
            total_w = button_w * count + button_gap * (count - 1)
            start_x = panel_rect.x + 20 + max(0, (available_w - total_w) // 2)
            button_y = panel_rect.bottom - button_h - 10

            for idx, (label, choice) in enumerate(self.combat_options):
                rect = pygame.Rect(start_x + idx * (button_w + button_gap), button_y, button_w, button_h)
                hovered = self.combat_hover_choice == choice
                pygame.draw.rect(self.screen, MENU_BUTTON_HOVER if hovered else MENU_BUTTON_BG, rect, border_radius=6)
                pygame.draw.rect(self.screen, MENU_PANEL_BORDER, rect, 1, border_radius=6)
                label_surf = self.font.render(f"{idx + 1}) {label}", True, MENU_BUTTON_TEXT)
                self.screen.blit(label_surf, (
                    rect.x + max(8, (rect.width - label_surf.get_width()) // 2),
                    rect.y + (button_h - label_surf.get_height()) // 2
                ))
                self.combat_button_rects.append((rect, choice))
        else:
            button_h = 34
            button_gap = 8
            max_bottom = panel_rect.bottom - 12
            available_h = max(44, max_bottom - y)
            visible_count = max(1, (available_h + button_gap) // (button_h + button_gap))
            max_scroll = max(0, len(self.combat_options) - visible_count)
            self.combat_scroll = max(0, min(self.combat_scroll, max_scroll))

            for local_idx, (label, choice) in enumerate(self.combat_options[self.combat_scroll:self.combat_scroll + visible_count]):
                idx = self.combat_scroll + local_idx
                rect = pygame.Rect(panel_rect.x + 20, y, panel_rect.width - 40, button_h)
                hovered = self.combat_hover_choice == choice
                pygame.draw.rect(self.screen, MENU_BUTTON_HOVER if hovered else MENU_BUTTON_BG, rect, border_radius=6)
                pygame.draw.rect(self.screen, MENU_PANEL_BORDER, rect, 1, border_radius=6)
                label_surf = self.font.render(f"{idx + 1}) {label}", True, MENU_BUTTON_TEXT)
                self.screen.blit(label_surf, (rect.x + 14, rect.y + (button_h - label_surf.get_height()) // 2))
                self.combat_button_rects.append((rect, choice))
                y += button_h + button_gap

            if max_scroll > 0:
                hint = f"Scroll {self.combat_scroll + 1}-{min(len(self.combat_options), self.combat_scroll + visible_count)} of {len(self.combat_options)}"
                hint_surf = self.font.render(hint, True, SYSTEM_COLOR)
                self.screen.blit(hint_surf, (
                    panel_rect.right - 20 - hint_surf.get_width(),
                    panel_rect.bottom - 14 - hint_surf.get_height()
                ))

    # ── event handling ────────────────────────────────────────────────────────

    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
                self.input_ready.set()
                self.menu_ready.set()
                return

            if event.type == pygame.VIDEORESIZE:
                self.width = max(320, event.w)
                self.height = max(240, event.h)
                self.screen = pygame.display.set_mode((self.width, self.height), pygame.RESIZABLE)
                self.text_area_height = self.height - self.input_height - self.margin_top - 14
                self.max_text_width = self.width - self.margin_left - self.margin_right

            if event.type == pygame.WINDOWFOCUSLOST:
                self.window_focused = False

            if event.type == pygame.WINDOWFOCUSGAINED:
                self.window_focused = True

            if event.type == pygame.KEYDOWN:
                if self.combat_active:
                    if event.key in (pygame.K_1, pygame.K_KP1, pygame.K_a):
                        if self.combat_options:
                            self.combat_choice = self.combat_options[0][1]
                            self.combat_ready.set()
                        continue
                    if event.key in (pygame.K_2, pygame.K_KP2, pygame.K_i):
                        if len(self.combat_options) > 1:
                            self.combat_choice = self.combat_options[1][1]
                            self.combat_ready.set()
                        continue
                    if event.key in (pygame.K_3, pygame.K_KP3, pygame.K_f):
                        if len(self.combat_options) > 2:
                            self.combat_choice = self.combat_options[2][1]
                            self.combat_ready.set()
                        continue
                    if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and self.combat_options:
                        self.combat_choice = self.combat_options[0][1]
                        self.combat_ready.set()
                        continue
                    if event.key == pygame.K_ESCAPE:
                        self.combat_choice = "flee"
                        self.combat_ready.set()
                        continue

                if self.menu_active:
                    if event.key == pygame.K_ESCAPE:
                        self.menu_choice = "quit"
                        self.menu_ready.set()
                        continue
                    if self.menu_layout == "vertical":
                        if event.key == pygame.K_UP:
                            self.menu_scroll = max(0, self.menu_scroll - 1)
                            continue
                        if event.key == pygame.K_DOWN:
                            self.menu_scroll += 1
                            continue
                    if pygame.K_1 <= event.key <= pygame.K_9:
                        idx = event.key - pygame.K_1
                        if self.menu_layout == "vertical":
                            idx += self.menu_scroll
                        if 0 <= idx < len(self.menu_options):
                            self.menu_choice = self.menu_options[idx][1]
                            self.menu_ready.set()
                            continue
                    if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and self.menu_options:
                        pick_idx = self.menu_scroll if self.menu_layout == "vertical" else 0
                        self.menu_choice = self.menu_options[pick_idx][1]
                        self.menu_ready.set()
                        continue
                    continue

                with self.lock:
                    any_animating = any(not b.fully_revealed for b in self.blocks)
                typed_cmd = self.input_text.strip().lower()

                if event.key == pygame.K_RETURN and typed_cmd in ("quit", "exit"):
                    self.pending_input = "quit"
                    self.input_text = ""
                    self.input_cursor_pos = 0
                    self._clear_selection()
                    self.input_ready.set()
                    continue

                if any_animating and event.key in (pygame.K_SPACE, pygame.K_RETURN):
                    self._skip_typewriter()
                    continue

                submitted = self.input_text.strip()
                if event.key == pygame.K_RETURN and (submitted or self.allow_empty_submit):
                    self.pending_input = submitted
                    self.input_text = ""
                    self.input_cursor_pos = 0
                    self._clear_selection()
                    self.input_ready.set()
                elif event.key == pygame.K_ESCAPE:
                    self.running = False
                    self.input_ready.set()
                else:
                    mods = pygame.key.get_mods()
                    shortcut_mod = bool(mods & (pygame.KMOD_CTRL | pygame.KMOD_META))
                    alt_mod = bool(mods & pygame.KMOD_ALT)
                    shift_mod = bool(mods & pygame.KMOD_SHIFT)

                    if shortcut_mod and event.key == pygame.K_a:
                        self.input_selection_anchor = 0
                        self.input_cursor_pos = len(self.input_text)
                    elif shortcut_mod and event.key == pygame.K_c:
                        bounds = self._selection_bounds()
                        if bounds:
                            self._set_clipboard_text(self.input_text[bounds[0]:bounds[1]])
                    elif shortcut_mod and event.key == pygame.K_x:
                        bounds = self._selection_bounds()
                        if bounds:
                            self._set_clipboard_text(self.input_text[bounds[0]:bounds[1]])
                            self._delete_selection_if_any()
                    elif shortcut_mod and event.key == pygame.K_v:
                        pasted = self._get_clipboard_text().replace("\r", "").replace("\n", " ")
                        if pasted:
                            self._insert_text_at_cursor(pasted)
                    elif event.key == pygame.K_LEFT:
                        self._move_cursor(self.input_cursor_pos - 1, selecting=shift_mod)
                    elif event.key == pygame.K_RIGHT:
                        self._move_cursor(self.input_cursor_pos + 1, selecting=shift_mod)
                    elif event.key == pygame.K_HOME:
                        self._move_cursor(0, selecting=shift_mod)
                    elif event.key == pygame.K_END:
                        self._move_cursor(len(self.input_text), selecting=shift_mod)
                    elif event.key == pygame.K_BACKSPACE:
                        if shortcut_mod or alt_mod:
                            self._delete_prev_word()
                        elif not self._delete_selection_if_any() and self.input_cursor_pos > 0:
                            pos = self.input_cursor_pos
                            self.input_text = self.input_text[:pos - 1] + self.input_text[pos:]
                            self.input_cursor_pos -= 1
                    elif event.key == pygame.K_DELETE:
                        if shortcut_mod or alt_mod:
                            self._delete_next_word()
                        elif not self._delete_selection_if_any() and self.input_cursor_pos < len(self.input_text):
                            pos = self.input_cursor_pos
                            self.input_text = self.input_text[:pos] + self.input_text[pos + 1:]
                    elif event.key == pygame.K_TAB:
                        continue
                    elif event.unicode and event.unicode.isprintable():
                        self._insert_text_at_cursor(event.unicode)
                    else:
                        if not shift_mod:
                            self._clear_selection()

                    if not shift_mod and event.key not in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_HOME, pygame.K_END):
                        if self.input_selection_anchor == self.input_cursor_pos:
                            self._clear_selection()

            if event.type == pygame.MOUSEMOTION and self.menu_active:
                self.menu_hover_choice = ""
                for rect, choice in self.menu_button_rects:
                    if rect.collidepoint(event.pos):
                        self.menu_hover_choice = choice
                        break

            if event.type == pygame.MOUSEBUTTONDOWN and self.menu_active and event.button == 1:
                for rect, choice in self.menu_button_rects:
                    if rect.collidepoint(event.pos):
                        self.menu_choice = choice
                        self.menu_ready.set()
                        break

            if event.type == pygame.MOUSEMOTION and self.combat_active:
                self.combat_hover_choice = ""
                for rect, choice in self.combat_button_rects:
                    if rect.collidepoint(event.pos):
                        self.combat_hover_choice = choice
                        break

            if event.type == pygame.MOUSEBUTTONDOWN and self.combat_active and event.button == 1:
                for rect, choice in self.combat_button_rects:
                    if rect.collidepoint(event.pos):
                        self.combat_choice = choice
                        self.combat_ready.set()
                        break

            if event.type == pygame.MOUSEBUTTONDOWN and not self.menu_active and event.button == 1:
                if self.input_bar_rect.collidepoint(event.pos):
                    prev_cursor = self.input_cursor_pos
                    click_x = max(0, event.pos[0] - self.input_text_x)
                    idx = self.input_view_start
                    while idx <= self.input_view_end:
                        if self._measure_text_width(self.input_text[self.input_view_start:idx]) >= click_x:
                            break
                        idx += 1
                    self.input_cursor_pos = max(self.input_view_start, min(idx, len(self.input_text)))
                    mods = pygame.key.get_mods()
                    if not (mods & pygame.KMOD_SHIFT):
                        self._clear_selection()
                    elif self.input_selection_anchor is None:
                        self.input_selection_anchor = prev_cursor

            if event.type == pygame.MOUSEWHEEL:
                if self.menu_active:
                    if self.menu_layout == "vertical":
                        self.menu_scroll = max(0, self.menu_scroll - event.y)
                    continue
                self.scroll_offset = max(0, self.scroll_offset - event.y * self.line_height * 3)
                content_h = self._total_content_height()
                visible_h = self._effective_visible_height()
                max_scroll = max(0, content_h - visible_h)
                self.scroll_offset = min(self.scroll_offset, max_scroll)

    # ── main loop hooks ───────────────────────────────────────────────────────

    def render(self):
        if not self.window_focused:
            return
        self.screen.fill(BG_COLOR)
        self._render_text_area()
        if self.combat_active:
            self._render_combat_hud()
        elif not self.menu_active:
            self._render_input_bar()
        else:
            self._render_menu_overlay()
        self._render_combat_intro()
        pygame.display.flip()

    def tick(self, dt: float):
        if not self.window_focused:
            return
        if self.combat_intro_active:
            self.combat_intro_timer += dt
            if self.combat_intro_timer >= self.combat_intro_interval:
                self.combat_intro_timer = 0.0
                self.combat_intro_visible = not self.combat_intro_visible
                self.combat_intro_flips_left -= 1
                if self.combat_intro_flips_left <= 0:
                    self.combat_intro_active = False
                    self.combat_intro_ready.set()
        self.cursor_timer += dt
        if self.cursor_timer >= 0.5:
            self.cursor_visible = not self.cursor_visible
            self.cursor_timer = 0
        self._update_typewriter(dt)