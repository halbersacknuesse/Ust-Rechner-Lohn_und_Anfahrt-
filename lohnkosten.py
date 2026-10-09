#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lohnkosten-Rechner - Textbaustein für nach § 35a EStG begünstigte Kosten

Berechnet aus Arbeitsleistung, Anfahrtspauschale und Verbrauchsmaterial den
Satz für die Rechnung und legt ihn in die Zwischenablage.

Alle Beträge werden mit Decimal gerechnet und kaufmännisch auf Cent gerundet
(halbe Cent aufwärts, ROUND_HALF_UP). Funktionsgleich mit lohnkosten.html.

Start:  python3 lohnkosten.py
"""

import json
import math
import os
import shutil
import subprocess
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

try:
    from PySide6.QtCore import QLocale, Qt, QTimer, Signal
    from PySide6.QtGui import (QColor, QFont, QGuiApplication, QKeySequence,
                               QPainter, QPen, QShortcut)
    from PySide6.QtWidgets import (
        QApplication, QButtonGroup, QCheckBox, QDoubleSpinBox, QFrame,
        QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
        QListWidgetItem, QPushButton, QScrollArea, QSizePolicy, QSlider,
        QStyle, QStyleOptionSlider, QTabWidget, QVBoxLayout, QWidget,
    )
except ModuleNotFoundError:
    sys.exit(
        "PySide6 fehlt.\n\n"
        "Fedora:  sudo dnf install python3-pyside6\n"
        "oder:    pip install --user PySide6\n"
    )

# ==========================================================================
# Konfiguration
# ==========================================================================

# Betragsformat im Rechnungstext. "{}€" -> 137,45€   |   "{} €" -> 137,45 €
CURRENCY = "{}€"

# Der Rechnungsbaustein. {brutto} = begünstigte Kosten brutto, {ust} = USt darin
TEMPLATE = ("Im Rechnungsbetrag sind Arbeits- und Fahrtkosten von {brutto} brutto "
            "enthalten, die Sie nach § 35a EStG steuerlich geltend machen können.\n"
            "Die darin enthaltene Umsatzsteuer beträgt {ust}.")


def dec_range(start, stop, step):
    """Liste von Decimal-Werten, Grenzen einschließlich."""
    values, value = [], Decimal(start)
    stop, step = Decimal(stop), Decimal(step)
    while value <= stop:
        values.append(value)
        value += step
    return values


# Stundensatz-Skala: fein dort, wo abgerechnet wird, grob nach oben.
RATE_STOPS = (dec_range("40", "70", "1")
              + dec_range("72", "80", "2")
              + dec_range("85", "100", "5"))
RATE_LABELS = ["40", "80", "100"]       # Rastpunkte kommen aus den Einstellungen
RATE_SNAP_STEPS = 2

# Zeit-Skala: viertelstundengenau im häufigen Bereich, dann gröber.
HOUR_STOPS = (dec_range("0.5", "3", "0.25")
              + dec_range("3.5", "6", "0.5")
              + dec_range("7", "10", "1"))
HOUR_SNAPS = [Decimal("1"), Decimal("1.5"), Decimal("2"), Decimal("2.5")]
HOUR_PRESETS = [Decimal("0.5"), Decimal("1"), Decimal("1.5"), Decimal("2")]
HOUR_LABELS = ["0.5", "1", "1.5", "2", "2.5", "3", "6", "10"]
HOUR_SNAP_STEPS = 1
HOUR_DEFAULT = Decimal("1")
HOUR_STEP = Decimal("0.5")

TAX_PRESETS = [Decimal("0"), Decimal("7"), Decimal("19")]
TAX_DEFAULT = Decimal("19")

# Voreinstellungen, im Einstellungsreiter änderbar. Beispielwerte.
CFG_DEFAULT = {
    "rate_a": "55", "label_a": "Hausverwaltung",
    "rate_b": "65", "label_b": "Privatkunde",
    "trips": [
        ["ohne Anfahrt", "0"],
        ["bis 5 km", "20"],
        ["bis 10 km", "25"],
        ["bis 20 km", "35"],
        ["bis 40 km", "55"],
        ["bis 50 km", "65"],
        ["bis 60 km", "75"],
        ["bis 70 km", "85"],
        ["bis 80 km", "95"],
        ["bis 90 km", "105"],
        ["bis 100 km", "115"],
        ["bis 150 km", "175"],
        ["bis 200 km", "230"],
    ],
}

AUTO_COPY_DELAY = 450          # ms Ruhe vor dem automatischen Kopieren
HISTORY_MAX = 60
TRIP_COLUMNS = 3

# ==========================================================================

INK      = "#16212b"
INK_SOFT = "#5d6b7a"
LINE     = "#dfe4ea"
PAPER    = "#ffffff"
DESK     = "#eef1f4"
ACCENT   = "#0f6b5c"
ACCENT_D = "#0b4f44"
ACCENT_L = "#e6f1ee"
AMBER    = "#b4761f"

CENT = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    """Kaufmännisch auf Cent runden: halbe Cent immer aufwärts."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    d = Path(base) / "lohnkosten"
    d.mkdir(parents=True, exist_ok=True)
    return d


HISTORY_FILE = data_dir() / "verlauf.json"
CONFIG_FILE = data_dir() / "einstellungen.json"


def fmt_num(value: Decimal) -> str:
    """Decimal('1234.5') -> '1.234,50'"""
    s = f"{money(value):,.2f}"
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def fmt_eur(value: Decimal) -> str:
    return CURRENCY.format(fmt_num(value))


def fmt_plain(value: Decimal) -> str:
    """Decimal('1.00') -> '1'   Decimal('0.25') -> '0,25'"""
    return format(value.normalize(), "f").replace(".", ",") or "0"


def parse_decimal(text):
    text = str(text).strip().replace("€", "").replace(" ", "").replace(",", ".")
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def nearest_index(stops, value: Decimal) -> int:
    return min(range(len(stops)), key=lambda i: abs(stops[i] - value))


def to_clipboard(text: str) -> None:
    """In die Zwischenablage legen - über wl-copy/xclip auch dauerhaft,
    wenn das Fenster danach geschlossen wird."""
    QGuiApplication.clipboard().setText(text)
    for cmd in (["wl-copy"],
                ["xclip", "-selection", "clipboard"],
                ["xsel", "--clipboard", "--input"]):
        if shutil.which(cmd[0]):
            try:
                p = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                     stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL,
                                     start_new_session=True)
                p.stdin.write(text.encode("utf-8"))
                p.stdin.close()
            except OSError:
                pass
            break


def clear_layout(layout):
    """Alle Kinder eines Layouts entfernen, auch verschachtelte."""
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            clear_layout(item.layout())


# --------------------------------------------------------------------------
# Bausteine
# --------------------------------------------------------------------------

class Card(QFrame):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(16, 12, 16, 14)
        self.box.setSpacing(8)
        if title:
            head = QLabel(title)
            head.setObjectName("CardTitle")
            self.box.addWidget(head)

    def add(self, item):
        if isinstance(item, QWidget):
            self.box.addWidget(item)
        else:
            self.box.addLayout(item)
        return item


class Chip(QPushButton):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("Chip")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)


class TripButton(QPushButton):
    """Eine Stufe der Anfahrtsstaffel: Bezeichnung über Betrag."""

    def __init__(self, label: str, amount: Decimal, parent=None):
        super().__init__(f"{label}\n{fmt_eur(amount)}", parent)
        self.setObjectName("Trip")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.amount = amount


class ScaleBar(QWidget):
    """Beschriftete Skala unter einem Slider. Die Position jedes Strichs wird
    beim Slider selbst erfragt, damit Skala und Griff übereinander liegen -
    die Skala ist absichtlich nicht gleichmäßig geteilt, und der Griff hat an
    den Rändern eine halbe Griffbreite Spiel."""

    def __init__(self, slider: QSlider, stops, labels, marks, parent=None):
        super().__init__(parent)
        self.slider = slider
        self.stops = stops
        self.labels = sorted(Decimal(v) for v in labels)
        self.marks = [Decimal(m) for m in marks]
        self.setFixedHeight(21)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_marks(self, marks):
        """Rastpunkte setzen; sie werden zugleich beschriftet."""
        self.marks = [Decimal(m) for m in marks]
        labels = {str(v) for v in self.labels} | {str(m) for m in self.marks}
        self.labels = sorted(Decimal(v) for v in labels)
        self.update()

    def x_for(self, value: Decimal) -> float:
        index = nearest_index(self.stops, value)
        slider = self.slider
        opt = QStyleOptionSlider()
        opt.initFrom(slider)
        opt.orientation = Qt.Horizontal
        opt.minimum, opt.maximum = slider.minimum(), slider.maximum()
        opt.sliderPosition = opt.sliderValue = index
        style = slider.style()
        groove = style.subControlRect(QStyle.CC_Slider, opt,
                                      QStyle.SC_SliderGroove, slider)
        handle = style.subControlRect(QStyle.CC_Slider, opt,
                                      QStyle.SC_SliderHandle, slider)
        span = groove.width() - handle.width()
        if span <= 0:
            return self.width() / 2
        pos = QStyle.sliderPositionFromValue(
            slider.minimum(), slider.maximum(), index, span)
        return groove.x() + pos + handle.width() / 2

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        font = QFont(self.font())
        font.setPointSizeF(max(font.pointSizeF() - 2.0, 7.0))
        p.setFont(font)
        fm = p.fontMetrics()
        marked = {nearest_index(self.stops, m) for m in self.marks}

        for value in self.labels:
            x = self.x_for(value)
            on = nearest_index(self.stops, value) in marked
            p.setPen(QPen(QColor(ACCENT if on else "#aab4be"), 2 if on else 1))
            p.drawLine(int(x), 1, int(x), 6 if on else 4)
            text = fmt_plain(value)
            w = fm.horizontalAdvance(text)
            tx = min(max(x - w / 2, 0), self.width() - w)
            p.setPen(QColor(ACCENT if on else INK_SOFT))
            p.drawText(int(tx), 7 + fm.ascent(), text)
        p.end()


class HoursSpinBox(QDoubleSpinBox):
    """Zeigt 1 statt 1,00 und springt mit den Pfeilen auf die nächste halbe
    Stunde - auch aus krummen Werten heraus (2,75 -> 3)."""

    def textFromValue(self, value: float) -> str:
        return fmt_plain(Decimal(f"{value:.2f}"))

    def valueFromText(self, text: str) -> float:
        parsed = parse_decimal(text.replace("h", ""))
        return float(parsed) if parsed is not None else self.value()

    def stepBy(self, steps: int):
        if steps == 0:
            return
        step = float(HOUR_STEP)
        value = self.value()
        base = (math.floor(value / step + 1e-9) if steps > 0
                else math.ceil(value / step - 1e-9))
        self.setValue((base + steps) * step)


def money_box(suffix=" €", width=120, maximum=99999.0) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setLocale(QLocale(QLocale.German, QLocale.Germany))
    box.setRange(0, maximum)
    box.setDecimals(2)
    box.setSingleStep(1)
    box.setSuffix(suffix)
    box.setFixedWidth(width)
    box.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return box


# --------------------------------------------------------------------------

class Rechner(QWidget):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self._guard = False
        self._ready = False          # kein Auto-Kopieren beim Programmstart
        self.cfg = self.load_config()
        self.rate = parse_decimal(self.cfg["rate_a"]) or Decimal("55")
        self.hours = HOUR_DEFAULT
        self.tax = TAX_DEFAULT
        self.trip = Decimal(0)
        self.material = Decimal(0)
        self.net_override = None
        self.history = []

        self.setWindowTitle("Lohnkosten & Umsatzsteuer")
        self.setMinimumSize(560, 540)
        self.resize(640, 900)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        head = QHBoxLayout()
        title = QLabel("Lohnkosten für die Rechnung")
        title.setObjectName("Title")
        head.addWidget(title)
        head.addStretch(1)
        reset = QPushButton("Standardwerte")
        reset.setObjectName("Quiet")
        reset.setCursor(Qt.PointingHandCursor)
        reset.clicked.connect(lambda: self.apply_defaults())
        head.addWidget(reset)
        root.addLayout(head)

        tabs = QTabWidget()
        tabs.addTab(self._scroll(self._page_calc()), "Rechnen")
        tabs.addTab(self._scroll(self._page_config()), "Einstellungen")
        root.addWidget(tabs, 1)

        self.changed.connect(self.recalc)
        self.changed.connect(self.schedule_auto_copy)

        self.auto_timer = QTimer(self)
        self.auto_timer.setSingleShot(True)
        self.auto_timer.timeout.connect(lambda: self.copy_current(auto=True))

        for key in (Qt.Key_Return, Qt.Key_Enter):
            QShortcut(QKeySequence(key), self,
                      activated=lambda: self.copy_current())
        QShortcut(QKeySequence(Qt.Key_Escape), self,
                  activated=lambda: self.apply_defaults())

        self.load_history()
        self.apply_defaults()
        self._ready = True

    # --------------------------------------------------------------- Aufbau

    @staticmethod
    def _scroll(page: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidget(page)
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        return area

    def _page_calc(self) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(2, 4, 2, 4)
        box.setSpacing(10)
        box.addWidget(self._card_work())
        box.addWidget(self._card_trip())
        box.addWidget(self._card_material())
        box.addWidget(self._card_tax())
        box.addWidget(self._card_result())
        box.addWidget(self._card_history(), 1)
        return page

    def _page_config(self) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(2, 4, 2, 4)
        box.setSpacing(10)

        rates = Card("Stundensätze")
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        self.cfg_label_a = QLineEdit(self.cfg["label_a"])
        self.cfg_label_b = QLineEdit(self.cfg["label_b"])
        self.cfg_rate_a = money_box(" €/h")
        self.cfg_rate_b = money_box(" €/h")
        for row, (label, rate) in enumerate(((self.cfg_label_a, self.cfg_rate_a),
                                             (self.cfg_label_b, self.cfg_rate_b))):
            label.setPlaceholderText("Bezeichnung")
            grid.addWidget(label, row, 0)
            grid.addWidget(rate, row, 1)
        grid.setColumnStretch(0, 1)
        self.cfg_rate_a.setValue(float(parse_decimal(self.cfg["rate_a"]) or 0))
        self.cfg_rate_b.setValue(float(parse_decimal(self.cfg["rate_b"]) or 0))
        for widget in (self.cfg_label_a, self.cfg_label_b):
            widget.textEdited.connect(lambda _: self.on_config_rates())
        for widget in (self.cfg_rate_a, self.cfg_rate_b):
            widget.valueChanged.connect(lambda _: self.on_config_rates())
        rates.add(grid)
        hint = QLabel("Beide Sätze erscheinen als Schaltfläche und als Rastpunkt "
                      "auf dem Regler.")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        hint.setMinimumHeight(18)
        rates.add(hint)
        box.addWidget(rates)

        trips = Card("Anfahrtspauschalen (netto)")
        self.cfg_trip_box = QVBoxLayout()
        self.cfg_trip_box.setSpacing(6)
        trips.add(self.cfg_trip_box)
        row = QHBoxLayout()
        add = QPushButton("+ Stufe hinzufügen")
        add.setObjectName("Link")
        add.setCursor(Qt.PointingHandCursor)
        add.clicked.connect(lambda: self.add_trip_row())
        row.addWidget(add)
        row.addStretch(1)
        back = QPushButton("auf Auslieferungszustand zurücksetzen")
        back.setObjectName("Quiet")
        back.setCursor(Qt.PointingHandCursor)
        back.clicked.connect(lambda: self.reset_config())
        row.addWidget(back)
        trips.add(row)
        note = QLabel("Reihenfolge wie eingetragen. Eine Stufe ohne Bezeichnung "
                      "wird übersprungen. Änderungen gelten sofort und werden "
                      "gespeichert.")
        note.setObjectName("Hint")
        note.setWordWrap(True)
        note.setMinimumHeight(34)
        trips.add(note)
        box.addWidget(trips)
        box.addStretch(1)
        self.build_trip_rows()
        return page

    def _card_work(self) -> Card:
        card = Card("Arbeitsleistung")

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(2)
        self.rate_slider = QSlider(Qt.Horizontal)
        self.rate_slider.setRange(0, len(RATE_STOPS) - 1)
        self.rate_slider.setPageStep(3)
        self.rate_slider.valueChanged.connect(self.on_rate_slider)
        self.rate_slider.sliderMoved.connect(self.on_rate_drag)
        self.rate_slider.sliderReleased.connect(self.copy_after_drag)
        self.rate_scale = ScaleBar(self.rate_slider, RATE_STOPS, RATE_LABELS, [])
        grid.addWidget(self.rate_slider, 0, 0)
        grid.addWidget(self.rate_scale, 1, 0)
        grid.setColumnStretch(0, 1)
        self.rate_spin = money_box(" €/h", 124)
        self.rate_spin.valueChanged.connect(self.on_rate_spin)
        grid.addWidget(self.rate_spin, 0, 1)
        card.add(grid)

        self.rate_chip_row = QHBoxLayout()
        self.rate_chip_row.setSpacing(8)
        self.rate_chips = []
        card.add(self.rate_chip_row)

        grid2 = QGridLayout()
        grid2.setContentsMargins(0, 10, 0, 0)
        grid2.setHorizontalSpacing(12)
        grid2.setVerticalSpacing(2)
        self.hours_slider = QSlider(Qt.Horizontal)
        self.hours_slider.setRange(0, len(HOUR_STOPS) - 1)
        self.hours_slider.setPageStep(2)
        self.hours_slider.valueChanged.connect(self.on_hours_slider)
        self.hours_slider.sliderMoved.connect(self.on_hours_drag)
        self.hours_slider.sliderReleased.connect(self.copy_after_drag)
        grid2.addWidget(self.hours_slider, 0, 0)
        grid2.addWidget(ScaleBar(self.hours_slider, HOUR_STOPS,
                                 HOUR_LABELS, HOUR_SNAPS), 1, 0)
        grid2.setColumnStretch(0, 1)
        self.hours_spin = HoursSpinBox()
        self.hours_spin.setLocale(QLocale(QLocale.German, QLocale.Germany))
        self.hours_spin.setRange(0.25, 99)
        self.hours_spin.setDecimals(2)
        self.hours_spin.setSingleStep(float(HOUR_STEP))
        self.hours_spin.setSuffix(" h")
        self.hours_spin.setFixedWidth(124)
        self.hours_spin.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.hours_spin.setToolTip("Pfeile springen in halben Stunden.\n"
                                   "Eigene Zeiten wie 2,75 direkt eintippen.")
        self.hours_spin.valueChanged.connect(self.on_hours_spin)
        grid2.addWidget(self.hours_spin, 0, 1)
        card.add(grid2)

        chips = QHBoxLayout()
        chips.setSpacing(8)
        self.hour_chips = []
        for value in HOUR_PRESETS:
            chip = Chip(f"{fmt_plain(value)} h")
            chip.clicked.connect(lambda _, v=value: self.set_hours(v))
            self.hour_chips.append((value, chip))
            chips.addWidget(chip)
        chips.addStretch(1)
        card.add(chips)

        net_row = QHBoxLayout()
        net_row.setContentsMargins(0, 10, 0, 0)
        label = QLabel("Nettolohn (überschreibbar für Festpreise)")
        label.setObjectName("RowLabel")
        net_row.addWidget(label, 1)
        self.net_spin = money_box(" €", 124)
        self.net_spin.valueChanged.connect(self.on_net_spin)
        net_row.addWidget(self.net_spin)
        card.add(net_row)

        self.net_note = QWidget()
        note_row = QHBoxLayout(self.net_note)
        note_row.setContentsMargins(0, 0, 0, 0)
        note = QLabel("Festpreis gesetzt – Stundensatz und Zeit sind entkoppelt.")
        note.setObjectName("Warn")
        note_row.addWidget(note)
        back = QPushButton("zurück zur Berechnung")
        back.setObjectName("Link")
        back.setCursor(Qt.PointingHandCursor)
        back.clicked.connect(lambda: self.clear_override())
        note_row.addWidget(back)
        note_row.addStretch(1)
        self.net_note.hide()
        card.add(self.net_note)
        return card

    def _card_trip(self) -> Card:
        card = Card("Anfahrt (netto)")
        self.trip_grid = QGridLayout()
        self.trip_grid.setSpacing(8)
        card.add(self.trip_grid)
        self.trip_group = QButtonGroup(self)
        self.trip_group.setExclusive(True)
        return card

    def _card_material(self) -> Card:
        card = Card("Verbrauchsmaterial (netto)")
        row = QHBoxLayout()
        label = QLabel("Reiniger, Schmier- und Silikonspray, Tücher – "
                       "ohne verbautes Material")
        label.setObjectName("RowLabel")
        label.setWordWrap(True)
        label.setMinimumHeight(18)
        row.addWidget(label, 1)
        self.material_spin = money_box(" €", 124)
        self.material_spin.valueChanged.connect(self.on_material_spin)
        row.addWidget(self.material_spin)
        card.add(row)
        return card

    def _card_tax(self) -> Card:
        card = Card("Umsatzsteuer")
        row = QHBoxLayout()
        row.setSpacing(8)
        self.tax_group = QButtonGroup(self)
        self.tax_group.setExclusive(True)
        self.tax_chips = []
        for value in TAX_PRESETS:
            chip = Chip(f"{fmt_plain(value)} %")
            chip.clicked.connect(lambda _, v=value: self.set_tax(v, custom=False))
            self.tax_group.addButton(chip)
            self.tax_chips.append((value, chip))
            row.addWidget(chip)
        self.tax_custom_chip = Chip("eigener")
        self.tax_custom_chip.clicked.connect(
            lambda: self.set_tax(Decimal(f"{self.tax_spin.value():.1f}"), True))
        self.tax_group.addButton(self.tax_custom_chip)
        row.addWidget(self.tax_custom_chip)

        self.tax_spin = QDoubleSpinBox()
        self.tax_spin.setLocale(QLocale(QLocale.German, QLocale.Germany))
        self.tax_spin.setRange(0, 99.9)
        self.tax_spin.setDecimals(1)
        self.tax_spin.setSuffix(" %")
        self.tax_spin.setValue(float(TAX_DEFAULT))
        self.tax_spin.setFixedWidth(96)
        self.tax_spin.setEnabled(False)
        self.tax_spin.valueChanged.connect(self.on_tax_spin)
        row.addWidget(self.tax_spin)
        row.addStretch(1)
        card.add(row)
        return card

    def _card_result(self) -> Card:
        card = Card("Ergebnis")
        self.lines = QGridLayout()
        self.lines.setHorizontalSpacing(14)
        self.lines.setVerticalSpacing(4)
        card.add(self.lines)

        self.preview = QLabel()
        self.preview.setObjectName("Preview")
        self.preview.setWordWrap(True)
        self.preview.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.preview.setMinimumHeight(92)
        self.preview.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        card.add(self.preview)

        note = QLabel("Auf Cent kaufmännisch gerundet · Enter kopiert · "
                      "Esc setzt zurück")
        note.setObjectName("Hint")
        note.setWordWrap(True)
        note.setMinimumHeight(18)
        card.add(note)

        row = QHBoxLayout()
        self.copy_btn = QPushButton("Text kopieren")
        self.copy_btn.setObjectName("Primary")
        self.copy_btn.setCursor(Qt.PointingHandCursor)
        self.copy_btn.clicked.connect(lambda: self.copy_current())
        row.addWidget(self.copy_btn)
        self.flash = QLabel("")
        self.flash.setObjectName("Flash")
        row.addWidget(self.flash, 1)
        self.auto_chk = QCheckBox("bei jeder Änderung")
        self.auto_chk.setObjectName("Auto")
        self.auto_chk.setChecked(True)
        self.auto_chk.setCursor(Qt.PointingHandCursor)
        self.auto_chk.setToolTip(
            "Legt den Text automatisch in die Zwischenablage.\n"
            "In den Verlauf kommt nur, was du über den Button\n"
            "oder mit Enter kopierst.")
        row.addWidget(self.auto_chk)
        card.add(row)

        self.flash_timer = QTimer(self)
        self.flash_timer.setSingleShot(True)
        self.flash_timer.timeout.connect(lambda: self.flash.setText(""))
        return card

    def _card_history(self) -> Card:
        card = Card("Bisherige Berechnungen")
        hint = QLabel("Über \"Text kopieren\" gemerkt · Eintrag anklicken, "
                      "um ihn erneut zu kopieren")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        hint.setMinimumHeight(18)
        card.add(hint)

        self.list = QListWidget()
        self.list.setObjectName("History")
        self.list.setWordWrap(True)
        self.list.setCursor(Qt.PointingHandCursor)
        self.list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.list.setMinimumHeight(110)
        self.list.itemClicked.connect(self.on_history_click)
        card.add(self.list)

        row = QHBoxLayout()
        row.addStretch(1)
        clear = QPushButton("Verlauf leeren")
        clear.setObjectName("Quiet")
        clear.setCursor(Qt.PointingHandCursor)
        clear.clicked.connect(lambda: self.clear_history())
        row.addWidget(clear)
        card.add(row)
        return card

    # -------------------------------------------------------- Einstellungen

    def load_config(self) -> dict:
        cfg = json.loads(json.dumps(CFG_DEFAULT))
        try:
            raw = json.loads(CONFIG_FILE.read_text("utf-8"))
        except (OSError, ValueError):
            return cfg
        if not isinstance(raw, dict):
            return cfg
        for key in ("label_a", "label_b"):
            if isinstance(raw.get(key), str):
                cfg[key] = raw[key]
        for key in ("rate_a", "rate_b"):
            if parse_decimal(raw.get(key, "")) is not None:
                cfg[key] = str(raw[key])
        trips = raw.get("trips")
        if isinstance(trips, list):
            clean = [[str(entry[0]), str(entry[1])] for entry in trips
                     if isinstance(entry, (list, tuple)) and len(entry) == 2
                     and parse_decimal(entry[1]) is not None]
            if clean:
                cfg["trips"] = clean
        return cfg

    def save_config(self):
        try:
            CONFIG_FILE.write_text(
                json.dumps(self.cfg, ensure_ascii=False, indent=1), "utf-8")
        except OSError:
            pass

    def rate_presets(self):
        return [(parse_decimal(self.cfg["rate_a"]) or Decimal(0), self.cfg["label_a"]),
                (parse_decimal(self.cfg["rate_b"]) or Decimal(0), self.cfg["label_b"])]

    def on_config_rates(self):
        if self._guard:
            return
        self.cfg["label_a"] = self.cfg_label_a.text()
        self.cfg["label_b"] = self.cfg_label_b.text()
        self.cfg["rate_a"] = f"{self.cfg_rate_a.value():.2f}"
        self.cfg["rate_b"] = f"{self.cfg_rate_b.value():.2f}"
        self.save_config()
        self.build_rate_chips()

    def build_rate_chips(self):
        clear_layout(self.rate_chip_row)
        self.rate_chips = []
        for value, label in self.rate_presets():
            shown = fmt_num(value).replace(",00", "")
            chip = Chip(f"{shown} €  ·  {label}" if label else f"{shown} €")
            chip.clicked.connect(lambda _, v=value: self.set_rate(v))
            chip.setChecked(value == self.rate)
            self.rate_chips.append((value, chip))
            self.rate_chip_row.addWidget(chip)
        self.rate_chip_row.addStretch(1)
        self.rate_scale.set_marks([v for v, _ in self.rate_presets()])

    def trip_entries(self):
        return [(label, parse_decimal(amount) or Decimal(0))
                for label, amount in self.cfg["trips"] if str(label).strip()]

    def build_trip_buttons(self):
        for button in list(self.trip_group.buttons()):
            self.trip_group.removeButton(button)
        clear_layout(self.trip_grid)
        for index, (label, amount) in enumerate(self.trip_entries()):
            button = TripButton(label, amount)
            button.clicked.connect(lambda _, a=amount: self.set_trip(a))
            self.trip_group.addButton(button)
            self.trip_grid.addWidget(button, index // TRIP_COLUMNS,
                                     index % TRIP_COLUMNS)
        self.sync_trip_buttons()

    def sync_trip_buttons(self):
        taken = False
        for button in self.trip_group.buttons():
            on = (not taken) and button.amount == self.trip
            button.setChecked(on)
            taken = taken or on

    def build_trip_rows(self):
        clear_layout(self.cfg_trip_box)
        for index, (label, amount) in enumerate(self.cfg["trips"]):
            row = QWidget()
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(8)
            edit = QLineEdit(label)
            edit.setPlaceholderText("Bezeichnung, z. B. bis 25 km")
            edit.textEdited.connect(
                lambda text, i=index: self.on_trip_label(i, text))
            spin = money_box(" €", 112)
            spin.setValue(float(parse_decimal(amount) or 0))
            spin.valueChanged.connect(
                lambda value, i=index: self.on_trip_amount(i, value))
            remove = QPushButton("✕")
            remove.setObjectName("Delete")
            remove.setFixedWidth(34)
            remove.setCursor(Qt.PointingHandCursor)
            remove.setToolTip("Stufe entfernen")
            remove.clicked.connect(lambda _, i=index: self.remove_trip_row(i))
            line.addWidget(edit, 1)
            line.addWidget(spin)
            line.addWidget(remove)
            self.cfg_trip_box.addWidget(row)

    def on_trip_label(self, index: int, text: str):
        if 0 <= index < len(self.cfg["trips"]):
            self.cfg["trips"][index][0] = text
            self.save_config()
            self.build_trip_buttons()

    def on_trip_amount(self, index: int, value: float):
        if self._guard or not (0 <= index < len(self.cfg["trips"])):
            return
        self.cfg["trips"][index][1] = f"{value:.2f}"
        self.save_config()
        self.build_trip_buttons()

    def add_trip_row(self):
        self.cfg["trips"].append(["neue Stufe", "0"])
        self.save_config()
        self.build_trip_rows()
        self.build_trip_buttons()

    def remove_trip_row(self, index: int):
        if 0 <= index < len(self.cfg["trips"]):
            del self.cfg["trips"][index]
            self.save_config()
            self.build_trip_rows()
            self.build_trip_buttons()

    def reset_config(self):
        self.cfg = json.loads(json.dumps(CFG_DEFAULT))
        self.save_config()
        self._guard = True
        self.cfg_label_a.setText(self.cfg["label_a"])
        self.cfg_label_b.setText(self.cfg["label_b"])
        self.cfg_rate_a.setValue(float(parse_decimal(self.cfg["rate_a"]) or 0))
        self.cfg_rate_b.setValue(float(parse_decimal(self.cfg["rate_b"]) or 0))
        self._guard = False
        self.build_trip_rows()
        self.build_trip_buttons()
        self.build_rate_chips()

    # ------------------------------------------------------------- Eingaben

    def snap(self, stops, snaps, index: int, tolerance: int) -> int:
        best, distance = index, tolerance + 1
        for value in snaps:
            target = nearest_index(stops, value)
            if abs(index - target) < distance:
                best, distance = target, abs(index - target)
        return best if distance <= tolerance else index

    def on_rate_drag(self, index: int):
        target = self.snap(RATE_STOPS, [v for v, _ in self.rate_presets()],
                           index, RATE_SNAP_STEPS)
        if target != index:
            self.rate_slider.setValue(target)

    def on_rate_slider(self, index: int):
        if self._guard:
            return
        self.set_rate(RATE_STOPS[index], from_slider=True)

    def on_rate_spin(self, value: float):
        if self._guard:
            return
        self.set_rate(Decimal(f"{value:.2f}"), from_spin=True)

    def set_rate(self, value: Decimal, from_slider=False, from_spin=False):
        self.rate = value
        self.net_override = None
        self._guard = True
        if not from_slider:
            self.rate_slider.setValue(nearest_index(RATE_STOPS, value))
        if not from_spin:
            self.rate_spin.setValue(float(value))
        self._guard = False
        for preset, chip in self.rate_chips:
            chip.setChecked(value == preset)
        self.changed.emit()

    def on_hours_drag(self, index: int):
        target = self.snap(HOUR_STOPS, HOUR_SNAPS, index, HOUR_SNAP_STEPS)
        if target != index:
            self.hours_slider.setValue(target)

    def on_hours_slider(self, index: int):
        if self._guard:
            return
        self.set_hours(HOUR_STOPS[index], from_slider=True)

    def on_hours_spin(self, value: float):
        if self._guard:
            return
        self.set_hours(Decimal(f"{value:.2f}"), from_spin=True)

    def set_hours(self, value: Decimal, from_slider=False, from_spin=False):
        self.hours = value
        self.net_override = None
        self._guard = True
        if not from_slider:
            self.hours_slider.setValue(nearest_index(HOUR_STOPS, value))
        if not from_spin:
            self.hours_spin.setValue(float(value))
        self._guard = False
        for preset, chip in self.hour_chips:
            chip.setChecked(value == preset)
        self.changed.emit()

    def on_net_spin(self, value: float):
        if self._guard:
            return
        self.net_override = money(Decimal(f"{value:.2f}"))
        self.changed.emit()

    def clear_override(self):
        self.net_override = None
        self.changed.emit()

    def set_trip(self, amount: Decimal):
        self.trip = amount
        self.sync_trip_buttons()
        self.changed.emit()

    def on_material_spin(self, value: float):
        if self._guard:
            return
        self.material = money(Decimal(f"{value:.2f}"))
        self.changed.emit()

    def on_tax_spin(self, value: float):
        if self._guard:
            return
        self.set_tax(Decimal(f"{value:.1f}"), custom=True)

    def set_tax(self, value: Decimal, custom: bool):
        self.tax = value
        self.tax_spin.setEnabled(custom)
        if custom:
            self.tax_custom_chip.setChecked(True)
        self.changed.emit()

    def apply_defaults(self):
        self._guard = True
        self.material = Decimal(0)
        self.material_spin.setValue(0.0)
        self._guard = False
        self.net_override = None
        self.build_rate_chips()
        self.build_trip_buttons()
        entries = self.trip_entries()
        self.set_trip(entries[0][1] if entries else Decimal(0))
        self.set_rate(parse_decimal(self.cfg["rate_a"]) or Decimal(0))
        self.set_hours(HOUR_DEFAULT)
        self.set_tax(TAX_DEFAULT, custom=TAX_DEFAULT not in TAX_PRESETS)
        for value, chip in self.tax_chips:
            chip.setChecked(value == TAX_DEFAULT)

    # -------------------------------------------------------------- Rechnen

    def amounts(self):
        """Arbeitsleistung, Anfahrt und Material ergeben den Nettobetrag; die
        Umsatzsteuer wird daraus kaufmännisch gerundet, der Bruttobetrag ist
        die exakte Summe. So ergibt brutto - USt immer wieder netto."""
        lohn = (self.net_override if self.net_override is not None
                else money(self.hours * self.rate))
        net = lohn + self.trip + self.material
        ust = money(net * self.tax / Decimal(100))
        return lohn, net, ust, net + ust

    def current_text(self) -> str:
        _, _, ust, brutto = self.amounts()
        return TEMPLATE.format(brutto=fmt_eur(brutto), ust=fmt_eur(ust))

    def recalc(self):
        lohn, net, ust, brutto = self.amounts()
        custom = self.net_override is not None
        self.net_note.setVisible(custom)
        self._guard = True
        if not self.net_spin.hasFocus():
            self.net_spin.setValue(float(lohn))
        self._guard = False

        rows = [("Arbeitsleistung (Festpreis)" if custom else
                 f"Arbeitsleistung · {fmt_plain(self.hours)} h × "
                 f"{fmt_num(self.rate)} €", lohn, False)]
        if self.trip:
            rows.append(("Anfahrt", self.trip, False))
        if self.material:
            rows.append(("Verbrauchsmaterial", self.material, False))
        if len(rows) > 1:
            rows.append(("Summe netto", net, False))
        rows.append((f"Umsatzsteuer {fmt_plain(self.tax)} %", ust, False))
        rows.append(("Begünstigt brutto", brutto, True))

        clear_layout(self.lines)
        for row, (name, value, strong) in enumerate(rows):
            label = QLabel(name)
            label.setObjectName("RowLabel")
            amount = QLabel(fmt_eur(value))
            amount.setObjectName("RowValueStrong" if strong else "RowValue")
            amount.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.lines.addWidget(label, row, 0)
            self.lines.addWidget(amount, row, 1)
        self.lines.setColumnStretch(0, 1)
        self.preview.setText(self.current_text())

    # ------------------------------------------------------------- Kopieren

    def schedule_auto_copy(self):
        """Nach jeder Änderung kopieren - aber erst, wenn der Regler
        losgelassen ist und kurz Ruhe war."""
        if not self._ready or not self.auto_chk.isChecked():
            return
        if self.rate_slider.isSliderDown() or self.hours_slider.isSliderDown():
            return
        self.auto_timer.start(AUTO_COPY_DELAY)

    def copy_after_drag(self):
        if self._ready and self.auto_chk.isChecked():
            self.auto_timer.start(120)

    def copy_current(self, auto: bool = False):
        """auto=True kommt vom Regler oder Timer: nur Zwischenablage.
        Nur eine bewusste Kopie (Button oder Enter) landet im Verlauf."""
        self.auto_timer.stop()
        lohn, net, _, _ = self.amounts()
        text = self.current_text()
        to_clipboard(text)
        self.flash.setText("Kopiert" if auto else "Kopiert und gemerkt")
        self.flash_timer.start(2200)
        if not auto:
            self.add_history(lohn, net, text)

    # -------------------------------------------------------------- Verlauf

    def add_history(self, lohn: Decimal, net: Decimal, text: str):
        entry = {"netto": str(net), "lohn": str(lohn), "fahrt": str(self.trip),
                 "material": str(self.material), "text": text,
                 "zeit": datetime.now().isoformat(timespec="seconds")}
        top = self.history[0] if self.history else None
        if top is not None and top.get("text") == text \
                and top.get("netto") == entry["netto"]:
            self.history[0] = entry      # dieselbe Berechnung, nicht doppeln
        else:
            self.history.insert(0, entry)
        del self.history[HISTORY_MAX:]
        self.render_history()
        self.save_history()

    def render_history(self):
        self.list.clear()
        for entry in self.history:
            net = parse_decimal(entry.get("netto", "0")) or Decimal(0)
            lohn = parse_decimal(entry.get("lohn", "0")) or Decimal(0)
            fahrt = parse_decimal(entry.get("fahrt", "0")) or Decimal(0)
            material = parse_decimal(entry.get("material", "0")) or Decimal(0)
            parts = [f"Lohn {fmt_num(lohn)}"]
            if fahrt:
                parts.append(f"Anfahrt {fmt_num(fahrt)}")
            if material:
                parts.append(f"Material {fmt_num(material)}")
            item = QListWidgetItem(
                f"{fmt_eur(net)} netto · {' · '.join(parts)}\n"
                f"{entry.get('text', '')}")
            item.setData(Qt.UserRole, entry.get("text", ""))
            try:
                stamp = datetime.fromisoformat(entry.get("zeit", ""))
                item.setToolTip(stamp.strftime("%d.%m.%Y, %H:%M Uhr"))
            except ValueError:
                pass
            self.list.addItem(item)

    def on_history_click(self, item: QListWidgetItem):
        to_clipboard(item.data(Qt.UserRole))
        self.flash.setText("Kopiert")
        self.flash_timer.start(2200)

    def clear_history(self):
        self.history = []
        self.render_history()
        self.save_history()

    def load_history(self):
        try:
            data = json.loads(HISTORY_FILE.read_text("utf-8"))
            self.history = [e for e in data if isinstance(e, dict)][:HISTORY_MAX]
        except (OSError, ValueError):
            self.history = []
        self.render_history()

    def save_history(self):
        try:
            HISTORY_FILE.write_text(
                json.dumps(self.history, ensure_ascii=False, indent=1), "utf-8")
        except OSError:
            pass


STYLE = f"""
QWidget {{ background: {DESK}; color: {INK}; font-size: 14px; }}
QLabel#Title {{ font-size: 21px; font-weight: 600; letter-spacing: -0.2px; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{
    background: {PAPER}; color: {INK_SOFT}; border: 1px solid {LINE};
    padding: 9px 20px; margin-right: 4px; border-radius: 9px; font-weight: 600;
}}
QTabBar::tab:selected {{ background: {ACCENT}; color: #ffffff; border-color: {ACCENT}; }}
QScrollArea {{ background: {DESK}; border: none; }}
QFrame#Card {{ background: {PAPER}; border: 1px solid {LINE}; border-radius: 12px; }}
QFrame#Card QLabel, QFrame#Card QListWidget {{ background: transparent; }}
QLabel#CardTitle {{ color: {INK_SOFT}; font-size: 12px; font-weight: 600; }}
QLabel#Hint {{ color: {INK_SOFT}; font-size: 12px; }}
QLabel#Warn {{ color: {AMBER}; font-size: 12px; }}
QLabel#RowLabel {{ color: {INK_SOFT}; }}
QLabel#RowValue {{ font-size: 15px; }}
QLabel#RowValueStrong {{ font-size: 19px; font-weight: 600; color: {ACCENT_D}; }}
QLabel#Preview {{
    background: {ACCENT_L}; border: 1px solid #cfe2dd; border-radius: 9px;
    padding: 10px 12px; margin-top: 2px;
}}
QLabel#Flash {{ color: {ACCENT}; font-size: 12px; padding-left: 10px; }}
QCheckBox#Auto {{ color: {INK_SOFT}; font-size: 12px; spacing: 6px; }}
QCheckBox#Auto::indicator {{
    width: 15px; height: 15px; border: 1px solid #c3ccd4;
    border-radius: 4px; background: {PAPER};
}}
QCheckBox#Auto::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

QSlider::groove:horizontal {{ height: 6px; background: #e2e7ec; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 3px; }}
QSlider::handle:horizontal {{
    background: {PAPER}; border: 3px solid {ACCENT};
    width: 15px; height: 15px; margin: -7px 0; border-radius: 10px;
}}
QSlider::handle:horizontal:hover {{ border-color: {ACCENT_D}; }}

QPushButton#Chip {{
    background: {PAPER}; border: 1px solid {LINE}; border-radius: 15px;
    padding: 6px 13px; color: {INK_SOFT};
}}
QPushButton#Chip:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}
QPushButton#Chip:checked {{ background: {ACCENT}; border-color: {ACCENT}; color: #ffffff; }}
QPushButton#Trip {{
    background: {PAPER}; border: 1px solid {LINE}; border-radius: 10px;
    padding: 8px 10px; color: {INK}; text-align: left; min-height: 42px;
}}
QPushButton#Trip:hover {{ border-color: {ACCENT}; }}
QPushButton#Trip:checked {{ background: {ACCENT}; border-color: {ACCENT}; color: #ffffff; }}
QPushButton#Primary {{
    background: {ACCENT}; color: #ffffff; border: none; border-radius: 9px;
    padding: 11px 20px; font-weight: 600;
}}
QPushButton#Primary:hover {{ background: {ACCENT_D}; }}
QPushButton#Primary:pressed {{ background: #093a32; }}
QPushButton#Quiet {{
    background: transparent; border: none; color: {INK_SOFT};
    font-size: 12px; padding: 4px 2px;
}}
QPushButton#Quiet:hover {{ color: {AMBER}; }}
QPushButton#Link {{
    background: transparent; border: none; color: {ACCENT};
    font-size: 12px; text-decoration: underline; padding: 0 4px;
}}
QPushButton#Delete {{
    background: transparent; border: none; color: {INK_SOFT}; font-size: 15px;
}}
QPushButton#Delete:hover {{ color: #c0392b; }}

QDoubleSpinBox, QLineEdit {{
    background: {PAPER}; border: 1px solid {LINE}; border-radius: 8px;
    padding: 7px 9px; selection-background-color: {ACCENT};
}}
QDoubleSpinBox:focus, QLineEdit:focus {{ border-color: {ACCENT}; }}
QDoubleSpinBox:disabled {{ color: #a8b2bc; background: #f6f8f9; }}

QListWidget#History {{
    border: 1px solid {LINE}; border-radius: 9px; padding: 3px; outline: none;
}}
QListWidget#History::item {{ padding: 9px 10px; border-radius: 6px; color: #33414f; }}
QListWidget#History::item:hover {{ background: {ACCENT_L}; }}
QListWidget#History::item:selected {{ background: #d7e8e3; color: {ACCENT_D}; }}

QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #c6ced6; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #9fabb6; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
"""


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Lohnkosten")
    app.setStyleSheet(STYLE)
    window = Rechner()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
