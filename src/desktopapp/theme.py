"""Design tokens and Qt style sheets for the desktop GUI.

A quiet, neutral system: white content, soft grey tiles, graphite primary
actions and a single blue accent reserved for interactive state (focus,
toggles, selection). Widget behaviour lives in the window modules; this file
only describes appearance.
"""
from string import Template
from .paths import ROOT

COLORS = dict(
    # Surfaces
    window='#ffffff', sidebar='#f5f5f7', tile='#f5f5f7', surface='#ffffff', raised='#fbfbfd',
    hover='#f5f5f7', pressed='#ebebef', nav_hover='#ebebef', nav_selected='#e3e3e8',
    # Lines
    separator='#e5e5ea', border='#d2d2d7', strong='#c7c7cc', strong_hover='#aeaeb2',
    # Text
    text='#1d1d1f', muted='#6e6e73', faint='#aeaeb2', nav_text='#1d1d1f',
    log='#f5f5f7', log_text='#3a3a3c',
    # Primary action: graphite, like a camera body
    primary='#1d1d1f', primary_hover='#3a3a3c', primary_pressed='#000000', primary_text='#ffffff',
    primary_disabled='#e3e3e8', primary_disabled_text='#aeaeb2',
    # Accent: interactive state only
    accent='#0071e3', accent_hover='#0077ed', accent_pressed='#006edb', accent_text='#ffffff',
    accent_soft='#e8f1fc', accent_line='#80b8f1', accent_disabled_text='#8ab6e8', selection='#cce2fa',
    # Status
    success='#248a3d', warning='#b25000', warning_soft='#fff5e6', danger='#d70015', danger_soft='#fdecee',
)
ICONS = ROOT / 'src/desktopapp/assets'
FONT = '"Segoe UI Variable Text","Segoe UI","PingFang SC","Microsoft YaHei UI","Microsoft YaHei"'
MONO = '"Cascadia Mono","SF Mono","Consolas","Menlo","Microsoft YaHei UI"'


def asset(name):
    return (ICONS / name).as_posix()


def _sheet(text):
    return Template(text).substitute(
        COLORS, font=FONT, mono=MONO, check=asset('check.svg'), chevron=asset('chevron-down.svg'),
        chevron_up=asset('chevron-up.svg'), switch_on=asset('switch-on.svg'), switch_off=asset('switch-off.svg'),
        switch_on_disabled=asset('switch-on-disabled.svg'), switch_off_disabled=asset('switch-off-disabled.svg'))


_COMMON = '''
QLabel {background:transparent;}
QLabel[hint="true"],QLabel[muted="true"],QLabel[note="true"] {color:$muted;}
QLabel[note="true"] {font-size:12px;}
QLabel[warning="true"] {color:$warning;}
QLabel[callout="true"] {background:$warning_soft;color:#7a3a00;border-radius:10px;padding:10px 14px;}

QPushButton {background:$surface;border:1px solid $border;border-radius:8px;padding:7px 16px;color:$text;min-height:20px;}
QPushButton:hover {background:$hover;border-color:$strong;}
QPushButton:pressed {background:$pressed;}
QPushButton:disabled {background:$surface;color:$faint;border-color:$separator;}
QPushButton[primary="true"] {background:$primary;color:$primary_text;border-color:$primary;font-weight:600;padding:7px 20px;}
QPushButton[primary="true"]:hover {background:$primary_hover;border-color:$primary_hover;}
QPushButton[primary="true"]:pressed {background:$primary_pressed;}
QPushButton[primary="true"]:disabled {background:$primary_disabled;color:$primary_disabled_text;border-color:$primary_disabled;}
QPushButton:focus {outline:none;}

QLineEdit,QSpinBox,QDoubleSpinBox,QComboBox {background:$surface;border:1px solid $border;border-radius:8px;
    padding:6px 10px;min-height:20px;selection-background-color:$selection;selection-color:$text;}
QLineEdit:hover,QComboBox:hover,QSpinBox:hover,QDoubleSpinBox:hover {border-color:$strong;}
QLineEdit:focus,QComboBox:focus,QSpinBox:focus,QDoubleSpinBox:focus,QPlainTextEdit:focus {border:1px solid $accent;}
QLineEdit:disabled,QComboBox:disabled,QSpinBox:disabled,QDoubleSpinBox:disabled {color:$faint;background:$raised;border-color:$separator;}
QLineEdit[readOnly="true"] {background:$raised;}
QComboBox {padding-right:26px;}
QComboBox::drop-down {border:0;width:26px;}
QComboBox::down-arrow {image:url("$chevron");width:10px;height:10px;}
QComboBox QAbstractItemView {background:$surface;border:1px solid $separator;border-radius:8px;padding:4px;color:$text;
    selection-background-color:$accent_soft;selection-color:$text;outline:0;}
QAbstractSpinBox::up-button,QAbstractSpinBox::down-button {border:0;background:transparent;width:18px;}
QAbstractSpinBox::up-button:hover,QAbstractSpinBox::down-button:hover {background:$hover;border-radius:4px;}
QAbstractSpinBox::up-arrow {image:url("$chevron_up");width:9px;height:9px;}
QAbstractSpinBox::down-arrow {image:url("$chevron");width:9px;height:9px;}

QCheckBox {spacing:10px;padding:5px 0;background:transparent;color:$text;}
QCheckBox::indicator {width:38px;height:22px;image:url("$switch_off");}
QCheckBox::indicator:checked {image:url("$switch_on");}
QCheckBox::indicator:disabled {image:url("$switch_off_disabled");}
QCheckBox::indicator:checked:disabled {image:url("$switch_on_disabled");}
QCheckBox:disabled {color:$faint;}

QScrollArea {border:0;background:transparent;}
QScrollArea > QWidget > QWidget {background:transparent;}
QScrollBar:vertical {background:transparent;width:10px;margin:2px;}
QScrollBar::handle:vertical {background:$strong;border-radius:3px;min-height:36px;margin:0 2px;}
QScrollBar::handle:vertical:hover {background:$strong_hover;}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {height:0;}
QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical {background:transparent;}
QScrollBar:horizontal {height:0;}
QToolTip {background:$surface;color:$text;border:1px solid $separator;border-radius:6px;padding:6px 8px;}
'''

WINDOW = _sheet('''
QWidget {font-family:$font;font-size:13px;color:$text;}
QMainWindow,QDialog,QMessageBox {background:$window;}
QWidget#content,QWidget#pageBody {background:$window;}

QFrame#sidebar {background:$sidebar;border:0;border-right:1px solid $separator;}
QLabel#brandName {font-size:15px;font-weight:600;color:$text;}
QLabel#brandDetail {font-size:11px;color:$muted;}
QLabel#sidebarCaption {font-size:11px;color:$muted;}
QFrame#sidebar QComboBox:focus {border-color:$border;}
QFrame#sidebar QComboBox {background:$surface;padding:3px 8px;padding-right:22px;min-height:18px;border-radius:6px;font-size:12px;}
QListWidget#nav {background:transparent;border:0;outline:0;padding:0;}
QListWidget#nav::item {height:34px;padding:0 8px;margin:1px 0;border-radius:8px;color:$nav_text;border:0;}
QListWidget#nav::item:hover {background:$nav_hover;}
QListWidget#nav::item:selected {background:$nav_selected;color:$text;}

QLabel[pageTitle="true"] {font-size:26px;font-weight:600;color:$text;}
QLabel[subtitle="true"] {font-size:13px;color:$muted;}
QLabel[section="true"] {font-size:13px;font-weight:600;color:$text;}

QGroupBox {background:$tile;border:0;border-radius:14px;margin-top:32px;padding:16px 18px 14px;}
QGroupBox::title {subcontrol-origin:margin;subcontrol-position:top left;left:2px;top:6px;padding:0;
    color:$text;font-size:13px;font-weight:600;background:transparent;}
QGroupBox[optional="true"] {background:transparent;padding:6px 0 0;margin-top:30px;}
QGroupBox[optional="true"]::title {left:0;spacing:10px;}
QGroupBox::indicator {width:38px;height:22px;image:url("$switch_off");}
QGroupBox::indicator:checked {image:url("$switch_on");}
QFrame[card="true"] {background:$tile;border:0;border-radius:14px;}
QFrame[card="true"] QLabel,QGroupBox QLabel,QGroupBox QCheckBox {background:transparent;}
QFrame[subpanel="true"] {background:$surface;border:0;border-radius:12px;}
QRadioButton {background:transparent;color:$text;spacing:7px;padding:3px 0;}
QRadioButton::indicator {width:16px;height:16px;border:1px solid $border;border-radius:9px;background:$surface;}
QRadioButton::indicator:checked {width:8px;height:8px;border:5px solid $accent;}
QRadioButton:disabled {color:$faint;}

QToolButton {background:transparent;border:0;color:$muted;padding:4px 2px;}
QToolButton:hover,QToolButton:checked {color:$text;}
QToolButton[disclosure="true"] {font-weight:600;padding:6px 0;}
QToolButton#voiceCleanupHelp {background:$tile;border-radius:10px;min-width:20px;max-width:20px;min-height:20px;max-height:20px;padding:0;color:$muted;font-weight:600;}
QToolButton#voiceCleanupHelp:hover {background:$nav_selected;color:$text;}

QFrame#footer {background:$window;border:0;border-top:1px solid $separator;}
QLabel#statusText {color:$text;font-size:12px;}
QLabel#statusDot {border-radius:4px;min-width:8px;max-width:8px;min-height:8px;max-height:8px;background:$faint;}
QLabel#statusDot[state="running"] {background:$accent;}
QLabel#statusDot[state="success"] {background:$success;}
QLabel#statusDot[state="error"] {background:$danger;}
QFrame#footer QPushButton {padding:4px 12px;font-size:12px;min-height:18px;}
QFrame#footer QToolButton {font-size:12px;padding:4px 8px;border-radius:6px;}
QFrame#footer QToolButton:hover,QFrame#footer QToolButton:checked {background:$tile;color:$text;}
QProgressBar {border:0;background:transparent;max-height:2px;min-height:2px;}
QProgressBar::chunk {background:$accent;}
QPlainTextEdit {background:$log;color:$log_text;border:0;border-radius:10px;padding:8px 10px;
    font-family:$mono;font-size:11px;selection-background-color:$selection;}

*[segmented="true"] {background:$nav_selected;border-radius:9px;}
*[segmented="true"] QCheckBox {padding:5px 14px;border-radius:7px;color:$muted;spacing:0;}
*[segmented="true"] QCheckBox::indicator {width:0;height:0;image:none;}
*[segmented="true"] QCheckBox:checked {background:$surface;color:$text;font-weight:600;}
*[segmented="true"] QCheckBox:hover:!checked {color:$text;}
*[segmented="true"] QCheckBox:disabled {color:$faint;}

QTextBrowser {background:$surface;border:1px solid $separator;border-radius:10px;padding:6px;}
''' + _COMMON)

EDITOR = _sheet('''
QWidget {font-family:$font;font-size:13px;color:$text;}
QLabel[title="true"] {font-size:26px;font-weight:600;color:$text;}
QLabel[badge="true"] {background:$accent_soft;color:$accent;border-radius:6px;padding:4px 10px;}
QFrame[card="true"] {background:$tile;border:0;border-radius:14px;}
QFrame[card="true"] QLabel {background:transparent;}
QWidget#operationDetails,QStackedWidget#operationStack {background:transparent;}
''' + _COMMON + '''
QComboBox::down-arrow {image:none;}
QPushButton[quiet="true"] {background:transparent;border:0;color:$muted;padding:6px 10px;}
QPushButton[quiet="true"]:hover {background:$danger_soft;color:$danger;}
''')
