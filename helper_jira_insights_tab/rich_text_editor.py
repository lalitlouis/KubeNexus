from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTextEdit, QToolBar, QAction, QFontComboBox, QSpinBox
from PyQt5.QtGui import QFont, QTextListFormat, QTextCursor
from PyQt5.QtCore import Qt
import re
from PyQt5.QtWidgets import QComboBox, QListView
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QStandardItemModel, QStandardItem

class AutocompleteComboBox(QComboBox):
    def __init__(self, parent=None, fetch_users_callback=None):
        super().__init__(parent)
        self.fetch_users_callback = fetch_users_callback
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.update_completions)
        self.lineEdit().textEdited.connect(self.start_timer)
        self.users = []
        
        # Increase the size of the dropdown
        self.view().setMinimumWidth(400)  # Adjust this value as needed
        self.view().setMinimumHeight(300)  # Adjust this value as needed

        # Use custom view to show both display name and username
        self.setView(QListView())
        self.view().setUniformItemSizes(True)
        self.view().setSpacing(2)

    def start_timer(self):
        self.timer.start(300)  # 300 ms delay

    def update_completions(self):
        text = self.lineEdit().text()
        if self.fetch_users_callback:
            self.users = self.fetch_users_callback(text)
            model = QStandardItemModel()
            for user in self.users:
                item = QStandardItem(f"{user['displayName']} ({user['name']})")
                item.setData(user['name'], Qt.UserRole)
                model.appendRow(item)
            self.setModel(model)
            self.showPopup()

    def get_selected_username(self):
        index = self.currentIndex()
        if index >= 0:
            return self.model().item(index).data(Qt.UserRole)
        return self.currentText()

    def keyPressEvent(self, event):
        super().keyPressEvent(event)
        if event.key() not in (Qt.Key_Enter, Qt.Key_Return, Qt.Key_Up, Qt.Key_Down):
            self.start_timer()

class CustomTextEdit(QTextEdit):
    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.handleReturn()
        elif event.key() == Qt.Key_Tab:
            self.handleTab()
        elif event.key() == Qt.Key_Backtab:
            self.handleBacktab()
        else:
            super().keyPressEvent(event)

    def handleReturn(self):
        cursor = self.textCursor()
        current_block = cursor.block()
        current_text = current_block.text()

        bullet_match = re.match(r'^(\s*)([*+-]) (.*)$', current_text)
        number_match = re.match(r'^(\s*)(\d+)\. (.*)$', current_text)
        letter_match = re.match(r'^(\s*)([a-z])\. (.*)$', current_text)

        if bullet_match:
            indent, bullet, content = bullet_match.groups()
            if content:
                self.insertPlainText('\n' + indent + bullet + ' ')
            else:
                cursor.select(QTextCursor.BlockUnderCursor)
                cursor.removeSelectedText()
                self.insertPlainText('\n')
        elif number_match:
            indent, number, content = number_match.groups()
            if content:
                next_number = int(number) + 1
                self.insertPlainText('\n' + indent + f"{next_number}. ")
            else:
                cursor.select(QTextCursor.BlockUnderCursor)
                cursor.removeSelectedText()
                self.insertPlainText('\n')
        elif letter_match:
            indent, letter, content = letter_match.groups()
            if content:
                next_letter = chr(ord(letter) + 1)
                if next_letter > 'z':
                    next_letter = 'a'
                self.insertPlainText('\n' + indent + f"{next_letter}. ")
            else:
                cursor.select(QTextCursor.BlockUnderCursor)
                cursor.removeSelectedText()
                self.insertPlainText('\n')
        else:
            self.insertPlainText('\n')

    def handleTab(self):
        cursor = self.textCursor()
        current_block = cursor.block()
        current_text = current_block.text()

        bullet_match = re.match(r'^(\s*)([*+-]) (.*)$', current_text)
        number_match = re.match(r'^(\s*)(\d+)\.(.*)$', current_text)
        letter_match = re.match(r'^(\s*)([a-z])\.(.*)$', current_text)

        if bullet_match:
            indent, bullet, content = bullet_match.groups()
            new_indent = indent + '  '
            new_bullet = '-' if bullet == '*' else ('*' if bullet == '-' else '+')
            cursor.movePosition(QTextCursor.EndOfBlock)
            cursor.insertText('\n' + new_indent + new_bullet + ' ')
        elif number_match:
            indent, number, content = number_match.groups()
            new_indent = indent + '  '
            cursor.movePosition(QTextCursor.EndOfBlock)
            cursor.insertText('\n' + new_indent + 'a. ')
        elif letter_match:
            indent, letter, content = letter_match.groups()
            new_indent = indent + '  '
            new_bullet = '*'
            cursor.movePosition(QTextCursor.EndOfBlock)
            cursor.insertText('\n' + new_indent + new_bullet + ' ')
        else:
            cursor.insertText('  ')

        self.setTextCursor(cursor)

    def handleBacktab(self):
        cursor = self.textCursor()
        current_block = cursor.block()
        current_text = current_block.text()

        if current_text.startswith('  '):
            cursor.movePosition(QTextCursor.StartOfBlock)
            cursor.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor, 2)
            cursor.removeSelectedText()

        self.setTextCursor(cursor)

class RichTextEditor(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUI()

    def setupUI(self):
        layout = QVBoxLayout(self)
        
        # Create toolbar
        self.toolbar = QToolBar()
        layout.addWidget(self.toolbar)

        # Text edit
        self.editor = CustomTextEdit()
        self.editor.setAcceptRichText(False)
        layout.addWidget(self.editor)

        # Font type
        self.fontCombo = QFontComboBox()
        self.fontCombo.currentFontChanged.connect(self.changeFont)
        self.toolbar.addWidget(self.fontCombo)

        # Font size
        self.sizeCombo = QSpinBox()
        self.sizeCombo.setRange(8, 72)
        self.sizeCombo.setValue(12)
        self.sizeCombo.valueChanged.connect(self.changeFontSize)
        self.toolbar.addWidget(self.sizeCombo)

        # Bold
        boldAction = QAction('B', self)
        boldAction.setCheckable(True)
        boldAction.triggered.connect(lambda: self.insertMarkdown('**'))
        self.toolbar.addAction(boldAction)

        # Italic
        italicAction = QAction('I', self)
        italicAction.setCheckable(True)
        italicAction.triggered.connect(lambda: self.insertMarkdown('*'))
        self.toolbar.addAction(italicAction)

        # Bullet list
        bulletAction = QAction('•', self)
        bulletAction.triggered.connect(self.setBulletList)
        self.toolbar.addAction(bulletAction)

        # Numbered list
        numberedAction = QAction('1.', self)
        numberedAction.triggered.connect(self.setNumberedList)
        self.toolbar.addAction(numberedAction)

        # Code block
        codeAction = QAction('Code', self)
        codeAction.triggered.connect(lambda: self.insertMarkdown('```'))
        self.toolbar.addAction(codeAction)

        # Link
        linkAction = QAction('Link', self)
        linkAction.triggered.connect(self.insertLink)
        self.toolbar.addAction(linkAction)

    def changeFont(self, font):
        self.editor.setCurrentFont(font)

    def changeFontSize(self, size):
        self.editor.setFontPointSize(size)

    def insertMarkdown(self, markdown):
        cursor = self.editor.textCursor()
        if cursor.hasSelection():
            start = cursor.selectionStart()
            end = cursor.selectionEnd()
            cursor.beginEditBlock()
            cursor.setPosition(start)
            cursor.insertText(markdown)
            cursor.setPosition(end + len(markdown))
            cursor.insertText(markdown)
            cursor.endEditBlock()
        else:
            cursor.insertText(markdown)
        self.editor.setTextCursor(cursor)

    def setBulletList(self):
        cursor = self.editor.textCursor()
        cursor.insertText("- ")

    def setNumberedList(self):
        cursor = self.editor.textCursor()
        cursor.insertText("1. ")

    def insertLink(self):
        cursor = self.editor.textCursor()
        cursor.insertText("[Link Text](https://example.com)")

    def toPlainText(self):
        return self.editor.toPlainText()

    def setPlainText(self, text):
        self.editor.setPlainText(text)