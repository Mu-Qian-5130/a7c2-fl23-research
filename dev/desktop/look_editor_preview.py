"""Standalone UI proposal. No camera/backend imports or device operations.

Run normally for an interactive preview, --example for a mixed example, or
--render DIRECTORY to capture the empty, default-restore and mixed states.
"""
import argparse
from pathlib import Path
import sys
from PySide6 import QtCore, QtGui, QtWidgets as W

STYLE = '''
QWidget {font-family:"Segoe UI","Microsoft YaHei";font-size:13px;color:#dce6ef;background:#101923;}
QLabel[muted="true"] {color:#94a8ba;}
QLabel[title="true"] {font-size:27px;font-weight:650;color:#f0f5fa;}
QLabel[badge="true"] {background:#173c43;color:#91dfd4;border-radius:5px;padding:6px 10px;}
QLabel[warning="true"] {color:#dfb984;}
QFrame[card="true"] {background:#152332;border:1px solid #30495d;border-radius:9px;}
QFrame[card="true"] QLabel {background:transparent;}
QComboBox,QLineEdit {background:#101d2a;border:1px solid #3a5266;border-radius:5px;padding:8px;min-height:19px;}
QComboBox {padding-right:25px;}
QComboBox::drop-down {border:0;border-left:1px solid #30495d;width:24px;}
QComboBox QAbstractItemView {background:#192c3d;selection-background-color:#20575e;}
QLineEdit:disabled {color:#60778a;}
QPushButton {background:#223a4e;border:1px solid #3b586e;border-radius:6px;padding:9px 15px;}
QPushButton:hover {background:#2c4d62;}
QPushButton:disabled {background:#182c38;color:#6b8495;border-color:#294252;}
QPushButton[primary="true"] {background:#147b80;color:white;border-color:#2ca7aa;font-weight:600;}
QPushButton[primary="true"]:disabled {background:#21444d;color:#819da5;border-color:#35515d;}
QPushButton[quiet="true"] {background:transparent;border:0;color:#9cb0c0;padding:6px;}
QPushButton[quiet="true"]:hover {background:#3c2931;color:#efb1b1;}
QListWidget {background:#10202d;border:0;padding:14px 9px;}
QListWidget::item {padding:17px 13px;margin-bottom:4px;border-radius:6px;color:#c4d2dc;}
QListWidget::item:selected {background:#214759;color:#b1e8e7;}
QScrollArea {border:0;}
QScrollBar:vertical {background:#12222e;width:8px;}
QScrollBar::handle:vertical {background:#365363;border-radius:4px;min-height:30px;}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {height:0;}
QWidget#operationDetails,QStackedWidget#operationStack {background:transparent;}
'''


def label(text, *, muted=False):
    result=W.QLabel(text)
    result.setProperty('muted',muted)
    return result


class Choice(W.QComboBox):
    def paintEvent(self,event):
        super().paintEvent(event)
        painter=QtGui.QPainter(self);painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setPen(QtCore.Qt.NoPen);painter.setBrush(QtGui.QColor('#a7bfce'))
        x,y=self.width()-13,self.height()//2
        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x-4,y-2),QtCore.QPoint(x+4,y-2),QtCore.QPoint(x,y+3)]))


class Operation(W.QFrame):
    changed=QtCore.Signal()
    remove_requested=QtCore.Signal(object)

    def __init__(self,slot):
        super().__init__()
        self.setProperty('card',True)
        self.file_path=''
        box=W.QVBoxLayout(self);box.setContentsMargins(17,15,17,15);box.setSpacing(12)
        top=W.QHBoxLayout();box.addLayout(top)
        top.addWidget(label('目标槽位',muted=True))
        self.slot=Choice()
        for number in range(1,7):self.slot.addItem('自订 '+str(number),number)
        self.slot.setCurrentIndex(slot-1);self.slot.setFixedWidth(115)
        top.addWidget(self.slot);top.addSpacing(18)
        top.addWidget(label('本次操作',muted=True))
        self.action=Choice();self.action.addItems(['恢复 ST 默认','写入 A7Look'])
        self.action.setFixedWidth(160);top.addWidget(self.action);top.addStretch()
        remove=W.QPushButton('移除这项');remove.setProperty('quiet',True)
        remove.setToolTip('仅移除此操作项，该槽保持原样')
        remove.clicked.connect(lambda:self.remove_requested.emit(self));top.addWidget(remove)
        self.details=W.QStackedWidget();self.details.setObjectName('operationStack');box.addWidget(self.details)
        restore=W.QWidget();restore.setObjectName('operationDetails');restore_box=W.QHBoxLayout(restore);restore_box.setContentsMargins(0,0,0,0)
        note=label('此槽恢复为 ST 默认；不会找回导入前的旧配方。',muted=True)
        restore_box.addWidget(note);restore_box.addStretch();self.details.addWidget(restore)
        write=W.QWidget();write.setObjectName('operationDetails');grid=W.QGridLayout(write);grid.setContentsMargins(0,0,0,0);grid.setHorizontalSpacing(12);grid.setVerticalSpacing(6)
        grid.addWidget(label('A7Look 文件',muted=True),0,0)
        grid.addWidget(label('机内显示名称',muted=True),0,2)
        self.file=W.QLineEdit();self.file.setReadOnly(True);self.file.setPlaceholderText('请选择 .a7look 文件')
        self.browse=W.QPushButton('选择文件…');self.browse.clicked.connect(self.choose_file)
        self.name=W.QLineEdit();self.name.setPlaceholderText('留空沿用文件内名称')
        grid.addWidget(self.file,1,0);grid.addWidget(self.browse,1,1);grid.addWidget(self.name,1,2)
        grid.setColumnStretch(0,3);grid.setColumnStretch(2,2);self.details.addWidget(write)
        self.action.currentIndexChanged.connect(self.update_mode)
        self.slot.currentIndexChanged.connect(self.changed)
        self.name.textChanged.connect(self.changed)
        self.update_mode()

    def update_mode(self):
        self.details.setCurrentIndex(self.action.currentIndex())
        self.details.setFixedHeight(36 if self.action.currentIndex()==0 else 74)
        self.setFixedHeight(115 if self.action.currentIndex()==0 else 153)
        self.changed.emit()

    def choose_file(self):
        path=W.QFileDialog.getOpenFileName(self,'选择 A7Look 文件',self.file_path,'A7Look (*.a7look)')[0]
        if path:self.set_file(path)

    def set_file(self,path):
        self.file_path=str(path);self.file.setText(Path(path).name);self.file.setToolTip(str(path));self.changed.emit()

    def value(self):
        value=dict(slot=self.slot.currentData(),action='restore' if self.action.currentIndex()==0 else 'write')
        if value['action']=='write':value.update(file=self.file_path,name=self.name.text().strip())
        return value


class Preview(W.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('A7C II Tools · 自定义创意外观 UI 预览（不连接相机）')
        self.resize(1240,940);self.setMinimumSize(1070,790);self.setStyleSheet(STYLE)
        self.rows=[]
        center=W.QWidget();self.setCentralWidget(center)
        outer=W.QHBoxLayout(center);outer.setContentsMargins(0,0,0,0);outer.setSpacing(0)
        nav=W.QListWidget();nav.setFixedWidth(202)
        nav.addItems(['首页 · 一键安装','连接与驱动','恢复原厂功能','FL2 / FL3','自定义创意外观','竖屏显示','电子快门声音'])
        nav.setCurrentRow(4);nav.setFocusPolicy(QtCore.Qt.NoFocus)
        outer.addWidget(nav)
        content=W.QWidget();outer.addWidget(content,1)
        layout=W.QVBoxLayout(content);layout.setContentsMargins(29,25,29,20);layout.setSpacing(15)
        head=W.QHBoxLayout();head.addWidget(label('A7C II Tools'));head.addStretch()
        badge=label('界面预览 · 不连接相机');badge.setProperty('badge',True);head.addWidget(badge)
        layout.addLayout(head)
        title=label('自定义创意外观');title.setProperty('title',True);layout.addWidget(title)
        layout.addWidget(label('按需添加本次要改的槽位。未添加的槽位保持原样。',muted=True))
        toolbar=W.QHBoxLayout()
        self.add=W.QPushButton('+ 添加操作项');self.add.clicked.connect(lambda:self.add_row());toolbar.addWidget(self.add)
        toolbar.addWidget(label('新增项默认“恢复 ST 默认”，可切换为写入。',muted=True));toolbar.addStretch()
        layout.addLayout(toolbar)
        self.scroll=W.QScrollArea();self.scroll.setWidgetResizable(True);layout.addWidget(self.scroll,1)
        self.row_container=W.QWidget();self.row_box=W.QVBoxLayout(self.row_container)
        self.row_box.setContentsMargins(0,0,4,0);self.row_box.setSpacing(12)
        self.empty=W.QFrame();self.empty.setProperty('card',True)
        empty_layout=W.QVBoxLayout(self.empty);empty_layout.setContentsMargins(30,43,30,43);empty_layout.setSpacing(12)
        empty_title=label('尚未添加操作项');empty_title.setStyleSheet('font-size:18px;font-weight:600;');empty_title.setAlignment(QtCore.Qt.AlignCenter)
        empty_layout.addWidget(empty_title)
        empty_text=label('点击“添加操作项”，选择目标槽位和操作。\n当前六个槽位均保持原样。',muted=True)
        empty_text.setAlignment(QtCore.Qt.AlignCenter);empty_layout.addWidget(empty_text)
        self.row_box.addWidget(self.empty);self.row_box.addStretch();self.scroll.setWidget(self.row_container)
        summary=W.QFrame();summary.setProperty('card',True)
        summary_layout=W.QVBoxLayout(summary);summary_layout.setContentsMargins(16,13,16,13);summary_layout.setSpacing(7)
        self.summary=label('');self.summary.setStyleSheet('font-size:15px;font-weight:600;');summary_layout.addWidget(self.summary)
        self.preserved=label('',muted=True);summary_layout.addWidget(self.preserved)
        self.validation=label('');self.validation.setProperty('warning',True);summary_layout.addWidget(self.validation)
        layout.addWidget(summary)
        self.review=W.QPushButton('查看并确认本次更改');self.review.setProperty('primary',True)
        self.review.clicked.connect(self.review_plan);layout.addWidget(self.review)
        tools=W.QHBoxLayout()
        for name in ['从 DCP／LUT 生成 A7Look…','安装 LrC 自动识别插件…']:
            button=W.QPushButton(name);button.clicked.connect(self.preview_only);tools.addWidget(button)
        layout.addLayout(tools)
        layout.addWidget(label('仅更改清单内的槽位。保留 FL23、声音与竖屏设置。',muted=True))
        self.update_summary()

    def add_row(self,slot=None):
        occupied={row.slot.currentData() for row in self.rows}
        free=[n for n in range(1,7) if n not in occupied]
        if not free:return None
        row=Operation(slot if slot is not None else free[0]);self.rows.append(row)
        row.changed.connect(self.update_summary);row.remove_requested.connect(self.remove_row)
        self.row_box.insertWidget(self.row_box.count()-1,row);self.update_summary()
        return row

    def remove_row(self,row):
        self.rows.remove(row);self.row_box.removeWidget(row);row.setParent(None);row.deleteLater();self.update_summary()

    def plan(self):return [row.value() for row in self.rows]

    def update_summary(self):
        plan=self.plan();slots=[row['slot'] for row in plan];occupied=set(slots)
        self.empty.setVisible(not plan);self.add.setEnabled(len(plan)<6)
        for row in self.rows:
            for index in range(6):row.slot.model().item(index).setEnabled(index+1 not in occupied or index+1==row.slot.currentData())
        writes=sum(row['action']=='write' for row in plan);restores=len(plan)-writes
        self.summary.setText('本次更改 %d 个槽位：%d 项写入 · %d 项恢复'%(len(plan),writes,restores))
        untouched=[str(n) for n in range(1,7) if n not in occupied]
        self.preserved.setText('保持原样：'+('自订 '+'、'.join(untouched) if untouched else '无（六个槽位均在本次清单中）'))
        errors=[]
        if len(slots)!=len(occupied):errors.append('同一槽位只能添加一个操作。')
        missing=[str(row['slot']) for row in plan if row['action']=='write' and not row['file']]
        if missing:errors.append('请为自订 '+'、'.join(missing)+' 选择 A7Look 文件。')
        self.validation.setText(' '.join(errors));self.validation.setVisible(bool(errors))
        self.review.setEnabled(bool(plan) and not errors)
        self.review.setText('查看并确认这 %d 项更改'%len(plan) if plan else '添加操作项后继续')

    def review_plan(self):
        lines=['这是 UI 预览，不会连接或写入相机。','']
        for row in self.plan():
            if row['action']=='restore':lines.append('自订 %s → 恢复 ST 默认'%row['slot'])
            else:lines.append('自订 %s → 写入 %s\n机内名称：%s'%(row['slot'],Path(row['file']).name,row['name'] or '沿用文件内名称'))
        lines.extend(['',self.preserved.text()])
        W.QMessageBox.information(self,'确认本次操作 · 界面预览','\n\n'.join(lines))

    def preview_only(self):W.QMessageBox.information(self,'界面预览','此处仅展示入口；本预览不安装插件、不转换文件，也不操作相机。')

    def example(self):
        one=self.add_row(2);one.action.setCurrentIndex(1);one.set_file('Classic Chrome.a7look');one.name.setText('Classic Chrome')
        self.add_row(4)
        three=self.add_row(6);three.action.setCurrentIndex(1);three.set_file('GR Negative Film.a7look');three.name.setText('GR Negative Film')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--example',action='store_true');parser.add_argument('--render',type=Path)
    args=parser.parse_args()
    app=W.QApplication(sys.argv)
    app.setStyle('Fusion')
    font=Path('C:/Windows/Fonts/msyh.ttc')
    if font.is_file():QtGui.QFontDatabase.addApplicationFont(str(font))
    window=Preview();window.show()
    if args.render:
        args.render.mkdir(parents=True,exist_ok=True)
        def capture(name):
            app.processEvents()
            if not window.grab().save(str(args.render/name)):raise OSError('Could not capture preview')
        assert window.plan()==[] and not window.review.isEnabled()
        capture('empty.png')
        row=window.add_row();assert row.value()==dict(slot=1,action='restore')
        capture('default-restore.png');window.remove_row(row)
        window.example();assert [r['slot'] for r in window.plan()]==[2,4,6]
        assert [r['action'] for r in window.plan()]==['write','restore','write']
        assert '1、3、5' in window.preserved.text()
        capture('mixed.png')
        print('UI smoke passed: empty default, restore default, sparse mixed operations, unselected slots preserved. No camera I/O.')
        window.close();return 0
    if args.example:window.example()
    return app.exec()


if __name__=='__main__':raise SystemExit(main())
