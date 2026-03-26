import sys
import json
import base64
import requests
from datetime import datetime
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QPushButton, QLabel, QLineEdit, QTextEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QSpinBox, QMessageBox, QInputDialog,
    QListWidget, QListWidgetItem, QSplitter, QGroupBox, QFormLayout, QComboBox
)
from PySide6.QtCore import Qt, QThread, Signal, QSize
from PySide6.QtGui import QFont, QIcon, QColor, QPalette

# ---------------------------- GitHub API класс ----------------------------
class GitHubAPI:
    def __init__(self, token, owner, repo):
        self.token = token
        self.owner = owner
        self.repo = repo
        self.base_url = f"https://api.github.com/repos/{owner}/{repo}"
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json"
        })

    def _request(self, method, endpoint, **kwargs):
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        resp = self.session.request(method, url, **kwargs)
        resp.raise_for_status()
        return resp.json() if resp.status_code != 204 else None

    def get_file_content(self, path):
        data = self._request("GET", f"contents/{path}")
        content = base64.b64decode(data["content"]).decode("utf-8")
        return content, data["sha"]

    def update_file(self, path, content, commit_message):
        try:
            _, sha = self.get_file_content(path)
        except Exception:
            sha = None
        encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
        payload = {"message": commit_message, "content": encoded}
        if sha:
            payload["sha"] = sha
        return self._request("PUT", f"contents/{path}", json=payload)

    def get_workflow_runs(self, workflow_id="bot.yml", limit=5):
        data = self._request("GET", f"actions/workflows/{workflow_id}/runs")
        return data.get("workflow_runs", [])[:limit]

    def dispatch_workflow(self, workflow_id="bot.yml", ref="main", inputs=None):
        payload = {"ref": ref}
        if inputs:
            payload["inputs"] = inputs
        self._request("POST", f"actions/workflows/{workflow_id}/dispatches", json=payload)
        return True

    def get_run_logs(self, run_id):
        resp = self.session.get(f"{self.base_url}/actions/runs/{run_id}/logs")
        resp.raise_for_status()
        return resp.text


# ---------------------------- Рабочий поток ----------------------------
class ApiWorker(QThread):
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            result = self.func(*self.args, **self.kwargs)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


# ---------------------------- Стили ----------------------------
DARK_STYLE = """
QMainWindow {
    background-color: #1e1e2f;
}
QTabWidget::pane {
    border: 1px solid #2d2d3a;
    background-color: #252533;
}
QTabBar::tab {
    background-color: #2d2d3a;
    color: #cdd6f4;
    padding: 8px 16px;
    margin-right: 2px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
}
QTabBar::tab:selected {
    background-color: #45475a;
}
QPushButton {
    background-color: #45475a;
    color: #cdd6f4;
    border: none;
    padding: 8px 16px;
    border-radius: 6px;
    font-weight: bold;
}
QPushButton:hover {
    background-color: #585b70;
}
QPushButton:pressed {
    background-color: #313244;
}
QLineEdit, QSpinBox, QTextEdit, QListWidget, QTableWidget {
    background-color: #2d2d3a;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 4px;
}
QLabel {
    color: #cdd6f4;
}
QGroupBox {
    border: 1px solid #45475a;
    border-radius: 6px;
    margin-top: 10px;
    font-weight: bold;
    color: #cdd6f4;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
}
QHeaderView::section {
    background-color: #313244;
    color: #cdd6f4;
    padding: 4px;
    border: none;
}
QTableWidget::item {
    padding: 4px;
}
"""


# ---------------------------- Виджеты ----------------------------
class AuthWidget(QWidget):
    auth_success = Signal(object)

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignCenter)

        form = QFormLayout()
        self.token_edit = QLineEdit()
        self.token_edit.setEchoMode(QLineEdit.Password)
        self.owner_edit = QLineEdit()
        self.repo_edit = QLineEdit()
        form.addRow("GitHub Token:", self.token_edit)
        form.addRow("Owner:", self.owner_edit)
        form.addRow("Repository:", self.repo_edit)

        self.btn_connect = QPushButton("Connect")
        self.btn_connect.clicked.connect(self.on_connect)

        layout.addLayout(form)
        layout.addWidget(self.btn_connect, alignment=Qt.AlignCenter)
        self.setLayout(layout)

    def on_connect(self):
        token = self.token_edit.text().strip()
        owner = self.owner_edit.text().strip()
        repo = self.repo_edit.text().strip()
        if not token or not owner or not repo:
            QMessageBox.warning(self, "Error", "All fields are required")
            return
        self.api = GitHubAPI(token, owner, repo)
        self.auth_success.emit(self.api)


class ControlWidget(QWidget):
    def __init__(self, api):
        super().__init__()
        self.api = api
        self.setup_ui()
        self.refresh_status()

    def setup_ui(self):
        layout = QVBoxLayout()

        self.btn_run = QPushButton("▶ Run Workflow Now")
        self.btn_run.clicked.connect(self.run_workflow)
        layout.addWidget(self.btn_run, alignment=Qt.AlignCenter)

        self.status_label = QLabel("Status: Unknown")
        layout.addWidget(self.status_label)

        logs_group = QGroupBox("Last Run Logs")
        logs_layout = QVBoxLayout()
        self.logs_text = QTextEdit()
        self.logs_text.setReadOnly(True)
        logs_layout.addWidget(self.logs_text)
        logs_group.setLayout(logs_layout)
        layout.addWidget(logs_group)

        self.btn_refresh = QPushButton("Refresh Logs")
        self.btn_refresh.clicked.connect(self.refresh_logs)
        layout.addWidget(self.btn_refresh)

        self.setLayout(layout)

    def run_workflow(self):
        self.btn_run.setEnabled(False)
        self.btn_run.setText("⏳ Dispatching...")
        worker = ApiWorker(self.api.dispatch_workflow)
        worker.finished.connect(self.on_dispatch_success)
        worker.error.connect(self.on_dispatch_error)
        worker.start()

    def on_dispatch_success(self, result):
        self.btn_run.setEnabled(True)
        self.btn_run.setText("▶ Run Workflow Now")
        QMessageBox.information(self, "Success", "Workflow dispatched")
        self.refresh_status()

    def on_dispatch_error(self, error):
        self.btn_run.setEnabled(True)
        self.btn_run.setText("▶ Run Workflow Now")
        QMessageBox.critical(self, "Error", f"Failed to dispatch: {error}")

    def refresh_status(self):
        worker = ApiWorker(self.api.get_workflow_runs, limit=1)
        worker.finished.connect(self.update_status)
        worker.error.connect(lambda e: self.status_label.setText(f"Error: {e}"))
        worker.start()

    def update_status(self, runs):
        if runs:
            run = runs[0]
            status = run.get("status", "unknown")
            conclusion = run.get("conclusion", "")
            created = run.get("created_at", "")
            self.status_label.setText(f"Status: {status} ({conclusion})\nLast run: {created}")
            self.current_run_id = run["id"]
            self.refresh_logs()
        else:
            self.status_label.setText("No runs found")

    def refresh_logs(self):
        if hasattr(self, "current_run_id"):
            worker = ApiWorker(self.api.get_run_logs, self.current_run_id)
            worker.finished.connect(self.update_logs)
            worker.error.connect(lambda e: self.logs_text.setPlainText(f"Failed to fetch logs: {e}"))
            worker.start()
        else:
            self.logs_text.setPlainText("No run selected. Run workflow first or refresh status.")

    def update_logs(self, logs):
        self.logs_text.setPlainText(logs)


class SettingsWidget(QWidget):
    def __init__(self, api):
        super().__init__()
        self.api = api
        self.setup_ui()
        self.load_settings()

    def setup_ui(self):
        layout = QVBoxLayout()

        # Основные настройки
        group_main = QGroupBox("General Settings")
        form = QFormLayout()
        self.spin_min_likes = QSpinBox()
        self.spin_min_likes.setRange(0, 10000)
        self.spin_min_image_size = QSpinBox()
        self.spin_min_image_size.setRange(256, 4096)
        self.watermark_edit = QLineEdit()
        form.addRow("MIN_LIKES:", self.spin_min_likes)
        form.addRow("MIN_IMAGE_SIZE:", self.spin_min_image_size)
        form.addRow("Watermark Text:", self.watermark_edit)
        group_main.setLayout(form)
        layout.addWidget(group_main)

        # Чёрный список тегов
        group_blacklist = QGroupBox("Blacklist Tags")
        black_layout = QVBoxLayout()
        self.blacklist_list = QListWidget()
        self.blacklist_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.btn_add_black = QPushButton("Add Tag")
        self.btn_remove_black = QPushButton("Remove Selected")
        self.btn_add_black.clicked.connect(self.add_blacklist_tag)
        self.btn_remove_black.clicked.connect(self.remove_blacklist_tags)
        black_layout.addWidget(self.blacklist_list)
        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.btn_add_black)
        btn_layout.addWidget(self.btn_remove_black)
        black_layout.addLayout(btn_layout)
        group_blacklist.setLayout(black_layout)
        layout.addWidget(group_blacklist)

        # Шаблоны промптов
        group_prompts = QGroupBox("Prompt Templates")
        prompts_layout = QVBoxLayout()
        self.prompts_list = QListWidget()
        self.prompts_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.btn_add_prompt = QPushButton("Add Template")
        self.btn_edit_prompt = QPushButton("Edit Selected")
        self.btn_remove_prompt = QPushButton("Remove Selected")
        self.btn_add_prompt.clicked.connect(self.add_prompt)
        self.btn_edit_prompt.clicked.connect(self.edit_prompt)
        self.btn_remove_prompt.clicked.connect(self.remove_prompts)
        prompts_layout.addWidget(self.prompts_list)
        btn_prompts = QHBoxLayout()
        btn_prompts.addWidget(self.btn_add_prompt)
        btn_prompts.addWidget(self.btn_edit_prompt)
        btn_prompts.addWidget(self.btn_remove_prompt)
        prompts_layout.addLayout(btn_prompts)
        group_prompts.setLayout(prompts_layout)
        layout.addWidget(group_prompts)

        self.btn_save = QPushButton("💾 Save All to GitHub")
        self.btn_save.clicked.connect(self.save_settings)
        layout.addWidget(self.btn_save)

        self.setLayout(layout)

    def load_settings(self):
        try:
            content, _ = self.api.get_file_content("config.json")
            config = json.loads(content)
            self.spin_min_likes.setValue(config.get("MIN_LIKES", 20))
            self.spin_min_image_size.setValue(config.get("MIN_IMAGE_SIZE", 512))
            self.watermark_edit.setText(config.get("WATERMARK_TEXT", "@eroslabai"))
            blacklist = config.get("BLACKLIST_TAGS", [])
            self.blacklist_list.clear()
            for tag in blacklist:
                self.blacklist_list.addItem(tag)
            prompts = config.get("PROMPT_TEMPLATES", [])
            self.prompts_list.clear()
            for prompt in prompts:
                self.prompts_list.addItem(prompt)
        except Exception as e:
            QMessageBox.warning(self, "Warning", f"Could not load config: {e}")

    def add_blacklist_tag(self):
        tag, ok = QInputDialog.getText(self, "Add Tag", "Enter tag:")
        if ok and tag.strip():
            self.blacklist_list.addItem(tag.strip())

    def remove_blacklist_tags(self):
        for item in self.blacklist_list.selectedItems():
            self.blacklist_list.takeItem(self.blacklist_list.row(item))

    def add_prompt(self):
        prompt, ok = QInputDialog.getMultiLineText(self, "Add Prompt", "Enter prompt template:")
        if ok and prompt.strip():
            self.prompts_list.addItem(prompt.strip())

    def edit_prompt(self):
        current = self.prompts_list.currentItem()
        if not current:
            return
        old_text = current.text()
        new_text, ok = QInputDialog.getMultiLineText(self, "Edit Prompt", "Edit prompt:", text=old_text)
        if ok:
            current.setText(new_text)

    def remove_prompts(self):
        for item in self.prompts_list.selectedItems():
            self.prompts_list.takeItem(self.prompts_list.row(item))

    def save_settings(self):
        config = {
            "MIN_LIKES": self.spin_min_likes.value(),
            "MIN_IMAGE_SIZE": self.spin_min_image_size.value(),
            "WATERMARK_TEXT": self.watermark_edit.text(),
            "BLACKLIST_TAGS": [self.blacklist_list.item(i).text() for i in range(self.blacklist_list.count())],
            "PROMPT_TEMPLATES": [self.prompts_list.item(i).text() for i in range(self.prompts_list.count())]
        }
        try:
            self.api.update_file("config.json", json.dumps(config, indent=2, ensure_ascii=False), "Update config via GUI")
            QMessageBox.information(self, "Saved", "Settings saved to GitHub")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save: {e}")


class HistoryStatsWidget(QWidget):
    def __init__(self, api):
        super().__init__()
        self.api = api
        self.setup_ui()
        self.load_data()

    def setup_ui(self):
        layout = QVBoxLayout()
        splitter = QSplitter(Qt.Horizontal)

        # История (posted_ids.json)
        hist_group = QGroupBox("Posted IDs")
        hist_layout = QVBoxLayout()
        self.hist_table = QTableWidget()
        self.hist_table.setColumnCount(2)
        self.hist_table.setHorizontalHeaderLabels(["ID", "Date (approx)"])
        self.hist_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.btn_refresh_hist = QPushButton("Refresh History")
        self.btn_refresh_hist.clicked.connect(self.load_history)
        self.btn_remove_hist = QPushButton("Remove Selected")
        self.btn_remove_hist.clicked.connect(self.remove_selected_ids)
        hist_layout.addWidget(self.hist_table)
        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.btn_refresh_hist)
        btn_layout.addWidget(self.btn_remove_hist)
        hist_layout.addLayout(btn_layout)
        hist_group.setLayout(hist_layout)

        # Статистика
        stats_group = QGroupBox("Statistics")
        stats_layout = QVBoxLayout()
        self.stats_label = QLabel()
        self.stats_label.setWordWrap(True)
        self.btn_refresh_stats = QPushButton("Refresh Stats")
        self.btn_refresh_stats.clicked.connect(self.load_stats)
        stats_layout.addWidget(self.stats_label)
        stats_layout.addWidget(self.btn_refresh_stats)
        stats_group.setLayout(stats_layout)

        splitter.addWidget(hist_group)
        splitter.addWidget(stats_group)
        splitter.setSizes([500, 300])

        layout.addWidget(splitter)
        self.setLayout(layout)

    def load_data(self):
        self.load_history()
        self.load_stats()

    def load_history(self):
        try:
            content, _ = self.api.get_file_content("posted_ids.json")
            ids = json.loads(content)
            self.hist_table.setRowCount(len(ids))
            for i, item_id in enumerate(ids):
                self.hist_table.setItem(i, 0, QTableWidgetItem(item_id))
                self.hist_table.setItem(i, 1, QTableWidgetItem(""))
        except Exception as e:
            QMessageBox.warning(self, "Warning", f"Could not load history: {e}")

    def load_stats(self):
        try:
            content, _ = self.api.get_file_content("stats.json")
            stats = json.loads(content)
            total = stats.get("total_posts", 0)
            top_tags = stats.get("top_tags", {})
            top_str = "\n".join(f"{tag}: {count}" for tag, count in list(top_tags.items())[:20])
            self.stats_label.setText(f"Total posts: {total}\n\nTop tags:\n{top_str}")
        except Exception as e:
            self.stats_label.setText(f"Error loading stats: {e}")

    def remove_selected_ids(self):
        selected_rows = set()
        for item in self.hist_table.selectedItems():
            selected_rows.add(item.row())
        if not selected_rows:
            return
        reply = QMessageBox.question(self, "Confirm", f"Remove {len(selected_rows)} IDs?",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        try:
            content, sha = self.api.get_file_content("posted_ids.json")
            ids = json.loads(content)
            for row in sorted(selected_rows, reverse=True):
                if row < len(ids):
                    del ids[row]
            self.api.update_file("posted_ids.json", json.dumps(ids, indent=2), "Remove IDs via GUI")
            QMessageBox.information(self, "Updated", "IDs removed")
            self.load_history()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to update: {e}")


class LogsWidget(QWidget):
    def __init__(self, api):
        super().__init__()
        self.api = api
        self.setup_ui()
        self.load_runs()

    def setup_ui(self):
        layout = QVBoxLayout()
        self.run_combo = QComboBox()
        self.run_combo.currentIndexChanged.connect(self.load_run_logs)
        self.logs_text = QTextEdit()
        self.logs_text.setReadOnly(True)
        layout.addWidget(QLabel("Select workflow run:"))
        layout.addWidget(self.run_combo)
        layout.addWidget(self.logs_text)
        self.setLayout(layout)

    def load_runs(self):
        worker = ApiWorker(self.api.get_workflow_runs, limit=5)
        worker.finished.connect(self.populate_runs)
        worker.error.connect(lambda e: self.logs_text.setPlainText(f"Error: {e}"))
        worker.start()

    def populate_runs(self, runs):
        self.run_combo.clear()
        self.run_data = {}
        for run in runs:
            run_id = run["id"]
            created = run["created_at"]
            status = run["status"]
            text = f"{created} - {status} (ID: {run_id})"
            self.run_combo.addItem(text, run_id)
            self.run_data[run_id] = run
        if runs:
            self.load_run_logs(0)

    def load_run_logs(self, index):
        run_id = self.run_combo.itemData(index)
        if run_id:
            worker = ApiWorker(self.api.get_run_logs, run_id)
            worker.finished.connect(self.logs_text.setPlainText)
            worker.error.connect(lambda e: self.logs_text.setPlainText(f"Failed to fetch logs: {e}"))
            worker.start()


# ---------------------------- Главное окно ----------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ErosLab Bot Manager")
        self.resize(900, 700)
        self.setStyleSheet(DARK_STYLE)

        self.api = None
        self.setup_auth()

    def setup_auth(self):
        self.auth_widget = AuthWidget()
        self.auth_widget.auth_success.connect(self.on_auth_success)
        self.setCentralWidget(self.auth_widget)

    def on_auth_success(self, api):
        self.api = api
        self.setup_main_ui()

    def setup_main_ui(self):
        self.tabs = QTabWidget()

        self.control_tab = ControlWidget(self.api)
        self.settings_tab = SettingsWidget(self.api)
        self.history_tab = HistoryStatsWidget(self.api)
        self.logs_tab = LogsWidget(self.api)

        self.tabs.addTab(self.control_tab, "🚀 Control")
        self.tabs.addTab(self.settings_tab, "⚙️ Settings")
        self.tabs.addTab(self.history_tab, "📜 History & Stats")
        self.tabs.addTab(self.logs_tab, "📋 All Logs")

        self.setCentralWidget(self.tabs)


# ---------------------------- Запуск ----------------------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())