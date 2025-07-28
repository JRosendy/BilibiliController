import ctypes
import logging
import re
import sys
import threading
import time

from PyQt5.QtCore import Qt, QPoint
from PyQt5.QtGui import QFont, QIcon
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLineEdit, QPushButton,
                             QLabel, QTextEdit, QGridLayout)
from ppadb.client import Client
from pynput import keyboard as pynput_keyboard

# 设置日志
logging.basicConfig(filename='bilibili_controller.log', level=logging.INFO,
                    format='%(asctime)s: %(message)s')

# 用于模拟 Scan Code 级别的按键输入
PUL = ctypes.POINTER(ctypes.c_ulong)


class KeyBdInput(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort),
                ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", PUL)]


class Input_I(ctypes.Union):
    _fields_ = [("ki", KeyBdInput)]


class Input(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong),
                ("ii", Input_I)]


SendInput = ctypes.windll.user32.SendInput

scan_codes = {
    'v': 0x2F,
    'left': 0x4B,
    'right': 0x4D
}


def press_scancode(sc):
    ii = Input_I()
    ii.ki = KeyBdInput(0, sc, 0x0008, 0, ctypes.pointer(ctypes.c_ulong(0)))
    inp = Input(1, ii)
    SendInput(1, ctypes.pointer(inp), ctypes.sizeof(inp))


def release_scancode(sc):
    ii = Input_I()
    ii.ki = KeyBdInput(0, sc, 0x0008 | 0x0002, 0, ctypes.pointer(ctypes.c_ulong(0)))
    inp = Input(1, ii)
    SendInput(1, ctypes.pointer(inp), ctypes.sizeof(inp))


def tap_key(sc):
    press_scancode(sc)
    time.sleep(0.05)
    release_scancode(sc)


class BilibiliController(QMainWindow):
    def __init__(self):
        super().__init__()
        # Remove default title bar
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setWindowTitle("BilibiliController")
        self.setGeometry(100, 100, 1200, 800)
        self.setStyleSheet("background-color: #1a1a1a; color: #FFFFFF;")
        self.oldPos = None

        self.key_map = {
            'play_pause': 'v',
            'rewind': 'left',
            'fast_forward': 'right'
        }
        self.listening = False
        self.listener = None
        self.device = None
        self.tap_x, self.tap_y = 960, 540
        self.progress_y = 960
        self.last_action_time = 0
        self.debounce_interval = 0.5
        self.long_press_event = threading.Event()
        self.long_press_thread = None

        self.init_ui()
        self.connect_adb()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.title_bar.underMouse():
            self.oldPos = event.globalPos()

    def mouseMoveEvent(self, event):
        if not self.oldPos:
            return
        delta = QPoint(event.globalPos() - self.oldPos)
        self.move(self.x() + delta.x(), self.y() + delta.y())
        self.oldPos = event.globalPos()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.oldPos = None

    def connect_adb(self):
        try:
            adb = Client(host='127.0.0.1', port=5037)
            devices = adb.devices()
            if not devices:
                self.log("未找到设备，请检查 ADB 连接")
                self.status_label.setText("未连接设备")
                self.status_icon.setStyleSheet("color: #666666; font-size: 14px;")
                return
            self.device = devices[0]
            self.log(f"已连接设备：{self.device.serial}")
            self.status_label.setText(f"已连接 {self.device.serial}")
            self.status_icon.setStyleSheet("color: #4EC9B0; font-size: 14px;")

            output = self.device.shell("wm size")
            match = re.search(r'Physical size: (\d+)x(\d+)', output)
            if match:
                width, height = map(int, match.groups())

                # 横屏适配修复：若为竖屏手机则交换宽高
                if width < height:
                    width, height = height, width

                self.tap_x, self.tap_y = width // 2, height // 2
                self.progress_y = int(height * 0.9)
                self.log(f"屏幕分辨率：{width}x{height}，点击坐标：({self.tap_x}, {self.tap_y})")
        except Exception as e:
            self.log(f"ADB 连接失败：{e}")
            self.status_label.setText("ADB 连接失败")
            self.status_icon.setStyleSheet("color: #CC3333; font-size: 14px;")

        if self.device:
            try:
                self.device.shell("am start -n tv.danmaku.bili/.ui.splash.SplashActivity")
                time.sleep(1)
                self.log("已启动 Bilibili 应用")
            except Exception as e:
                self.log(f"启动 Bilibili 失败：{e}")

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Custom title bar with increased height and rounded corners
        self.title_bar = QWidget()
        self.title_bar.setFixedHeight(60)
        self.title_bar.setStyleSheet("""
            QWidget {
                background-color: #1C1C1C;
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
            }
        """)
        title_bar_layout = QHBoxLayout(self.title_bar)
        title_bar_layout.setContentsMargins(10, 0, 10, 0)
        title_bar_layout.setSpacing(5)

        # Custom icon on the far left
        icon_label = QLabel()
        icon_label.setPixmap(QIcon("icon.png").pixmap(32, 32))  # Replace "icon.png" with your icon file path
        title_bar_layout.addWidget(icon_label)

        # Title label
        title_label = QLabel("BilibiliController")
        title_label.setFont(QFont("Microsoft YaHei UI", 14, QFont.Bold))
        title_label.setStyleSheet("color: #FFFFFF;")
        title_bar_layout.addWidget(title_label)
        title_bar_layout.addStretch()

        # Minimize button
        minimize_button = QPushButton("−")
        minimize_button.setFixedSize(40, 40)
        minimize_button.setStyleSheet("""
            QPushButton {
                background-color: #1C1C1C;
                color: #FFFFFF;
                border: none;
                font-size: 28px;
                border-radius: 20px;
            }
            QPushButton:hover {
                background-color: #666666;
            }
            QPushButton:pressed {
                background-color: #444444;
            }
        """)
        minimize_button.clicked.connect(self.showMinimized)
        title_bar_layout.addWidget(minimize_button)

        # Close button
        close_button = QPushButton("×")
        close_button.setFixedSize(40, 40)
        close_button.setStyleSheet("""
            QPushButton {
                background-color: #1C1C1C;
                color: #FFFFFF;
                border: none;
                font-size: 28px;
                border-radius: 20px;
            }
            QPushButton:hover {
                background-color: #CC3333;
            }
            QPushButton:pressed {
                background-color: #AA2222;
            }
        """)
        close_button.clicked.connect(self.close)
        title_bar_layout.addWidget(close_button)

        main_layout.addWidget(self.title_bar)

        # Main content
        content_widget = QWidget()
        content_layout = QHBoxLayout(content_widget)
        content_layout.setContentsMargins(20, 20, 20, 20)

        # Left panel (35% width)
        left_widget = QWidget()
        left_widget.setStyleSheet("background-color: #242424; border-radius: 10px;")
        left_widget.setMaximumWidth(500)
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(25, 25, 25, 25)
        left_layout.setSpacing(30)

        font = QFont("Microsoft YaHei UI")
        font.setPointSize(11)

        # Title
        content_title_label = QLabel("一键遥控视频进度")
        content_title_label.setFont(QFont("Microsoft YaHei UI", 16, QFont.Bold))
        content_title_label.setStyleSheet("color: #FFFFFF; padding: 10px 0;")
        left_layout.addWidget(content_title_label)

        # Status section
        status_container = QWidget()
        status_layout = QHBoxLayout(status_container)
        status_layout.setContentsMargins(0, 0, 0, 0)

        self.status_icon = QLabel("●")
        self.status_icon.setStyleSheet("color: #666666; font-size: 14px;")
        status_layout.addWidget(self.status_icon)

        self.status_label = QLabel("未连接设备")
        self.status_label.setFont(font)
        self.status_label.setStyleSheet("color: #999999; padding-left: 5px;")
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()

        left_layout.addWidget(status_container)

        # Key bindings section
        bindings_label = QLabel("按键绑定")
        bindings_label.setFont(QFont("Microsoft YaHei UI", 13))
        bindings_label.setStyleSheet("color: #CCCCCC; padding-top: 10px;")
        left_layout.addWidget(bindings_label)

        # Key binding inputs
        bindings_container = QWidget()
        bindings_layout = QGridLayout(bindings_container)
        bindings_layout.setSpacing(20)
        bindings_layout.setHorizontalSpacing(10)

        input_style = """
            QLineEdit {
                background-color: #333333;
                color: #FFFFFF;
                border: 1px solid #444444;
                padding: 10px;
                border-radius: 6px;
                font-size: 18px;
                font-weight: 500;
            }
            QLineEdit:focus {
                border: 1px solid #666666;
                background-color: #3a3a3a;
            }
        """

        # Play/Pause
        play_label = QLabel("播放/暂停")
        play_label.setFont(font)
        play_label.setStyleSheet("color: #999999; min-width: 80px;")
        bindings_layout.addWidget(play_label, 0, 0)

        self.play_pause_input = QLineEdit(self.key_map['play_pause'])
        self.play_pause_input.setFont(font)
        self.play_pause_input.setStyleSheet(input_style)
        self.play_pause_input.setMaximumWidth(80)
        self.play_pause_input.setAlignment(Qt.AlignCenter)
        self.play_pause_input.textChanged.connect(
            lambda: self.update_key_binding('play_pause', self.play_pause_input.text()))
        bindings_layout.addWidget(self.play_pause_input, 0, 1)

        # Rewind
        rewind_label = QLabel("快退")
        rewind_label.setFont(font)
        rewind_label.setStyleSheet("color: #999999; min-width: 80px;")
        bindings_layout.addWidget(rewind_label, 1, 0)

        self.rewind_input = QLineEdit(self.key_map['rewind'])
        self.rewind_input.setFont(font)
        self.rewind_input.setStyleSheet(input_style)
        self.rewind_input.setMaximumWidth(80)
        self.rewind_input.setAlignment(Qt.AlignCenter)
        self.rewind_input.textChanged.connect(lambda: self.update_key_binding('rewind', self.rewind_input.text()))
        bindings_layout.addWidget(self.rewind_input, 1, 1)

        # Fast Forward
        forward_label = QLabel("快进")
        forward_label.setFont(font)
        forward_label.setStyleSheet("color: #999999; min-width: 80px;")
        bindings_layout.addWidget(forward_label, 2, 0)

        self.fast_forward_input = QLineEdit(self.key_map['fast_forward'])
        self.fast_forward_input.setFont(font)
        self.fast_forward_input.setStyleSheet(input_style)
        self.fast_forward_input.setMaximumWidth(80)
        self.fast_forward_input.setAlignment(Qt.AlignCenter)
        self.fast_forward_input.textChanged.connect(
            lambda: self.update_key_binding('fast_forward', self.fast_forward_input.text()))
        bindings_layout.addWidget(self.fast_forward_input, 2, 1)

        left_layout.addWidget(bindings_container)
        left_layout.addStretch()

        # Start button
        self.toggle_button = QPushButton("Link Start!")
        self.toggle_button.setFont(QFont("Microsoft YaHei UI", 12))
        self.toggle_button.setStyleSheet("""
            QPushButton {
                background-color: #333333;
                color: #CCCCCC;
                padding: 12px 24px;
                border: 1px solid #444444;
                border-radius: 6px;
                min-height: 45px;
            }
            QPushButton:hover {
                background-color: #3a3a3a;
                border: 1px solid #555555;
            }
            QPushButton:pressed {
                background-color: #2a2a2a;
            }
        """)
        self.toggle_button.clicked.connect(self.toggle_listening)
        left_layout.addWidget(self.toggle_button)

        # Right panel (70% width) - Log area
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.log_area = QTextEdit()
        self.log_area.setFont(QFont("Consolas", 10))
        self.log_area.setReadOnly(True)
        self.log_area.setStyleSheet("""
            QTextEdit {
                background-color: #1a1a1a;
                color: #CCCCCC;
                border: none;
                padding: 10px;
            }
        """)
        right_layout.addWidget(self.log_area)

        # Copyright label
        copyright_label = QLabel("made by JRosend")
        copyright_label.setFont(QFont("Arial", 9))
        copyright_label.setStyleSheet("color: #444444; padding: 5px;")
        copyright_label.setAlignment(Qt.AlignRight)
        right_layout.addWidget(copyright_label)

        # Combine layouts with 3:7 ratio
        content_layout.addWidget(left_widget)
        content_layout.addWidget(right_widget)
        content_layout.setStretch(0, 3)
        content_layout.setStretch(1, 6)

        main_layout.addWidget(content_widget)

    def log(self, message):
        timestamp = time.strftime("%H:%M:%S", time.localtime())
        if hasattr(self, 'log_area'):
            self.log_area.append(f"{timestamp}  {message}")
        logging.info(message)

    def update_key_binding(self, action, key):
        if key:
            if key.lower() not in scan_codes and not key.isalnum():
                self.log(f"无效按键：{key}（{action}），请使用有效键名")
                return
            self.key_map[action] = key.lower()
            self.log(f"更新 {action} 按键绑定为：{key}")
            if self.listening:
                self.toggle_listening()
                self.toggle_listening()

    def double_tap(self):
        if self.device:
            try:
                self.device.shell(f"input tap {self.tap_x} {self.tap_y}")
                time.sleep(0.15)
                self.device.shell(f"input tap {self.tap_x} {self.tap_y}")
                self.log("执行播放/暂停")
            except Exception as e:
                self.log(f"双击失败：{e}")

    def send_keyevent(self, keycode):
        if self.device:
            try:
                self.device.shell(f"input keyevent {keycode}")
                self.device.shell(f"input keyevent {keycode}")
                self.log(f"发送键码 {keycode}")
            except Exception as e:
                self.log(f"发送键码失败：{e}")

    def send_swipe(self, x1, x2, y, duration):
        if self.device:
            try:
                self.device.shell(f"input tap {self.tap_x} {self.progress_y}")
                time.sleep(0.1)
                self.device.shell(f"input swipe {x1} {y} {x2} {y} {duration}")
            except Exception as e:
                self.log(f"滑动失败：{e}")

    def long_press_loop(self, key_name):
        action = "快退" if key_name == self.key_map['rewind'] else "快进"
        x_start = self.tap_x + 20 if key_name == self.key_map['rewind'] else self.tap_x - 20
        x_end = self.tap_x - 20 if key_name == self.key_map['rewind'] else self.tap_x + 20
        self.log(f"开始{action}长按")
        while not self.long_press_event.is_set() and self.listening:
            threading.Thread(target=self.send_swipe, args=(x_start, x_end, self.progress_y, 200), daemon=True).start()
            time.sleep(0.2)
        self.log(f"停止{action}长按")

    def on_key_press(self, key):
        current_time = time.time()
        if current_time - self.last_action_time < self.debounce_interval:
            return

        try:
            key_name = key.char.lower() if hasattr(key, 'char') and key.char else str(key).replace('Key.', '')
            if key_name == self.key_map['play_pause']:
                self.last_action_time = current_time
                threading.Thread(target=self.double_tap, daemon=True).start()
            elif key_name in (self.key_map['rewind'], self.key_map['fast_forward']):
                self.last_action_time = current_time
                if not self.long_press_event.is_set():
                    self.long_press_event.clear()
                    self.long_press_thread = threading.Thread(
                        target=self.long_press_loop, args=(key_name,), daemon=True
                    )
                    self.long_press_thread.start()
                else:
                    keycode = 21 if key_name == self.key_map['rewind'] else 22
                    action = "快退" if key_name == self.key_map['rewind'] else "快进"
                    threading.Thread(target=self.send_keyevent, args=(keycode,), daemon=True).start()
                    self.log(f"执行{action}")
        except Exception as e:
            self.log(f"按键处理错误：{e}")

    def on_key_release(self, key):
        try:
            key_name = key.char.lower() if hasattr(key, 'char') and key.char else str(key).replace('Key.', '')
            if key_name in (self.key_map['rewind'], self.key_map['fast_forward']):
                self.long_press_event.set()
                self.long_press_thread = None
        except Exception as e:
            self.log(f"释放按键错误：{e}")

    def toggle_listening(self):
        if self.listening:
            if self.listener:
                self.listener.stop()
            self.listening = False
            self.toggle_button.setText("Link Start!")
            self.toggle_button.setStyleSheet("""
                QPushButton {
                    background-color: #333333;
                    color: #CCCCCC;
                    padding: 12px 24px;
                    border: 1px solid #444444;
                    border-radius: 6px;
                    min-height: 45px;
                }
                QPushButton:hover {
                    background-color: #3a3a3a;
                    border: 1px solid #555555;
                }
                QPushButton:pressed {
                    background-color: #2a2a2a;
                }
            """)
            self.long_press_event.set()
            self.log("已停止监听")
        else:
            self.listener = pynput_keyboard.Listener(on_press=self.on_key_press, on_release=self.on_key_release)
            self.listener.start()
            self.listening = True
            self.toggle_button.setText("暂停")
            self.toggle_button.setStyleSheet("""
                QPushButton {
                    background-color: #4a4a4a;
                    color: #FFFFFF;
                    padding: 12px 24px;
                    border: 1px solid #666666;
                    border-radius: 6px;
                    min-height: 45px;
                }
                QPushButton:hover {
                    background-color: #555555;
                    border: 1px solid #777777;
                }
                QPushButton:pressed {
                    background-color: #3a3a3a;
                }
            """)
            self.log("已启动监听")


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = BilibiliController()
    window.show()
    sys.exit(app.exec_())