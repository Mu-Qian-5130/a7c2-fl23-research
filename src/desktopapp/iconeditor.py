"""Edit embedded artwork in a new .a7look; never change fitted coefficients."""
from pathlib import Path
from PySide6 import QtCore,QtGui,QtWidgets as W


class MenuIconDialog(W.QDialog):
    def __init__(self,source,parent=None):
        super().__init__(parent)
        from looktool import lookfile
        self.source=Path(source);self.output=None
        self.icon=lookfile.read(source).get('menu_icon')
        self.setWindowTitle('A7Look 菜单图标');self.resize(540,350)
        box=W.QVBoxLayout(self)
        intro=W.QLabel('图标随 .a7look 保存；原文件和色彩参数保留。\n在“生成固件”的自选外观中使用，菜单横屏／竖屏同步生成。')
        intro.setWordWrap(True);box.addWidget(intro)
        form=W.QHBoxLayout();box.addLayout(form)
        self.text=W.QLineEdit();self.text.setPlaceholderText('缩写：1–3 个字母、数字或汉字');form.addWidget(self.text)
        generate=W.QPushButton('生成缩写图标');generate.clicked.connect(self.generate);form.addWidget(generate)
        self.preview=W.QLabel();self.preview.setAlignment(QtCore.Qt.AlignCenter);self.preview.setMinimumHeight(95);box.addWidget(self.preview)
        note=W.QLabel('素材预览（不含原生边框和槽号）。PNG 使用 26×19 像素透明或黑白图案。\n本轮只处理菜单图标；取景／照片回放未适配。')
        note.setWordWrap(True);box.addWidget(note)
        actions=W.QHBoxLayout();box.addLayout(actions)
        png=W.QPushButton('导入 PNG…');png.clicked.connect(self.choose_png);actions.addWidget(png)
        remove=W.QPushButton('移除嵌入图标');remove.clicked.connect(self.remove_icon);actions.addWidget(remove);actions.addStretch()
        buttons=W.QDialogButtonBox(W.QDialogButtonBox.Save|W.QDialogButtonBox.Cancel)
        buttons.button(W.QDialogButtonBox.Save).setText('另存 A7Look…')
        buttons.accepted.connect(self.save);buttons.rejected.connect(self.reject);box.addWidget(buttons)
        self.show_icon()

    def show_icon(self):
        from looktool import iconfile
        if self.icon is None:self.preview.clear();self.preview.setText('未附带图标');return
        pixels=iconfile.mask(self.icon)
        image=QtGui.QImage(pixels,26,19,26,QtGui.QImage.Format_Grayscale8).copy()
        self.preview.setPixmap(QtGui.QPixmap.fromImage(image).scaled(104,76,QtCore.Qt.KeepAspectRatio,QtCore.Qt.FastTransformation))

    def generate(self):
        from looktool import iconfile
        try:self.icon=iconfile.from_text(self.text.text().strip());self.show_icon()
        except (OSError,ValueError) as exc:W.QMessageBox.warning(self,'无法生成图标',str(exc))

    def choose_png(self):
        from looktool import iconfile
        path=W.QFileDialog.getOpenFileName(self,'选择 26×19 PNG 图案',str(self.source.parent),'PNG (*.png)')[0]
        if not path:return
        try:self.icon=iconfile.from_png(path);self.show_icon()
        except (OSError,ValueError) as exc:W.QMessageBox.warning(self,'无法导入图标',str(exc))

    def remove_icon(self):self.icon=None;self.show_icon()

    def save(self):
        from looktool import iconfile
        suggested=self.source.with_name(self.source.stem+'-menu.a7look')
        path=W.QFileDialog.getSaveFileName(self,'另存带图标的 A7Look',str(suggested),'A7Look (*.a7look)')[0]
        if not path:return
        if Path(path).suffix.lower()!='.a7look':path+='.a7look'
        try:iconfile.save_copy(self.source,path,self.icon)
        except (OSError,ValueError) as exc:W.QMessageBox.warning(self,'未保存文件',str(exc));return
        self.output=path;self.accept()
