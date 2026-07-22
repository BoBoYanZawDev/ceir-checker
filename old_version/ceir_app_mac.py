import sys
import os
import json
import csv
import hashlib
import base64
import time
import threading
import subprocess
import platform
from datetime import datetime
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QTabWidget, QTextEdit, QLineEdit, QPushButton, QLabel,
                             QTableWidget, QTableWidgetItem, QHeaderView, QSplitter,
                             QGroupBox, QFormLayout, QSpinBox, QFileDialog, QProgressBar,
                             QMessageBox, QPlainTextEdit)
from PyQt6.QtCore import Qt, QUrl, QTimer, pyqtSignal, pyqtSlot, QObject
from PyQt6.QtGui import QFont, QColor
from PyQt6.QtWebEngineWidgets import QWebEngineView

CEIR_BASE = 'https://www.ceir.gov.mm'
CEIR_ALTCHA_URL = f'{CEIR_BASE}/openapi/API/Auth/altcha/altcha'
CEIR_VERIFY_URL = f'{CEIR_BASE}/openapi/API/IMEI/Verify'
CONFIG_FILE = 'auto_ceir_config.json'

def solve_altcha(challenge_data):
    challenge = challenge_data['challenge']
    salt = challenge_data['salt']
    maxnumber = challenge_data.get('maxnumber', 1000000)
    signature = challenge_data['signature']
    algorithm = challenge_data.get('algorithm', 'SHA-256')
    start = time.time()
    for number in range(maxnumber + 1):
        if hashlib.sha256((salt + str(number)).encode()).hexdigest() == challenge:
            took = int((time.time() - start) * 1000)
            token = {'algorithm': algorithm, 'challenge': challenge, 'number': number, 'salt': salt, 'signature': signature, 'took': took}
            return (base64.b64encode(json.dumps(token).encode()).decode(), took)
    return (None, 0)

def load_config():
    default = {'router_ip': '192.168.1.1', 'adb_port': 5555, 'imeis_per_sim': 20, 'network_wait_sec': 10, 'reboot_wait_sec': 15, 'ceir_check_delay_sec': 2, 'batch_size': 5}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                default.update(json.load(f))
        except Exception:
            pass
    return default

def save_config(cfg):
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass

class JSExecutor(QObject):
    """Runs JavaScript on QWebEnginePage from any thread, returns result synchronously."""
    request_signal = pyqtSignal(str, str)
    def __init__(self, page):
        super().__init__()
        self._page = page
        self._results = {}
        self._events = {}
        self.request_signal.connect(self._execute_on_main_thread)
    @pyqtSlot(str, str)
    def _execute_on_main_thread(self, js_code, request_id):
        def callback(result):
            self._results[request_id] = result
            evt = self._events.get(request_id)
            if evt:
                evt.set()
        self._page.runJavaScript(js_code, callback)
    def run(self, js_code, timeout=20):
        request_id = f'req_{time.time()}_{threading.current_thread().ident}'
        evt = threading.Event()
        self._events[request_id] = evt
        self._results[request_id] = None
        self.request_signal.emit(js_code, request_id)
        evt.wait(timeout=timeout)
        result = self._results.pop(request_id, None)
        self._events.pop(request_id, None)
        return result

class CEIRApp(QMainWindow):
    log_signal = pyqtSignal(str, str)
    result_signal = pyqtSignal(dict)
    progress_signal = pyqtSignal(int, int)
    done_signal = pyqtSignal()
    pause_signal = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self._pc_name = platform.node() or 'Unknown'
        self._base_title = f'CEIR Auto IMEI Tool — {self._pc_name}'
        self.setWindowTitle(self._base_title)
        self.setMinimumSize(1100, 750)
        self.cfg = load_config()
        self.is_running = False
        self.stop_requested = False
        self._paused = False
        self.is_dark_mode = True
        self.results = []
        self.cf_verified = False
        self._alarm_active = False
        self._alarm_timer = QTimer()
        self._alarm_timer.setInterval(500)
        self._alarm_flash_on = False
        self._alarm_timer.timeout.connect(self._flash_title)
        self.log_signal.connect(self._add_log)
        self.result_signal.connect(self._add_result)
        self.progress_signal.connect(self._update_progress)
        self.done_signal.connect(self._on_done)
        self.pause_signal.connect(self._on_pause)
        self._build_ui()
        self._apply_dark_theme()
        QTimer.singleShot(1000, self._init_js_executor)

    def _init_js_executor(self):
        self.js = JSExecutor(self.browser.page())

    def _toggle_theme(self):
        self.is_dark_mode = not self.is_dark_mode
        if self.is_dark_mode:
            self.theme_btn.setText('☀️ Light Mode')
            self._apply_dark_theme()
        else:
            self.theme_btn.setText('🌙 Dark Mode')
            self._apply_light_theme()

    def _apply_dark_theme(self):
        self.setStyleSheet('''
            QMainWindow, QWidget { background-color: #111111; color: #EFEFEF; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
            QTabWidget::pane { border: 1px solid #282828; background: #161616; border-radius: 10px; }
            QTabBar::tab { background: #111111; color: #888888; padding: 10px 20px; border: none; border-bottom: 2px solid transparent; margin-right: 8px; font-weight: 500; font-size: 13px; border-top-left-radius: 6px; border-top-right-radius: 6px; }
            QTabBar::tab:selected { color: #EFEFEF; border-bottom: 2px solid #5E5CE6; }
            QTabBar::tab:hover:!selected { color: #BBBBBB; }
            QGroupBox { border: 1px solid #282828; background: #161616; border-radius: 10px; margin-top: 18px; padding-top: 22px; font-weight: 600; color: #EFEFEF; font-size: 13px; }
            QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 2px 8px; background: #111111; border-radius: 4px; left: 12px; top: 0px; }
            QLineEdit, QSpinBox, QPlainTextEdit, QTextEdit { background: #1A1A1A; border: 1px solid #282828; border-radius: 8px; padding: 10px; color: #EFEFEF; font-family: 'SF Mono', 'ui-monospace', monospace; font-size: 13px; selection-background-color: #5E5CE6; selection-color: #FFFFFF; }
            QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus { border: 1px solid #5E5CE6; background: #1F1F1F; }
            QPushButton { background: #232323; border: 1px solid #333333; border-radius: 8px; padding: 8px 16px; color: #EFEFEF; font-weight: 500; font-size: 13px; }
            QPushButton:hover { background: #2A2A2A; border: 1px solid #444444; }
            QPushButton:pressed { background: #333333; }
            QPushButton:disabled { color: #555555; background: #1A1A1A; border: 1px solid #222222; }
            QPushButton#startBtn { background: #30D158; color: #111111; border: none; font-size: 14px; font-weight: 600; }
            QPushButton#startBtn:hover { background: #34E05E; }
            QPushButton#stopBtn { background: #FF453A; color: #FFFFFF; border: none; font-size: 14px; font-weight: 600; }
            QPushButton#stopBtn:hover { background: #FF554B; }
            QPushButton#resumeBtn { background: #FF9F0A; color: #111111; border: none; font-weight: 600; }
            QPushButton#cfBtn { background: #5E5CE6; color: #FFFFFF; border: none; font-weight: 600; }
            QPushButton#testBtn { background: #BF5AF2; color: #FFFFFF; border: none; font-weight: 600; }
            QTableWidget { background: #161616; border: 1px solid #282828; border-radius: 8px; gridline-color: #282828; color: #EFEFEF; }
            QHeaderView::section { background: #1A1A1A; color: #888888; border: none; border-bottom: 1px solid #282828; border-right: 1px solid #282828; padding: 10px 8px; font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; }
            QHeaderView { background: #161616; border: none; }
            QProgressBar { border: none; border-radius: 4px; background: #282828; height: 6px; }
            QProgressBar::chunk { background: #5E5CE6; border-radius: 4px; }
            QLabel { color: #BBBBBB; }
            QSplitter::handle { background: #282828; width: 4px; border-radius: 2px; }
            QTableWidget { alternate-background-color: #1A1A1A; }
            QScrollBar:vertical { border: none; background: #161616; width: 10px; border-radius: 5px; margin: 0px; }
            QScrollBar::handle:vertical { background: #333333; min-height: 20px; border-radius: 5px; }
            QScrollBar::handle:vertical:hover { background: #444444; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { border: none; background: none; }
        ''')

    def _apply_light_theme(self):
        self.setStyleSheet('''
            QMainWindow, QWidget { background-color: #F7F9FC; color: #111827; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }
            QTabWidget::pane { border: 1px solid #E5E7EB; background: #FFFFFF; border-radius: 8px; }
            QTabBar::tab { background: #F3F4F6; color: #6B7280; padding: 10px 24px; border: 1px solid #E5E7EB; border-bottom: none; margin-right: 4px; font-weight: 600; font-size: 13px; border-top-left-radius: 6px; border-top-right-radius: 6px; }
            QTabBar::tab:selected { color: #4F46E5; background: #FFFFFF; border-top: 3px solid #4F46E5; }
            QTabBar::tab:hover:!selected { background: #E5E7EB; color: #374151; }
            QGroupBox { border: 1px solid #E5E7EB; background: #FFFFFF; border-radius: 8px; margin-top: 18px; padding-top: 22px; font-weight: bold; color: #111827; font-size: 14px; }
            QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 2px 8px; background: #E5E7EB; border-radius: 4px; left: 12px; top: 0px; }
            QLineEdit, QSpinBox, QPlainTextEdit, QTextEdit { background: #FFFFFF; border: 1px solid #D1D5DB; border-radius: 6px; padding: 10px; color: #111827; font-family: 'SF Mono', 'ui-monospace', 'Cascadia Code', monospace; font-size: 13px; selection-background-color: #C7D2FE; selection-color: #111827; }
            QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus { border: 1px solid #6366F1; background: #FDFEFE; }
            QPushButton { background: #FFFFFF; border: 1px solid #D1D5DB; border-radius: 6px; padding: 8px 16px; color: #374151; font-weight: 600; font-size: 13px; }
            QPushButton:hover { background: #F9FAFB; border: 1px solid #9CA3AF; }
            QPushButton:pressed { background: #E5E7EB; }
            QPushButton:disabled { color: #9CA3AF; background: #F3F4F6; border: 1px solid #E5E7EB; }
            QPushButton#startBtn { background: #10B981; color: #FFFFFF; border: none; font-size: 14px; font-weight: bold; }
            QPushButton#startBtn:hover { background: #059669; }
            QPushButton#stopBtn { background: #EF4444; color: #FFFFFF; border: none; font-size: 14px; font-weight: bold; }
            QPushButton#stopBtn:hover { background: #DC2626; }
            QPushButton#resumeBtn { background: #F59E0B; color: #FFFFFF; border: none; font-weight: bold; }
            QPushButton#cfBtn { background: #4F46E5; color: #FFFFFF; border: none; font-weight: bold; }
            QPushButton#testBtn { background: #8B5CF6; color: #FFFFFF; border: none; font-weight: bold; }
            QTableWidget { background: #FFFFFF; border: 1px solid #E5E7EB; border-radius: 8px; gridline-color: #F3F4F6; color: #374151; }
            QHeaderView::section { background: #F9FAFB; color: #6B7280; border: none; border-bottom: 1px solid #E5E7EB; border-right: 1px solid #E5E7EB; padding: 10px 8px; font-weight: bold; font-size: 12px; text-transform: uppercase; }
            QHeaderView { background: #FFFFFF; border: none; }
            QProgressBar { border: none; border-radius: 4px; background: #E5E7EB; height: 8px; }
            QProgressBar::chunk { background: #4F46E5; border-radius: 4px; }
            QLabel { color: #4B5563; }
            QSplitter::handle { background: #E5E7EB; width: 4px; border-radius: 2px; }
            QTableWidget { alternate-background-color: #F9FAFB; }
            QScrollBar:vertical { border: none; background: #F3F4F6; width: 10px; border-radius: 5px; margin: 0px; }
            QScrollBar::handle:vertical { background: #D1D5DB; min-height: 20px; border-radius: 5px; }
            QScrollBar::handle:vertical:hover { background: #9CA3AF; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { border: none; background: none; }
        ''')

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 12, 12, 12)
        title = QLabel('CEIR Auto IMEI Tool')
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet('font-size: 18px; font-weight: bold; color: #58a6ff; margin-bottom: 5px;')
        main_layout.addWidget(title)

        status_row = QHBoxLayout()
        self.status_label = QLabel('Idle')
        self.status_label.setStyleSheet('color: #58a6ff; font-weight: bold; font-size: 13px;')
        status_row.addWidget(self.status_label)
        status_row.addStretch()

        self.theme_btn = QPushButton('☀️ Light Mode')
        self.theme_btn.setFixedSize(110, 26)
        self.theme_btn.clicked.connect(self._toggle_theme)
        self.theme_btn.setStyleSheet("font-size: 11px; font-weight: bold; border-radius: 4px;")
        status_row.addWidget(self.theme_btn)

        self.progress_label = QLabel('')
        status_row.addWidget(self.progress_label)
        main_layout.addLayout(status_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setTextVisible(False)
        main_layout.addWidget(self.progress_bar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter, 1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()
        left_layout.addWidget(self.tabs)

        browser_tab = QWidget()
        browser_layout = QVBoxLayout(browser_tab)
        cf_group = QGroupBox('Cloudflare Session')
        cf_layout = QVBoxLayout(cf_group)
        cf_info = QLabel("1. Wait for page to load  2. Click 'Test API' to verify connection")
        cf_info.setWordWrap(True)
        cf_layout.addWidget(cf_info)
        cf_btns = QHBoxLayout()
        self.cf_status = QLabel('Not verified')
        self.cf_status.setStyleSheet('color: #da3633; font-weight: bold;')
        cf_btns.addWidget(self.cf_status)
        cf_btns.addStretch()
        self.cf_btn = QPushButton('Confirm Session')
        self.cf_btn.setObjectName('cfBtn')
        self.cf_btn.clicked.connect(self.confirm_cloudflare)
        cf_btns.addWidget(self.cf_btn)
        self.test_btn = QPushButton('Test API')
        self.test_btn.setObjectName('testBtn')
        self.test_btn.clicked.connect(self.test_api)
        cf_btns.addWidget(self.test_btn)
        cf_layout.addLayout(cf_btns)
        browser_layout.addWidget(cf_group)

        self.browser = QWebEngineView()
        self.browser.setMinimumHeight(300)
        self.browser.setUrl(QUrl(CEIR_BASE))
        browser_layout.addWidget(self.browser)
        self.tabs.addTab(browser_tab, 'CEIR Browser')

        imei_tab = QWidget()
        imei_layout = QVBoxLayout(imei_tab)
        imei_group = QGroupBox('IMEI Pairs (IMEI1,IMEI2 per line — or single IMEI per line)')
        ig_layout = QVBoxLayout(imei_group)
        self.imei_input = QPlainTextEdit()
        self.imei_input.setPlaceholderText('353456789012345,353456789012346\n357440806712128,357440806712129\n# or single: 353456789012345')
        self.imei_input.setFont(QFont('SF Mono', 11))
        self.imei_input.textChanged.connect(self._update_imei_count)
        ig_layout.addWidget(self.imei_input)
        imei_btns = QHBoxLayout()
        self.imei_count_label = QLabel('0 IMEIs')
        imei_btns.addWidget(self.imei_count_label)
        imei_btns.addStretch()
        load_btn = QPushButton('Load File')
        load_btn.clicked.connect(self._load_imei_file)
        imei_btns.addWidget(load_btn)
        ig_layout.addLayout(imei_btns)
        imei_layout.addWidget(imei_group)
        
        mode_group = QGroupBox('Mode')
        mode_layout = QHBoxLayout(mode_group)
        self.mode_btns = {}
        for m, label in [('check', 'Check Only'), ('change', 'Change Only'), ('full', 'Full Auto')]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _, mode=m: self._select_mode(mode))
            mode_layout.addWidget(btn)
            self.mode_btns[m] = btn
        self.mode_btns['check'].setChecked(True)
        self.mode_btns['check'].setStyleSheet('background: #1f6feb; color: white;')
        self.current_mode = 'check'
        imei_layout.addWidget(mode_group)
        self.tabs.addTab(imei_tab, 'IMEI Input')

        cfg_tab = QWidget()
        cfg_layout = QVBoxLayout(cfg_tab)
        adb_group = QGroupBox('ADB / Router')
        adb_form = QFormLayout(adb_group)
        self.cfg_ip = QLineEdit(self.cfg.get('router_ip', '192.168.1.1'))
        adb_form.addRow('Router IP:', self.cfg_ip)
        self.cfg_port = QSpinBox()
        self.cfg_port.setRange(1, 65535)
        self.cfg_port.setValue(self.cfg.get('adb_port', 5555))
        adb_form.addRow('ADB Port:', self.cfg_port)
        self.cfg_per_sim = QSpinBox()
        self.cfg_per_sim.setRange(1, 100)
        self.cfg_per_sim.setValue(self.cfg.get('imeis_per_sim', 20))
        adb_form.addRow('IMEIs per SIM:', self.cfg_per_sim)
        cfg_layout.addWidget(adb_group)

        delay_group = QGroupBox('Delays (seconds)')
        delay_form = QFormLayout(delay_group)
        self.cfg_net = QSpinBox()
        self.cfg_net.setRange(0, 120)
        self.cfg_net.setValue(self.cfg.get('network_wait_sec', 10))
        delay_form.addRow('Network Wait:', self.cfg_net)
        self.cfg_reboot = QSpinBox()
        self.cfg_reboot.setRange(0, 120)
        self.cfg_reboot.setValue(self.cfg.get('reboot_wait_sec', 15))
        delay_form.addRow('Reboot Wait:', self.cfg_reboot)
        self.cfg_delay = QSpinBox()
        self.cfg_delay.setRange(0, 30)
        self.cfg_delay.setValue(self.cfg.get('ceir_check_delay_sec', 2))
        delay_form.addRow('Check Delay:', self.cfg_delay)
        self.cfg_batch = QSpinBox()
        self.cfg_batch.setRange(1, 20)
        self.cfg_batch.setValue(self.cfg.get('batch_size', 5))
        delay_form.addRow('Batch Size (Check):', self.cfg_batch)
        cfg_layout.addWidget(delay_group)

        save_btn = QPushButton('Save Settings')
        save_btn.clicked.connect(self._save_settings)
        cfg_layout.addWidget(save_btn)
        cfg_layout.addStretch()
        self.tabs.addTab(cfg_tab, 'Settings')

        ctrl_layout = QHBoxLayout()
        self.start_btn = QPushButton('START')
        self.start_btn.setObjectName('startBtn')
        self.start_btn.clicked.connect(self._start_process)
        ctrl_layout.addWidget(self.start_btn)
        self.stop_btn = QPushButton('STOP')
        self.stop_btn.setObjectName('stopBtn')
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_process)
        ctrl_layout.addWidget(self.stop_btn)
        self.resume_btn = QPushButton('RESUME (SIM Swapped)')
        self.resume_btn.setObjectName('resumeBtn')
        self.resume_btn.setVisible(False)
        self.resume_btn.clicked.connect(self._resume_process)
        ctrl_layout.addWidget(self.resume_btn)
        left_layout.addLayout(ctrl_layout)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        log_group = QGroupBox('Log')
        log_layout = QVBoxLayout(log_group)
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setFont(QFont('SF Mono', 10))
        log_layout.addWidget(self.log_output)

        res_group = QGroupBox('Results')
        res_layout = QVBoxLayout(res_group)
        res_top = QHBoxLayout()
        res_top.addStretch()
        export_btn = QPushButton('Export CSV')
        export_btn.clicked.connect(self._export_csv)
        res_top.addWidget(export_btn)
        res_layout.addLayout(res_top)

        self.results_table = QTableWidget()
        self.results_table.setColumnCount(6)
        self.results_table.setHorizontalHeaderLabels(['IMEI 1', 'IMEI 2', 'Payment 1', 'Payment 2', 'Block', 'Status'])
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.results_table.setAlternatingRowColors(True)
        res_layout.addWidget(self.results_table)
        right_layout.addWidget(res_group)
        right_layout.addWidget(log_group)
        splitter.addWidget(right)
        splitter.setSizes([500, 600])

    def confirm_cloudflare(self):
        page = self.browser.page()
        page.runJavaScript('document.cookie', self._on_cookies)

    def _on_cookies(self, cookie_string):
        if cookie_string:
            self.cf_status.setText('Cookies captured')
            self.cf_status.setStyleSheet('color: #d29922; font-weight: bold;')
            self._add_log('COOKIE', "Got browser cookies, now click 'Test API'")
        else:
            self.cf_status.setText('No cookies yet - pass Cloudflare first!')
            self.cf_status.setStyleSheet('color: #da3633; font-weight: bold;')

    def test_api(self):
        self._add_log('TEST', 'Testing CEIR API access...')
        js = f'''
        (function() {{
            try {{
                var xhr = new XMLHttpRequest();
                xhr.open('GET', '{CEIR_ALTCHA_URL}', false);
                xhr.send();
                return JSON.stringify({{status: xhr.status, body: xhr.responseText}});
            }} catch(e) {{
                return JSON.stringify({{error: e.message}});
            }}
        }})()
        '''
        self.browser.page().runJavaScript(js, self._on_test_result)

    def _on_test_result(self, result):
        if not result:
            self._add_log('ERROR', 'No response from browser JS')
            self.cf_verified = False
            return None
        try:
            data = json.loads(result)
            if data.get('status') == 200:
                body = json.loads(data['body'])
                if 'challenge' in body and 'salt' in body:
                    self.cf_verified = True
                    self.cf_status.setText('API Ready! Session verified')
                    self.cf_status.setStyleSheet('color: #3fb950; font-weight: bold;')
                    self._add_log('OK', f"CEIR API accessible! challenge={body.get('challenge', '')[:20]}...")
                else:
                    self._add_log('ERROR', f"Unexpected API response: {data.get('body', '')[:100]}")
            elif data.get('status') == 403:
                self._add_log('ERROR', 'Cloudflare still blocking (403) - pass the check first!')
                self.cf_status.setText('Blocked - pass Cloudflare!')
                self.cf_status.setStyleSheet('color: #da3633; font-weight: bold;')
            else:
                self._add_log('ERROR', f"API returned HTTP {data.get('status')}: {data.get('body', '')[:100]}")
        except Exception as e:
            self._add_log('ERROR', f'Test failed: {e}')

    @pyqtSlot(str, str)
    def _add_log(self, tag, message):
        ts = datetime.now().strftime('%H:%M:%S')
        colors = {'OK': '#3fb950', 'DONE': '#3fb950', 'ERROR': '#f85149', 'WARN': '#d29922', 'ALTCHA': '#bc8cff', 'CHECK': '#58a6ff', 'PROG': '#58a6ff', 'IMEI': '#79c0ff', 'SIM': '#f0883e', 'ADB': '#8b949e', 'REBOOT': '#8b949e', 'WAIT': '#484f58', 'STOP': '#f85149', 'COOKIE': '#d29922', 'TEST': '#8957e5'}
        color = colors.get(tag, '#c9d1d9')
        self.log_output.append(f'<span style="color:#484f58">[{ts}]</span> <span style="color:{color};font-weight:bold">[{tag}]</span> {message}')

    def _color_item(self, text, green_vals=(), red_vals=()):
        item = QTableWidgetItem(text)
        if any(g in text for g in green_vals):
            item.setForeground(QColor('#3fb950'))
            return item
        if any(r in text for r in red_vals):
            item.setForeground(QColor('#f85149'))
            return item
        item.setForeground(QColor('#d29922'))
        return item

    @pyqtSlot(dict)
    def _add_result(self, result):
        self.results.append(result)
        row = self.results_table.rowCount()
        self.results_table.insertRow(row)
        self.results_table.setItem(row, 0, QTableWidgetItem(result.get('imei1', '')))
        self.results_table.setItem(row, 1, QTableWidgetItem(result.get('imei2', '')))
        p1 = result.get('payment1', '')
        self.results_table.setItem(row, 2, self._color_item(p1, ('ACCUMULATION',), ('FAIL', 'BLOCK')))
        p2 = result.get('payment2', '')
        self.results_table.setItem(row, 3, self._color_item(p2, ('ACCUMULATION',), ('FAIL', 'BLOCK')))
        block = result.get('blockState', '')
        self.results_table.setItem(row, 4, self._color_item(block, ('UNBLOCKED',), ('BLOCKED',)))
        status = result.get('status', 'OK')
        self.results_table.setItem(row, 5, self._color_item(status, ('OK', 'PASS'), ('ERROR', 'FAIL')))
        self.results_table.scrollToBottom()

    @pyqtSlot(int, int)
    def _update_progress(self, current, total):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        self.progress_label.setText(f'{current}/{total}')

    @pyqtSlot()
    def _on_done(self):
        self.is_running = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText(f'✅ Complete — {self._pc_name}')
        self.status_label.setStyleSheet('color: #3fb950; font-weight: bold; font-size: 15px;')
        self._alarm_active = True
        self._alarm_sim = 0
        self._alarm_timer.start()
        threading.Thread(target=self._done_sound, daemon=True).start()
        QMessageBox.information(self, f'Done — {self._pc_name}', f'✅ All IMEI changes complete!\n\nComputer: {self._pc_name}')
        self._stop_alarm()

    def _done_sound(self):
        for _ in range(3):
            if not self._alarm_active:
                return
            try:
                if sys.platform == 'darwin':
                    subprocess.run(['afplay', '/System/Library/Sounds/Hero.aiff'], timeout=5)
                elif sys.platform == 'win32':
                    import winsound
                    winsound.Beep(1500, 300)
                    winsound.Beep(2000, 300)
                else:
                    print('\\a', flush=True)
            except Exception:
                pass
            time.sleep(1)

    def _start_alarm(self, sim_num):
        self._alarm_active = True
        self._alarm_sim = sim_num
        self._alarm_timer.start()
        threading.Thread(target=self._alarm_sound_loop, daemon=True).start()

    def _stop_alarm(self):
        self._alarm_active = False
        self._alarm_timer.stop()
        self.setWindowTitle(self._base_title)

    def _flash_title(self):
        self._alarm_flash_on = not self._alarm_flash_on
        if self._alarm_flash_on:
            if self._alarm_sim == 0:
                self.setWindowTitle(f'✅ DONE — {self._pc_name} ✅')
            else:
                self.setWindowTitle(f'⚠️ SIM SWAP #{self._alarm_sim} — {self._pc_name} ⚠️')
        else:
            self.setWindowTitle(self._base_title)

    def _alarm_sound_loop(self):
        while self._alarm_active:
            try:
                if sys.platform == 'darwin':
                    subprocess.run(['afplay', '/System/Library/Sounds/Glass.aiff'], timeout=5)
                elif sys.platform == 'win32':
                    import winsound
                    winsound.Beep(1000, 500)
                else:
                    print('\\a', flush=True)
            except Exception:
                pass
            time.sleep(2)

    @pyqtSlot(int)
    def _on_pause(self, sim_num):
        self.resume_btn.setVisible(True)
        self.status_label.setText(f'⚠️ PAUSED — Swap to SIM #{sim_num} — {self._pc_name}')
        self.status_label.setStyleSheet('color: #d29922; font-weight: bold; font-size: 15px;')
        self._start_alarm(sim_num)
        QMessageBox.warning(self, f'SIM Swap — {self._pc_name}', f'⚠️ Computer: {self._pc_name}\n\nInsert SIM #{sim_num} and click RESUME')

    def _select_mode(self, mode):
        self.current_mode = mode
        for m, btn in self.mode_btns.items():
            btn.setChecked(m == mode)
            btn.setStyleSheet('background: #1f6feb; color: white;' if m == mode else '')

    def _parse_imei_lines(self):
        pairs = []
        for line in self.imei_input.toPlainText().split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = [p.strip() for p in line.replace('\\t', ',').split(',') if p.strip()]
            parts = [p for p in parts if p.isdigit()]
            if len(parts) >= 2:
                pairs.append((parts[0], parts[1]))
            elif len(parts) == 1:
                pairs.append((parts[0], None))
        return pairs

    def _update_imei_count(self):
        pairs = self._parse_imei_lines()
        dual = sum((1 for _, b in pairs if b))
        single = len(pairs) - dual
        label = f'{len(pairs)} phones'
        if dual:
            label += f' ({dual} dual-IMEI'
        if dual and single:
            label += f', {single} single'
        if dual:
            label += ')'
        self.imei_count_label.setText(label)

    def _load_imei_file(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Load IMEI File', '', 'Files (*.txt *.csv *.xlsx)')
        if not path:
            return None
        if path.endswith('.xlsx'):
            self._load_xlsx(path)
            return None
        try:
            with open(path) as f:
                self.imei_input.setPlainText(f.read())
        except Exception as e:
            QMessageBox.warning(self, 'Error', f'Failed to load file: {e}')

    def _load_xlsx(self, path):
        try:
            import openpyxl
        except ImportError:
            QMessageBox.warning(self, 'Error', 'Install openpyxl: pip3 install openpyxl')
            return None
        try:
            wb = openpyxl.load_workbook(path, read_only=True)
            ws = wb.active
            lines = []
            for row in ws.iter_rows(values_only=True):
                vals = [str(v).strip() for v in row if v is not None]
                digits = [v for v in vals if v.isdigit()]
                if len(digits) >= 2:
                    lines.append(f'{digits[0]},{digits[1]}')
                elif len(digits) == 1:
                    lines.append(digits[0])
            wb.close()
            self.imei_input.setPlainText('\n'.join(lines))
        except Exception as e:
            QMessageBox.warning(self, 'Error', f'Failed to load xlsx: {e}')

    def _save_settings(self):
        self.cfg['router_ip'] = self.cfg_ip.text()
        self.cfg['adb_port'] = self.cfg_port.value()
        self.cfg['imeis_per_sim'] = self.cfg_per_sim.value()
        self.cfg['network_wait_sec'] = self.cfg_net.value()
        self.cfg['reboot_wait_sec'] = self.cfg_reboot.value()
        self.cfg['ceir_check_delay_sec'] = self.cfg_delay.value()
        self.cfg['batch_size'] = self.cfg_batch.value()
        save_config(self.cfg)
        self._add_log('OK', 'Settings saved')

    def _fetch_altcha(self):
        js = f'''
        (function() {{
            try {{
                var xhr = new XMLHttpRequest();
                xhr.open('GET', '{CEIR_ALTCHA_URL}', false);
                xhr.send();
                return xhr.responseText;
            }} catch(e) {{
                return JSON.stringify({{"error": e.message}});
            }}
        }})()
        '''
        result = self.js.run(js, timeout=15)
        if not result:
            return None
        try:
            data = json.loads(result)
            if 'challenge' in data:
                return data
            if 'error' in data:
                self.log_signal.emit('ERROR', f"Altcha fetch: {data['error']}")
        except Exception:
            self.log_signal.emit('ERROR', f"Altcha parse error: {str(result)[:100]}")
        return None

    def _check_imei_via_browser(self, imei, token):
        url = f'{CEIR_VERIFY_URL}?altcha={token}'
        js = f'''
        (function() {{
            try {{
                var xhr = new XMLHttpRequest();
                xhr.open('POST', '{url}', false);
                xhr.setRequestHeader('Content-Type', 'application/json');
                xhr.send(JSON.stringify(["{str(imei)}"]));
                return xhr.responseText;
            }} catch(e) {{
                return JSON.stringify({{"error": e.message}});
            }}
        }})()
        '''
        result = self.js.run(js, timeout=15)
        if not result:
            return None
        try:
            data = json.loads(result)
            if 'IMEI_CHECK_LIST' in data and data['IMEI_CHECK_LIST']:
                return data['IMEI_CHECK_LIST'][0]
            if 'error' in data:
                self.log_signal.emit('ERROR', f"Check error: {data['error']}")
            return data
        except Exception:
            self.log_signal.emit('ERROR', f"Check parse error: {str(result)[:100]}")
            return None

    def check_single_imei(self, imei):
        results = self.check_batch_imeis([imei])
        return results.get(imei)

    def _get_altcha_token(self):
        self.log_signal.emit('ALTCHA', 'Fetching challenge...')
        challenge = self._fetch_altcha()
        if not challenge:
            self.log_signal.emit('ERROR', 'Failed to get altcha challenge')
            return None
        self.log_signal.emit('ALTCHA', f"Solving (max {challenge.get('maxnumber', '?')})...")
        token, took = solve_altcha(challenge)
        if not token:
            self.log_signal.emit('ERROR', 'Altcha solve failed')
            return None
        self.log_signal.emit('ALTCHA', f'Solved in {took}ms')
        return token

    def check_batch_imeis(self, imeis):
        token = self._get_altcha_token()
        if not token:
            return {imei: None for imei in imeis}
        url = f'{CEIR_VERIFY_URL}?altcha={token}'
        imei_array = json.dumps(imeis)
        js = f'''
        (function() {{
            try {{
                var xhr = new XMLHttpRequest();
                xhr.open('POST', '{url}', false);
                xhr.setRequestHeader('Content-Type', 'application/json');
                xhr.send('{imei_array.replace("'", "\\'")}');
                return xhr.responseText;
            }} catch(e) {{
                return JSON.stringify({{"error": e.message}});
            }}
        }})()
        '''
        result = self.js.run(js, timeout=30)
        out = {}
        if not result:
            self.log_signal.emit('ERROR', 'Batch check: no response')
            return {imei: None for imei in imeis}
        try:
            data = json.loads(result)
            if 'IMEI_CHECK_LIST' in data:
                for item in data['IMEI_CHECK_LIST']:
                    imei_val = item.get('IMEI', '')
                    out[imei_val] = item
                    self.log_signal.emit('CHECK', f"{imei_val}: payment={item.get('paymentState', '?')} block={item.get('blockState', '?')}")
            elif 'error' in data:
                self.log_signal.emit('ERROR', f"Batch check error: {data['error']}")
        except Exception as e:
            self.log_signal.emit('ERROR', f'Batch parse error: {e}')
        for imei in imeis:
            if imei not in out:
                out[imei] = None
        return out

    def _run_adb(self, args, timeout=30):
        try:
            r = subprocess.run(['adb'] + args, capture_output=True, text=True, timeout=timeout)
            return r.stdout.strip()
        except Exception:
            return None

    def _adb_connect(self):
        out = self._run_adb(['connect', f"{self.cfg['router_ip']}:{self.cfg['adb_port']}"])
        if out and 'connected' in out.lower():
            self.log_signal.emit('ADB', f'Connected: {out}')
            return True
        self.log_signal.emit('ERROR', f'ADB failed: {out}')
        return False

    def _wait_for_offline(self, timeout=30):
        start = time.time()
        while time.time() - start < timeout:
            if self.stop_requested:
                return True
            state = self._run_adb(['get-state'])
            if state != 'device':
                self.log_signal.emit('REBOOT', 'Device offline — reboot in progress')
                return True
            time.sleep(1)
        self.log_signal.emit('WARN', "Device didn't go offline — forcing reconnect")
        self._run_adb(['disconnect'])
        time.sleep(2)
        return True

    def _wait_for_device(self, timeout=90):
        start = time.time()
        self._adb_connect()
        while time.time() - start < timeout:
            if self.stop_requested:
                return False
            if self._run_adb(['get-state']) == 'device':
                uid = self._run_adb(['shell', 'id'])
                if uid and 'uid=' in uid:
                    return True
            time.sleep(2)
            self._adb_connect()
        return False

    def _change_imei_adb(self, imei):
        self.log_signal.emit('IMEI', f'Changing to: {imei}')
        self._run_adb(['shell', f'atc AT^PHYNUM=IMEI,{imei}'])
        self.log_signal.emit('REBOOT', 'Sending reboot...')
        self._run_adb(['shell', 'atc AT^RESET'])
        self._wait_for_offline(timeout=30)
        self.log_signal.emit('WAIT', 'Waiting for device to boot...')
        if not self._wait_for_device(timeout=90):
            self.log_signal.emit('ERROR', 'Device not responding after reboot')
            return False
        self.log_signal.emit('ADB', 'Device ready')
        return True

    def _start_process(self):
        imeis = self._parse_imei_lines()
        if not imeis:
            QMessageBox.warning(self, 'Error', 'No IMEIs entered!')
            return None
        if self.current_mode in ['check', 'full'] and not self.cf_verified:
            QMessageBox.warning(self, 'Error', "Go to 'CEIR Browser' tab, pass Cloudflare,\nclick 'Confirm Session', then 'Test API' first!")
            return None
        self._save_settings()
        self.is_running = True
        self.stop_requested = False
        self._paused = False
        self.results = []
        self.results_table.setRowCount(0)
        self.log_output.clear()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status_label.setText('Running...')
        self.status_label.setStyleSheet('color: #58a6ff; font-weight: bold; font-size: 13px;')
        worker = {'check': self._w_check, 'change': self._w_change, 'full': self._w_full}[self.current_mode]
        threading.Thread(target=worker, args=(imeis,), daemon=True).start()

    def _stop_process(self):
        self.stop_requested = True

    def _resume_process(self):
        self._stop_alarm()
        self.resume_btn.setVisible(False)
        self._paused = False
        self.status_label.setText('Running...')
        self.status_label.setStyleSheet('color: #58a6ff; font-weight: bold; font-size: 13px;')

    def _w_check(self, pairs):
        total = len(pairs)
        BATCH_SIZE = self.cfg.get('batch_size', 5)
        done = 0
        for batch_start in range(0, total, BATCH_SIZE):
            if self.stop_requested:
                self.log_signal.emit('STOP', 'Stopped')
                break
            batch = pairs[batch_start:batch_start + BATCH_SIZE]
            all_imeis = []
            for imei1, imei2 in batch:
                all_imeis.append(imei1)
                if imei2:
                    all_imeis.append(imei2)
            self.log_signal.emit('PROG', f'[{done + 1}-{done + len(batch)}/{total}] Checking {len(all_imeis)} IMEIs ({len(batch)} phones)')
            results = self.check_batch_imeis(all_imeis)
            for imei1, imei2 in batch:
                done += 1
                self.progress_signal.emit(done, total)
                r1 = results.get(imei1)
                r2 = results.get(imei2) if imei2 else None
                p1 = r1.get('paymentState', '') if r1 else 'FAILED'
                p2 = r2.get('paymentState', '') if r2 else 'FAILED' if imei2 else ''
                b1 = r1.get('blockState', '') if r1 else ''
                b2 = r2.get('blockState', '') if r2 else ''
                if imei2:
                    block = 'UNBLOCKED' if b1 == 'UNBLOCKED' and b2 == 'UNBLOCKED' else f'{b1}/{b2}'
                    ok = r1 is not None and r2 is not None
                else:
                    block = b1
                    ok = r1 is not None
                self.result_signal.emit({'imei1': imei1, 'imei2': imei2 or '', 'payment1': p1, 'payment2': p2, 'blockState': block, 'status': 'OK' if ok else 'FAILED'})
            if batch_start + BATCH_SIZE < total:
                time.sleep(self.cfg['ceir_check_delay_sec'])
        self.log_signal.emit('DONE', f'Checked {total} phones')
        self.done_signal.emit()

    def _after_sim_swap(self):
        self.log_signal.emit('SIM', 'Rebooting router for new SIM...')
        self._run_adb(['shell', 'atc AT^RESET'])
        self._wait_for_offline(timeout=30)
        self.log_signal.emit('WAIT', 'Waiting for router to boot with new SIM...')
        if not self._wait_for_device(timeout=90):
            self.log_signal.emit('ERROR', 'Router not responding after SIM swap reboot')
            return False
        self.log_signal.emit('SIM', 'Waiting for network registration...')
        time.sleep(self.cfg['network_wait_sec'])
        self.log_signal.emit('SIM', 'Router ready with new SIM')
        return True

    def _check_sim_swap(self, sim_count, per_sim, current_sim):
        if sim_count >= per_sim:
            current_sim += 1
            sim_count = 0
            self._paused = True
            self.pause_signal.emit(current_sim)
            while self._paused and not self.stop_requested:
                time.sleep(1)
            if self.stop_requested:
                return None
            self._after_sim_swap()
        return (sim_count, current_sim)

    def _w_change(self, pairs):
        total = len(pairs)
        per_sim = self.cfg.get('imeis_per_sim', 20)
        self._adb_connect()
        sim_count = 0
        current_sim = 1
        for i, (imei1, imei2) in enumerate(pairs):
            if self.stop_requested:
                self.log_signal.emit('STOP', 'Stopped')
                break
            status = 'OK'
            r = self._check_sim_swap(sim_count, per_sim, current_sim)
            if r is None:
                break
            sim_count, current_sim = r
            self.progress_signal.emit(i + 1, total)
            self.log_signal.emit('PROG', f'[{i + 1}/{total}] Phone IMEI1 — SIM #{current_sim}')
            ok1 = self._change_imei_adb(imei1)
            sim_count += 1
            if not ok1:
                status = 'IMEI1_FAIL'
            ok2 = True
            if imei2:
                if self.stop_requested:
                    break
                r = self._check_sim_swap(sim_count, per_sim, current_sim)
                if r is None:
                    break
                sim_count, current_sim = r
                self.log_signal.emit('PROG', f'[{i + 1}/{total}] Phone IMEI2 — SIM #{current_sim}')
                ok2 = self._change_imei_adb(imei2)
                sim_count += 1
                if not ok2:
                    status = 'IMEI2_FAIL' if ok1 else 'BOTH_FAIL'
            self.result_signal.emit({'imei1': imei1, 'imei2': imei2 or '', 'payment1': '', 'payment2': '', 'blockState': '', 'status': status})
        self.log_signal.emit('DONE', f'Changed {total} phones')
        self.done_signal.emit()

    def _w_full(self, pairs):
        total = len(pairs)
        per_sim = self.cfg.get('imeis_per_sim', 20)
        self._adb_connect()
        sim_count = 0
        current_sim = 1
        for i, (imei1, imei2) in enumerate(pairs):
            if self.stop_requested:
                self.log_signal.emit('STOP', 'Stopped')
                break
            p1 = ''
            p2 = ''
            b1 = ''
            b2 = ''
            status = 'OK'
            r = self._check_sim_swap(sim_count, per_sim, current_sim)
            if r is None:
                break
            sim_count, current_sim = r
            self.progress_signal.emit(i + 1, total)
            self.log_signal.emit('PROG', f'[{i + 1}/{total}] Phone IMEI1 — SIM #{current_sim}')
            ok1 = self._change_imei_adb(imei1)
            sim_count += 1
            if ok1:
                c1 = self.check_single_imei(imei1)
                p1 = c1.get('paymentState', '') if c1 else 'CHECK_FAILED'
                b1 = c1.get('blockState', '') if c1 else ''
            else:
                p1 = 'CHANGE_FAIL'
                status = 'IMEI1_FAIL'
            if imei2:
                if self.stop_requested:
                    break
                r = self._check_sim_swap(sim_count, per_sim, current_sim)
                if r is None:
                    break
                sim_count, current_sim = r
                self.log_signal.emit('PROG', f'[{i + 1}/{total}] Phone IMEI2 — SIM #{current_sim}')
                ok2 = self._change_imei_adb(imei2)
                sim_count += 1
                if ok2:
                    c2 = self.check_single_imei(imei2)
                    p2 = c2.get('paymentState', '') if c2 else 'CHECK_FAILED'
                    b2 = c2.get('blockState', '') if c2 else ''
                else:
                    p2 = 'CHANGE_FAIL'
                    status = 'IMEI2_FAIL' if ok1 else 'BOTH_FAIL'
            if imei2:
                block = 'UNBLOCKED' if b1 == 'UNBLOCKED' and b2 == 'UNBLOCKED' else f'{b1}/{b2}'
            else:
                block = b1
            self.result_signal.emit({'imei1': imei1, 'imei2': imei2 or '', 'payment1': p1, 'payment2': p2, 'blockState': block, 'status': status})
        self.log_signal.emit('DONE', f'Processed {total} phones')
        self.done_signal.emit()

    def _export_csv(self):
        if not self.results:
            QMessageBox.warning(self, 'Error', 'No results')
            return None
        path, _ = QFileDialog.getSaveFileName(self, 'Save CSV', 'ceir_results.csv', 'CSV (*.csv)')
        if path:
            keys = list(self.results[0].keys())
            try:
                with open(path, 'w', newline='') as f:
                    w = csv.DictWriter(f, fieldnames=keys)
                    w.writeheader()
                    w.writerows(self.results)
                self._add_log('OK', f'Exported to {path}')
            except Exception as e:
                QMessageBox.warning(self, 'Error', f'Failed to export CSV: {e}')

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setApplicationName('CEIR Auto IMEI Tool')
    window = CEIRApp()
    window.show()
    sys.exit(app.exec())
