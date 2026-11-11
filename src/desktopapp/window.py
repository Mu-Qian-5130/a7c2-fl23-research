"""Six explicit workflows, background workers and a complete diagnostic log."""
from datetime import datetime
import json
from pathlib import Path
import sys
import uuid
from PySide6 import QtCore, QtGui, QtWidgets as W
from . import VERSION
from . import jobs
from . import presets
from . import reloadguide
from .disclaimer import require_consent

DRIVER_HINT = ('\n驱动或连接没有成功：先在“连接与驱动”页卸载驱动后重装；仍不行，'
               '可点该页的“用 Zadig 手动安装驱动”，按说明给 0E8A 和 0336 两个身份分别装 libusbK。')
from . import connectionguide
from .paths import ROOT, data_root, load_settings, write_json
from .theme import WINDOW as STYLE, asset

# Sidebar glyphs for the current navigation (page index → assets/nav/*.svg).
NAV_ICONS = {1:'driver',11:'trust',9:'firmware',4:'looks',6:'sound',2:'restore',10:'connection'}


class TransportChoice(W.QWidget):
    changed=QtCore.Signal()

    def __init__(self,key):
        super().__init__()
        self.setObjectName(key+'Transport')
        # Drawn as a two-segment control; the exclusive checkboxes stay as-is.
        self.setProperty('segmented',True);self.setAttribute(QtCore.Qt.WA_StyledBackground,True)
        row=W.QHBoxLayout(self);row.setContentsMargins(2,2,2,2);row.setSpacing(0)
        self.usb=W.QCheckBox('USB · 线刷');self.ssh=W.QCheckBox('SSH · Wi-Fi')
        self.usb.setObjectName(key+'Usb');self.ssh.setObjectName(key+'Ssh')
        self.group=W.QButtonGroup(self);self.group.setExclusive(True)
        for index,button in enumerate((self.usb,self.ssh)):
            self.group.addButton(button,index);row.addWidget(button)
        self.usb.setChecked(True)
        self.group.idToggled.connect(lambda index,checked:self.changed.emit() if checked else None)

    def value(self):return 'ssh' if self.ssh.isChecked() else 'usb'

    def select(self,value):
        if value not in ('usb','ssh'):raise ValueError('Unknown connection choice')
        (self.ssh if value=='ssh' else self.usb).setChecked(True)


class Window(W.QMainWindow):
    def __init__(self, *, demo=False):
        super().__init__()
        self.setWindowTitle('A7C II Tools · LUT Preview Test 3' if '--preview-gate-test' in sys.argv else
                            'A7C II Tools · Desktop Preview')
        self.setWindowIcon(QtGui.QIcon(asset('mark.png')))
        self.resize(1180, 860)
        self.setMinimumSize(960, 730)
        self.settings = load_settings()
        self.fields, self.buttons = {}, []
        self.current_job = None
        self.log_offset = 0
        self.process = None
        self.demo = demo
        self.camera_operation = False
        self.setStyleSheet(STYLE)
        central = W.QWidget()
        central.setObjectName('content')
        self.setCentralWidget(central)
        layout = W.QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        sidebar = W.QFrame()
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(228)
        side = W.QVBoxLayout(sidebar)
        side.setContentsMargins(14, 22, 14, 16)
        side.setSpacing(0)
        brand = W.QHBoxLayout()
        brand.setSpacing(10)
        brand.setContentsMargins(6, 0, 0, 0)
        mark = W.QLabel()
        mark.setPixmap(QtGui.QIcon(asset('mark.png')).pixmap(QtCore.QSize(34, 34), self.devicePixelRatioF()))
        mark.setFixedSize(34, 34)
        brand.addWidget(mark, 0, QtCore.Qt.AlignTop)
        names = W.QVBoxLayout()
        names.setSpacing(1)
        brand_name = W.QLabel('A7C II Tools')
        brand_name.setObjectName('brandName')
        names.addWidget(brand_name)
        self.description = W.QLabel()
        self.description.setObjectName('brandDetail')
        self.description.setWordWrap(True)
        names.addWidget(self.description)
        brand.addLayout(names, 1)
        side.addLayout(brand)
        side.addSpacing(22)
        self.nav = W.QListWidget()
        self.nav.setObjectName('nav')
        self.nav.setIconSize(QtCore.QSize(18, 18))
        self.nav.setFocusPolicy(QtCore.Qt.NoFocus)
        self.nav.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.nav.addItems(['旧版 · 一键安装', '旧版 · 连接与驱动', '旧版 · 恢复原厂功能', '旧版 · FL2 / FL3', '旧版 · 自定义创意外观', '旧版 · 竖屏显示', '旧版 · 快门声音', '旧版 · 白平衡', '开发调试 · SSH', '本地固件 · 卡刷候选', '滤镜与音效 · SSH'])
        self.nav.addItem('首次授信')
        self.nav_items=[self.nav.item(index) for index in range(self.nav.count())]
        for index,item in enumerate(self.nav_items):item.setData(QtCore.Qt.UserRole,index)
        if '--legacy-usb' not in sys.argv:
            for index,name in NAV_ICONS.items():
                self.nav_items[index].setIcon(QtGui.QIcon(asset('nav/'+name+'.svg')))
        for item in self.nav_items:item.setSizeHint(QtCore.QSize(0, 36))
        side.addWidget(self.nav, 1)
        base = W.QHBoxLayout()
        base.setContentsMargins(8, 10, 2, 0)
        caption = W.QLabel('固件版本' if '--legacy-usb' in sys.argv else '原厂基础版本')
        caption.setObjectName('sidebarCaption')
        base.addWidget(caption)
        base.addStretch()
        self.firmware = W.QComboBox()
        self.firmware.addItems(['2.01'])
        base.addWidget(self.firmware)
        side.addLayout(base)
        layout.addWidget(sidebar)
        right = W.QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        layout.addLayout(right, 1)
        self.description.setText(('Windows 测试版' if sys.platform == 'win32' else '桌面开发版') +
            (' · 一键安装与独立功能入口 · ' if '--legacy-usb' in sys.argv else ' · 本地固件与 SSH 更新候选 · ') + VERSION)
        self.pages = W.QStackedWidget()
        right.addWidget(self.pages, 1)
        self.home_page()
        self.connection_page()
        self.recovery_page()
        self.fl23_page()
        self.look_page()
        self.vertical_page()
        self.sound_page()
        self.whitebalance_page()
        self.ssh_page()
        self.firmware_page()
        self.ssh_updates_page()
        self.trust_page()
        self.nav.currentItemChanged.connect(lambda item,previous:self.pages.setCurrentIndex(item.data(QtCore.Qt.UserRole)) if item else None)
        if '--legacy-usb' not in sys.argv:
            order=(1,11,9,4,6,2,10,0,3,5,7,8)
            while self.nav.count():self.nav.takeItem(0)
            for index in order:self.nav.addItem(self.nav_items[index])
            titles={1:'安装驱动',11:'首次授信',9:'生成固件',4:'滤镜',6:'快门音效',2:'一键恢复',10:'连接设置'}
            for index,item in enumerate(self.nav_items):
                item.setHidden(index not in titles)
                if index in titles:item.setText(titles[index])
        self.description.setText('电脑端制作与编辑\nSSH / USB 更新 · ' + VERSION)
        self.select_page(0 if '--legacy-usb' in sys.argv else 9)
        self.polish_pages()
        footer = W.QFrame()
        footer.setObjectName('footer')
        activity = W.QVBoxLayout(footer)
        activity.setContentsMargins(0, 0, 0, 0)
        activity.setSpacing(0)
        self.progress = W.QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        activity.addWidget(self.progress)
        bottom = W.QHBoxLayout()
        bottom.setContentsMargins(24, 9, 20, 10)
        bottom.setSpacing(8)
        self.status_dot = W.QLabel()
        self.status_dot.setObjectName('statusDot')
        bottom.addWidget(self.status_dot, 0, QtCore.Qt.AlignVCenter)
        bottom.addSpacing(2)
        self.status = W.QLabel('就绪。选择左侧功能；启动软件不会访问相机。')
        self.status.setObjectName('statusText')
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        bottom.addWidget(self.status, 1)
        self.log_toggle = W.QToolButton()
        self.log_toggle.setText('日志')
        self.log_toggle.setCheckable(True)
        self.log_toggle.setToolTip('显示或隐藏完整运行日志')
        bottom.addWidget(self.log_toggle)
        open_log = W.QPushButton('打开任务目录')
        open_log.clicked.connect(self.open_job)
        bottom.addWidget(open_log)
        export = W.QPushButton('导出诊断包')
        export.clicked.connect(self.export_logs)
        bottom.addWidget(export)
        self.stop = W.QPushButton('停止离线任务')
        self.stop.setEnabled(False)
        self.stop.clicked.connect(self.cancel_offline)
        bottom.addWidget(self.stop)
        activity.addLayout(bottom)
        self.log = W.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFixedHeight(150)
        self.log.setPlaceholderText('完整运行日志与原始报错会显示在这里。')
        self.log.setVisible(False)
        log_box = W.QHBoxLayout()
        log_box.setContentsMargins(20, 0, 20, 14)
        log_box.addWidget(self.log)
        activity.addLayout(log_box)
        self.log_toggle.toggled.connect(self.log.setVisible)
        right.addWidget(footer)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.poll_job)
        self.timer.start(250)

    def page(self, title, detail):
        wrapper = W.QScrollArea()
        wrapper.setWidgetResizable(True)
        wrapper.setFrameShape(W.QFrame.NoFrame)
        body = W.QWidget()
        body.setObjectName('pageBody')
        outer = W.QHBoxLayout(body)
        outer.setContentsMargins(44, 34, 36, 28)
        column = W.QWidget()
        column.setMaximumWidth(840)
        outer.addWidget(column, 1)
        outer.addStretch(0)
        layout = W.QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        label = W.QLabel(title)
        label.setProperty('pageTitle', True)
        layout.addWidget(label)
        hint = W.QLabel(detail)
        hint.setWordWrap(True)
        hint.setProperty('subtitle', True)
        layout.addWidget(hint)
        layout.addSpacing(8)
        wrapper.setWidget(body)
        self.pages.addWidget(wrapper)
        return layout

    def select_page(self,index):
        self.nav.setCurrentItem(self.nav_items[index])

    def box(self, layout, title):
        group = W.QGroupBox(title)
        form = W.QFormLayout(group)
        form.setFieldGrowthPolicy(W.QFormLayout.AllNonFixedFieldsGrow)
        form.setLabelAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(10)
        layout.addWidget(group)
        return form

    def card(self, layout, title=None, *, stretch=0):
        """A grey tile with an optional heading; returns its vertical layout."""
        frame = W.QFrame()
        frame.setProperty('card', True)
        inner = W.QVBoxLayout(frame)
        inner.setContentsMargins(18, 16, 18, 16)
        inner.setSpacing(10)
        if title:
            heading = W.QLabel(title)
            heading.setProperty('section', True)
            inner.addWidget(heading)
        layout.addWidget(frame, stretch)
        return inner

    def advanced(self, layout, title):
        toggle = W.QToolButton()
        toggle.setText(title)
        toggle.setCheckable(True)
        toggle.setProperty('disclosure', True)
        toggle.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        toggle.setIcon(QtGui.QIcon(asset('chevron-right.svg')))
        toggle.setIconSize(QtCore.QSize(14, 14))
        content = W.QWidget()
        content.setVisible(False)
        inner = W.QVBoxLayout(content)
        inner.setContentsMargins(0, 0, 0, 6)
        inner.setSpacing(10)
        toggle.toggled.connect(content.setVisible)
        toggle.toggled.connect(lambda open: toggle.setIcon(QtGui.QIcon(asset('chevron-open.svg' if open else 'chevron-right.svg'))))
        layout.addSpacing(4)
        layout.addWidget(toggle, 0, QtCore.Qt.AlignLeft)
        layout.addWidget(content)
        return inner

    def polish_pages(self):
        """Apply the layout conventions every page shares.

        Long explanatory labels become secondary notes, and stand-alone
        buttons keep their natural width instead of stretching across the
        page. Widgets, names and behaviour are untouched.
        """
        from .lookeditor import LookEditor
        skip = tuple(self.pages.widget(i).findChildren(LookEditor) for i in range(self.pages.count()))
        editors = {editor for group in skip for editor in group}

        def inside_editor(widget):
            parent = widget
            while parent is not None:
                if parent in editors:return True
                parent = parent.parentWidget()
            return False

        for index in range(self.pages.count()):
            page = self.pages.widget(index)
            for label in page.findChildren(W.QLabel):
                standalone = isinstance(label.parentWidget().layout(), W.QVBoxLayout) and len(label.text()) >= 24
                if ((label.wordWrap() or standalone) and not inside_editor(label) and not any(
                        label.property(name) for name in ('hint','subtitle','pageTitle','callout','section','warning'))):
                    label.setProperty('note', True)
                    label.setWordWrap(True)
            column = page.widget().layout().itemAt(0).widget()
            self._align_buttons(column.layout(), editors)

    def _align_buttons(self, layout, editors):
        if layout is None or layout.property('fill'):return
        items = [layout.itemAt(i) for i in range(layout.count())]
        if isinstance(layout, W.QVBoxLayout):
            for item in items:
                widget = item.widget()
                if isinstance(widget, W.QPushButton):layout.setAlignment(widget, QtCore.Qt.AlignLeft)
        elif isinstance(layout, W.QHBoxLayout):
            widgets = [item.widget() for item in items if item.widget() is not None]
            if (widgets and not any(item.spacerItem() for item in items)
                    and all(isinstance(w, (W.QPushButton, W.QComboBox)) for w in widgets)):
                layout.addStretch(1)
        for item in items:
            if item.layout() is not None:
                self._align_buttons(item.layout(), editors)
            widget = item.widget()
            if widget is not None and widget not in editors and not isinstance(widget, W.QGroupBox) and widget.layout() is not None:
                self._align_buttons(widget.layout(), editors)

    def direct_args(self, group, **values):
        work = self.work(group)
        return dict(self.common(), workspace=work, **{key: value for key, value in values.items() if key != 'mode'})

    def setup_args(self):
        root = self.settings.get('setup_work', '')
        state = Path(root, 'setup.private.json') if root else None
        if state is not None and state.is_file():
            saved = json.loads(state.read_text(encoding='utf-8'))
            if saved['phase'] != 'COMPLETE':
                return dict(self.common(), workspace=root, options=saved['options'])
        root = self.work('setup')
        tool = ROOT / ('desktop-assets/exiftool/exiftool.exe' if sys.platform=='win32' else 'desktop-assets/exiftool/exiftool')
        looks = [dict(slot=s, path=self.text('setup_look_' + str(s))) for s in range(1, 7) if self.text('setup_look_' + str(s))]
        options = dict(fl23=self.setup_fl23.isChecked(), sound=self.setup_sound.isChecked(),
            vertical=self.setup_vertical.isChecked(), plugin=self.setup_plugin.isChecked(),
            exiftool=str(tool), looks=[] if self.setup_presets.isChecked() else looks,
            preset_pack=presets.PACK if self.setup_presets.isChecked() else None)
        options['voice_cleanup_policy']=1
        return dict(self.common(), workspace=root, options=options)

    def home_page(self):
        layout = self.page('一键安装', '六款外观、FL2／FL3、电子快门声及竖屏保存开关合并安装。按提示断电重开后，同一按钮只核对加载；无需逐槽安装。')
        self.setup_presets = W.QCheckBox('安装内置六款外观（替换自订 1–6，原有创意外观保留）')
        self.setup_presets.setChecked(True)
        self.setup_fl23 = W.QCheckBox('启用 FL2／FL3'); self.setup_fl23.setChecked(True)
        self.setup_sound = W.QCheckBox('启用索尼原生电子快门声音'); self.setup_sound.setChecked(True)
        self.setup_vertical = W.QCheckBox('保存开启竖屏拍摄信息显示（重开后自动生效）'); self.setup_vertical.setChecked(True)
        self.setup_voice=W.QCheckBox('清理无障碍语音包，并将语音指南置灰（安装必选）')
        self.setup_voice.setChecked(True);self.setup_voice.setEnabled(False)
        self.setup_voice.setToolTip('删除十种语言的菜单朗读音频，约释放 283 MiB；不删除对焦提示音或快门声音。只能通过一键恢复补回。')
        self.setup_plugin = W.QCheckBox('安装 Lightroom 自动识别插件（需要 Lightroom）')
        prior_path=Path(self.settings.get('setup_work',''),'setup.private.json')
        prior=json.loads(prior_path.read_text(encoding='utf-8')) if prior_path.is_file() else {}
        if prior and prior.get('phase')!='COMPLETE':
            options=prior['options']
            self.setup_presets.setChecked(options.get('preset_pack') == presets.PACK)
            for box,key in ((self.setup_fl23,'fl23'),(self.setup_sound,'sound'),(self.setup_vertical,'vertical'),(self.setup_plugin,'plugin')):
                box.setChecked(bool(options.get(key,key!='plugin')))
            for box in (self.setup_presets,self.setup_fl23,self.setup_sound,self.setup_vertical,self.setup_plugin):box.setEnabled(False)

        self.setup_note=W.QLabel('安装尚未结束，请点击“继续安装”，按弹窗完成下一步；需要断电时，接回 USB 后仍点击此按钮。')
        self.setup_note.setWordWrap(True);self.setup_note.setProperty('callout',True)
        self.setup_note.setVisible(bool(prior) and prior.get('phase')!='COMPLETE')
        layout.addWidget(self.setup_note)
        layout.addWidget(self.setup_presets)
        self.setup_preset_summary = W.QLabel(presets.SUMMARY)
        self.setup_preset_summary.setWordWrap(True)
        if prior and prior.get('phase')!='COMPLETE':
            names = ['%s %s' % (r['slot'], r.get('name', Path(r['path']).stem)) for r in prior['options'].get('looks', [])]
            self.setup_preset_summary.setText('本次已保存外观：' + (' · '.join(names) if names else '未选择外观，不会新增六款'))
        else:
            self.setup_preset_summary.setEnabled(self.setup_presets.isChecked())
            self.setup_presets.toggled.connect(self.setup_preset_summary.setEnabled)
        layout.addWidget(self.setup_preset_summary)
        for check in (self.setup_fl23, self.setup_sound, self.setup_vertical, self.setup_plugin):layout.addWidget(check)
        voice_row=W.QHBoxLayout();voice_row.addWidget(self.setup_voice)
        voice_help=W.QToolButton();voice_help.setText('？');voice_help.setObjectName('voiceCleanupHelp')
        voice_help.setToolTip(self.setup_voice.toolTip())
        voice_help.clicked.connect(lambda:W.QMessageBox.information(self,'无障碍语音包是什么',
            '这是相机为视障使用者提供的菜单朗读／语音指南，包含十种语言的音频，约占 283 MiB。\n\n'
            '一键安装会关闭语音指南、将相关机内选项置灰，重开核对后删除音频，为竖屏等资源腾出空间。'
            '不会删除语言索引、对焦提示音、原生快门声或自定义电子快门音效。\n\n'
            '该项属于新安装方案，不能取消。仅“一键恢复原厂功能”会从用户的官方固件或可用同机备份补回；机内初始化不能恢复。'
            '需要语音指南辅助操作的用户请勿使用本安装方案。'))
        voice_row.addWidget(voice_help);voice_row.addStretch();layout.addLayout(voice_row)
        source_notice=W.QLabel('备份与恢复来源：可在“恢复原厂功能”页备份当前项目与语音。'
            '为尊重原厂版权、降低包括 DMCA 在内的法律风险，安装包不附带完整官方固件或原厂语音包。'
            '一键恢复的程序、设置及语音来源由你提供：使用可用同机原始备份，或自行从索尼官方下载 ILCE-7CM2 2.01 BODYDATA.DAT。'
            '普通安装不强制先备份或下载；恢复也不保证能救回无法开机的相机。')
        source_notice.setObjectName('setupRecoverySourceNotice');source_notice.setWordWrap(True)
        layout.addWidget(source_notice)
        recovery_source=W.QPushButton('查看可选备份与官方固件恢复来源')
        recovery_source.clicked.connect(lambda:self.select_page(2))
        layout.addWidget(recovery_source);self.buttons.append(recovery_source)
        self.setup_button=self.button(layout, '开始新的一键安装' if prior.get('phase')=='COMPLETE' else '继续安装' if prior else '一键安装',
                                      'setup_all', self.setup_args, primary=True)
        self.setup_result_button=W.QPushButton('查看上次安装结果（不连接相机）')
        self.setup_result_button.clicked.connect(self.show_setup_result)
        self.setup_result_button.setVisible(prior.get('phase')=='COMPLETE')
        layout.addWidget(self.setup_result_button);self.buttons.append(self.setup_result_button)
        look_section=self.advanced(layout,'改用自己的 A7Look 文件（先取消勾选内置六款）')
        custom_container = self.setup_custom_container = look_section.parentWidget()
        custom_container.setEnabled(not self.setup_presets.isChecked() and not (prior and prior.get('phase')!='COMPLETE'))
        self.setup_presets.toggled.connect(lambda enabled: custom_container.setEnabled(not enabled))
        form = self.box(look_section, '选择 A7Look 文件')
        for slot in range(1, 7):
            self.field(form, 'setup_look_' + str(slot), '自订 ' + str(slot), kind='file', filter='Compiled looks (*.a7look)')
        compile_button = W.QPushButton('从 DCP／LUT 生成 A7Look…')
        compile_button.clicked.connect(self.compiler_dialog); look_section.addWidget(compile_button); self.buttons.append(compile_button)
        hint = W.QLabel('恢复出厂、卸载驱动和删除外观不会混入安装流程。自定义声音请在“快门声音”中转换后选择机械／电子／两者并保存，试听可选。')
        hint.setWordWrap(True); layout.addWidget(hint); layout.addStretch()

    def drivers_first(self, arguments):
        """Suggest the connection page before a first one-click install on Windows."""
        if (sys.platform != 'win32' or self.settings.get('connection_verified')
                or Path(arguments.get('workspace', ''), 'setup.private.json').is_file()):
            return True
        choice = self.ask_drivers_first()
        if choice == 'drivers':
            self.select_page(1)
        return choice == 'continue'

    def ask_drivers_first(self):
        box = W.QMessageBox(self)
        box.setWindowTitle('建议先安装驱动')
        box.setText('这台电脑还没有成功连接过相机。建议先到“连接与驱动”页，点“准备两阶段驱动并测试连接”，'
                    '看到连接成功后再回来一键安装。')
        box.setInformativeText('一键安装也会自动尝试安装驱动，但驱动失败时排查更麻烦。'
                               '驱动反复装不上，可点该页的“用 Zadig 手动安装驱动”，按说明操作。')
        go = box.addButton('先去安装驱动', W.QMessageBox.AcceptRole)
        box.addButton('直接一键安装', W.QMessageBox.DestructiveRole)
        cancel = box.addButton(W.QMessageBox.Cancel)
        box.setDefaultButton(go)
        box.exec()
        return 'drivers' if box.clickedButton() is go else 'cancel' if box.clickedButton() is cancel else 'continue'

    def driver_step_failed(self, action):
        if action in ('usb_prepare', 'connect', 'driver_install'):
            return True
        if action != 'setup_all':
            return False
        try:
            state = json.loads(Path(self.settings.get('setup_work', ''), 'setup.private.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return False
        return 'drivers' not in state.get('completed_steps', [])

    def direct_verify_args(self, group, accepted=False):
        workspace=self.settings.get(group + '_direct_work', '')
        args={'workspace': workspace, 'accepted': accepted}
        if group=='factory':args.update(workspace=self.text('factory_failed_work') or workspace,factory_verify=True)
        return args

    def show_setup_result(self):
        from .completion import archive_error,text
        path=Path(self.settings.get('setup_work',''),'setup.private.json')
        if not path.is_file():return
        state=json.loads(path.read_text(encoding='utf-8'))
        if state.get('phase')!='COMPLETE':
            W.QMessageBox.information(self,'安装尚未结束','请点首页“继续安装”，按提示完成后续步骤。')
            return
        if archive_error(state):write_json(path,state)
        W.QMessageBox.information(self,'安装完成',text(state))

    def refresh_setup_controls(self):
        path=Path(self.settings.get('setup_work',''),'setup.private.json')
        state=json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
        pending=bool(state) and state.get('phase')!='COMPLETE'
        self.setup_button.setText('继续安装' if pending else '开始新的一键安装' if state else '一键安装')
        self.setup_result_button.setVisible(state.get('phase')=='COMPLETE')
        self.setup_note.setVisible(pending)
        self.setup_custom_container.setEnabled(not pending and not self.setup_presets.isChecked() and self.process is None)
        if not state:
            self.setup_preset_summary.setText(presets.SUMMARY)
            self.setup_preset_summary.setEnabled(self.setup_presets.isChecked())
        for box in (self.setup_presets,self.setup_fl23,self.setup_sound,self.setup_vertical,self.setup_plugin):
            box.setEnabled(not pending and self.process is None)

    def clear_installation_state(self, verified=True):
        # Clear active navigation/resume pointers, not diagnostic evidence or
        # user source files. A verified factory reset invalidates these plans.
        # Before verification only the sound records are retired: the restore
        # has already returned every sound program window to stock.
        if verified:
            for key in ('setup_work','fl23_direct_work','look_direct_work',
                        'look_resume_source','look_job_dir'):
                self.settings.pop(key,None)
            self._look_displayed_pending=None
            self.look_editor.set_operations([])
            self.fl23_accept.setChecked(False)
        self.sound_accept.setChecked(False)
        # The old sound workspace describes the pre-reset camera installation.
        # Start fresh while retaining its files and the selected source clip.
        sound=self.work('sound')
        for key,value in (('sound_work',sound),('sound_backup',sound+'-backup')):
            self.fields[key].setText(value);self.settings[key]=value
        write_json(data_root()/'desktop.json',self.settings)
        self.log.appendPlainText('原厂恢复已核对通过；已清除旧安装状态。历史诊断日志保留，新安装从头开始。' if verified else
                                 '原厂恢复写入已完成；旧的声音记录已停用（文件保留），之后的声音操作不再受它们影响。')

    def reload_controls(self, layout, checks):
        guide = W.QPushButton('如何断电重开？查看详细步骤')
        guide.clicked.connect(lambda: self.show_reload_guide())
        layout.addWidget(guide)
        self.buttons.append(guide)
        confirm = W.QCheckBox('已拔 USB、等灯停、关机，取下电池至少 1 分钟后重开；\n已确认' + checks)
        confirm.setToolTip(reloadguide.text())
        layout.addWidget(confirm)
        return confirm

    def show_reload_guide(self, *, setup=False, mode=None):
        title = ('恢复尚未完成，请重启后核对' if mode=='factory_reset' else
                 '试听结果已记录，请断电恢复原声' if mode=='sound_confirm' else '读写已结束，请断电重开')
        W.QMessageBox.information(self, title, reloadguide.text(setup=setup, mode=mode))

    def show_connection_notice(self):
        if '--legacy-usb' not in sys.argv:return
        W.QMessageBox.information(self,connectionguide.TITLE,connectionguide.TEXT)

    def field(self, form, key, label, *, kind=None, filter='All files (*)', value=''):
        line = W.QLineEdit(str(self.settings.get(key, value)))
        line.setObjectName(key)
        self.fields[key] = line
        if kind:
            row = W.QHBoxLayout()
            row.addWidget(line, 1)
            button = W.QPushButton('选择…')
            button.clicked.connect(lambda: self.browse(line, kind, filter))
            row.addWidget(button)
            form.addRow(label, row)
        else:
            form.addRow(label, line)
        return line

    def browse(self, field, kind, filter):
        if kind in ('folder','directory'):
            path = W.QFileDialog.getExistingDirectory(self, '选择目录', field.text())
        elif kind == 'save':
            path = W.QFileDialog.getSaveFileName(self, '保存文件', field.text(), filter)[0]
        else:
            path = W.QFileDialog.getOpenFileName(self, '选择文件', field.text(), filter)[0]
        if path:
            field.setText(path)

    def button(self, layout, text, action, arguments=lambda: {}, *, primary=False):
        button = W.QPushButton(text)
        button.setObjectName('action_' + action)
        button.setProperty('primary', primary)
        button.clicked.connect(lambda: self.launch(action, arguments()))
        layout.addWidget(button)
        self.buttons.append(button)
        return button

    def text(self, key):
        return self.fields[key].text().strip()

    def common(self):
        return {'firmware': self.firmware.currentText()}

    def work(self, label):
        return str(data_root() / 'work' / (datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + label + '-' + uuid.uuid4().hex[:5]))

    def connection_page(self):
        layout = self.page('安装驱动与 USB 连接', '相机开机并选择“海量存储／Mass Storage”，使用可传数据的 USB 线。一次只连接一台相机。')
        form = self.box(layout, 'USB 连接')
        self.driver_identity = W.QComboBox()
        self.driver_identity.addItems(['普通连接 · 054C:0E8A', '服务连接 · 054C:0336'])
        form.addRow('驱动目标', self.driver_identity)
        if sys.platform == 'darwin':
            self.field(form, 'mac_volume', 'macOS 相机存储卷', kind='folder', value='/Volumes/')
        self.button(layout, '检测相机与驱动', 'driver_scan')
        if sys.platform == 'win32':
            # Manual Zadig installation sits beside the automatic one: many
            # computers where the automatic install fails succeed with it.
            drivers = W.QHBoxLayout()
            layout.addLayout(drivers)
            self.button(drivers, '准备两阶段驱动并测试连接（自动）', 'usb_prepare', primary=True)
            zadig = W.QPushButton('用 Zadig 手动安装驱动（自动失败时）')
            zadig.setObjectName('zadig_guide')
            zadig.setProperty('primary', True)
            zadig.clicked.connect(self.show_zadig_guide)
            drivers.addWidget(zadig)
            self.buttons.append(zadig)
        else:
            self.button(layout, '准备 USB 服务连接', 'usb_prepare', primary=True)
        self.button(layout, '单独安装所选身份的驱动（高级）' if sys.platform == 'win32'
                    else '检查 USB 访问（macOS 无需 Zadig）', 'driver_install',
                    lambda: {'pid': ['0e8a', '0336'][self.driver_identity.currentIndex()]})
        if sys.platform == 'darwin':
            self.button(layout, '推出选中的相机存储卷', 'mac_unmount', lambda: {'volume': self.text('mac_volume')})
        self.button(layout, '测试服务连接（不写固件）', 'connect')
        self.button(layout, '检测 USB 连接稳定性（只读）', 'usb_stability')
        if sys.platform == 'win32':
            self.button(layout, '卸载相机驱动，恢复 Windows 默认连接', 'driver_uninstall',
                        lambda: {'pids': ['0e8a', '0336']})
        hint = W.QLabel('连接中断后先查看完整日志。报错不会触发重新刷写或自动重装驱动。')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch()

    def recovery_page(self):
        layout=self.page('一键恢复','通过 USB 恢复原厂功能；通过 SSH 修正更新器版本号。')
        self.recovery_transport=self.transport_controls(layout,'recovery')
        self.recovery_usb_panel=W.QWidget();self.recovery_usb_panel.setObjectName('recoveryUsbPanel')
        usb=W.QVBoxLayout(self.recovery_usb_panel);usb.setContentsMargins(0,0,0,0);usb.setSpacing(10)
        self.recovery_usb_controls(usb);layout.addWidget(self.recovery_usb_panel)
        self.recovery_ssh_panel=W.QWidget();self.recovery_ssh_panel.setObjectName('recoverySshPanel')
        ssh=W.QVBoxLayout(self.recovery_ssh_panel);ssh.setContentsMargins(0,0,0,0);ssh.setSpacing(10)
        self.recovery_ssh_controls(ssh);layout.addWidget(self.recovery_ssh_panel)
        self.recovery_transport.changed.connect(self.refresh_recovery_transport)
        self.refresh_recovery_transport();self.refresh_factory_controls()

    def refresh_recovery_transport(self):
        usb=self.recovery_transport.value()=='usb'
        self.recovery_usb_panel.setVisible(usb);self.recovery_ssh_panel.setVisible(not usb)

    def recovery_ssh_controls(self,layout):
        form=self.box(layout,'版本号修正 · SSH')
        self.field(form,'factory_version_source','当前研究版本',value='3.01')
        form.addRow('目标版本',W.QLabel('2.00'))
        row=W.QHBoxLayout();layout.addLayout(row)
        self.button(row,'通过 SSH 将版本号改回 2.00','ssh_restore_version',
            lambda:dict(self.ssh_update_args(),workspace=self.work('version-restore'),source_version=self.text('factory_version_source')),primary=True)
        settings=W.QPushButton('SSH 连接设置…');settings.clicked.connect(lambda:self.select_page(10))
        row.addWidget(settings);self.buttons.append(settings)
        note=W.QLabel('这里只修正版本号。原厂授信恢复入口在“首次授信”页，必须使用本机安装备份；实际官方卡刷仍待验收。')
        note.setWordWrap(True);layout.addWidget(note)
        self.button(layout,'重开后核对本次版本号修正','ssh_verify_update',
            lambda:dict(self.ssh_update_args(),workspace=self.settings.get('factory_version_work','')))
        optional=self.advanced(layout,'其他恢复工具 · 生成离线候选')
        form=self.box(optional,'原厂程序与资源来源')
        self.field(form,'factory_package_source','官方 2.01 BODYDATA.DAT',kind='file',filter='Sony firmware (*.DAT)')
        self.field(form,'factory_package_output','新的输出目录',value=self.work('factory-firmware'),kind='directory')
        self.button(optional,'生成原厂程序与资源恢复候选','firmware_factory_build',
            lambda:dict(sony_firmware=self.text('factory_package_source'),workspace=self.text('factory_package_output'),automatic_identity=True),primary=True)
        note=W.QLabel('恢复包包含完整原厂机身程序和资源。更新器公钥恢复与实际卡刷尚未验收；此入口只生成本地候选，不执行旧 USB 恢复。')
        note.setWordWrap(True);optional.addWidget(note);layout.addStretch()

    def recovery_usb_controls(self,layout):
        note=W.QLabel('恢复本项目功能：六槽回 ST、快门回机械、关闭静音模式和新增电子音效。保留机身校准；语音包可选择同时恢复。')
        note.setWordWrap(True);layout.addWidget(note)
        original=self.box(layout,'恢复来源（程序、设置及所选语音均从你的本地文件取得）')
        self.field(original,'factory_voice_firmware','官方 2.01 BODYDATA.DAT',kind='file',filter='Sony firmware (*.DAT *.bin);;All files (*)')
        self.field(original,'factory_original_backup','或：同机原始备份',kind='file',filter='Backup (*.zip);;All files (*)')
        source_notice=W.QLabel('应用不内置原厂恢复文件。为尊重版权、降低包括 DMCA 在内的法律风险，一键恢复需使用你自行取得的官方 2.01 固件，或可用的同机原始备份。'
            '普通安装不要求预先下载；这项说明适用于所有原厂恢复，不仅是语音包。')
        source_notice.setWordWrap(True);layout.addWidget(source_notice)
        local_config=data_root()/'local-recovery-source.private.json'
        if local_config.is_file():
            local_note=W.QLabel('本机测试：已配置本地原厂来源，以上留空也可恢复；手动选择文件优先，不跳过恢复与读回。')
            local_note.setWordWrap(True);layout.addWidget(local_note)
        download=W.QPushButton('打开索尼官方 2.01 固件下载页')
        from .screenreader import DOWNLOAD_URL
        download.clicked.connect(lambda:QtGui.QDesktopServices.openUrl(QtCore.QUrl(DOWNLOAD_URL)))
        layout.addWidget(download);self.buttons.append(download)
        self.factory_voice=W.QCheckBox('同时恢复无障碍语音包，并解除语音指南置灰')
        self.factory_voice.setChecked(True);layout.addWidget(self.factory_voice)
        voice_note=W.QLabel('勾选时补回语音文件并解除置灰；不勾选则不补回已删除的语音，已禁用的语音指南保持关闭、置灰。')
        voice_note.setWordWrap(True);layout.addWidget(voice_note)
        self.factory_button=W.QPushButton('开始一键恢复')
        self.factory_button.setObjectName('factoryPrimaryAction');self.factory_button.setProperty('primary',True)
        self.factory_button.clicked.connect(self.factory_action)
        layout.addWidget(self.factory_button);self.buttons.append(self.factory_button)
        self.factory_status=W.QLabel('点击开始；写入后按提示重启，再点同一个按钮继续完成恢复。')
        self.factory_status.setWordWrap(True);layout.addWidget(self.factory_status)
        resume_section = self.advanced(layout, '上次恢复记录（可选）')
        resume_form = W.QFormLayout()
        self.field(resume_form, 'factory_failed_work', '恢复任务目录', kind='folder',value=self.settings.get('factory_direct_work', ''))
        resume_section.addLayout(resume_form)
        self.factory_wait_controls=W.QWidget()
        wait_layout=W.QVBoxLayout(self.factory_wait_controls);wait_layout.setContentsMargins(0,0,0,0)
        self.factory_accept = self.reload_controls(wait_layout, '取景、拍照和回放正常')
        layout.addWidget(self.factory_wait_controls)
        layout.addWidget(W.QLabel('相机仍需能够进入 USB 服务通信；此操作不是索尼更新器的降级重刷。'))
        backup = self.advanced(layout, '备份当前项目状态（可选）')
        backup_form=W.QFormLayout()
        self.field(backup_form,'backup_folder','保存位置',kind='folder',value=str(data_root()/'backups'))
        self.backup_voice=W.QCheckBox('同时备份语音指南音频（约 287 MiB，耗时较长）')
        backup_form.addRow('',self.backup_voice);backup.addLayout(backup_form)
        self.button(backup,'备份当前程序、外观、设置和名称（只读）','backup_current',
            lambda:dict(self.common(),workspace=str(Path(self.text('backup_folder'))/
                ('backup-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6])),
                include_voice=self.backup_voice.isChecked()))
        backup_note=W.QLabel('保存创建时的当前项目状态，可能已修改；不是原厂基准或完整相机镜像。'
            '项目检查点可用下方“使用旧备份”入口恢复；语音包另存，不包含在当前项目还原范围内。'
            '安装和一键恢复无需先备份。')
        backup_note.setWordWrap(True);backup.addWidget(backup_note)
        legacy = self.advanced(layout, '使用旧备份回到过去的状态（可选）')
        self.backup_recovery_controls(legacy)
        layout.addStretch()

    def factory_state(self):
        work=self.text('factory_failed_work') or self.settings.get('factory_direct_work','')
        path=Path(work,'direct.private.json') if work else None
        try:state=json.loads(path.read_text(encoding='utf-8')) if path and path.is_file() else {}
        except (OSError,ValueError):state={}
        return state if isinstance(state,dict) else {}

    def factory_action(self):
        state=self.factory_state()
        waiting=state.get('phase') in ('AWAITING_RELOAD','LOADED','COMPLETE') and not (
            state.get('readonly_after_reload_verified') and state.get('private_sound_files_removed'))
        if waiting:
            args=self.direct_verify_args('factory',self.factory_accept.isChecked())
            args.update(sony_firmware=self.text('factory_voice_firmware') or None,
                backup=self.text('factory_original_backup') or None)
            self.launch('direct_verify',args)
        else:
            from .official import local_recovery_source
            if not (self.text('factory_voice_firmware') or self.text('factory_original_backup') or local_recovery_source()):
                W.QMessageBox.information(self,'请选择恢复来源','请先选择官方 ILCE-7CM2 2.01 BODYDATA.DAT，或可用的同机原始备份；程序、设置及所选语音均从该来源取得。')
                return
            self.launch('direct_factory_reset',self.direct_args('factory',
                sony_firmware=self.text('factory_voice_firmware') or None,
                backup=self.text('factory_original_backup') or None,restore_voice=self.factory_voice.isChecked()))

    def refresh_factory_controls(self):
        state=self.factory_state();phase=state.get('phase')
        waiting=phase in ('AWAITING_RELOAD','LOADED','COMPLETE') and not (
            state.get('readonly_after_reload_verified') and state.get('private_sound_files_removed'))
        self.factory_button.setText('继续完成一键恢复' if waiting else '开始一键恢复')
        self.factory_wait_controls.setVisible(waiting)
        self.factory_voice.setEnabled(not waiting)
        if waiting:
            self.factory_voice.setChecked(state.get('restore_voice',True))
            self.factory_status.setText('恢复尚未完成：写入已结束。请按提示重启、接回 USB，然后点击上面的“继续完成一键恢复”；不会重复刷写程序。')
        elif phase in ('LOADED','COMPLETE'):
            self.factory_status.setText('上次恢复已完成'+('，按本次选择保留语音禁用及置灰。' if state.get('restore_voice') is False else '。')+
                '机身取景、拍照与回放仍请实际检查。')
        elif phase=='NEEDS_REVIEW':
            self.factory_status.setText('上次操作未完成或尚未开始，日志已保留。选择恢复来源后，点击“开始一键恢复”。')
        else:self.factory_status.setText('点击开始；写入后按提示重启，再点同一个按钮继续完成恢复。')

    def backup_recovery_controls(self, layout):
        form = self.box(layout, '恢复来源')
        self.field(form, 'restore_backup', '备份目录', kind='folder')
        choose_zip = W.QPushButton('或选择完整备份 ZIP…')
        choose_zip.clicked.connect(lambda: self.browse(self.fields['restore_backup'], 'file', 'Backup (*.zip);;All files (*)'))
        form.addRow('', choose_zip)
        self.field(form, 'restore_work', '恢复任务目录', kind='folder', value=self.work('recovery'))
        self.button(layout, '检查所选备份（离线）', 'backup_inspect', lambda: {'backup': self.text('restore_backup')})
        auto = W.QPushButton('一键还原：查找并使用最初完整备份')
        auto.setObjectName('one_click_restore')
        auto.clicked.connect(self.one_click_restore)
        self.buttons.append(auto)
        layout.addWidget(auto)
        self.button(layout, '恢复所选备份并完整读回', 'restore', lambda: dict(self.common(),
            backup=self.text('restore_backup'), workspace=self.text('restore_work'),
            sony_firmware=self.text('factory_voice_firmware') or None), primary=True)
        self.recovery_accept = self.reload_controls(layout, '恢复后取景、拍照和回放正常')
        self.button(layout, '核对旧备份恢复后的加载状态', 'restore_verify', lambda: {
            'workspace': self.text('restore_work'), 'accepted': self.recovery_accept.isChecked()})
        note = W.QLabel('相机需要仍可进入服务通信。此入口使用机身备份；不把官方 BODYDATA.DAT 当作备份刷入。')
        note.setWordWrap(True)
        layout.addWidget(note)

    def fl23_page(self):
        layout = self.page('FL2 / FL3', '直接启用／移除，不要求创建备份。移除只关闭 FL2／FL3 的列表入口，保留自定义外观所需的共用色彩代码；之后可以重新启用。')
        self.button(layout, '启用／重新启用 FL2 / FL3', 'direct_fl23_enable',
                    lambda: self.direct_args('fl23', mode='fl23_enable'), primary=True)
        self.button(layout, '从列表移除 FL2 / FL3，保留自定义外观', 'direct_fl23_disable',
                    lambda: self.direct_args('fl23', mode='fl23_disable'))
        info = W.QLabel('写入读回后按弹窗断电重开，在相机确认即可使用；无需再接电脑核对。')
        info.setWordWrap(True); layout.addWidget(info)
        diagnostic = self.advanced(layout, '加载核对（可选诊断，不是使用前提）')
        self.fl23_accept = self.reload_controls(diagnostic, '菜单、拍照和回放正常')
        self.button(diagnostic, '只读核对已加载的版本（可选）', 'direct_verify',
                    lambda: self.direct_verify_args('fl23', self.fl23_accept.isChecked()))
        if '--preview-gate-test' in sys.argv:
            preview = layout
            preview.addWidget(W.QLabel('取景器横线＋实时预览：第 3 版候选（等待实机验收）'))
            hint = W.QLabel('第 1 版横线消失，但切槽预览可能停在上一个外观。第 3 版补传未提交的色表，'
                           '并修正第 2 版的重复上传问题。应用后按弹窗断电重开，再检查横线和六槽切换。')
            hint.setWordWrap(True); preview.addWidget(hint)
            self.button(preview, '应用横线＋实时预览修复候选（第 3 版）', 'direct_preview_pending',
                        lambda: self.direct_args('preview'), primary=True)
            self.button(preview, '切回第 1 版：原生刷新（预览可能滞留）', 'direct_preview_native',
                        lambda: self.direct_args('preview'))
            self.button(preview, '撤回测试：恢复旧版刷新方式', 'direct_preview_legacy',
                        lambda: self.direct_args('preview'))
            self.preview_accept = self.reload_controls(preview, '横线消失、六槽实时切换、拍摄和回放正常')
            self.button(preview, '断电重开后只读核对本轮测试', 'direct_verify',
                        lambda: self.direct_verify_args('preview', self.preview_accept.isChecked()))
        layout.addStretch()

    def firmware_args(self):
        from looktool import bundle
        use_custom=self.local_looks.isChecked() and self.local_custom_looks.isChecked()
        errors=self.firmware_look_editor.errors() if use_custom else []
        if errors:raise ValueError(' '.join(errors))
        custom=[{k:v for k,v in row.items() if k!='action'} for row in self.firmware_look_editor.values()] if use_custom else []
        if custom:bundle.documents(dict(looks=custom),allow_menu_icons=True)
        return dict(sony_firmware=self.text('firmware_source'),workspace=self.text('firmware_output'),
                    update_version=self.text('firmware_update_version'),
                    fl23=self.local_fl23.isChecked(),whitebalance=self.local_wb.isChecked(),
                    sound=self.local_sound.isChecked(),ssh=self.local_ssh.isChecked(),
                    custom_looks=self.local_looks.isChecked(),vertical=self.local_vertical.isChecked(),
                    precapture=False,voice_cleanup=True,
                    automatic_identity=True,
                    looks=custom,
                    preset_pack=presets.PACK if self.local_looks.isChecked() and self.local_presets.isChecked() else None)

    def firmware_page(self):
        layout=self.page('本地修改官方固件',
            '选择功能，在电脑生成固件。签名材料由应用自动管理。')
        form=self.box(layout,'来源与输出')
        self.field(form,'firmware_source','官方 A7C II 2.01 BODYDATA.DAT',kind='file',filter='Sony firmware (*.DAT);;All files (*)')
        self.field(form,'firmware_output','新的输出目录',value=self.work('local-firmware'),kind='directory')
        self.field(form,'firmware_update_version','更新头版本',value='3.10')
        page_layout=layout
        layout=self.card(page_layout,'固件功能');layout.setSpacing(2)
        self.local_fl23=W.QCheckBox('加入 FL2／FL3');self.local_fl23.setChecked(True)
        self.local_wb=W.QCheckBox('加入自动白平衡优化');self.local_wb.setChecked(True)
        self.local_sound=W.QCheckBox('加入快门音效与自定义声音支持');self.local_sound.setChecked(True)
        self.local_looks=W.QCheckBox('应用自定义外观');self.local_looks.setChecked(True)
        self.local_vertical=W.QCheckBox('加入竖屏显示资源');self.local_vertical.setChecked(True)
        self.local_voice=W.QCheckBox('删除无障碍语音音频并禁用语音指南（必选，保留索引）')
        self.local_voice.setChecked(True);self.local_voice.setEnabled(False)
        self.local_ssh=W.QCheckBox('加入索尼云创内置接口');self.local_ssh.setChecked(True)
        self.local_ssh.setToolTip('需要先应用自定义外观。')
        layout.addWidget(self.local_looks)
        self.local_looks_panel=W.QFrame();self.local_looks_panel.setProperty('subpanel',True)
        looks=W.QVBoxLayout(self.local_looks_panel);looks.setContentsMargins(16,12,16,14);looks.setSpacing(10)
        choices=W.QHBoxLayout();choices.setSpacing(22)
        self.local_presets=W.QRadioButton('使用默认六款')
        self.local_custom_looks=W.QRadioButton('自选外观')
        self.local_look_choices=W.QButtonGroup(self.local_looks_panel)
        for index,button in enumerate((self.local_presets,self.local_custom_looks)):
            self.local_look_choices.addButton(button,index);choices.addWidget(button)
        self.local_presets.setChecked(True);choices.addStretch();looks.addLayout(choices)
        self.local_default_looks=W.QWidget();default_box=W.QVBoxLayout(self.local_default_looks)
        default_box.setContentsMargins(0,0,0,0);default_box.setSpacing(6)
        self.local_preset_summary=W.QLabel('默认包含以下六款，依次应用到槽位 1–6：')
        self.local_preset_summary.setProperty('note',True);default_box.addWidget(self.local_preset_summary)
        names=W.QGridLayout();names.setHorizontalSpacing(20);names.setVerticalSpacing(5)
        for index,name in enumerate(presets.NAMES):
            label=W.QLabel('%d · %s'%(index+1,name));label.setWordWrap(True)
            label.setObjectName('firmwareDefaultLookName%d'%(index+1))
            names.addWidget(label,index//2,index%2)
        names.setColumnStretch(0,1);names.setColumnStretch(1,1);default_box.addLayout(names)
        looks.addWidget(self.local_default_looks)
        self.local_custom_looks_panel=W.QWidget();custom_box=W.QVBoxLayout(self.local_custom_looks_panel)
        custom_box.setContentsMargins(0,0,0,0);custom_box.setSpacing(8)
        from .lookeditor import LookEditor
        self.firmware_look_editor=LookEditor(write_only=True,for_firmware=True);custom_box.addWidget(self.firmware_look_editor)
        custom_note=W.QLabel('外观文件中附带的菜单图标会一同加入固件；未选择的槽位使用原生 ST。')
        custom_note.setWordWrap(True);custom_note.setProperty('note',True);custom_box.addWidget(custom_note)
        looks.addWidget(self.local_custom_looks_panel)
        panel_row=W.QHBoxLayout();panel_row.setContentsMargins(48,4,0,8);panel_row.addWidget(self.local_looks_panel)
        layout.addLayout(panel_row)
        def refresh_looks():
            on=self.local_looks.isChecked()
            self.local_looks_panel.setVisible(on);self.local_looks_panel.setEnabled(on)
            self.local_default_looks.setVisible(on and self.local_presets.isChecked())
            self.local_custom_looks_panel.setVisible(on and self.local_custom_looks.isChecked())
        def custom_changed(checked):
            self.local_ssh.setEnabled(checked)
            if not checked:self.local_ssh.setChecked(False)
            refresh_looks()
        self.local_looks.toggled.connect(custom_changed)
        self.local_look_choices.idToggled.connect(lambda _index,_checked:refresh_looks())
        refresh_looks()
        for item in (self.local_voice,self.local_fl23,self.local_wb,self.local_sound,
                     self.local_vertical,self.local_ssh):layout.addWidget(item)
        layout=page_layout
        note=W.QLabel('Wi-Fi 就绪后自动提供云创接口。首次机身授信与实际卡刷仍待验证。')
        note.setWordWrap(True);layout.addWidget(note)
        layout.addSpacing(6)
        self.button(layout,'生成本地固件候选（不访问相机）','firmware_build',self.firmware_args,primary=True)
        layout.addStretch()

    def trust_page(self):
        layout=self.page('首次授信','通过 USB 安装本应用公钥与验签策略，然后在电脑生成固件、手动卡刷。签名私钥留在电脑。')
        note=W.QLabel('安装前读取并保存本机原始更新器；仅修改公钥与四个验签库所在范围，逐批及整分区读回。'
            '当前已通过离线与虚拟机测试，实机授信及完整卡刷尚未验收。')
        note.setWordWrap(True);layout.addWidget(note)
        self.trust_install_button=self.button(layout,'通过 USB 安装机身公钥','firmware_trust_install',
            lambda:dict(workspace=self.work('trust-install')),primary=True)
        form=self.box(layout,'安装记录与恢复')
        self.field(form,'trust_record','首次安装备份记录',value=self.settings.get('trust_install_work',''),kind='directory')
        self.trust_verify_button=self.button(layout,'断电重开后，通过 USB 核对','firmware_trust_verify',
            lambda:dict(workspace=self.work('trust-verify'),source_workspace=self.trust_verify_source()))
        self.trust_restore_button=self.button(layout,'通过 USB 恢复本机原厂授信','firmware_trust_restore',
            lambda:dict(workspace=self.work('trust-restore'),source_workspace=self.text('trust_record')))
        self.trust_state=W.QLabel();self.trust_state.setWordWrap(True);layout.addWidget(self.trust_state)
        advanced=W.QGroupBox('开发工具 · 离线准备');advanced.setCheckable(True);advanced.setChecked(False);advanced.setProperty('optional',True)
        self.trust_advanced=advanced
        advanced_layout=W.QVBoxLayout(advanced);layout.addWidget(advanced)
        content=W.QWidget();advanced_layout.addWidget(content);offline=W.QVBoxLayout(content)
        content.setVisible(False);advanced.toggled.connect(content.setVisible)
        form=self.box(offline,'仅用于已有解包文件')
        self.field(form,'trust_source','本机更新器解包目录',kind='directory')
        self.fields['trust_source'].setPlaceholderText('选择包含 usr/lib 下四个更新器库的解包根目录')
        self.field(form,'trust_output','新的输出目录',value=self.work('first-trust'),kind='directory')
        self.trust_prepare_button=self.button(offline,'在电脑准备公钥与策略文件','firmware_trust_prepare',
            lambda:dict(updater_root=self.text('trust_source'),workspace=self.text('trust_output')))
        self.trust_hint=W.QLabel();self.trust_hint.setWordWrap(True);offline.addWidget(self.trust_hint)
        for key in ('trust_source','trust_output','trust_record'):self.fields[key].textChanged.connect(self.refresh_trust_controls)
        self.refresh_trust_controls();layout.addStretch()

    def trust_verify_source(self):
        original=self.text('trust_record')
        return self.settings.get('trust_latest_work',original) if original==self.settings.get('trust_install_work') else original

    def refresh_trust_controls(self):
        from .firmwaretrust import validate
        try:
            validate(dict(updater_root=self.text('trust_source'),workspace=self.text('trust_output')))
            hint='文件来源已找到。此按钮仅在电脑生成离线文件，不写入相机，也不表示机身授信完成。'
            ready=True
        except (ValueError,OSError) as exc:
            hint=str(exc);ready=False
        self.trust_hint.setText(hint)
        self.trust_prepare_button.setEnabled(ready and self.process is None)
        origin=Path(self.text('trust_record'))
        try:
            from .trustinstall import STATE
            state=json.loads((origin/STATE).read_text(encoding='utf-8')) if self.text('trust_record') else {}
            restorable=state.get('mode')=='trust_install' and state.get('backup_verified',False)
            latest=json.loads((Path(self.trust_verify_source())/STATE).read_text(encoding='utf-8')) if self.trust_verify_source() else {}
        except (OSError,ValueError):state={};latest={};restorable=False
        idle=self.process is None
        restored=latest.get('mode')=='trust_restore' and latest.get('phase')=='LOADED'
        self.trust_install_button.setEnabled(idle and not (restorable and state.get('write_attempted') and not restored))
        self.trust_restore_button.setEnabled(idle and restorable)
        self.trust_verify_button.setEnabled(idle and latest.get('phase')=='AWAITING_RELOAD')
        self.trust_state.setText('记录状态：'+latest.get('phase',state.get('phase','尚无安装记录'))+
            '。分区读回及重开核对不等于完整卡刷验收。')

    def whitebalance_page(self):
        layout = self.page('自动白平衡优先级（实验）',
            '参考 R5 的白色优先 97／气氛优先 −1，适配 A7C II 2.01 的原生修正链。标准 AWB 不变；机内仍可选择三种优先级。')
        note = W.QLabel('已通过原厂指令离线对照，尚未验证实拍效果。此开关独立于创意外观，不会随一键安装自动开启。'
            '保留机身校准、手动色温和白平衡微调；关闭后重新使用本机原有优先级参数。')
        note.setWordWrap(True); layout.addWidget(note)
        self.button(layout, '启用白平衡优先级实验', 'direct_wb_enable',
                    lambda: self.direct_args('wb'), primary=True)
        self.button(layout, '关闭实验，恢复原生白平衡优先级', 'direct_wb_disable',
                    lambda: self.direct_args('wb'))
        self.wb_accept = self.reload_controls(layout, '已检查白平衡、取景、拍摄和回放')
        self.button(layout, '重开后核对本次白平衡更改', 'direct_verify',
                    lambda: self.direct_verify_args('wb', self.wb_accept.isChecked()))
        layout.addStretch()

    def ssh_update_args(self,**values):
        baseline=self.text('ssh_update_baseline')
        public=Path(baseline).parent/'ssh/host-public.json' if baseline else None
        return dict(self.common(),workspace=self.text('ssh_update_work'),baseline=self.text('ssh_update_baseline'),
                    host_public=str(public) if public and public.is_file() else None,bind_ip=self.text('ssh_update_ip'),
                    client_private=None,previous_look_update=self.settings.get('look_ssh_work'),**values)

    def ssh_updates_page(self):
        layout=self.page('连接设置','滤镜、快门音效和一键恢复共用这里的连接信息，在各自页面选择 SSH 或 USB。')
        form=self.box(layout,'SSH · Wi-Fi 连接')
        self.field(form,'ssh_update_ip','相机 Wi-Fi IPv4')
        form.addRow('登录信息',W.QLabel('root / A7C2Tools · 端口 2222（自动登录）'))
        self.button(layout,'测试 SSH 连接','ssh_connect',self.ssh_update_args,primary=True)
        note=W.QLabel('相机固件需包含索尼云创内置接口。开启相机 Wi-Fi 后连接；关闭 Wi-Fi 后服务自动停止。')
        note.setWordWrap(True);layout.addWidget(note)
        usb=self.box(layout,'USB · 线刷连接')
        usb.addRow(W.QLabel('相机开机，USB 连接模式选择“海量存储”。'))
        row=W.QHBoxLayout();usb.addRow(row)
        self.button(row,'检测相机与驱动','driver_scan')
        driver=W.QPushButton('USB 驱动安装与连接工具…')
        driver.clicked.connect(lambda:self.select_page(1));row.addWidget(driver);self.buttons.append(driver)
        advanced=self.advanced(layout,'滤镜构建记录')
        form=self.box(advanced,'SSH 批量滤镜更新')
        self.field(form,'ssh_update_baseline','本地固件的 baseline 目录',kind='directory')
        self.field(form,'ssh_update_work','本次更新目录',value=self.work('ssh-update'),kind='directory')
        layout.addStretch()

    def transport_controls(self,layout,key):
        row=W.QHBoxLayout();row.addWidget(W.QLabel('连接方式'))
        choice=TransportChoice(key)
        row.addWidget(choice);row.addStretch()
        settings=W.QPushButton('连接设置…');settings.clicked.connect(lambda:self.select_page(10))
        row.addWidget(settings);self.buttons.append(settings);layout.addLayout(row)
        return choice

    def ssh_args(self):
        return dict(self.common(), workspace=self.text('ssh_work'),
                    client_key=self.text('ssh_public_key'), client_private=self.text('ssh_private_key'),
                    bind_ip=self.text('ssh_ip'), artifacts=self.text('ssh_artifacts'),
                    listen_all=self.ssh_listen_all.isChecked())

    def ssh_page(self):
        layout = self.page('临时 SSH 开发调试',
            '通过 USB 启动独立 Dropbear，Wi-Fi 登录端口 2222。只在内存运行，不修改原厂 SSH、系统账号或开机配置。')
        form = self.box(layout, '会话与电脑端密钥')
        self.field(form, 'ssh_work', '会话目录', value=self.work('ssh'), kind='directory')
        self.field(form, 'ssh_ip', '相机 Wi-Fi IPv4')
        self.field(form, 'ssh_public_key', '电脑端 Ed25519 公钥', kind='file', filter='SSH public key (*.pub);;All files (*)')
        self.field(form, 'ssh_private_key', '电脑端配对私钥（仅登录核对）', kind='file')
        self.field(form, 'ssh_artifacts', 'Dropbear 资源目录', value=str(ROOT / 'desktop-assets/ssh'), kind='directory')
        self.ssh_listen_all = W.QCheckBox('监听全部相机接口（USB 退出后再连接 Wi-Fi 时使用）')
        layout.addWidget(self.ssh_listen_all)
        note = W.QLabel('先连接相机 Wi-Fi 并记下 IP，在电脑生成或选择 Ed25519 密钥。公钥会用于相机登录，私钥只留在电脑。'
            '离线准备 → 接回 USB 并启动 → 拔 USB、保持相机开机和 Wi-Fi 连接 → 核对 SSH 登录。'
            '查询和停止使用 USB；断电后临时服务失效。实机 Wi-Fi／休眠待验收，当前不提供持久启动。')
        note.setWordWrap(True); layout.addWidget(note)
        fresh = W.QPushButton('使用新的会话目录')
        fresh.clicked.connect(lambda: self.fields['ssh_work'].setText(self.work('ssh')))
        layout.addWidget(fresh); self.buttons.append(fresh)
        self.button(layout, '离线准备临时 SSH', 'ssh_prepare', self.ssh_args)
        self.button(layout, '通过 USB 启动临时 SSH', 'ssh_start', self.ssh_args, primary=True)
        self.button(layout, '通过 USB 查询当前会话', 'ssh_status', self.ssh_args)
        self.button(layout, '通过 Wi-Fi 核对 SSH 登录', 'ssh_verify_login', self.ssh_args)
        self.button(layout, '通过 USB 停止临时 SSH', 'ssh_stop', self.ssh_args)
        layout.addStretch()

    def look_page(self):
        from .lookeditor import LookEditor
        layout=self.page('滤镜','选择槽位、名称和 A7Look 文件，批量应用；DCP／LUT 转换在电脑完成。')
        self.look_transport=self.transport_controls(layout,'look')
        self.look_pending=W.QLabel();self.look_pending.setWordWrap(True);self.look_pending.setProperty('callout',True);layout.addWidget(self.look_pending)
        self.look_editor=LookEditor();layout.addWidget(self.look_editor)
        self.look_button=W.QPushButton('添加操作项后继续');self.look_button.setProperty('primary',True)
        self.look_button.setObjectName('action_direct_looks_import');self.look_button.clicked.connect(self.launch_look_changes)
        layout.addWidget(self.look_button);self.buttons.append(self.look_button)
        tools=W.QHBoxLayout();layout.addLayout(tools)
        for title,callback in [('打开内置 DCP／A7Look 配对库',self.open_profile_library),('从 DCP／LUT 生成 A7Look＋DCP…',self.compiler_dialog),('安装 LrC 自动识别插件…',self.plugin_dialog)]:
            button=W.QPushButton(title);button.clicked.connect(callback);tools.addWidget(button);self.buttons.append(button)
        formats=W.QPushButton('LUT 格式说明：ST / sRGB，不是 S-Log3…')
        formats.clicked.connect(self.show_look_format_guide);layout.addWidget(formats);self.buttons.append(formats)
        layout.addWidget(W.QLabel('写入页选择 .a7look；.cube / .dcp 先用上方工具转换。仅更改清单内的槽位。'))
        self.look_help=W.QLabel();self.look_help.setWordWrap(True);layout.addWidget(self.look_help)
        self.look_verify_button=self.button(layout,'SSH · 重开后核对上次滤镜更新','ssh_verify_update',
                    lambda:dict(self.ssh_update_args(),workspace=self.settings.get('look_ssh_work','')))
        layout.addStretch()
        self._look_displayed_pending=None;self._look_refreshing=False
        self.look_editor.changed.connect(self.refresh_look_controls)
        self.look_transport.changed.connect(self.refresh_look_controls)
        self.refresh_look_controls()

    def open_profile_library(self):
        from .profilelibrary import location
        folder=location()
        if not (folder/'catalog.json').is_file():
            W.QMessageBox.warning(self,'配对库缺失','没有找到内置 DCP／A7Look 配对库，请保留完整测试包目录。\n查找位置：'+str(folder));return
        if not QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(folder))):
            W.QMessageBox.warning(self,'无法打开配对库','系统未能打开配对库文件夹。位置：\n'+str(folder))

    def look_pending_state(self):
        prior=self.settings.get('look_direct_work')
        if not prior:return None
        try:
            job=self.settings.get('look_job_dir')
            if job and Path(job,'status.private.json').is_file():
                status=json.loads(Path(job,'status.private.json').read_text(encoding='utf-8'))
                request=json.loads(Path(job,'request.private.json').read_text(encoding='utf-8'))
                matches=prior in (request.get('arguments',{}).get('workspace'),status.get('result',{}).get('workspace'))
                if matches and status.get('phase')=='SUCCEEDED':
                    prior=status['result']['workspace']
                elif matches and status.get('phase') in ('RUNNING','QUEUED') and self.process is None:
                    return prior,dict(phase='BACKGROUND_UNCONFIRMED',error='后台任务尚未确认结束，请等待原结果或查看日志，不重复写入。')
            if not Path(prior,'direct.private.json').is_file():
                prior=self.settings.get('look_resume_source')
                if not prior or not Path(prior,'direct.private.json').is_file():return None
            state=json.loads(Path(prior,'direct.private.json').read_text(encoding='utf-8'))
            nested=Path(prior,'program-install/direct.private.json')
            if state.get('phase')=='RESOURCE_RELOAD_VERIFIED' and nested.is_file():
                prior=str(nested.parent);state=json.loads(nested.read_text(encoding='utf-8'))
        except (ValueError,OSError,KeyError) as exc:return str(prior),dict(phase='UNREADABLE',error=str(exc))
        return None if state.get('phase') in ('AWAITING_RELOAD','LOADED','COMPLETE') else (prior,state)

    def refresh_look_controls(self):
        if self._look_refreshing:return
        self._look_refreshing=True
        try:
            pending=self.look_pending_state();busy=self.process is not None
            self.look_transport.setEnabled(not busy and not pending)
            if pending:self.look_transport.select('usb')
            ssh=self.look_transport.value()=='ssh'
            self.look_verify_button.setVisible(ssh)
            self.look_help.setText('先在连接设置中选择这台相机的固件构建记录。应用后按提示断电重开，再核对本次更新。' if ssh else
                '同一次操作自动检查当前状态、写入并完整读回。结束后按弹窗断电加载，无需单独点击核对。')
            if not pending and self.look_transport.value()=='ssh':
                rows=self.look_editor.values();busy=self.process is not None
                self.look_pending.hide();self.look_editor.setEnabled(not busy)
                self.look_button.setText('通过 SSH 应用这 %d 项更改'%len(rows) if rows else '添加操作项后继续')
                self.look_button.setEnabled(bool(rows) and not self.look_editor.errors() and not busy)
                return
            if pending:
                prior,state=pending;phase=state.get('phase')
                token=(prior,phase)
                if self._look_displayed_pending!=token:
                    options=state.get('bundle_options',{});by_slot={r['slot']:r for r in options.get('looks',[])}
                    operations=options.get('slot_operations') or [dict(r,action='write') for r in by_slot.values()]+[dict(slot=n,action='restore') for n in options.get('reset_slots',[])]
                    if not operations and state.get('mode')=='slot_default':operations=[dict(slot=state['slot'],action='restore')]
                    if not operations and state.get('mode')=='look_import':operations=[dict(slot=state['slot'],action='write',path=str(Path(prior)/'reference.a7look'),name=state.get('name') or '')]
                    operations=[dict(r,**{k:v for k,v in by_slot.get(r['slot'],{}).items() if k!='slot'}) if r.get('action')=='write' else r for r in operations]
                    self.look_editor.set_operations(operations);self._look_displayed_pending=token
                self.look_editor.setEnabled(False);self.look_button.setEnabled(not busy)
                if phase in ('AWAITING_RESOURCE_RELOAD','RESOURCE_RELOAD_VERIFIED') or (phase=='NEEDS_REVIEW' and state.get('forward_name_build',{}).get('stream_install') and 'readonly=-16' in state.get('error','')):
                    text='上次操作正在等待资源续接，将沿用已保存的清单。'
                    self.look_button.setText('继续槽位更改')
                else:
                    from .lookbatch import read_only_failure
                    if read_only_failure(state):
                        text='上次在写入前停止，旧记录已保留；可以调整清单后重试。'
                        self.look_editor.setEnabled(not busy)
                        self.look_button.setText('重试本次更改（上次未写入）')
                        self.look_button.setEnabled(not busy and bool(self.look_editor.values()) and not self.look_editor.errors())
                    else:
                        text='上次操作尚未完成；请查看原任务记录，不自动重复写入。'
                        self.look_button.setText('查看未完成任务记录')
                self.look_pending.setText(text);self.look_pending.show()
            else:
                if self._look_displayed_pending is not None:
                    self._look_displayed_pending=None;self.look_editor.set_operations([])
                self.look_pending.hide();self.look_editor.setEnabled(not busy)
                rows=self.look_editor.values()
                self.look_button.setText('查看并应用这 %d 项更改'%len(rows) if rows else '添加操作项后继续')
                self.look_button.setEnabled(bool(rows) and not self.look_editor.errors() and not busy)
        finally:self._look_refreshing=False

    def look_batch_args(self):
        return self.direct_args('look',operations=self.look_editor.values())

    def launch_look_changes(self):
        if not self.look_pending_state() and self.look_transport.value()=='ssh':
            self.launch('ssh_save_looks',dict(self.ssh_update_args(),workspace=self.work('ssh-look'),operations=self.look_editor.values()))
            return
        pending=self.look_pending_state()
        if pending:
            prior,state=pending;phase=state.get('phase')
            if phase in ('AWAITING_RESOURCE_RELOAD','RESOURCE_RELOAD_VERIFIED') or (phase=='NEEDS_REVIEW' and state.get('forward_name_build',{}).get('stream_install') and 'readonly=-16' in state.get('error','')):
                self.launch('direct_resume_looks',dict(self.common(),workspace=self.work('look'),failed_workspace=prior));return
            from .lookbatch import read_only_failure
            if read_only_failure(state):
                self.launch('direct_looks_import',self.look_batch_args());return
            W.QMessageBox.warning(self,'上次任务尚未完成',state.get('error','请保留原记录，核对未知结果后再继续。')+'\n任务目录：'+prior)
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(prior));return
        self.launch('direct_looks_import',self.look_batch_args())

    def vertical_page(self):
        layout = self.page('竖屏显示', '竖握相机时，拍摄信息、图标和布局跟随转向。开启会保存原生开关，断电重开后自动生效；不是整个 MENU 转向。')
        form = self.box(layout, '显示任务')
        self.field(form, 'vertical_work', '任务目录', kind='folder', value=str(data_root() / 'vertical'))
        args = lambda: dict(self.common(), workspace=self.text('vertical_work'))
        self.button(layout, '开启竖屏显示', 'vertical_enable', args, primary=True)
        self.button(layout, '关闭竖屏显示', 'vertical_disable', args)
        frame_hint=W.QLabel('采用与 M4 相同的原生资源分流：横／竖屏各自读取独立资源，保留原图像 ID 和原生刻度绘制。'
            '从旧版升级时先撤回补偿并按提示重开，再点开启继续；新竖屏资源完整复制与读回后才保存开启。'
            '资源约占 28 MiB，空间不足会停止；可在恢复页选择清理语音，工具不会自动删除。')
        frame_hint.setWordWrap(True);layout.addWidget(frame_hint)
        known=W.QLabel('当前为原生竖屏路径候选，尚未真机验收。重开后请检查横握／两侧竖握的 Fn、外框、橙色指针、触摸／按键方向及拍摄回放。')
        known.setWordWrap(True);layout.addWidget(known)
        hint = W.QLabel('开启／关闭会一次完成所选写入和读回，再统一弹窗提示断电加载。相同状态可重复点击，相同内容不重复写入。')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch()

    def sound_page(self):
        layout = self.page('快门音效', '在电脑导入、生成、试听和调整音量，再通过 SSH 或 USB 应用到相机。')
        self.sound_transport=self.transport_controls(layout,'sound')
        outer=layout;columns=W.QHBoxLayout();columns.setSpacing(14);outer.addLayout(columns)
        prepare=self.card(columns,'1 · 在电脑准备声音',stretch=1);apply=self.card(columns,'2 · 应用自定义声音',stretch=1)
        for column in (prepare,apply):column.setProperty('fill',True)
        layout=prepare
        args = lambda: dict(self.common(), workspace=self.text('sound_work'), backup=self.text('sound_backup'))
        media = W.QFormLayout();media.setHorizontalSpacing(14);media.setVerticalSpacing(10)
        media.setFieldGrowthPolicy(W.QFormLayout.AllNonFixedFieldsGrow);layout.addLayout(media)
        self.field(media, 'sound_source', '声音文件', kind='file', filter='Audio / video (*.wav *.mp3 *.mp4 *.m4a *.flac *.ogg);;All files (*)')
        self.sound_start = W.QDoubleSpinBox()
        self.sound_start.setRange(0, 86400)
        self.sound_start.setDecimals(3)
        self.sound_duration = W.QDoubleSpinBox()
        self.sound_duration.setRange(.01, 2)
        self.sound_duration.setDecimals(3)
        self.sound_duration.setValue(.08)
        timing=W.QHBoxLayout();timing.setSpacing(8);timing.addWidget(W.QLabel('起点'));timing.addWidget(self.sound_start)
        timing.addWidget(W.QLabel('长度'));timing.addWidget(self.sound_duration)
        media.addRow('片段（秒）',timing)
        row = W.QHBoxLayout()
        layout.addLayout(row)
        self.button(row, '导入并转换所选片段', 'sound_import', lambda: dict(args(), source=self.text('sound_source'),
            start=self.sound_start.value(), duration=self.sound_duration.value(), peak=.4))
        row=W.QHBoxLayout();layout.addLayout(row)
        self.sound_preset=W.QComboBox()
        self.sound_preset.addItem('清脆短音',880);self.sound_preset.addItem('柔和短音',660)
        row.addWidget(self.sound_preset)
        self.button(row,'生成示例音效','sound_generate',lambda:dict(args(),frequency=self.sound_preset.currentData(),duration=self.sound_duration.value()))
        volume = W.QHBoxLayout()
        layout.addLayout(volume)
        self.button(volume, '音量降低 −3 dB', 'sound_volume', lambda: dict(args(), decibels=-3))
        self.button(volume, '音量提高 +3 dB', 'sound_volume', lambda: dict(args(), decibels=3))
        self.button(layout, '还原转换时音量', 'sound_volume', lambda: dict(args(), reset=True))
        preview=W.QHBoxLayout();layout.addLayout(preview)
        play=W.QPushButton('在电脑试听');play.clicked.connect(self.preview_sound)
        preview.addWidget(play);self.buttons.append(play)
        stop=W.QPushButton('停止试听');stop.clicked.connect(self.stop_sound_preview)
        preview.addWidget(stop);self.buttons.append(stop)
        self.sound_preview_status=W.QLabel('导入或生成后可试听；音量调整只在电脑完成。')
        self.sound_preview_status.setWordWrap(True);layout.addWidget(self.sound_preview_status)
        prepare.addStretch();layout=apply
        targets=W.QVBoxLayout();targets.setSpacing(0)
        self.sound_electronic=W.QCheckBox('应用于电子快门声音');self.sound_electronic.setChecked(True)
        self.sound_mechanical=W.QCheckBox('应用于机械快门声音')
        targets.addWidget(self.sound_electronic);targets.addWidget(self.sound_mechanical);layout.addLayout(targets)
        save=W.QPushButton('保存到所选快门');save.setObjectName('saveSelectedSound');save.setProperty('primary',True)
        save.clicked.connect(self.save_sound);layout.addWidget(save);self.buttons.append(save)
        hint=W.QLabel('两项都勾选即可同时应用。保存使用当前调整后的声音，并开启所选音效；完成后按提示断电重开。')
        hint.setWordWrap(True);layout.addWidget(hint)
        layout.addSpacing(6)
        heading=W.QLabel('独立开关 · 保留已保存的声音');heading.setProperty('section',True);layout.addWidget(heading)
        switches=W.QFormLayout();switches.setHorizontalSpacing(14);switches.setVerticalSpacing(8)
        switches.setFieldGrowthPolicy(W.QFormLayout.AllNonFixedFieldsGrow);layout.addLayout(switches)
        for selection,label in (('electronic','电子'),('mechanical','机械')):
            row=W.QHBoxLayout();row.setSpacing(8)
            for enabled,title in ((True,'开启'),(False,'关闭')):
                button=W.QPushButton(title)
                button.setObjectName('switch_'+selection+'_'+('on' if enabled else 'off'))
                button.setToolTip(title+label+'快门音效')
                button.clicked.connect(lambda checked=False,selection=selection,enabled=enabled:self.switch_sound(selection,enabled))
                row.addWidget(button);self.buttons.append(button)
            switches.addRow(label+'快门',row)
        note=W.QLabel('机械快门的开关仅控制扬声器音效，机械结构本身仍会发声。')
        note.setWordWrap(True);layout.addWidget(note)
        check=W.QPushButton('重开后查询／核对音效');check.clicked.connect(self.verify_sound)
        layout.addWidget(check);self.buttons.append(check)
        apply.addStretch();layout=outer
        optional=self.advanced(layout,'工作目录与 USB 高级工具')
        form=self.box(optional,'电脑声音工作区')
        self.field(form,'sound_work','工作目录',kind='folder',value=str(data_root()/'sound'))
        self.field(form,'sound_backup','第二份备份',kind='folder',value=str(data_root()/'sound-backup'))
        self.button(optional,'USB · 相机内临时试听','sound_audition',args)
        self.button(optional, '确认试听正确', 'sound_confirm', lambda: dict(args(), result='correct'))
        self.button(optional, '已断电恢复原声，记录恢复完成', 'sound_confirm_recovery', args)
        self.sound_accept = self.reload_controls(optional, '声音正确、拍摄和回放正常')
        self.button(optional, 'USB · 移除全部自定义音效，关闭电子快门音效', 'sound_restore_sound', args)
        layout.addStretch()

    def sound_selection(self):
        electronic,mechanical=self.sound_electronic.isChecked(),self.sound_mechanical.isChecked()
        if not (electronic or mechanical):raise ValueError('请至少勾选一种快门声音。')
        return 'both' if electronic and mechanical else 'electronic' if electronic else 'mechanical'

    def save_sound(self):
        try:selection=self.sound_selection()
        except ValueError as exc:
            W.QMessageBox.information(self,'选择应用范围',str(exc));return
        if self.sound_transport.value()=='ssh':
            self.launch('ssh_sound_custom',dict(self.ssh_update_args(),workspace=self.work('ssh-sound'),
                sound_workspace=self.text('sound_work'),selection=selection))
        else:
            self.launch('sound_install',dict(self.common(),workspace=self.text('sound_work'),
                backup=self.text('sound_backup'),sound_target=selection))

    def switch_sound(self,selection,enabled):
        if self.sound_transport.value()=='ssh':
            self.launch('ssh_sound_switch',dict(self.ssh_update_args(),workspace=self.work('ssh-sound'),selection=selection,enabled=enabled))
        else:
            action=('sound_mechanical_' if selection=='mechanical' else 'sound_')+('on' if enabled else 'off')
            self.launch(action,dict(self.common(),workspace=self.text('sound_work')))

    def verify_sound(self):
        if self.sound_transport.value()=='ssh':self.launch('ssh_sound_task',self.ssh_update_args())
        else:self.launch('sound_verify',dict(self.common(),workspace=self.text('sound_work'),accepted=self.sound_accept.isChecked()))

    def stop_sound_preview(self):
        if hasattr(self,'sound_player'):self.sound_player.stop()

    def preview_sound(self):
        from .actions.sound import converted_file
        try:path=converted_file(self.text('sound_work'),'preview.private.wav')
        except (ValueError,OSError,KeyError) as exc:
            W.QMessageBox.information(self,'请先准备声音',str(exc));return
        from PySide6.QtMultimedia import QAudioOutput,QMediaPlayer
        if not hasattr(self,'sound_player'):
            self.sound_player=QMediaPlayer(self);self.sound_output=QAudioOutput(self)
            self.sound_output.setVolume(1);self.sound_player.setAudioOutput(self.sound_output)
            self.sound_player.errorOccurred.connect(lambda *args:self.sound_preview_status.setText('电脑试听失败：'+self.sound_player.errorString()))
        self.sound_player.stop();self.sound_player.setSource(QtCore.QUrl.fromLocalFile(str(path)))
        self.sound_player.play();self.sound_preview_status.setText('正在电脑播放当前声音。')

    def show_shutter_notice(self):
        from . import shutterguide
        W.QMessageBox.information(self,shutterguide.TITLE,shutterguide.TEXT)

    def show_zadig_guide(self):
        from .zadigguide import TITLE, TEXT, URL
        dialog = W.QDialog(self); dialog.setWindowTitle(TITLE); dialog.resize(820, 680)
        layout = W.QVBoxLayout(dialog)
        content = W.QTextBrowser(); content.setPlainText(TEXT); layout.addWidget(content)
        row = W.QHBoxLayout(); layout.addLayout(row)
        download = W.QPushButton('打开 Zadig 下载页'); download.setProperty('primary', True)
        download.clicked.connect(lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl(URL)))
        close = W.QPushButton('关闭'); close.clicked.connect(dialog.accept)
        row.addWidget(download); row.addWidget(close)
        dialog.exec()

    def show_look_format_guide(self):
        from .lookguide import TITLE,TEXT
        dialog=W.QDialog(self);dialog.setWindowTitle(TITLE);dialog.resize(800,650)
        layout=W.QVBoxLayout(dialog)
        content=W.QTextBrowser();content.setPlainText(TEXT);layout.addWidget(content)
        close=W.QPushButton('关闭');close.clicked.connect(dialog.accept);layout.addWidget(close)
        dialog.exec()

    def compiler_dialog(self):
        dialog = W.QDialog(self)
        dialog.setWindowTitle('生成 A7Look ＋ DCP')
        dialog.resize(760, 520)
        layout = W.QVBoxLayout(dialog)
        hint = W.QLabel('同时输出同名 A7Look 和 DCP。CUBE：输入必须是 Sony ST / sRGB，输出 sRGB；不能直接使用 S-Log3 / S-Gamut3.Cine 或其他 Log LUT。\nDCP：保留源颜色，配套拟合机内 A7Look；CUBE：制作配套 DCP 并拟合 A7Look。两种格式均为拟合／重建近似。本工具只生成文件，不写相机。')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        help_button=W.QPushButton('支持哪些格式和色彩空间？查看完整说明…')
        help_button.clicked.connect(self.show_look_format_guide);layout.addWidget(help_button)
        form = self.box(layout, '源文件与输出')
        self.field(form, 'compile_source', 'DCP / CUBE', kind='file', filter='Reference (*.dcp *.cube)')
        self.field(form, 'compile_name', '外观名称')
        self.field(form, 'compile_icon', '菜单图标（可选）')
        self.fields['compile_icon'].setMaxLength(4)
        self.fields['compile_icon'].setPlaceholderText('自动匹配，或输入 1–4 字符，如 F400、5213、RN')
        include_icon=W.QCheckBox('附带图标（用于机内 API／SSH／生成固件）')
        include_icon.setChecked(True);form.addRow('',include_icon)
        include_icon.toggled.connect(self.fields['compile_icon'].setEnabled)
        compatibility=W.QLabel('名称使用完整名称；已知外观自动匹配图案。USB 直接导入请取消“附带图标”。')
        compatibility.setWordWrap(True);form.addRow('',compatibility)
        from looktool.looklabels import lookup
        preview=W.QLabel();preview.setMinimumHeight(82);preview.setAlignment(QtCore.Qt.AlignCenter)
        form.addRow('图标预览',preview)
        def update_icon_preview(*_):
            if not include_icon.isChecked():preview.clear();preview.setText('仅生成完整名称和色彩数据');return
            text=self.text('compile_icon')
            if not text:preview.clear();preview.setText('可输入自定义图标缩写');return
            from looktool import iconfile
            try:pixels=iconfile.mask(iconfile.from_text(text))
            except (ValueError,OSError) as error:preview.clear();preview.setText(str(error));return
            image=QtGui.QImage(pixels,26,19,26,QtGui.QImage.Format_Grayscale8).copy()
            preview.setPixmap(QtGui.QPixmap.fromImage(image).scaled(104,76,QtCore.Qt.KeepAspectRatio,QtCore.Qt.FastTransformation))
        include_icon.toggled.connect(update_icon_preview)
        self.fields['compile_icon'].textChanged.connect(update_icon_preview)
        last_auto=dict(name='',icon='')
        def suggest_icon(*_):
            row=lookup(self.text('compile_name'));text=row['icon_text'] if row else ''
            if self.text('compile_icon') in ('',last_auto['icon']):self.fields['compile_icon'].setText(text)
            last_auto['icon']=text
        def suggest_name(*_):
            row=lookup(self.text('compile_source'))
            if row and self.text('compile_name') in ('',last_auto['name']):self.fields['compile_name'].setText(row['name'])
            last_auto['name']=row['name'] if row else ''
            suggest_icon()
        self.fields['compile_source'].textChanged.connect(suggest_name)
        self.fields['compile_name'].textChanged.connect(suggest_icon)
        suggest_name()
        update_icon_preview()
        self.field(form, 'compile_output', '输出 A7Look（同时生成同名 DCP）', kind='save', filter='A7Look (*.a7look)')
        self.field(form, 'compile_hybrid_response', 'C2 Hybrid 响应文件', kind='file', filter='Response (*.json)',
                   value=str(ROOT / 'src/looks/looktool/r5fit/data/response.json'))
        run = W.QPushButton('开始生成')
        run.clicked.connect(lambda: (dialog.accept(), self.launch('compile_look', {
            'source': self.text('compile_source'), 'name': self.text('compile_name'),
            'output': self.text('compile_output'), 'model': self.text('compile_hybrid_response'),
            'include_menu_icon':include_icon.isChecked(),'menu_icon_text':self.text('compile_icon'),
            'input_space': 'sony-st-srgb', 'passes': 12})))
        layout.addWidget(run)
        dialog.exec()

    def plugin_dialog(self):
        self.launch('plugin_install', {})

    def one_click_restore(self):
        roots = [str(data_root() / 'backups'), str(data_root() / 'initial-checkpoints')]
        for key in ('fl23_backup', 'look_backup', 'restore_backup'):
            if key in self.fields and self.text(key):
                roots.append(self.text(key))
        self.fields['restore_work'].setText(self.work('recovery'))
        self.launch('restore_auto', dict(self.common(), roots=roots, workspace=self.text('restore_work'),
            sony_firmware=self.text('factory_voice_firmware') or None))

    def launch(self, action, arguments):
        if self.process is not None:
            return
        if action=='firmware_trust_prepare':
            from .firmwaretrust import validate
            try:validate(arguments)
            except (ValueError,OSError) as exc:
                W.QMessageBox.information(self,'请检查离线准备来源',str(exc));return
        if action in ('firmware_trust_install','firmware_trust_verify','firmware_trust_restore'):
            from .trustinstall import validate_request
            try:validate_request(action,arguments)
            except (ValueError,OSError,KeyError) as exc:
                W.QMessageBox.information(self,'请检查安装记录',str(exc));return
        if action=='ssh_verify_update' and not Path(arguments.get('workspace',''),'update.private.json').is_file():
            W.QMessageBox.information(self,'尚无待核对的更新','请先完成本次 SSH 更新，再断电重开并核对。');return
        if action == 'setup_all' and not self.drivers_first(arguments):
            return
        if action=='direct_looks_import' and arguments.get('failed_workspace'):
            action='direct_resume_looks'
        if action=='direct_looks_import':
            try:
                from .worker import setup_runtime
                setup_runtime()
                from .lookbatch import options
                chosen=options(arguments.get('operations',arguments.get('looks',[])))
                arguments=dict(arguments,operations=chosen['slot_operations'])
            except (ValueError,OSError,KeyError,TypeError) as exc:
                W.QMessageBox.warning(self,'请检查操作清单',str(exc));return
        if action=='ssh_save_looks':
            try:
                from .worker import setup_runtime
                setup_runtime()
                from .lookbatch import options
                arguments=dict(arguments,operations=options(arguments['operations'],allow_menu_icons=True)['slot_operations'])
                if not arguments.get('baseline'):raise ValueError('请在连接设置中选择本地固件构建结果的 baseline 目录。')
            except (ValueError,OSError,KeyError,TypeError) as exc:
                W.QMessageBox.warning(self,'请检查滤镜更新',str(exc));return
        if action=='ssh_sound_custom':
            try:
                from .actions.sound import converted_file
                converted_file(arguments['sound_workspace'])
            except (ValueError,OSError,KeyError) as exc:
                W.QMessageBox.information(self,'请先准备声音',str(exc));return
        if action == 'sound_audition':
            from .actions.sound import has_conversion
            try:
                ready = has_conversion(arguments['workspace'])
            except (ValueError, OSError, KeyError) as exc:
                W.QMessageBox.warning(self, '声音工作区需要核对', str(exc));return
            if not ready:
                W.QMessageBox.information(self, '请先转换片段', '还没有转换好的声音。请先选择声音文件、设置起点和长度，点「转换所选片段」，成功后再试听。');return
        if action == 'restore_verify' and not Path(arguments.get('workspace', ''), 'rollback.private.json').is_file():
            # This button checks a backup restore only. A built-in or firmware
            # file restore is checked by the factory verification button.
            answer = W.QMessageBox.question(self, '这里没有旧备份恢复记录',
                '“核对旧备份恢复后的加载状态”只用于“使用旧备份回到过去的状态”。\n'
                '用原厂来源恢复后，应点“继续完成一键恢复”。\n现在改为核对原厂恢复？',
                W.QMessageBox.Yes | W.QMessageBox.Cancel, W.QMessageBox.Yes)
            if answer != W.QMessageBox.Yes:
                return
            action, arguments = 'direct_verify', self.direct_verify_args('factory', bool(arguments.get('accepted')))
        if action == 'driver_uninstall':
            answer = W.QMessageBox.question(self, '卸载相机驱动',
                '将备份并卸载 Sony 054C:0E8A／0336 的第三方驱动，让 Windows 重新识别相机。\n'
                '完成后可能需要拔插 USB，重新选择海量存储模式。此操作不修改相机固件。\n现在卸载？',
                W.QMessageBox.Yes | W.QMessageBox.Cancel, W.QMessageBox.Cancel)
            if answer != W.QMessageBox.Yes:
                return
        writing = action in jobs.POWER_ACTIONS
        if writing:
            target = (('首页勾选的功能；替换自订 1–6：' + presets.SUMMARY if arguments.get('options', {}).get('preset_pack') else '首页勾选的功能及所选 A7Look 槽位') if action == 'setup_all' else
                      '自动选择已连接机身最早可用的完整备份' if action == 'restore_auto' else
                      arguments.get('backup') if action == 'restore' else arguments.get('look') or arguments.get('workspace'))
            if action in jobs.DIRECT_ACTIONS:
                target = ({'direct_preview_pending': '取景器与实时预览第三版候选',
                           'direct_preview_native': '第一版原生刷新条件',
                           'direct_preview_legacy': '测试前的旧版刷新方式'}[action]
                          if action in ('direct_preview_pending', 'direct_preview_native', 'direct_preview_legacy') else
                          '；'.join('自订 %s → %s' % (r['slot'], '恢复 ST 默认' if r['action']=='restore' else '写入 '+r['name']) for r in arguments.get('operations', []))
                          if action == 'direct_looks_import' else
                          '继续已写好名称的外观安装：'+arguments.get('failed_workspace','') if action=='direct_resume_looks' else
                          '按当前相机重新恢复原厂 2.01 功能' if action == 'direct_resume_factory' else
                          '竖屏显示＋Fn／子菜单线框修正' if action=='vertical_enable' else
                          '关闭竖屏显示并撤销线框修正' if action=='vertical_disable' else
                          '原厂 2.01 功能' if action == 'direct_factory_reset' else
                          'FL2／FL3：启用' if action == 'direct_fl23_enable' else
                          'FL2／FL3：从列表移除' if action == 'direct_fl23_disable' else
                          '自动白平衡：启用优先级实验' if action == 'direct_wb_enable' else
                          '自动白平衡：恢复原生优先级' if action == 'direct_wb_disable' else
                          '自订 %s：%s' % (arguments.get('slot'), 'ST 默认' if action == 'direct_slot_default'
                                           else arguments.get('name') or Path(arguments.get('look', '')).stem))
            scope = ('保存本机更新器原始备份，安装应用公钥与四个验签库；私钥不写入相机。当前仅完成离线与虚拟机测试。\n' if action=='firmware_trust_install' else
                     '从本机首次安装备份恢复更新器原厂授信，逐批及整分区读回。此步骤不恢复机身功能或版本号。\n' if action=='firmware_trust_restore' else
                     '仅修正机内版本资料，不恢复原厂程序或官方签名信任；结束后按提示断电重开。\n' if action=='ssh_restore_version' else
                     '仅更改白平衡两处优先级参数读取，保留标准 AWB、机身校准与创意外观。写入后按提示断电重开。\n' if action in ('direct_wb_enable','direct_wb_disable') else
                     '在内存目录上传独立 SSH 服务并监听 2222；不写固件、校准或开机文件。\n' if action=='ssh_start' else
                     '仅更改 CP 的 LUT 刷新代码；保留色表、名称、配方和其他功能。写入后完整断电重开，检查横线及切槽刷新。\n' if action in ('direct_preview_native','direct_preview_legacy','direct_preview_pending') else
                     '一次应用清单内的写入和恢复，未添加的槽位保持原样；保留 FL23、声音和竖屏。写入读回完成后统一提示断电重开。\n' if action=='direct_looks_import' else
                     '自动准备驱动并安装首页勾选的功能。断电重开必须由你按提示完成；结果不明时停止，不自动重复刷写。\n' if action == 'setup_all' else
                     '从当前相机字节重新生成原厂恢复计划；旧记录不影响本次操作，已符合目标的内容不重复写入。\n' if action == 'direct_resume_factory' else
                     '将移除项目程序修改、将六个自订栏位设为 ST，快门设回机械并关闭新增电子快门音效；旧配方不找回。'+
                     ('本次同时补回语音包并解除置灰；' if arguments.get('restore_voice',True) else '本次保留语音已删除与置灰状态；')+
                     '重开后继续完成恢复，再清除私有音效文件。\n' if action == 'direct_factory_reset' else
                     '先关闭语音指南并将机内语音选项置灰；写入后须按提示重开，再点同一按钮核对并删除十份语音音频。不会删除索引、对焦提示音或快门音频。\n' if action=='voice_cleanup' else
                     '从所选官方 2.01 文件或语音备份完整补回资源，核对全部文件后再解除限制。\n' if action=='voice_restore' else
                     '只关闭 FL2／FL3 列表入口，保留 LUT 与共用代码。请先在相机选择 ST。\n' if action == 'direct_fl23_disable' else
                     '将所选自订栏位设为 ST 默认，保留其他栏位。\n' if action == 'direct_slot_default' else '')
            ssh_write=action in ('ssh_save_looks','ssh_sound_custom','ssh_sound_switch','ssh_apply_update','ssh_restore_version')
            connection='Wi-Fi / SSH' if ssh_write else 'USB'
            if ssh_write:
                target=('所选 %d 个滤镜槽位'%len(arguments['operations']) if action=='ssh_save_looks' else
                    '版本号 '+arguments['source_version']+' → 2.00（仅修改版本资料）' if action=='ssh_restore_version' else
                    {'electronic':'电子快门音效','mechanical':'机械快门音效','both':'电子与机械快门音效'}.get(arguments.get('selection'),'本次更新'))
            firmware_label='基于官方 2.01 的研究固件' if action=='ssh_restore_version' else '固件 2.01'
            answer = W.QMessageBox.question(self, '开始相机写入',
                scope + '目标：' + str(target) + '\n请确认机身为 ILCE-7CM2、'+firmware_label+'，电量充足（建议至少 50%）。\n'
                '操作和读回期间保持供电、'+connection+' 连接，不要关机或断开连接。\n确认供电充足并开始？',
                W.QMessageBox.Yes | W.QMessageBox.Cancel, W.QMessageBox.Cancel)
            if answer != W.QMessageBox.Yes:
                return
            arguments = dict(arguments, power_confirmed=True)
            arguments.pop('battery', None)
        if action=='ssh_save_looks':self.settings['look_ssh_work']=arguments['workspace']
        if action=='ssh_restore_version':self.settings['factory_version_work']=arguments['workspace']
        if action=='firmware_trust_install':
            self.settings['trust_install_work']=arguments['workspace']
            self.fields['trust_record'].setText(arguments['workspace'])
        if action in ('firmware_trust_install','firmware_trust_restore'):
            self.settings['trust_latest_work']=arguments['workspace']
        if action in ('sound_import','sound_generate','sound_volume'):self.stop_sound_preview()
        if action in jobs.DIRECT_ACTIONS:
            group = ('preview' if action in ('direct_preview_native', 'direct_preview_legacy', 'direct_preview_pending') else
                     'factory' if action in ('direct_factory_reset', 'direct_resume_factory') else 'wb' if action in ('direct_wb_enable','direct_wb_disable') else 'fl23' if 'fl23' in action else 'look')
            self.settings[group + '_direct_work'] = arguments['workspace']
            if group=='look':
                self.settings['look_resume_source']=arguments.get('failed_workspace','')
            if group!='look':getattr(self, group + '_accept').setChecked(False)
        if action == 'setup_all':
            self.settings['setup_work'] = arguments['workspace']
            self.setup_button.setText('正在安装…')
            for box in (self.setup_presets,self.setup_fl23,self.setup_sound,self.setup_vertical,self.setup_plugin):box.setEnabled(False)
        for key, field in self.fields.items():
            self.settings[key] = field.text()
        write_json(data_root() / 'desktop.json', self.settings)
        self.current_job = jobs.new_job(action, arguments)
        if action in ('direct_looks_import','direct_resume_looks') or (action=='direct_verify' and arguments.get('workspace')==self.settings.get('look_direct_work')):
            self.settings['look_job_dir']=str(self.current_job)
            write_json(data_root()/'desktop.json',self.settings)
        self.log_offset = 0
        self.log.clear()
        self.log_toggle.setChecked(True)
        self.camera_operation = action in jobs.CAMERA_ACTIONS or action == 'driver_install'
        for button in self.buttons:
            button.setEnabled(False)
        self.look_editor.setEnabled(False)
        self.stop.setEnabled(not self.camera_operation)
        self.progress.setRange(0, 0)
        self.status.setText('正在执行：' + action + '。详细日志持续保存。')
        self.process = QtCore.QProcess(self)
        self.process.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        env = QtCore.QProcessEnvironment.systemEnvironment()
        env.insert('PYTHONUTF8', '1')
        env.insert('PYTHONIOENCODING', 'utf-8')
        self.process.setProcessEnvironment(env)
        command = jobs.worker_command(self.current_job / 'request.private.json')
        self.process.readyReadStandardOutput.connect(self.process_output)
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(self.process_error)
        self.process.start(command[0], command[1:])

    def process_output(self):
        text = bytes(self.process.readAllStandardOutput()).decode('utf-8', errors='replace')
        if text:
            with (self.current_job / 'process.log').open('a', encoding='utf-8') as stream:
                stream.write(text)
            self.log.appendPlainText(text.rstrip())

    def tail_log(self):
        if not self.current_job:
            return
        path = self.current_job / 'worker.log'
        if path.exists():
            with path.open('rb') as stream:
                stream.seek(self.log_offset)
                text = stream.read()
                self.log_offset = stream.tell()
            if text:
                self.log.appendPlainText(text.decode('utf-8', errors='replace').rstrip())

    def poll_job(self):
        self.tail_log()
        self.refresh_status_dot()
        if self.process is None and (self._look_displayed_pending is not None or self.look_pending_state()):self.refresh_look_controls()
        # The status file also recovers completion if Qt missed its signal.
        if self.process is not None and self.process.state() == QtCore.QProcess.NotRunning:
            self.finished(self.process.exitCode(), self.process.exitStatus())

    def refresh_status_dot(self):
        state=('running' if self.process is not None else 'error' if self.status.text().startswith('操作停止') else
               'success' if self.progress.value()==100 else 'idle')
        if self.status_dot.property('state')!=state:
            self.status_dot.setProperty('state',state)
            self.status_dot.style().unpolish(self.status_dot);self.status_dot.style().polish(self.status_dot)

    def finished(self, code, exit_status):
        if self.process is None:
            return
        self.tail_log()
        status_path = self.current_job / 'status.private.json'
        status = json.loads(status_path.read_text(encoding='utf-8')) if status_path.exists() else {}
        success = code == 0 and status.get('phase') == 'SUCCEEDED'
        if success and (status.get('action') in ('usb_prepare', 'connect') or
                        (status.get('action') == 'setup_all' and 'drivers' in status.get('result', {}).get('completed_steps', []))):
            self.settings['connection_verified'] = True
        if success and status.get('action') == 'restore_auto':
            self.fields['restore_backup'].setText(status['result']['backup'])
            self.fields['restore_work'].setText(status['result']['workspace'])
        if success and status.get('action') in ('direct_factory_reset', 'direct_resume_factory'):
            self.settings['factory_direct_work'] = status['result']['workspace']
            self.fields['factory_failed_work'].setText(status['result']['workspace'])
        if success and status.get('action')=='direct_verify' and status['result'].get('mode')=='factory_reset':
            self.settings['factory_direct_work']=status['result']['workspace']
        if success and status.get('action')=='firmware_trust_verify':
            self.settings['trust_latest_work']=status['result']['workspace']
        if success and (status.get('action') in ('direct_looks_import','direct_resume_looks') or
                (status.get('action')=='direct_verify' and status['result'].get('mode') in ('install_all','look_import','slot_default'))):
            self.settings['look_direct_work']=status['result']['workspace']
            self.settings.pop('look_resume_source',None)
        if success and status.get('action') == 'setup_all':
            for key in ('sound_workspace','sound_backup'):
                target='sound_work' if key=='sound_workspace' else 'sound_backup'
                if status['result'].get(key):self.fields[target].setText(status['result'][key])
        for key, field in self.fields.items():
            self.settings[key] = field.text()
        write_json(data_root() / 'desktop.json', self.settings)
        waiting=success and reloadguide.required(status.get('action'),status.get('result',{}))
        sound_notice=reloadguide.sound_notice(status.get('action'),status.get('result',{})) if success else None
        factory_wait=success and status.get('result',{}).get('mode')=='factory_reset' and (status['result'].get('phase')=='AWAITING_RELOAD' or status['result'].get('verification_required'))
        factory_done=success and status.get('result',{}).get('mode')=='factory_reset' and status['result'].get('recovery_complete') is True
        if factory_done:self.clear_installation_state()
        elif factory_wait:self.clear_installation_state(verified=False)
        resource_wait=status.get('result',{}).get('phase') in ('WAIT_RESOURCE_RELOAD','AWAITING_RESOURCE_RELOAD')
        resource_ready=success and status.get('result',{}).get('phase')=='RESOURCE_RELOAD_VERIFIED'
        setup_wait=waiting and status.get('action')=='setup_all'
        self.status.setText(('名称已写好，程序尚未写入。按弹窗断电重开、接回 USB，再点击首页“继续安装”。' if resource_wait and setup_wait else
                             '名称已写好，程序尚未写入。按弹窗断电重开、接回 USB，再点自定义外观页“继续槽位更改”。' if resource_wait else
                             '批量外观写入完成，已完整读回；按弹窗统一断电重开即可加载。' if status.get('action')=='direct_looks_import' else
                             'FL23 操作完成，写入与完整读回均已结束。重开相机后生效，无需再点核对。' if
                             status.get('result',{}).get('mode') in ('fl23_enable','fl23_disable') else
                             '读写已结束。拔 USB → 等灯停 → 关机并等灯灭 → 取电池至少 1 分钟 → 开机 → 接回 USB → 点击首页“继续安装”。详见弹窗。' if setup_wait else
                             '读写已结束。拔 USB → 等灯停 → 关机并等灯灭 → 取电池至少 1 分钟 → 开机；详见弹窗。') if waiting else
                           '名称与只读挂载已确认；程序尚未安装，请点首页“继续安装”。' if resource_ready and status.get('action')=='setup_all' else
                           '名称与只读挂载已确认；程序尚未安装，请点自定义外观页“继续槽位更改”。' if resource_ready else
                           '完成。请按日志提示进行下一步。' if success else
                           '操作停止：' + status.get('error', '进程异常退出，退出码 ' + str(code)) + '。请导出诊断包。')
        if not success and sys.platform == 'win32' and self.driver_step_failed(status.get('action')) and status.get('error_type')!='ServiceExitUnconfirmed':
            self.status.setText(self.status.text() + DRIVER_HINT)
        if sound_notice:self.status.setText(sound_notice['status'])
        if success and status.get('action') in ('sound_import','sound_generate','sound_volume'):
            gain=status['result'].get('volume_gain_db',0)
            self.sound_preview_status.setText('电脑声音已准备好 · 音量调整 %+.0f dB · 可试听或保存'%gain)
        if success and status.get('action','').startswith('ssh_'):
            phase=status['result']['phase']
            messages={'SSH_VERIFIED':'SSH 连接正常。','AWAITING_RELOAD':'写入与读回已结束，请按提示取出电池后重开。',
                'LOADED':'已确认重开并完成文件／任务核对；请检查实际拍摄和音效。','IDLE':'相机当前没有接口更新任务。',
                'PREPARED':'电脑端更新已生成。'}
            if status['result'].get('kind')=='version':
                messages['LOADED']='版本资料核对完成；尚未完成原厂签名信任恢复。'
            self.status.setText(messages.get(phase,phase)+status['result'].get('message',''))
            if status['result'].get('next_baseline'):
                self.fields['ssh_update_baseline'].setText(status['result']['next_baseline'])
                self.settings['ssh_update_baseline']=status['result']['next_baseline']
                write_json(data_root()/'desktop.json',self.settings)
        if factory_wait:self.status.setText('恢复尚未完成：写入和读回已结束，必须断电重启、接回 USB，再点“继续完成一键恢复”。')
        elif factory_done:self.status.setText('原厂恢复核对通过，旧安装状态已清除。请继续检查机身拍摄和回放；重新安装请点首页“一键安装”。')
        if success and status.get('action') in ('firmware_trust_install','firmware_trust_restore','firmware_trust_verify'):
            self.status.setText('更新器写入与整分区读回已结束，请断电重开后核对。' if waiting else
                '重开后的更新器内容核对通过；完整更新器启动与实际卡刷尚未验收。')
        self.progress.setRange(0, 100)
        self.progress.setValue(40 if waiting and status.get('result',{}).get('mode')=='voice_disable' else
                              70 if factory_wait else 0 if sound_notice and status.get('action')=='sound_install' else
                              40 if success and (resource_wait or resource_ready) else 70 if waiting and status.get('action')=='setup_all' else 100 if success else 0)
        for button in self.buttons:
            button.setEnabled(True)
        self.stop.setEnabled(False)
        self.process.deleteLater()
        self.process = None
        if success and status.get('action') in ('direct_looks_import','direct_resume_looks','direct_verify') and status.get('result',{}).get('mode') in ('install_all','look_import','slot_default') and status['result'].get('phase') in ('COMPLETED','AWAITING_RELOAD','LOADED','COMPLETE') and (status['action']!='direct_verify' or self._look_displayed_pending is not None):
            self.look_editor.set_operations([])
        self.refresh_look_controls()
        self.refresh_setup_controls()
        self.refresh_factory_controls()
        self.refresh_trust_controls()
        driver_notice=connectionguide.completion(status.get('action'),status.get('result',{})) if success else None
        if driver_notice:
            self.status.setText(driver_notice[0])
            W.QMessageBox.information(self,*driver_notice)
        elif not success and status.get('error_type')=='ServiceExitUnconfirmed':
            W.QMessageBox.warning(self,'驱动步骤停止：尚未确认退出服务模式',status.get('error','请保留日志。'))
        elif sound_notice:
            W.QMessageBox.information(self,sound_notice['title'],sound_notice['text'])
        elif status.get('action') in ('voice_cleanup','voice_restore') and success and not waiting:
            W.QMessageBox.information(self,'语音资源操作完成',status['result'].get('message','语音文件已完整写回；关闭限制已解除，语音指南仍保持关闭，可在机内自行开启。'))
        elif status.get('action')=='backup_current' and success:
            result=status['result']
            self.fields['restore_backup'].setText(result['workspace'])
            self.settings['restore_backup']=result['workspace']
            write_json(data_root()/'desktop.json',self.settings)
            W.QMessageBox.information(self,'当前状态备份完成',
                '已保存程序、外观、设置和名称，并通过本地校验。没有写入相机。\n'
                '这是当前状态备份，不是原厂基准。\n保存位置：'+result['workspace']+
                ('\n语音包也已另存；当前项目还原不会自动写回语音包。' if result.get('voice_backup') else ''))
        elif status.get('action')=='usb_stability':
            if success:
                result=status['result']
                W.QMessageBox.information(self,'USB 只读检测通过',
                    '已完成 %d 轮、共 %.1f MB 程序文件只读传输，持续 %.0f 秒，每轮字节一致。\n\n没有写入固件、设置或运行原生写入程序。\n\n%s'%
                    (len(result['rounds']),result['total_bytes']/1024/1024,result.get('seconds',0),result['note']))
            else:
                error=status.get('error','请查看日志并换线后重测。')
                W.QMessageBox.warning(self,'USB 连接检测未完成' if '未完成' in error else 'USB 连接检测未通过',error)
        elif waiting:
            self.show_reload_guide(setup=status.get('action')=='setup_all', mode=('resource_reload' if resource_wait else status.get('action') if
                status.get('action','').startswith('sound_') else status.get('result',{}).get('mode')))
        elif success and status.get('action')=='setup_all' and status.get('result',{}).get('phase')=='COMPLETE':
            self.status.setText('安装完成。可查看上次安装结果，无需再次刷写。')
            self.setup_button.setText('开始新的一键安装')
            self.setup_result_button.setVisible(True)
            for box in (self.setup_presets,self.setup_fl23,self.setup_sound,self.setup_vertical,self.setup_plugin):box.setEnabled(True)
            self.show_setup_result()

    def process_error(self, error):
        if self.process and error == QtCore.QProcess.FailedToStart:
            self.log.appendPlainText(self.process.errorString())
            self.finished(-1, None)

    def open_job(self):
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(self.current_job or data_root())))

    def export_logs(self):
        if not self.current_job:
            return
        path = W.QFileDialog.getSaveFileName(self, '导出诊断包', 'a7c2-diagnostics.zip', 'ZIP (*.zip)')[0]
        if path:
            try:
                jobs.export_support(self.current_job, path)
            except Exception as exc:
                W.QMessageBox.warning(self, '导出失败', str(exc))

    def cancel_offline(self):
        if self.process and not self.camera_operation:
            self.process.terminate()

    def closeEvent(self, event):
        if self.process:
            W.QMessageBox.information(self, '任务仍在运行', '请等待当前任务结束后关闭。相机写入期间不要结束程序或拔线。')
            event.ignore()
        else:
            event.accept()


def main():
    app = W.QApplication.instance() or W.QApplication(sys.argv)
    if '--smoke-test' in sys.argv and sys.platform == 'win32':
        # Qt's headless test platform does not enumerate Windows system fonts.
        import os
        font = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/msyh.ttc'
        if font.is_file():
            QtGui.QFontDatabase.addApplicationFont(str(font))
    app.setWindowIcon(QtGui.QIcon(asset('mark.png')))
    app.setApplicationName('A7C2Tools')
    app.setOrganizationName('QAQLeonard')
    if '--smoke-test' not in sys.argv and not require_consent():
        return 0
    window = Window()
    if '--preview-gate-test' in sys.argv:
        window.select_page(3)
    window.show()
    if '--smoke-test' in sys.argv:
        data_root().mkdir(parents=True, exist_ok=True)
        for index in range(window.pages.count()):
            window.select_page(index)
            app.processEvents()
            if not window.grab().save(str(data_root() / ('desktop-page-' + str(index + 1) + '.png'))):
                raise OSError('Could not save desktop smoke screenshot')
        window.select_page(9 if '--legacy-usb' not in sys.argv else 0)
        QtCore.QTimer.singleShot(800, app.quit)
    else:
        QtCore.QTimer.singleShot(0,window.show_connection_notice)
    return app.exec()
