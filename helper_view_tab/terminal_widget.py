from PyQt5.QtWidgets import QTextEdit
from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtGui import QTextCursor, QTextCharFormat
import os
import re
import select
import pty
import subprocess
import termios

class TerminalWidget(QTextEdit):
    command_entered = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: black; color: white; font-family: monospace;")
        self.setReadOnly(False)
        self.prompt_position = 0
        self.current_command = ""
        self.ssh_client = None
        self.ssh_channel = None
        self.command_history = []
        self.history_index = 0

    def set_ssh_connection(self, ssh_client, ssh_channel, username, auth_method):
        self.ssh_client = ssh_client
        self.ssh_channel = ssh_channel
        hostname, port = self.ssh_client.get_transport().getpeername()
        self.append_output(f"Connected to {hostname}:{port} as {username} using {auth_method} authentication.\n")
        self.append_output("Type your commands below:\n")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Return:
            self.handle_return()
        elif event.key() == Qt.Key_Backspace:
            if self.textCursor().position() > self.prompt_position:
                cursor = self.textCursor()
                cursor.deletePreviousChar()
                self.setTextCursor(cursor)
                self.current_command = self.current_command[:-1]
        elif event.key() == Qt.Key_Up:
            self.handle_up_key()
        elif event.key() == Qt.Key_Down:
            self.handle_down_key()
        else:
            super().keyPressEvent(event)
            self.current_command += event.text()

    def handle_return(self):
        command = self.current_command.strip()
        self.command_history.append(command)
        self.history_index = len(self.command_history)
        self.current_command = ""
        self.append_output('\n')
        if self.ssh_channel:
            self.execute_ssh_command(command)
        else:
            self.command_entered.emit(command)
        
        # Handle the "clear" command
        if command == "clear":
            self.clear()
            self.set_prompt_position()

    def execute_ssh_command(self, command):
        if self.ssh_channel:
            try:
                self.ssh_channel.send(command + '\n')
            except Exception as e:
                self.append_output(f"Error sending command: {str(e)}\n")

    def append_output(self, output):
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(output)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()
        self.prompt_position = self.textCursor().position()

    def handle_up_key(self):
        if self.history_index > 0:
            self.history_index -= 1
            self.set_command(self.command_history[self.history_index])

    def handle_down_key(self):
        if self.history_index < len(self.command_history) - 1:
            self.history_index += 1
            self.set_command(self.command_history[self.history_index])
        elif self.history_index == len(self.command_history) - 1:
            self.history_index = len(self.command_history)
            self.set_command("")

    def set_command(self, command):
        cursor = self.textCursor()
        cursor.setPosition(self.prompt_position)
        cursor.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
        cursor.removeSelectedText()
        cursor.insertText(command)
        self.setTextCursor(cursor)
        self.current_command = command

    def set_prompt_position(self):
        self.prompt_position = self.textCursor().position()

    def ensure_cursor_at_end(self):
        cursor = self.textCursor()
        if cursor.position() < self.prompt_position:
            cursor.movePosition(QTextCursor.End)
            self.setTextCursor(cursor)
