import sys, csv, random, os, json, subprocess, tempfile, threading, datetime
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog, QSpinBox, QDoubleSpinBox,
    QComboBox, QFrame, QSlider, QCheckBox, QMessageBox, QScrollArea,
    QGroupBox, QGridLayout, QDialog, QTableWidget, QTableWidgetItem,
    QHeaderView, QColorDialog, QAbstractItemView, QSizePolicy, QShortcut,
    QTabWidget, QLineEdit
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont, QColor, QPalette, QKeySequence

# ── Silbentrennung ─────────────────────────────────────────────────────────
VOWELS        = "aeiouäöüAEIOUÄÖÜ"
DIPHTHONGS    = {"ai", "au", "ei", "eu", "ie", "äu", "oi"}
DIGRAPHS_NEXT = ["sch", "ch", "ph", "th", "qu", "ck", "tz"]
SPLIT_PAIRS   = ["ng", "nk"]

def split_syllables(word: str) -> list:
    if not word:
        return []
    if len(word) <= 2:
        return [word]
    wl = word.lower()
    masked = ""
    i = 0
    while i < len(wl):
        if wl[i] == 'q' and i + 1 < len(wl) and wl[i+1] == 'u':
            masked += 'q_'
            i += 2
        else:
            masked += wl[i]
            i += 1
    vowel_pos = [i for i, c in enumerate(masked) if c in VOWELS]
    if len(vowel_pos) <= 1:
        return [word]
    cuts = []
    for idx in range(len(vowel_pos) - 1):
        v1, v2 = vowel_pos[idx], vowel_pos[idx + 1]
        between = masked[v1 + 1:v2]
        if not between:
            if masked[v1:v2 + 1] not in DIPHTHONGS:
                cuts.append(v2)
            continue
        if len(between) == 1:
            cuts.append(v1 + 1)
        else:
            cut_pos = v2 - 1
            found = False
            for sp in SPLIT_PAIRS:
                pos = between.find(sp)
                if pos != -1:
                    cut_pos = v1 + 1 + pos + 1
                    found = True
                    break
            if not found:
                for dg in DIGRAPHS_NEXT:
                    dg_len = len(dg)
                    if masked[v2 - dg_len:v2] == dg:
                        cut_pos = v2 - dg_len
                        break
            if v1 < cut_pos < v2:
                cuts.append(cut_pos)
    result, prev = [], 0
    for c in sorted(set(cuts)):
        if c > prev:
            result.append(word[prev:c])
            prev = c
    result.append(word[prev:])
    return [s for s in result if s]

# ── Farben, Emojis, Hintergründe ────────────────────────────────────────────
SYLLABLE_COLORS = [
    "#2563EB", "#DC2626", "#16A34A", "#9333EA", "#D97706", "#0891B2"
]
DANCE_EMOJIS = ["🕺", "💃", "🎵", "🎶", "⭐", "🌟", "🎉", "🥳"]
BG_PRESETS = {
    "Weiß":          "#FFFFFF",
    "Hellgelb":      "#FFFDE7",
    "Hellblau":      "#E3F2FD",
    "Hellgrün":      "#E8F5E9",
    "Hellrosa":      "#FCE4EC",
    "Dunkelblau":    "#1a1a2e",
}

# ── Dia-Generierung ─────────────────────────────────────────────────────────
def build_slides(words: list, sentences: list,
                 words_per_round: int, sents_per_round: int = 2,
                 total_slides: int = 21) -> list:
    slides = []
    w_pool = words[:]
    s_pool = sentences[:]
    random.shuffle(w_pool)
    random.shuffle(s_pool)
    w_idx = 0
    s_idx = 0
    count = 0
    while count < total_slides:
        for _ in range(words_per_round):
            if count >= total_slides:
                break
            if w_pool:
                if w_idx >= len(w_pool):
                    w_idx = 0
                    random.shuffle(w_pool)
                slides.append({"type": "word", "content": w_pool[w_idx]})
                w_idx += 1
            count += 1
        if count >= total_slides:
            break
        for _ in range(sents_per_round):
            if count >= total_slides:
                break
            if s_pool:
                if s_idx >= len(s_pool):
                    s_idx = 0
                    random.shuffle(s_pool)
                slides.append({"type": "sentence", "content": s_pool[s_idx]})
                s_idx += 1
            count += 1
        if count >= total_slides:
            break
        slides.append({"type": "dance"})
        count += 1
    return slides[:total_slides]

# ── Blitzlesen-Diashow (SlideWindow) ────────────────────────────────────────
class SlideWindow(QWidget):
    closed = pyqtSignal()
    def __init__(self, slides, settings):
        super().__init__()
        self.slides   = slides
        self.settings = settings
        self.index    = 0
        self.timer    = QTimer()
        self.timer.timeout.connect(self.next_slide)
        self.setWindowTitle("Blitzlesen – Diashow")
        self.setWindowFlags(Qt.Window)
        self.showFullScreen()
        self._build_ui()
        self._show_slide()
        QShortcut(QKeySequence(Qt.Key_Space),  self).activated.connect(self.next_slide)
        QShortcut(QKeySequence(Qt.Key_Left),   self).activated.connect(self.prev_slide)
        QShortcut(QKeySequence(Qt.Key_Right),  self).activated.connect(self.next_slide)
        QShortcut(QKeySequence(Qt.Key_Escape), self).activated.connect(self.close)
        if settings["auto"]:
            self.timer.start(int(settings["tempo"] * 1000))
    def _build_ui(self):
        self.setStyleSheet(f"background-color: {self.settings['bg']};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        top.setContentsMargins(20, 10, 20, 0)
        self.progress_label = QLabel()
        self.progress_label.setFont(QFont("Segoe UI", 12))
        self.progress_label.setStyleSheet("color: #999;")
        top.addWidget(self.progress_label)
        top.addStretch()
        hint = QLabel("← → Pfeil  |  Leertaste  |  ESC = Beenden")
        hint.setFont(QFont("Segoe UI", 10))
        hint.setStyleSheet("color: #bbb;")
        top.addWidget(hint)
        layout.addLayout(top)
        self.content_label = QLabel()
        self.content_label.setAlignment(Qt.AlignCenter)
        self.content_label.setWordWrap(True)
        layout.addWidget(self.content_label, stretch=1)
        nav = QHBoxLayout()
        nav.setContentsMargins(40, 0, 40, 20)
        btn_prev = QPushButton("◀  Zurück")
        btn_prev.setFont(QFont("Segoe UI", 12))
        btn_prev.setFixedHeight(40)
        btn_prev.setStyleSheet("QPushButton { background:#00000022; color:#555; border:1px solid #ccc; border-radius:8px; padding:0 20px; } QPushButton:hover { background:#00000044; }")
        btn_prev.clicked.connect(self.prev_slide)
        btn_next = QPushButton("Weiter  ▶")
        btn_next.setFont(QFont("Segoe UI", 12))
        btn_next.setFixedHeight(40)
        btn_next.setStyleSheet("QPushButton { background:#00000022; color:#555; border:1px solid #ccc; border-radius:8px; padding:0 20px; } QPushButton:hover { background:#00000044; }")
        btn_next.clicked.connect(self.next_slide)
        btn_stop = QPushButton("✕  Beenden")
        btn_stop.setFont(QFont("Segoe UI", 12))
        btn_stop.setFixedHeight(40)
        btn_stop.setStyleSheet("QPushButton { background:#ff444422; color:#c00; border:1px solid #faa; border-radius:8px; padding:0 20px; } QPushButton:hover { background:#ff444444; }")
        btn_stop.clicked.connect(self.close)
        nav.addWidget(btn_prev)
        nav.addStretch()
        nav.addWidget(btn_stop)
        nav.addStretch()
        nav.addWidget(btn_next)
        layout.addLayout(nav)
    def _syllable_html(self, text: str, font_size: int) -> str:
        colors = self.settings.get("colors", SYLLABLE_COLORS)
        overrides = self.settings.get("overrides", {})
        words = text.split()
        parts = []
        for word in words:
            if text in overrides:
                all_syls = []
                for chunk in overrides[text].split():
                    all_syls.extend(chunk.split("-"))
                word_html = ""
                for i, syl in enumerate(all_syls):
                    color = colors[i % len(colors)]
                    word_html += f'<span style="color:{color};">{syl}</span>'
                return f'<p style="font-size:{font_size}px; font-family:Georgia,serif; font-weight:bold; line-height:1.4; text-align:center;">{word_html}</p>'
            syllables = split_syllables(word)
            word_html = ""
            for i, syl in enumerate(syllables):
                color = colors[i % len(colors)]
                word_html += f'<span style="color:{color};">{syl}</span>'
            parts.append(word_html)
        return f'<p style="font-size:{font_size}px; font-family:Georgia,serif; font-weight:bold; line-height:1.4; text-align:center;">{"&nbsp;&nbsp;".join(parts)}</p>'
    def _show_slide(self):
        if self.index >= len(self.slides):
            self._show_end()
            return
        slide = self.slides[self.index]
        self.progress_label.setText(f"Dia {self.index + 1} / {len(self.slides)}")
        fs = self.settings["font_size"]
        bg = self.settings["bg"]
        self.setStyleSheet(f"background-color: {bg};")
        if slide["type"] == "dance":
            emojis = " ".join(random.choices(DANCE_EMOJIS, k=5))
            html = f'<p style="font-size:{fs + 30}px; text-align:center;">{emojis}</p><p style="font-size:{fs + 10}px; font-family:Georgia,serif; font-weight:bold; color:#E91E63; text-align:center;">Jetzt tanzen! 🎉</p><p style="font-size:{fs - 5}px; font-family:Georgia,serif; color:#888; text-align:center;">Beweg dich zur Musik!</p>'
            self.setStyleSheet("background-color: #FFF9C4;")
            self.content_label.setText("")
            self.content_label.setTextFormat(Qt.RichText)
            self.content_label.setText(html)
        elif slide["type"] in ("word", "sentence"):
            html = self._syllable_html(slide["content"], fs)
            self.content_label.setTextFormat(Qt.RichText)
            self.content_label.setText(html)
    def _show_end(self):
        self.timer.stop()
        self.setStyleSheet("background-color: #E8F5E9;")
        self.content_label.setTextFormat(Qt.RichText)
        self.content_label.setText(f'<p style="font-size:80px; text-align:center;">🎊</p><p style="font-size:48px; font-family:Georgia,serif; font-weight:bold; color:#2E7D32; text-align:center;">Super gemacht!</p><p style="font-size:24px; font-family:Georgia,serif; color:#888; text-align:center;">Das Blitzlesen ist vorbei.</p>')
        self.progress_label.setText(f"Fertig! {len(self.slides)} Dias")
    def next_slide(self):
        if self.index < len(self.slides):
            self.index += 1
            self._show_slide()
        if self.settings["auto"]:
            self.timer.start(int(self.settings["tempo"] * 1000))
    def prev_slide(self):
        if self.index > 0:
            self.index -= 1
            self._show_slide()
        if self.settings["auto"]:
            self.timer.start(int(self.settings["tempo"] * 1000))
    def closeEvent(self, event):
        self.timer.stop()
        self.closed.emit()
        super().closeEvent(event)

# ── Mathe-Diashow und Sound-Helfer ──────────────────────────────────────────
def _play_sound(kind: str):
    def _do():
        try:
            import winsound
            if kind == "question":
                winsound.Beep(880, 80)
            elif kind == "answer":
                winsound.Beep(660, 120)
            elif kind == "applause":
                for f in [523, 659, 784, 1047]:
                    winsound.Beep(f, 80)
            elif kind == "finish":
                for f in [523, 659, 784, 1047, 1319]:
                    winsound.Beep(f, 100)
        except Exception:
            pass
    threading.Thread(target=_do, daemon=True).start()

class MathSlideWindow(QMainWindow):
    closed = pyqtSignal()
    APPLAUSE_EVERY = 5

    def __init__(self, tasks: list, settings: dict):
        super().__init__()
        self.tasks    = tasks
        self.settings = settings
        self.index    = 0
        self.phase    = "question"
        self.results  = []
        self.timer    = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._timer_tick)
        self.countdown_timer = QTimer(self)
        self.countdown_timer.setInterval(50)
        self.countdown_timer.timeout.connect(self._countdown_tick)
        self._countdown_end_ms = 0
        self.setWindowTitle("Mathe-Blitz")
        self.showFullScreen()
        self._build_ui()
        self._show_slide()
        QShortcut(QKeySequence(Qt.Key_Escape), self).activated.connect(self.close)
        QShortcut(QKeySequence(Qt.Key_Right),  self).activated.connect(self._advance)
        QShortcut(QKeySequence(Qt.Key_Space),  self).activated.connect(self._advance)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        top = QWidget()
        top.setFixedHeight(48)
        top_lay = QHBoxLayout(top)
        top_lay.setContentsMargins(20, 0, 20, 0)
        self.lbl_counter = QLabel("1 / 20")
        self.lbl_counter.setFont(QFont("Segoe UI", 10))
        self.lbl_counter.setStyleSheet("color:#aaa;")
        top_lay.addWidget(self.lbl_counter)
        top_lay.addStretch()
        self.lbl_phase = QLabel("Aufgabe")
        self.lbl_phase.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.lbl_phase.setStyleSheet("color:white; background:#6A1B9A; border-radius:10px; padding:2px 12px;")
        top_lay.addWidget(self.lbl_phase)
        top_lay.addStretch()
        btn_stop = QPushButton("✕  Beenden")
        btn_stop.setFont(QFont("Segoe UI", 9))
        btn_stop.setStyleSheet("QPushButton{border:1px solid #fca5a5;color:#c00;border-radius:6px;padding:3px 12px;} QPushButton:hover{background:#FEF2F2;}")
        btn_stop.clicked.connect(self.close)
        top_lay.addWidget(btn_stop)
        lay.addWidget(top)
        bar_bg = QFrame()
        bar_bg.setFixedHeight(8)
        bar_bg.setStyleSheet("background:#e0e0e0;")
        bar_inner = QHBoxLayout(bar_bg)
        bar_inner.setContentsMargins(0, 0, 0, 0)
        bar_inner.setSpacing(0)
        self.progress_bar = QFrame(bar_bg)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setStyleSheet("background:#6A1B9A; border-radius:0px;")
        self.progress_bar.setFixedWidth(0)
        lay.addWidget(bar_bg)
        self._bar_bg = bar_bg
        self.content = QWidget()
        self.content_lay = QVBoxLayout(self.content)
        self.content_lay.setAlignment(Qt.AlignCenter)
        self.content_lay.setSpacing(10)
        self.lbl_task = QLabel("")
        self.lbl_task.setFont(QFont("Georgia", 100, QFont.Bold))
        self.lbl_task.setAlignment(Qt.AlignCenter)
        self.lbl_task.setWordWrap(True)
        self.content_lay.addWidget(self.lbl_task)
        self.lbl_answer = QLabel("")
        self.lbl_answer.setFont(QFont("Georgia", 110, QFont.Bold))
        self.lbl_answer.setAlignment(Qt.AlignCenter)
        self.lbl_answer.setStyleSheet("color: #E65100;")
        self.content_lay.addWidget(self.lbl_answer)
        self.lbl_countdown = QLabel("")
        self.lbl_countdown.setFont(QFont("Segoe UI", 18))
        self.lbl_countdown.setAlignment(Qt.AlignCenter)
        self.lbl_countdown.setStyleSheet("color:#bbb;")
        self.content_lay.addWidget(self.lbl_countdown)
        lay.addWidget(self.content, stretch=1)
        bottom = QWidget()
        bottom.setFixedHeight(54)
        bottom.setStyleSheet("border-top:1px solid #eee;")
        bot_lay = QHBoxLayout(bottom)
        bot_lay.setContentsMargins(20, 0, 20, 0)
        self.lbl_hint = QLabel("Leertaste oder → | ESC = Beenden")
        self.lbl_hint.setFont(QFont("Segoe UI", 9))
        self.lbl_hint.setStyleSheet("color:#aaa;")
        bot_lay.addWidget(self.lbl_hint)
        bot_lay.addStretch()
        self.btn_correct = QPushButton("✓  Richtig")
        self.btn_correct.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.btn_correct.setFixedHeight(36)
        self.btn_correct.setStyleSheet("QPushButton{background:#2E7D32;color:white;border-radius:8px;padding:0 16px;} QPushButton:hover{background:#1B5E20;}")
        self.btn_correct.clicked.connect(lambda: self._record_and_advance(True))
        self.btn_correct.hide()
        bot_lay.addWidget(self.btn_correct)
        self.btn_wrong = QPushButton("✗  Falsch")
        self.btn_wrong.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.btn_wrong.setFixedHeight(36)
        self.btn_wrong.setStyleSheet("QPushButton{background:#C62828;color:white;border-radius:8px;padding:0 16px;} QPushButton:hover{background:#B71C1C;}")
        self.btn_wrong.clicked.connect(lambda: self._record_and_advance(False))
        self.btn_wrong.hide()
        bot_lay.addWidget(self.btn_wrong)
        self.btn_next = QPushButton("Weiter ▶")
        self.btn_next.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.btn_next.setFixedHeight(36)
        self.btn_next.setStyleSheet("QPushButton{background:#6A1B9A;color:white;border-radius:8px;padding:0 20px;} QPushButton:hover{background:#4A148C;}")
        self.btn_next.clicked.connect(self._advance)
        bot_lay.addWidget(self.btn_next)
        lay.addWidget(bottom)

    def _sound(self, kind: str):
        if self.settings.get("sound", True):
            _play_sound(kind)

    def _start_countdown(self, duration_s: float, color: str = "#6A1B9A"):
        import time
        self._countdown_end_ms = int(time.time() * 1000 + duration_s * 1000)
        self._countdown_duration_ms = int(duration_s * 1000)
        self.progress_bar.setStyleSheet(f"background:{color}; border-radius:0px;")
        self.countdown_timer.start()
        self._countdown_tick()

    def _stop_countdown(self):
        self.countdown_timer.stop()
        self.progress_bar.setFixedWidth(0)
        self.lbl_countdown.setText("")

    def _countdown_tick(self):
        import time
        now_ms = int(time.time() * 1000)
        remaining_ms = max(0, self._countdown_end_ms - now_ms)
        total = self._countdown_duration_ms or 1
        frac = remaining_ms / total
        w = max(0, int(self._bar_bg.width() * frac))
        self.progress_bar.setFixedWidth(w)
        secs = remaining_ms / 1000
        self.lbl_countdown.setText(f"{secs:.1f} s")
        if remaining_ms <= 0:
            self.countdown_timer.stop()

    def _get_gap_answer(self, task: tuple) -> str:
        q, result, typ, a, op, b = task
        if typ == "gap_left":
            return str(a)
        elif typ == "gap_right":
            return str(b)
        return str(result)

    def _show_slide(self):
        fs = self.settings["font_size"]
        bg = self.settings["bg"]
        no_auto = self.settings.get("no_auto_answer", False)
        self.content.setStyleSheet(f"background:{bg};")
        self._bar_bg.setStyleSheet("background:#e0e0e0;")
        if self.index >= len(self.tasks):
            self._stop_countdown()
            self.lbl_task.setFont(QFont("Georgia", 72, QFont.Bold))
            self.lbl_task.setStyleSheet("color:#2E7D32;")
            self.lbl_task.setText("🎊  Super gemacht!")
            correct = sum(1 for r in self.results if r['correct'])
            total   = len(self.results)
            self.lbl_answer.setFont(QFont("Segoe UI", 28))
            self.lbl_answer.setStyleSheet("color:#555;")
            self.lbl_answer.setText(f"{correct} von {total} richtig  —  {'⭐' * min(correct, 10)}")
            self.lbl_countdown.setText("")
            self.lbl_phase.setText("Fertig!")
            self.lbl_phase.setStyleSheet("color:white;background:#2E7D32;border-radius:10px;padding:2px 12px;")
            self.content.setStyleSheet("background:#E8F5E9;")
            self.btn_correct.hide()
            self.btn_wrong.hide()
            self._sound("finish")
            return
        if self.phase == "applause":
            self._stop_countdown()
            self.lbl_task.setFont(QFont("Georgia", 80, QFont.Bold))
            self.lbl_task.setStyleSheet("color:#E91E63;")
            self.lbl_task.setText("👏  Toll! Weiter so!")
            self.lbl_answer.setText("")
            self.lbl_countdown.setText("")
            self.lbl_phase.setText("Pause")
            self.lbl_phase.setStyleSheet("color:white;background:#E91E63;border-radius:10px;padding:2px 12px;")
            self.content.setStyleSheet("background:#FCE4EC;")
            self.btn_correct.hide()
            self.btn_wrong.hide()
            self._sound("applause")
            if not no_auto:
                self.timer.start(2000)
            return
        task = self.tasks[self.index]
        q = task[0]
        self.lbl_counter.setText(f"{self.index + 1} / {len(self.tasks)}")
        if self.phase == "question":
            self._stop_countdown()
            self.lbl_task.setFont(QFont("Georgia", fs, QFont.Bold))
            self.lbl_task.setStyleSheet("color:#1A237E;")
            self.lbl_task.setText(f"{q}  =  ?")
            self.lbl_answer.setText("")
            self.lbl_phase.setText("Aufgabe")
            self.lbl_phase.setStyleSheet("color:white;background:#6A1B9A;border-radius:10px;padding:2px 12px;")
            self.btn_correct.hide()
            self.btn_wrong.hide()
            self.btn_next.show()
            self._sound("question")
            if no_auto:
                self._stop_countdown()
                self.lbl_hint.setText("→ / Leertaste = Lösung  |  ESC = Beenden")
            else:
                q_ms = self.settings["q_time"]
                self._start_countdown(q_ms, "#6A1B9A")
                self.timer.start(int(q_ms * 1000))
                self.lbl_hint.setText("Leertaste / → = überspringen  |  ESC = Beenden")
        else:
            self._stop_countdown()
            ans_display = self._get_gap_answer(task)
            self.lbl_task.setFont(QFont("Georgia", int(fs * 0.65), QFont.Bold))
            self.lbl_task.setStyleSheet("color:#888;")
            self.lbl_task.setText(f"{q}  =")
            self.lbl_answer.setFont(QFont("Georgia", fs, QFont.Bold))
            self.lbl_answer.setStyleSheet("color:#E65100;")
            self.lbl_answer.setText(ans_display)
            self.lbl_phase.setText("Lösung")
            self.lbl_phase.setStyleSheet("color:white;background:#E65100;border-radius:10px;padding:2px 12px;")
            self._sound("answer")
            if no_auto:
                self.btn_next.hide()
                self.btn_correct.show()
                self.btn_wrong.show()
                self.lbl_hint.setText("Richtig oder Falsch drücken  |  ESC = Beenden")
            else:
                self.btn_correct.hide()
                self.btn_wrong.hide()
                self.btn_next.show()
                a_ms = self.settings["a_time"]
                self._start_countdown(a_ms, "#E65100")
                self.timer.start(int(a_ms * 1000))
                self.lbl_hint.setText("Leertaste / → = weiter  |  ESC = Beenden")
                self._auto_record()

    def _auto_record(self):
        if self.index < len(self.tasks):
            task = self.tasks[self.index]
            self.results.append({
                "question": task[0] + " = " + self._get_gap_answer(task),
                "answer":   self._get_gap_answer(task),
                "correct":  True,
            })

    def _record_and_advance(self, correct: bool):
        if self.index < len(self.tasks):
            task = self.tasks[self.index]
            self.results.append({
                "question": task[0] + " = ?",
                "answer":   self._get_gap_answer(task),
                "correct":  correct,
            })
        self.btn_correct.hide()
        self.btn_wrong.hide()
        self.btn_next.show()
        self._go_next()

    def _go_next(self):
        self.index += 1
        self.phase = "question"
        if self.index > 0 and self.index < len(self.tasks) and self.index % self.APPLAUSE_EVERY == 0:
            self.phase = "applause"
        self._show_slide()

    def _timer_tick(self):
        no_auto = self.settings.get("no_auto_answer", False)
        if self.phase == "applause":
            self.phase = "question"
            self._show_slide()
        elif self.phase == "question":
            self.phase = "answer"
            self._show_slide()
        else:
            self._go_next()

    def _advance(self):
        self.timer.stop()
        self._stop_countdown()
        no_auto = self.settings.get("no_auto_answer", False)
        if self.phase == "applause":
            self.phase = "question"
            self._show_slide()
        elif no_auto:
            if self.phase == "question":
                self.phase = "answer"
                self._show_slide()
        else:
            self._timer_tick()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_bar_bg') and hasattr(self, '_countdown_duration_ms'):
            import time
            if self._countdown_end_ms > 0:
                now_ms = int(time.time() * 1000)
                remaining_ms = max(0, self._countdown_end_ms - now_ms)
                total = self._countdown_duration_ms or 1
                frac = remaining_ms / total
                w = max(0, int(self._bar_bg.width() * frac))
                self.progress_bar.setFixedWidth(w)

    def closeEvent(self, event):
        self.timer.stop()
        self.countdown_timer.stop()
        self.closed.emit()
        super().closeEvent(event)

# ── Hauptfenster (MainWindow) ───────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Blitzlesen – Lehrer-Steuerung")
        self.setMinimumSize(700, 580)
        self.resize(760, 640)
        self.setStyleSheet("QMainWindow { background: #F5F5F5; }")
        self.words     = []
        self.sentences = []
        self.slide_win = None
        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        central.setStyleSheet("background: #F5F5F5;")
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.main_tabs = QTabWidget()
        self.main_tabs.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.main_tabs.setStyleSheet("QTabWidget::pane { border: none; background: #F5F5F5; } QTabBar::tab { padding: 10px 32px; font-size: 11pt; font-weight: 700; border-radius: 0; border-bottom: 3px solid transparent; } QTabBar::tab:selected { color: #1565C0; border-bottom: 3px solid #1565C0; background: #F5F5F5; } QTabBar::tab:!selected { color: #888; background: #EEEEEE; }")
        outer.addWidget(self.main_tabs)

        # ── Blitzlesen-Tab ──
        read_tab = QWidget()
        read_tab.setStyleSheet("background: #F5F5F5;")
        self.main_tabs.addTab(read_tab, "📖  Blitzlesen")
        root = QVBoxLayout(read_tab)
        root.setContentsMargins(32, 24, 32, 24)
        root.setSpacing(16)
        title = QLabel("📖  Blitzlesen")
        title.setFont(QFont("Georgia", 26, QFont.Bold))
        title.setStyleSheet("color: #1565C0;")
        title.setAlignment(Qt.AlignCenter)
        root.addWidget(title)
        sub = QLabel("Diashow-Generator für die 2. Klasse")
        sub.setFont(QFont("Segoe UI", 11))
        sub.setStyleSheet("color: #888;")
        sub.setAlignment(Qt.AlignCenter)
        root.addWidget(sub)

        # Set-Name & Speichern
        set_group = QGroupBox("1.  Set-Name & Speichern")
        set_group.setFont(QFont("Segoe UI", 10, QFont.Bold))
        set_layout = QGridLayout(set_group)
        set_layout.setSpacing(8)
        set_layout.addWidget(QLabel("Set-Name:"), 0, 0)
        self.set_name_edit = QLineEdit()
        self.set_name_edit.setPlaceholderText("z. B. Woche 3 – Tiere")
        self.set_name_edit.setFont(QFont("Segoe UI", 10))
        self.set_name_edit.setFixedHeight(32)
        self.set_name_edit.setStyleSheet("QLineEdit { border:1px solid #ccc; border-radius:5px; padding:0 8px; background:white; } QLineEdit:focus { border:1px solid #1565C0; }")
        set_layout.addWidget(self.set_name_edit, 0, 1)
        btn_save_set = QPushButton("💾  Set speichern")
        btn_save_set.setFont(QFont("Segoe UI", 10))
        btn_save_set.setFixedHeight(32)
        btn_save_set.setStyleSheet(self._btn_style("#2E7D32"))
        btn_save_set.clicked.connect(self._save_set)
        set_layout.addWidget(btn_save_set, 0, 2)
        btn_load_set = QPushButton("📂  Set laden")
        btn_load_set.setFont(QFont("Segoe UI", 10))
        btn_load_set.setFixedHeight(32)
        btn_load_set.setStyleSheet(self._btn_style("#7B1FA2"))
        btn_load_set.clicked.connect(self._load_set)
        set_layout.addWidget(btn_load_set, 0, 3)
        root.addWidget(set_group)

        # Wortliste
        word_group = QGroupBox("2.  Wortliste")
        word_group.setFont(QFont("Segoe UI", 10, QFont.Bold))
        wg_layout = QVBoxLayout(word_group)
        wg_layout.setSpacing(8)
        csv_row = QHBoxLayout()
        btn_load = QPushButton("📂  CSV laden")
        btn_load.setFont(QFont("Segoe UI", 9, QFont.Bold))
        btn_load.setFixedHeight(30)
        btn_load.setMinimumWidth(150)
        btn_load.setStyleSheet(self._btn_style("#1565C0"))
        btn_load.clicked.connect(self._load_csv)
        csv_row.addWidget(btn_load)
        self.csv_label = QLabel("Noch keine Datei geladen.")
        self.csv_label.setFont(QFont("Segoe UI", 9))
        self.csv_label.setStyleSheet("color:#555;")
        csv_row.addWidget(self.csv_label, stretch=1)
        wg_layout.addLayout(csv_row)

        self.word_tabs = QTabWidget()
        self.word_tabs.setFont(QFont("Segoe UI", 9))
        tab_style = "QTabWidget::pane{border:1px solid #ddd;border-radius:6px;} QTabBar::tab{padding:5px 18px;font-weight:700;border-radius:6px 6px 0 0;} QTabBar::tab:selected{background:#1565C0;color:white;} QTabBar::tab:!selected{background:#eee;color:#666;}"
        self.word_tabs.setStyleSheet(tab_style)

        # Tab "Wörter"
        word_tab = QWidget()
        wt_lay = QVBoxLayout(word_tab)
        wt_lay.setContentsMargins(8, 8, 8, 8)
        wt_lay.setSpacing(6)
        self.word_scroll = QScrollArea()
        self.word_scroll.setWidgetResizable(False)
        self.word_scroll.setFixedHeight(80)
        self.word_scroll.setStyleSheet("QScrollArea{border:1px solid #eee;border-radius:6px;background:white;}")
        self.word_chip_container = QWidget()
        self.word_chip_container.setStyleSheet("background:white;")
        self.word_chip_layout = QHBoxLayout(self.word_chip_container)
        self.word_chip_layout.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.word_chip_layout.setSpacing(4)
        self.word_chip_layout.setContentsMargins(4, 4, 4, 4)
        self.word_scroll.setWidget(self.word_chip_container)
        wt_lay.addWidget(self.word_scroll)
        add_word_row = QHBoxLayout()
        self.word_input = QLineEdit()
        self.word_input.setPlaceholderText("Wort tippen und Enter drücken…")
        self.word_input.setFont(QFont("Segoe UI", 10))
        self.word_input.setFixedHeight(30)
        self.word_input.setStyleSheet("QLineEdit{border:1px solid #ccc;border-radius:6px;padding:0 8px;background:white;} QLineEdit:focus{border:1px solid #1565C0;}")
        self.word_input.returnPressed.connect(self._add_word_manual)
        add_word_row.addWidget(self.word_input)
        btn_add_word = QPushButton("+ Hinzufügen")
        btn_add_word.setFont(QFont("Segoe UI", 9, QFont.Bold))
        btn_add_word.setFixedHeight(30)
        btn_add_word.setStyleSheet(self._btn_style("#1565C0"))
        btn_add_word.clicked.connect(self._add_word_manual)
        add_word_row.addWidget(btn_add_word)
        wt_lay.addLayout(add_word_row)
        self.word_tabs.addTab(word_tab, "Wörter (0)")

        # Tab "Sätze"
        sent_tab = QWidget()
        st_lay = QVBoxLayout(sent_tab)
        st_lay.setContentsMargins(8, 8, 8, 8)
        st_lay.setSpacing(6)
        self.sent_scroll = QScrollArea()
        self.sent_scroll.setWidgetResizable(False)
        self.sent_scroll.setFixedHeight(80)
        self.sent_scroll.setStyleSheet("QScrollArea{border:1px solid #eee;border-radius:6px;background:white;}")
        self.sent_chip_container = QWidget()
        self.sent_chip_container.setStyleSheet("background:white;")
        self.sent_chip_layout = QHBoxLayout(self.sent_chip_container)
        self.sent_chip_layout.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.sent_chip_layout.setSpacing(4)
        self.sent_chip_layout.setContentsMargins(4, 4, 4, 4)
        self.sent_scroll.setWidget(self.sent_chip_container)
        st_lay.addWidget(self.sent_scroll)
        add_sent_row = QHBoxLayout()
        self.sent_input = QLineEdit()
        self.sent_input.setPlaceholderText("Satz tippen und Enter drücken…")
        self.sent_input.setFont(QFont("Segoe UI", 10))
        self.sent_input.setFixedHeight(30)
        self.sent_input.setStyleSheet("QLineEdit{border:1px solid #ccc;border-radius:6px;padding:0 8px;background:white;} QLineEdit:focus{border:1px solid #2E7D32;}")
        self.sent_input.returnPressed.connect(self._add_sent_manual)
        add_sent_row.addWidget(self.sent_input)
        btn_add_sent = QPushButton("+ Hinzufügen")
        btn_add_sent.setFont(QFont("Segoe UI", 9, QFont.Bold))
        btn_add_sent.setFixedHeight(30)
        btn_add_sent.setStyleSheet(self._btn_style("#2E7D32"))
        btn_add_sent.clicked.connect(self._add_sent_manual)
        add_sent_row.addWidget(btn_add_sent)
        st_lay.addLayout(add_sent_row)
        self.word_tabs.addTab(sent_tab, "Sätze (0)")
        wg_layout.addWidget(self.word_tabs)
        root.addWidget(word_group)

        # Einstellungen
        settings_group = QGroupBox("3.  Einstellungen")
        settings_group.setFont(QFont("Segoe UI", 10, QFont.Bold))
        grid = QGridLayout(settings_group)
        grid.setSpacing(12)
        grid.addWidget(QLabel("Wörter pro Runde:"), 0, 0)
        self.spin_words = QSpinBox()
        self.spin_words.setRange(1, 20)
        self.spin_words.setValue(5)
        self.spin_words.setFixedWidth(80)
        grid.addWidget(self.spin_words, 0, 1)
        grid.addWidget(QLabel("Sätze pro Runde:"), 0, 2)
        self.spin_sents = QSpinBox()
        self.spin_sents.setRange(0, 10)
        self.spin_sents.setValue(2)
        self.spin_sents.setFixedWidth(80)
        grid.addWidget(self.spin_sents, 0, 3)
        grid.addWidget(QLabel("Gesamtanzahl Dias:"), 1, 0)
        self.spin_total = QSpinBox()
        self.spin_total.setRange(5, 100)
        self.spin_total.setValue(21)
        self.spin_total.setFixedWidth(80)
        grid.addWidget(self.spin_total, 1, 1)
        grid.addWidget(QLabel("Schriftgröße:"), 1, 2)
        self.spin_font = QSpinBox()
        self.spin_font.setRange(30, 160)
        self.spin_font.setValue(80)
        self.spin_font.setSuffix(" px")
        self.spin_font.setFixedWidth(90)
        grid.addWidget(self.spin_font, 1, 3)
        grid.addWidget(QLabel("Tempo (Sek./Dia):"), 2, 0)
        self.spin_tempo = QDoubleSpinBox()
        self.spin_tempo.setRange(0.5, 10.0)
        self.spin_tempo.setValue(2.0)
        self.spin_tempo.setSingleStep(0.5)
        self.spin_tempo.setSuffix(" s")
        self.spin_tempo.setFixedWidth(80)
        grid.addWidget(self.spin_tempo, 2, 1)
        grid.addWidget(QLabel("Modus:"), 2, 2)
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["Manuell (Pfeiltasten)", "Automatisch (Timer)", "Beides wählbar"])
        self.combo_mode.setFixedWidth(200)
        grid.addWidget(self.combo_mode, 2, 3)
        grid.addWidget(QLabel("Hintergrund:"), 3, 0)
        self.combo_bg = QComboBox()
        for name in BG_PRESETS:
            self.combo_bg.addItem(name)
        self.combo_bg.setFixedWidth(140)
        grid.addWidget(self.combo_bg, 3, 1)
        root.addWidget(settings_group)

        # Silbenfarben
        color_group = QGroupBox("4.  Silbenfarben")
        color_group.setFont(QFont("Segoe UI", 10, QFont.Bold))
        color_layout = QHBoxLayout(color_group)
        color_layout.setSpacing(8)
        self.syllable_colors = ["#2563EB","#DC2626","#16A34A","#9333EA","#D97706","#0891B2"]
        self.color_buttons = []
        for i, col in enumerate(self.syllable_colors):
            btn = QPushButton(f"Silbe {i+1}")
            btn.setFixedHeight(32)
            btn.setFixedWidth(80)
            btn.setStyleSheet(f"QPushButton {{ background:{col}; color:white; border-radius:6px; font-weight:bold; }}")
            btn.clicked.connect(lambda checked, idx=i: self._pick_color(idx))
            color_layout.addWidget(btn)
            self.color_buttons.append(btn)
        color_layout.addStretch()
        btn_reset_colors = QPushButton("↺ Zurücksetzen")
        btn_reset_colors.setFixedHeight(32)
        btn_reset_colors.setStyleSheet("QPushButton { background:#888; color:white; border-radius:6px; } QPushButton:hover { background:#555; }")
        btn_reset_colors.clicked.connect(self._reset_colors)
        color_layout.addWidget(btn_reset_colors)
        root.addWidget(color_group)

        # Aktionsbuttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        self.btn_preview_syls = QPushButton("🔍  Silben prüfen")
        self.btn_preview_syls.setFont(QFont("Georgia", 12, QFont.Bold))
        self.btn_preview_syls.setFixedHeight(54)
        self.btn_preview_syls.setEnabled(False)
        self.btn_preview_syls.setStyleSheet(self._btn_style("#F57C00", disabled=True))
        self.btn_preview_syls.clicked.connect(self._show_syllable_preview)
        btn_row.addWidget(self.btn_preview_syls)
        self.btn_start = QPushButton("▶  Diashow starten")
        self.btn_start.setFont(QFont("Georgia", 12, QFont.Bold))
        self.btn_start.setFixedHeight(54)
        self.btn_start.setEnabled(False)
        self.btn_start.setStyleSheet(self._btn_style("#2E7D32", disabled=True))
        self.btn_start.clicked.connect(self._start_slideshow)
        btn_row.addWidget(self.btn_start)
        self.btn_export = QPushButton("💾  Als PowerPoint speichern")
        self.btn_export.setFont(QFont("Georgia", 12, QFont.Bold))
        self.btn_export.setFixedHeight(54)
        self.btn_export.setEnabled(False)
        self.btn_export.setStyleSheet(self._btn_style("#1565C0", disabled=True))
        self.btn_export.clicked.connect(self._export_pptx)
        btn_row.addWidget(self.btn_export)
        root.addLayout(btn_row)

        self._build_mathe_tab()

    # ── Mathe-Tab ──
    def _build_mathe_tab(self):
        from PyQt5.QtWidgets import QCheckBox as _CB, QRadioButton, QButtonGroup
        math_tab = QWidget()
        math_tab.setStyleSheet("background: #F5F5F5;")
        self.main_tabs.addTab(math_tab, "🔢  Mathe-Blitz")
        mroot = QVBoxLayout(math_tab)
        mroot.setContentsMargins(32, 24, 32, 24)
        mroot.setSpacing(14)
        mt = QLabel("🔢  Mathe-Blitz")
        mt.setFont(QFont("Georgia", 26, QFont.Bold))
        mt.setStyleSheet("color: #6A1B9A;")
        mt.setAlignment(Qt.AlignCenter)
        mroot.addWidget(mt)
        ms = QLabel("Blitzrechnen für die Grundschule")
        ms.setFont(QFont("Segoe UI", 11))
        ms.setStyleSheet("color: #888;")
        ms.setAlignment(Qt.AlignCenter)
        mroot.addWidget(ms)

        diff_group = QGroupBox("1.  Schwierigkeitsgrad")
        diff_group.setFont(QFont("Segoe UI", 10, QFont.Bold))
        diff_lay = QHBoxLayout(diff_group)
        diff_lay.setSpacing(8)
        self._diff_btns = []
        diff_labels = [
            ("🟢  Leicht",  "#2E7D32", {"add_max":10,  "sub_max":10,  "q_time":4.0, "a_time":3.0}),
            ("🟡  Mittel",  "#F57C00", {"add_max":20,  "sub_max":20,  "q_time":3.0, "a_time":2.0}),
            ("🔴  Schwer",  "#C62828", {"add_max":100, "sub_max":100, "q_time":2.0, "a_time":1.5}),
            ("⚙️  Eigene",  "#555555", None),
        ]
        self._diff_presets = [d[2] for d in diff_labels]
        for i, (label, color, _) in enumerate(diff_labels):
            rb = QPushButton(label)
            rb.setCheckable(True)
            rb.setFixedHeight(34)
            rb.setFont(QFont("Segoe UI", 10, QFont.Bold))
            rb.setStyleSheet(f"QPushButton {{background:#eee; color:#555; border-radius:8px; padding:0 16px; border:2px solid transparent;}} QPushButton:checked {{background:{color}22; color:{color}; border:2px solid {color};}} QPushButton:hover {{background:{color}11;}}")
            rb.clicked.connect(lambda checked, idx=i: self._apply_difficulty(idx))
            diff_lay.addWidget(rb)
            self._diff_btns.append(rb)
        self._diff_btns[1].setChecked(True)
        mroot.addWidget(diff_group)

        op_group = QGroupBox("2.  Rechenarten")
        op_group.setFont(QFont("Segoe UI", 10, QFont.Bold))
        op_lay = QHBoxLayout(op_group)
        op_lay.setSpacing(20)
        self.chk_add = _CB("➕  Addition")
        self.chk_sub = _CB("➖  Subtraktion")
        self.chk_mul = _CB("✖  Einmaleins")
        self.chk_div = _CB("➗  Division")
        for chk in (self.chk_add, self.chk_sub, self.chk_mul, self.chk_div):
            chk.setFont(QFont("Segoe UI", 10))
            chk.setChecked(True)
            op_lay.addWidget(chk)
        op_lay.addStretch()
        self.chk_gap = _CB("❓  Lückenaufgaben  (z. B.  7 × ? = 21)")
        self.chk_gap.setFont(QFont("Segoe UI", 10))
        op_lay.addWidget(self.chk_gap)
        mroot.addWidget(op_group)

        ms_group = QGroupBox("3.  Einstellungen")
        ms_group.setFont(QFont("Segoe UI", 10, QFont.Bold))
        ms_grid = QGridLayout(ms_group)
        ms_grid.setSpacing(12)
        ms_grid.addWidget(QLabel("Addition/Subtraktion/Division bis:"), 0, 0)
        self.spin_math_max = QSpinBox()
        self.spin_math_max.setRange(5, 1000)
        self.spin_math_max.setValue(20)
        self.spin_math_max.setFixedWidth(80)
        ms_grid.addWidget(self.spin_math_max, 0, 1)
        ms_grid.addWidget(QLabel("Anzahl Aufgaben:"), 0, 2)
        self.spin_math_count = QSpinBox()
        self.spin_math_count.setRange(5, 100)
        self.spin_math_count.setValue(20)
        self.spin_math_count.setFixedWidth(80)
        ms_grid.addWidget(self.spin_math_count, 0, 3)
        ms_grid.addWidget(QLabel("Schriftgröße:"), 1, 0)
        self.spin_math_font = QSpinBox()
        self.spin_math_font.setRange(30, 160)
        self.spin_math_font.setValue(100)
        self.spin_math_font.setSuffix(" px")
        self.spin_math_font.setFixedWidth(90)
        ms_grid.addWidget(self.spin_math_font, 1, 1)
        ms_grid.addWidget(QLabel("Aufgabe sichtbar (Sek.):"), 1, 2)
        self.spin_math_q = QDoubleSpinBox()
        self.spin_math_q.setRange(0.5, 10.0)
        self.spin_math_q.setValue(3.0)
        self.spin_math_q.setSingleStep(0.5)
        self.spin_math_q.setSuffix(" s")
        self.spin_math_q.setFixedWidth(80)
        ms_grid.addWidget(self.spin_math_q, 1, 3)
        ms_grid.addWidget(QLabel("Lösung sichtbar (Sek.):"), 2, 0)
        self.spin_math_a = QDoubleSpinBox()
        self.spin_math_a.setRange(0.5, 10.0)
        self.spin_math_a.setValue(2.0)
        self.spin_math_a.setSingleStep(0.5)
        self.spin_math_a.setSuffix(" s")
        self.spin_math_a.setFixedWidth(80)
        ms_grid.addWidget(self.spin_math_a, 2, 1)
        ms_grid.addWidget(QLabel("Hintergrund:"), 2, 2)
        self.combo_math_bg = QComboBox()
        for name in BG_PRESETS:
            self.combo_math_bg.addItem(name)
        self.combo_math_bg.setFixedWidth(140)
        ms_grid.addWidget(self.combo_math_bg, 2, 3)
        self.chk_no_auto_answer = _CB("🚫  Ergebnis nicht automatisch anzeigen")
        self.chk_no_auto_answer.setFont(QFont("Segoe UI", 10))
        def _toggle_a_spin(state):
            self.spin_math_a.setEnabled(not self.chk_no_auto_answer.isChecked())
        self.chk_no_auto_answer.stateChanged.connect(_toggle_a_spin)
        ms_grid.addWidget(self.chk_no_auto_answer, 3, 0, 1, 2)
        self.chk_math_sound = _CB("🔔  Soundeffekte")
        self.chk_math_sound.setFont(QFont("Segoe UI", 10))
        self.chk_math_sound.setChecked(True)
        ms_grid.addWidget(self.chk_math_sound, 3, 2, 1, 2)
        mroot.addWidget(ms_group)

        mul_group = QGroupBox("4.  Reihen für Einmaleins & Division")
        mul_group.setFont(QFont("Segoe UI", 10, QFont.Bold))
        vbox = QVBoxLayout(mul_group)
        hbox_rows = QHBoxLayout()
        hbox_rows.setSpacing(8)
        self.mul_checks = []
        for n in range(1, 11):
            chk = _CB(str(n))
            chk.setFont(QFont("Segoe UI", 10, QFont.Bold))
            chk.setChecked(True)
            hbox_rows.addWidget(chk)
            self.mul_checks.append(chk)
        hbox_rows.addStretch()
        btn_all  = QPushButton("Alle")
        btn_none = QPushButton("Keine")
        for b in (btn_all, btn_none):
            b.setFixedHeight(28)
            b.setFont(QFont("Segoe UI", 9))
            b.setStyleSheet("QPushButton{background:#ddd;border-radius:5px;padding:0 10px;} QPushButton:hover{background:#bbb;}")
        btn_all.clicked.connect(lambda: [c.setChecked(True)  for c in self.mul_checks])
        btn_none.clicked.connect(lambda: [c.setChecked(False) for c in self.mul_checks])
        hbox_rows.addWidget(btn_all)
        hbox_rows.addWidget(btn_none)
        vbox.addLayout(hbox_rows)
        hbox_full_mul = QHBoxLayout()
        self.chk_full_mul = _CB("Alle Kombinationen (Multiplikation, systematisch)")
        self.chk_full_mul.setFont(QFont("Segoe UI", 10))
        self.chk_full_mul.stateChanged.connect(lambda state: self._toggle_systematic("mul", state))
        hbox_full_mul.addWidget(self.chk_full_mul)
        hbox_full_mul.addSpacing(20)
        hbox_full_mul.addWidget(QLabel("Wiederholungen:"))
        self.spin_mul_repeat = QSpinBox()
        self.spin_mul_repeat.setRange(1, 10)
        self.spin_mul_repeat.setValue(1)
        self.spin_mul_repeat.setFixedWidth(60)
        hbox_full_mul.addWidget(self.spin_mul_repeat)
        hbox_full_mul.addStretch()
        vbox.addLayout(hbox_full_mul)
        hbox_full_div = QHBoxLayout()
        self.chk_full_div = _CB("Alle Kombinationen (Division, systematisch)")
        self.chk_full_div.setFont(QFont("Segoe UI", 10))
        self.chk_full_div.stateChanged.connect(lambda state: self._toggle_systematic("div", state))
        hbox_full_div.addWidget(self.chk_full_div)
        hbox_full_div.addSpacing(20)
        hbox_full_div.addWidget(QLabel("Wiederholungen:"))
        self.spin_div_repeat = QSpinBox()
        self.spin_div_repeat.setRange(1, 10)
        self.spin_div_repeat.setValue(1)
        self.spin_div_repeat.setFixedWidth(60)
        hbox_full_div.addWidget(self.spin_div_repeat)
        hbox_full_div.addStretch()
        vbox.addLayout(hbox_full_div)
        mroot.addWidget(mul_group)
        mroot.addStretch()

        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        btn_session_save = QPushButton("💾  Session speichern")
        btn_session_save.setFont(QFont("Segoe UI", 10))
        btn_session_save.setFixedHeight(44)
        btn_session_save.setStyleSheet(self._btn_style("#37474F"))
        btn_session_save.clicked.connect(self._save_math_session)
        btn_row.addWidget(btn_session_save)
        btn_session_load = QPushButton("📂  Session laden")
        btn_session_load.setFont(QFont("Segoe UI", 10))
        btn_session_load.setFixedHeight(44)
        btn_session_load.setStyleSheet(self._btn_style("#546E7A"))
        btn_session_load.clicked.connect(self._load_math_session)
        btn_row.addWidget(btn_session_load)
        btn_row.addStretch()
        self.btn_math_start = QPushButton("▶  Mathe-Blitz starten")
        self.btn_math_start.setFont(QFont("Georgia", 14, QFont.Bold))
        self.btn_math_start.setFixedHeight(54)
        self.btn_math_start.setStyleSheet(self._btn_style("#6A1B9A"))
        self.btn_math_start.clicked.connect(self._start_math)
        btn_row.addWidget(self.btn_math_start)
        mroot.addLayout(btn_row)

        self._apply_difficulty(1)
        self._toggle_systematic("mul", Qt.Unchecked)
        self._toggle_systematic("div", Qt.Unchecked)

    # ── Gemeinsame Hilfsmethoden ────────────────────────────────────────────
    def _btn_style(self, color: str, disabled=False) -> str:
        return f"QPushButton {{ background: {color}; color: white; border-radius: 8px; padding: 6px 18px; }} QPushButton:hover {{ background: {color}cc; }} QPushButton:disabled {{ background: #cccccc; color: #888; }}"

    def _load_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "CSV-Datei öffnen", "", "CSV-Dateien (*.csv)")
        if not path:
            return
        self.words = []
        self.sentences = []
        encodings = ["utf-8-sig", "utf-8", "cp1252", "latin-1"]
        delimiters = [";", ",", "\t"]
        loaded = False
        for enc in encodings:
            if loaded:
                break
            for delim in delimiters:
                try:
                    tmp_words, tmp_sents = [], []
                    with open(path, newline="", encoding=enc) as f:
                        reader = csv.DictReader(f, delimiter=delim)
                        rows = list(reader)
                    if not rows:
                        continue
                    for row in rows:
                        clean = {k.strip().lstrip("\ufeff").lower(): v.strip() for k, v in row.items() if k}
                        typ = clean.get("typ", "").lower()
                        inhalt = clean.get("inhalt", "")
                        if not inhalt:
                            continue
                        if typ == "wort":
                            tmp_words.append(inhalt)
                        elif typ == "satz":
                            tmp_sents.append(inhalt)
                    if tmp_words or tmp_sents:
                        self.words = tmp_words
                        self.sentences = tmp_sents
                        loaded = True
                        break
                except Exception:
                    continue
        if not loaded or (not self.words and not self.sentences):
            preview = ""
            try:
                for enc in encodings:
                    try:
                        with open(path, encoding=enc) as f:
                            preview = f.readline() + f.readline()
                        break
                    except Exception:
                        continue
            except Exception:
                pass
            QMessageBox.warning(self, "Nicht erkannt", "Die CSV enthält keine gültigen Einträge.\n\n"
                                "Erwartet werden zwei Spalten:\n  typ     -> 'wort' oder 'satz'\n  inhalt  -> das Wort oder den Satz\n\n"
                                f"Erste Zeilen deiner Datei:\n{preview}")
            return
        fname = path.replace('\\', '/').split('/')[-1]
        self.csv_label.setText(f"✔  {fname}  —  {len(self.words)} Wörter, {len(self.sentences)} Sätze")
        self.csv_label.setStyleSheet("color: #2E7D32; font-weight: bold;")
        self._refresh_word_chips()
        self._refresh_sent_chips()
        self._update_after_change()

    def _add_word_manual(self):
        text = self.word_input.text().strip()
        if text and text not in self.words:
            self.words.append(text)
            self._refresh_word_chips()
            self._update_after_change()
        self.word_input.clear()

    def _add_sent_manual(self):
        text = self.sent_input.text().strip()
        if text and text not in self.sentences:
            self.sentences.append(text)
            self._refresh_sent_chips()
            self._update_after_change()
        self.sent_input.clear()

    def _remove_word(self, idx: int):
        if 0 <= idx < len(self.words):
            self.words.pop(idx)
            self._refresh_word_chips()
            self._update_after_change()

    def _remove_sent(self, idx: int):
        if 0 <= idx < len(self.sentences):
            self.sentences.pop(idx)
            self._refresh_sent_chips()
            self._update_after_change()

    def _make_chip(self, text: str, color: str, on_delete):
        chip = QWidget()
        chip.setStyleSheet(f"QWidget {{ background:{color}22; border:1px solid {color}66; border-radius:12px; }}")
        row = QHBoxLayout(chip)
        row.setContentsMargins(8, 3, 4, 3)
        row.setSpacing(4)
        lbl = QLabel(text)
        lbl.setFont(QFont("Segoe UI", 9, QFont.Bold))
        lbl.setStyleSheet(f"color:{color}; background:transparent; border:none;")
        row.addWidget(lbl)
        del_btn = QPushButton("×")
        del_btn.setFixedSize(16, 16)
        del_btn.setStyleSheet(f"QPushButton {{ background:transparent; border:none; color:{color}; font-weight:bold; font-size:13px; padding:0; }} QPushButton:hover {{ color:#c00; }}")
        del_btn.clicked.connect(on_delete)
        row.addWidget(del_btn)
        return chip

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _adjust_chip_container_size(self, container: QWidget):
        if not container.layout():
            return
        children = [container.layout().itemAt(i).widget() for i in range(container.layout().count())]
        children = [w for w in children if w is not None]
        total_width = container.layout().contentsMargins().left() + container.layout().contentsMargins().right()
        spacing = container.layout().spacing()
        for i, child in enumerate(children):
            if i > 0:
                total_width += spacing
            total_width += child.sizeHint().width()
        container.setMinimumWidth(total_width)
        container.adjustSize()

    def _refresh_word_chips(self):
        self._clear_layout(self.word_chip_layout)
        for i, w in enumerate(self.words):
            chip = self._make_chip(w, "#1565C0", lambda checked, idx=i: self._remove_word(idx))
            self.word_chip_layout.addWidget(chip)
        self.word_chip_layout.addStretch()
        self.word_tabs.setTabText(0, f"Wörter ({len(self.words)})")
        self._adjust_chip_container_size(self.word_chip_container)

    def _refresh_sent_chips(self):
        self._clear_layout(self.sent_chip_layout)
        for i, s in enumerate(self.sentences):
            chip = self._make_chip(s, "#2E7D32", lambda checked, idx=i: self._remove_sent(idx))
            self.sent_chip_layout.addWidget(chip)
        self.sent_chip_layout.addStretch()
        self.word_tabs.setTabText(1, f"Sätze ({len(self.sentences)})")
        self._adjust_chip_container_size(self.sent_chip_container)

    def _update_after_change(self):
        has = bool(self.words or self.sentences)
        self.btn_start.setEnabled(has)
        self.btn_start.setStyleSheet(self._btn_style("#2E7D32", disabled=not has))
        self.btn_export.setEnabled(has)
        self.btn_export.setStyleSheet(self._btn_style("#1565C0", disabled=not has))
        self.btn_preview_syls.setEnabled(has)
        self.btn_preview_syls.setStyleSheet(self._btn_style("#F57C00", disabled=not has))

    def _pick_color(self, idx: int):
        current = QColor(self.syllable_colors[idx])
        color = QColorDialog.getColor(current, self, f"Farbe für Silbe {idx + 1}")
        if color.isValid():
            self.syllable_colors[idx] = color.name()
            btn = self.color_buttons[idx]
            btn.setStyleSheet(f"QPushButton {{ background:{color.name()}; color:white; border-radius:6px; font-weight:bold; }}")

    def _reset_colors(self):
        defaults = ["#2563EB","#DC2626","#16A34A","#9333EA","#D97706","#0891B2"]
        for i, col in enumerate(defaults):
            self.syllable_colors[i] = col
            self.color_buttons[i].setStyleSheet(f"QPushButton {{ background:{col}; color:white; border-radius:6px; font-weight:bold; }}")

    def _show_syllable_preview(self):
        if not self.words and not self.sentences:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Silbenvorschau – Prüfen & Bearbeiten")
        dlg.resize(780, 560)
        dlg.setStyleSheet("background:#F5F5F5;")
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        hint = QLabel("Hier siehst du wie jedes Wort/jeden Satz getrennt wird. "
                      "Klicke auf eine Zelle in der Spalte 'Silben', um die Trennung manuell zu korrigieren "
                      "(Silben mit Bindestrich trennen, z. B. <b>Früh-stück</b>).")
        hint.setWordWrap(True)
        hint.setFont(QFont("Segoe UI", 9))
        hint.setStyleSheet("color:#555;")
        layout.addWidget(hint)
        all_items = [("wort", w) for w in self.words] + [("satz", s) for s in self.sentences]
        table = QTableWidget(len(all_items), 3)
        table.setHorizontalHeaderLabels(["Typ", "Original", "Silben (editierbar)"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setFont(QFont("Segoe UI", 10))
        table.setAlternatingRowColors(True)
        table.setStyleSheet("QTableWidget { border: 1px solid #ddd; border-radius: 6px; } "
                            "QHeaderView::section { background:#E3F2FD; color:#1565C0; font-weight:bold; padding:4px; border:none; }")
        for row, (typ, text) in enumerate(all_items):
            typ_item = QTableWidgetItem("Wort" if typ == "wort" else "Satz")
            typ_item.setFlags(Qt.ItemIsEnabled)
            typ_item.setForeground(QColor("#2E7D32" if typ == "wort" else "#1565C0"))
            table.setItem(row, 0, typ_item)
            orig_item = QTableWidgetItem(text)
            orig_item.setFlags(Qt.ItemIsEnabled)
            table.setItem(row, 1, orig_item)
            words_in_text = text.split()
            syl_parts = []
            for w in words_in_text:
                syl_parts.append("-".join(split_syllables(w)))
            syl_item = QTableWidgetItem(" ".join(syl_parts))
            table.setItem(row, 2, syl_item)
        layout.addWidget(table)
        btn_row = QHBoxLayout()
        btn_save = QPushButton("✔  Korrekturen übernehmen & schließen")
        btn_save.setFont(QFont("Segoe UI", 10, QFont.Bold))
        btn_save.setFixedHeight(38)
        btn_save.setStyleSheet("QPushButton { background:#2E7D32; color:white; border-radius:7px; padding:0 16px; } QPushButton:hover { background:#1B5E20; }")
        btn_cancel = QPushButton("Abbrechen")
        btn_cancel.setFont(QFont("Segoe UI", 10))
        btn_cancel.setFixedHeight(38)
        btn_cancel.setStyleSheet("QPushButton { background:#888; color:white; border-radius:7px; padding:0 16px; } QPushButton:hover { background:#555; }")
        btn_row.addWidget(btn_cancel)
        btn_row.addStretch()
        btn_row.addWidget(btn_save)
        layout.addLayout(btn_row)
        def save_corrections():
            self._syllable_overrides = {}
            for row in range(table.rowCount()):
                orig = table.item(row, 1).text()
                corrected = table.item(row, 2).text().strip()
                words_in_text = orig.split()
                default = " ".join("-".join(split_syllables(w)) for w in words_in_text)
                if corrected != default:
                    self._syllable_overrides[orig] = corrected
            dlg.accept()
        btn_save.clicked.connect(save_corrections)
        btn_cancel.clicked.connect(dlg.reject)
        dlg.exec_()

    def _save_set(self):
        if not self.words and not self.sentences:
            QMessageBox.warning(self, "Hinweis", "Bitte zuerst eine CSV-Datei laden, bevor du ein Set speicherst.")
            return
        set_name = self.set_name_edit.text().strip() or "Blitzlesen-Set"
        default_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), set_name.replace(" ", "_") + ".json")
        path, _ = QFileDialog.getSaveFileName(self, "Set speichern", default_path, "Blitzlesen-Set (*.json)")
        if not path:
            return
        data = {
            "set_name": set_name,
            "words": self.words,
            "sentences": self.sentences,
            "overrides": dict(getattr(self, "_syllable_overrides", {})),
            "colors": list(self.syllable_colors),
            "settings": {
                "words_per_round": self.spin_words.value(),
                "sents_per_round": self.spin_sents.value(),
                "total_slides": self.spin_total.value(),
                "font_size": self.spin_font.value(),
                "tempo": self.spin_tempo.value(),
                "mode": self.combo_mode.currentIndex(),
                "bg": self.combo_bg.currentText(),
            }
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "Gespeichert ✓", f'Set "{set_name}" wurde gespeichert:\n{path}')
        except Exception as e:
            QMessageBox.critical(self, "Fehler", f"Speichern fehlgeschlagen:\n{e}")

    def _load_set(self):
        path, _ = QFileDialog.getOpenFileName(self, "Set laden", "", "Blitzlesen-Set (*.json)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "Fehler", f"Set konnte nicht geladen werden:\n{e}")
            return
        self.words = data.get("words", [])
        self.sentences = data.get("sentences", [])
        self._syllable_overrides = data.get("overrides", {})
        colors = data.get("colors", [])
        if len(colors) == 6:
            self.syllable_colors = colors
            for i, col in enumerate(colors):
                self.color_buttons[i].setStyleSheet(f"QPushButton {{ background:{col}; color:white; border-radius:6px; font-weight:bold; }}")
        s = data.get("settings", {})
        if s:
            self.spin_words.setValue(s.get("words_per_round", 5))
            self.spin_sents.setValue(s.get("sents_per_round", 2))
            self.spin_total.setValue(s.get("total_slides", 21))
            self.spin_font.setValue(s.get("font_size", 80))
            self.spin_tempo.setValue(s.get("tempo", 2.0))
            self.combo_mode.setCurrentIndex(s.get("mode", 0))
            bg_name = s.get("bg", "Weiß")
            idx = self.combo_bg.findText(bg_name)
            if idx >= 0:
                self.combo_bg.setCurrentIndex(idx)
        self.set_name_edit.setText(data.get("set_name", ""))
        self.csv_label.setText(f"✔  Set geladen  —  {len(self.words)} Wörter, {len(self.sentences)} Sätze")
        self.csv_label.setStyleSheet("color: #7B1FA2; font-weight: bold;")
        self._refresh_word_chips()
        self._refresh_sent_chips()
        self._update_after_change()
        n_ov = len(self._syllable_overrides)
        ov_text = f", {n_ov} Silbenkorrektur{'en' if n_ov != 1 else ''}" if n_ov else ""
        QMessageBox.information(self, "Set geladen ✓", f'Set "{data.get("set_name", "")}" wurde geladen:\n'
                                f'{len(self.words)} Wörter, {len(self.sentences)} Sätze{ov_text}.')

    def _start_slideshow(self):
        if not self.words and not self.sentences:
            QMessageBox.warning(self, "Hinweis", "Bitte zuerst eine CSV-Datei laden.")
            return
        mode = self.combo_mode.currentIndex()
        auto = mode == 1
        tempo = self.spin_tempo.value()
        bg = BG_PRESETS[self.combo_bg.currentText()]
        fs = self.spin_font.value()
        wpr = self.spin_words.value()
        spr = self.spin_sents.value()
        total = self.spin_total.value()
        slides = build_slides(self.words, self.sentences, wpr, spr, total)
        settings = {
            "auto": auto,
            "tempo": tempo,
            "bg": bg,
            "font_size": fs,
            "colors": list(self.syllable_colors),
            "overrides": dict(getattr(self, "_syllable_overrides", {})),
        }
        self.slide_win = SlideWindow(slides, settings)
        self.slide_win.closed.connect(self._on_slideshow_closed)
        self.hide()

    def _export_pptx(self):
        if not self.words and not self.sentences:
            QMessageBox.warning(self, "Hinweis", "Bitte zuerst eine CSV-Datei laden.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "PowerPoint speichern", "Blitzlesen.pptx", "PowerPoint-Dateien (*.pptx)")
        if not path:
            return
        if not path.endswith(".pptx"):
            path += ".pptx"
        wpr = self.spin_words.value()
        spr = self.spin_sents.value()
        total = self.spin_total.value()
        fs = self.spin_font.value()
        bg = BG_PRESETS[self.combo_bg.currentText()]
        slides = build_slides(self.words, self.sentences, wpr, spr, total)
        js_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "make_blitzlesen_pptx.js")
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
            json.dump({
                "slides": slides,
                "output_path": path,
                "font_size": fs,
                "bg_color": bg,
                "colors": list(self.syllable_colors),
                "overrides": dict(getattr(self, "_syllable_overrides", {})),
            }, f, ensure_ascii=False)
            tmp_json = f.name
        try:
            result = subprocess.run(["node", js_script, tmp_json], capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and os.path.exists(path):
                QMessageBox.information(self, "Fertig! ✓", f"PowerPoint wurde gespeichert:\n{path}")
            else:
                err = result.stderr or result.stdout or "Unbekannter Fehler"
                QMessageBox.critical(self, "Fehler beim Export", f"PowerPoint konnte nicht erstellt werden:\n{err}")
        except FileNotFoundError:
            QMessageBox.critical(self, "Node.js nicht gefunden", "Node.js ist nicht installiert.\nBitte installiere Node.js von https://nodejs.org")
        except subprocess.TimeoutExpired:
            QMessageBox.critical(self, "Timeout", "Der Export hat zu lange gedauert.")
        finally:
            try:
                os.unlink(tmp_json)
            except Exception:
                pass

    def _start_math(self):
        ops = []
        if self.chk_add.isChecked(): ops.append("add")
        if self.chk_sub.isChecked(): ops.append("sub")
        if self.chk_mul.isChecked(): ops.append("mul")
        if self.chk_div.isChecked(): ops.append("div")
        if not ops:
            QMessageBox.warning(self, "Hinweis", "Bitte mindestens eine Rechenart auswählen.")
            return

        mul_rows = [i+1 for i, c in enumerate(self.mul_checks) if c.isChecked()]
        if ("mul" in ops or "div" in ops) and not mul_rows:
            QMessageBox.warning(self, "Hinweis", "Bitte mindestens eine Reihe auswählen.")
            return

        import random as _r
        tasks = []
        gap = self.chk_gap.isChecked()
        mx  = self.spin_math_max.value()

        if "mul" in ops and self.chk_full_mul.isChecked():
            repeat = self.spin_mul_repeat.value()
            for row in mul_rows:
                for factor in range(1, 11):
                    for _ in range(repeat):
                        result = row * factor
                        tasks.append((f"{row}  ×  {factor}", result, "normal", row, "×", factor))
            _r.shuffle(tasks)
        elif "div" in ops and self.chk_full_div.isChecked():
            repeat = self.spin_div_repeat.value()
            for divisor in mul_rows:
                for quotient in range(1, 11):
                    for _ in range(repeat):
                        dividend = divisor * quotient
                        tasks.append((f"{dividend}  ÷  {divisor}", quotient, "normal", dividend, "÷", divisor))
            _r.shuffle(tasks)
        else:
            count = self.spin_math_count.value()
            for _ in range(count):
                op = _r.choice(ops)
                if op == "add":
                    a = _r.randint(1, mx)
                    b = _r.randint(1, mx - a) if a < mx else 1
                    result = a + b
                    if gap and _r.random() < 0.4:
                        if _r.random() < 0.5:
                            tasks.append((f"?  +  {b}", result, "gap_left",  a, "+", b))
                        else:
                            tasks.append((f"{a}  +  ?", result, "gap_right", a, "+", b))
                    else:
                        tasks.append((f"{a}  +  {b}", result, "normal", a, "+", b))
                elif op == "sub":
                    a = _r.randint(1, mx)
                    b = _r.randint(0, a)
                    result = a - b
                    if gap and _r.random() < 0.4:
                        if _r.random() < 0.5:
                            tasks.append((f"?  −  {b}", result, "gap_left",  a, "−", b))
                        else:
                            tasks.append((f"{a}  −  ?", result, "gap_right", a, "−", b))
                    else:
                        tasks.append((f"{a}  −  {b}", result, "normal", a, "−", b))
                elif op == "mul":
                    row = _r.choice(mul_rows)
                    b   = _r.randint(1, 10)
                    result = row * b
                    if gap and _r.random() < 0.4:
                        if _r.random() < 0.5:
                            tasks.append((f"?  ×  {b}", result, "gap_left",  row, "×", b))
                        else:
                            tasks.append((f"{row}  ×  ?", result, "gap_right", row, "×", b))
                    else:
                        tasks.append((f"{row}  ×  {b}", result, "normal", row, "×", b))
                elif op == "div":
                    divisor = _r.choice(mul_rows)
                    factor = _r.randint(1, 10)
                    dividend = divisor * factor
                    result = factor
                    if gap and _r.random() < 0.4:
                        if _r.random() < 0.5:
                            tasks.append((f"?  ÷  {divisor}", result, "gap_left",  dividend, "÷", divisor))
                        else:
                            tasks.append((f"{dividend}  ÷  ?", result, "gap_right", dividend, "÷", divisor))
                    else:
                        tasks.append((f"{dividend}  ÷  {divisor}", result, "normal", dividend, "÷", divisor))

        settings = {
            "font_size":      self.spin_math_font.value(),
            "q_time":         self.spin_math_q.value(),
            "a_time":         self.spin_math_a.value(),
            "bg":             BG_PRESETS[self.combo_math_bg.currentText()],
            "no_auto_answer": self.chk_no_auto_answer.isChecked(),
            "sound":          self.chk_math_sound.isChecked(),
        }
        self.math_win = MathSlideWindow(tasks, settings)
        self.math_win.closed.connect(self._on_math_closed)
        self.hide()

    def _on_slideshow_closed(self):
        self.show()

    def _on_math_closed(self):
        self.show()
        win = getattr(self, 'math_win', None)
        if win and hasattr(win, 'results') and win.results:
            reply = QMessageBox.question(self, "Ergebnisse exportieren",
                                         f"Die Session ist beendet.\nRichtig: {sum(1 for r in win.results if r['correct'])} / {len(win.results)}\n\n"
                                         "Ergebnisse als CSV speichern?",
                                         QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                self._export_math_results(win.results)

    def _export_math_results(self, results: list):
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        default = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"mathe_ergebnisse_{ts}.csv")
        path, _ = QFileDialog.getSaveFileName(self, "Ergebnisse speichern", default, "CSV (*.csv)")
        if not path:
            return
        correct = sum(1 for r in results if r['correct'])
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["Aufgabe", "Antwort", "Richtig/Falsch"])
            for r in results:
                w.writerow([r['question'], r['answer'], "✓ Richtig" if r['correct'] else "✗ Falsch"])
            w.writerow([])
            w.writerow(["Gesamt", len(results), ""])
            w.writerow(["Richtig", correct, ""])
            w.writerow(["Falsch", len(results) - correct, ""])
        QMessageBox.information(self, "Gespeichert ✓", f"Ergebnisse gespeichert:\n{path}")

    def _toggle_systematic(self, typ: str, state):
        if typ == "mul":
            if state == Qt.Checked:
                self.chk_full_div.setChecked(False)
                self.chk_add.setEnabled(False)
                self.chk_sub.setEnabled(False)
                self.chk_div.setEnabled(False)
                self.chk_gap.setEnabled(False)
                self.chk_add.setChecked(False)
                self.chk_sub.setChecked(False)
                self.chk_div.setChecked(False)
                self.chk_gap.setChecked(False)
                self.spin_math_count.setEnabled(False)
                self.chk_mul.setChecked(True)
                self.chk_mul.setEnabled(False)
            else:
                self.chk_add.setEnabled(True)
                self.chk_sub.setEnabled(True)
                self.chk_div.setEnabled(True)
                self.chk_gap.setEnabled(True)
                self.spin_math_count.setEnabled(True)
                self.chk_mul.setEnabled(True)
        elif typ == "div":
            if state == Qt.Checked:
                self.chk_full_mul.setChecked(False)
                self.chk_add.setEnabled(False)
                self.chk_sub.setEnabled(False)
                self.chk_mul.setEnabled(False)
                self.chk_gap.setEnabled(False)
                self.chk_add.setChecked(False)
                self.chk_sub.setChecked(False)
                self.chk_mul.setChecked(False)
                self.chk_gap.setChecked(False)
                self.spin_math_count.setEnabled(False)
                self.chk_div.setChecked(True)
                self.chk_div.setEnabled(False)
            else:
                self.chk_add.setEnabled(True)
                self.chk_sub.setEnabled(True)
                self.chk_mul.setEnabled(True)
                self.chk_gap.setEnabled(True)
                self.spin_math_count.setEnabled(True)
                self.chk_div.setEnabled(True)

    def _apply_difficulty(self, idx: int):
        for i, btn in enumerate(self._diff_btns):
            btn.setChecked(i == idx)
        preset = self._diff_presets[idx]
        if preset is None:
            return
        self.spin_math_max.setValue(preset["add_max"])
        self.spin_math_q.setValue(preset["q_time"])
        self.spin_math_a.setValue(preset["a_time"])

    def _save_math_session(self):
        data = {
            "add":           self.chk_add.isChecked(),
            "sub":           self.chk_sub.isChecked(),
            "mul":           self.chk_mul.isChecked(),
            "div":           self.chk_div.isChecked(),
            "gap":           self.chk_gap.isChecked(),
            "no_auto":       self.chk_no_auto_answer.isChecked(),
            "sound":         self.chk_math_sound.isChecked(),
            "max":           self.spin_math_max.value(),
            "count":         self.spin_math_count.value(),
            "font":          self.spin_math_font.value(),
            "q_time":        self.spin_math_q.value(),
            "a_time":        self.spin_math_a.value(),
            "bg":            self.combo_math_bg.currentText(),
            "mul_rows":      [i for i, c in enumerate(self.mul_checks) if c.isChecked()],
            "full_mul":      self.chk_full_mul.isChecked(),
            "mul_repeat":    self.spin_mul_repeat.value(),
            "full_div":      self.chk_full_div.isChecked(),
            "div_repeat":    self.spin_div_repeat.value(),
        }
        default = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mathe_session.json")
        path, _ = QFileDialog.getSaveFileName(self, "Mathe-Session speichern", default, "JSON (*.json)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        QMessageBox.information(self, "Gespeichert ✓", f"Session gespeichert:\n{path}")

    def _load_math_session(self):
        path, _ = QFileDialog.getOpenFileName(self, "Mathe-Session laden", "", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "Fehler", str(e))
            return
        self.chk_add.setChecked(d.get("add", True))
        self.chk_sub.setChecked(d.get("sub", True))
        self.chk_mul.setChecked(d.get("mul", True))
        self.chk_div.setChecked(d.get("div", False))
        self.chk_gap.setChecked(d.get("gap", False))
        self.chk_no_auto_answer.setChecked(d.get("no_auto", False))
        self.chk_math_sound.setChecked(d.get("sound", True))
        self.spin_math_max.setValue(d.get("max", 20))
        self.spin_math_count.setValue(d.get("count", 20))
        self.spin_math_font.setValue(d.get("font", 100))
        self.spin_math_q.setValue(d.get("q_time", 3.0))
        self.spin_math_a.setValue(d.get("a_time", 2.0))
        idx = self.combo_math_bg.findText(d.get("bg", "Weiß"))
        if idx >= 0:
            self.combo_math_bg.setCurrentIndex(idx)
        for i, chk in enumerate(self.mul_checks):
            chk.setChecked(i in d.get("mul_rows", list(range(10))))
        self.chk_full_mul.setChecked(d.get("full_mul", False))
        self.spin_mul_repeat.setValue(d.get("mul_repeat", 1))
        self.chk_full_div.setChecked(d.get("full_div", False))
        self.spin_div_repeat.setValue(d.get("div_repeat", 1))
        self._toggle_systematic("mul", Qt.Checked if d.get("full_mul", False) else Qt.Unchecked)
        self._toggle_systematic("div", Qt.Checked if d.get("full_div", False) else Qt.Unchecked)
        self._apply_difficulty(3)
        QMessageBox.information(self, "Geladen ✓", f"Session geladen:\n{path}")

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()