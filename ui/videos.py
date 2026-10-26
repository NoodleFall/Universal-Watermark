import os
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QFontMetrics, QPalette, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from constants import (
    PREVIEW_HEIGHT,
    PREVIEW_TIME_SECONDS,
    PREVIEW_WIDTH,
    PREVIEW_WORKERS,
    VIDEO_EXTENSIONS,
)
from functions.video_files import find_videos, is_video_file, sort_videos
from functions.video_info import get_video_info, get_video_thumbnail
from ui.fields import make_title, set_secondary
from ui.var import Var

# Space between the tiles and inside each tile
TILE_SPACING = 10
TILE_PADDING = 8
# Space between the tiles and the edges of the list
GRID_MARGIN = 8
# Previews are read at twice the size of their box, so they stay sharp on high-DPI screens
PREVIEW_SCALE = 2


def format_duration(seconds):
    # 83 -> "1:23", 3725 -> "1:02:05"
    seconds = round(seconds)
    hours, minutes, seconds = seconds // 3600, seconds // 60 % 60, seconds % 60
    return f"{hours}:{minutes:02}:{seconds:02}" if hours else f"{minutes}:{seconds:02}"


def video_key(path):
    # The same file added twice, e.g. through a link or with different letter case on Windows
    return os.path.normcase(os.path.realpath(path))


def repolish(widget):
    # Apply the style rules that depend on a property or name that just changed
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def plural(count, word):
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


class PreviewLoader(QObject):
    """
    Reads the info and a preview frame of videos in background threads; loaded is emitted
    with the path, the info and the PNG data, or the path and an error message.
    Being emitted in another thread, it runs the connected methods in the main thread.
    """

    loaded = Signal(str, object, object, object)

    def __init__(self):
        super().__init__()
        self._executor = ThreadPoolExecutor(max_workers=PREVIEW_WORKERS)

    def load(self, path):
        self._executor.submit(self._load, path)

    def _load(self, path):
        try:
            info = get_video_info(path)
            # A frame a little after the start, which is often black
            time = min(PREVIEW_TIME_SECONDS, (info["duration"] or 0) / 2)
            png = get_video_thumbnail(path, time, PREVIEW_WIDTH * PREVIEW_SCALE, PREVIEW_HEIGHT * PREVIEW_SCALE)
        except Exception as e:
            self.loaded.emit(path, None, None, str(e))
        else:
            self.loaded.emit(path, info, png, None)

    def shutdown(self):
        # Don't keep the program running to read the videos still waiting
        self._executor.shutdown(wait=False, cancel_futures=True)


class VideoTile(QFrame):
    """
    Tile of a video: its preview with a button that removes the video, its name
    and its length and size once they are read.
    """

    def __init__(self, path, on_remove):
        super().__init__()
        self.path = path
        # Error message if the video can't be read, None otherwise
        self.error = None
        self.setObjectName("tile")
        self.setFixedWidth(PREVIEW_WIDTH + 2 * TILE_PADDING)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(TILE_PADDING, TILE_PADDING, TILE_PADDING, TILE_PADDING)
        layout.setSpacing(4)

        self.preview = QLabel("Loading…")
        self.preview.setObjectName("preview")
        self.preview.setFixedSize(PREVIEW_WIDTH, PREVIEW_HEIGHT)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        set_secondary(self.preview)
        layout.addWidget(self.preview)

        # The remove button sits in the corner of the preview
        remove = QToolButton(self.preview)
        remove.setObjectName("removeVideo")
        remove.setText("✕")
        remove.setToolTip("Remove from the list")
        remove.setCursor(Qt.CursorShape.PointingHandCursor)
        remove.clicked.connect(lambda: on_remove(self))
        remove.adjustSize()
        remove.move(PREVIEW_WIDTH - remove.width() - 4, 4)

        name = os.path.basename(path)
        name_label = QLabel(QFontMetrics(self.font()).elidedText(name, Qt.TextElideMode.ElideMiddle, PREVIEW_WIDTH))
        name_label.setToolTip(path)
        layout.addWidget(name_label)
        self.info_label = QLabel(" ")
        set_secondary(self.info_label)
        layout.addWidget(self.info_label)

    def set_preview(self, info, png):
        pixmap = QPixmap()
        pixmap.loadFromData(png)
        ratio = self.devicePixelRatioF()
        pixmap = pixmap.scaled(
            round(PREVIEW_WIDTH * ratio), round(PREVIEW_HEIGHT * ratio),
            Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
        pixmap.setDevicePixelRatio(ratio)
        self.preview.setPixmap(pixmap)
        self.info_label.setText(f"{format_duration(info['duration'] or 0)} · {info['width']}×{info['height']}")

    def set_error(self, error):
        self.error = error
        self.preview.setText("No preview")
        self.info_label.setText("Can't read this video")
        self.info_label.setToolTip(error)
        # Red from the style sheet instead of the lighter color of hints
        self.info_label.setForegroundRole(QPalette.ColorRole.WindowText)
        self.info_label.setObjectName("error")
        repolish(self.info_label)


class VideosPage(QWidget):
    """
    First page of the window: the videos to watermark, as tiles with their previews, always
    sorted by name. Videos are added with the buttons, or by dropping files and folders
    on the page; a folder adds the videos right in it. on_next opens the settings.
    """

    def __init__(self, on_next):
        super().__init__()
        self.on_next = on_next
        self.setAcceptDrops(True)
        # {video_key(path): tile}
        self.tiles = {}
        self.columns = 0
        # Folder the "Add" dialogs open in: the one videos were last added from
        self.last_folder_var = Var("")
        self.loader = PreviewLoader()
        self.loader.loaded.connect(self._on_loaded)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        header = QHBoxLayout()
        # Name of the mode: videos now, later also photos and PDF files
        header.addWidget(make_title("Video", 1.4))
        self.count_label = QLabel()
        set_secondary(self.count_label)
        header.addSpacing(6)
        header.addWidget(self.count_label, 0, Qt.AlignmentFlag.AlignBottom)
        header.addStretch()
        # One button adds both: a file dialog can't pick files and folders at once, so it asks which
        add_button = QPushButton("Add video")
        add_menu = QMenu(add_button)
        add_menu.addAction("Video files…", self._browse_videos)
        add_menu.addAction("Folder of videos…", self._browse_folder)
        add_button.setMenu(add_menu)
        header.addWidget(add_button)
        self.clear_button = QPushButton("Clear")
        self.clear_button.clicked.connect(self.clear)
        header.addWidget(self.clear_button)
        layout.addLayout(header)

        # The videos, or while there are none, an invitation to drop them;
        # the frame lights up while files are dragged over the page
        self.drop_area = QFrame()
        self.drop_area.setObjectName("dropArea")
        drop_layout = QVBoxLayout(self.drop_area)
        drop_layout.setContentsMargins(2, 2, 2, 2)
        self.content = QStackedWidget()
        drop_layout.addWidget(self.content)
        layout.addWidget(self.drop_area, 1)

        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        empty_layout.addStretch()
        drop_title = make_title("Drop videos or a folder here", 1.3)
        drop_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(drop_title)
        drop_hint = QLabel(
            "or use \"Add video\" above\n"
            + " ".join(extension[1:] for extension in VIDEO_EXTENSIONS)
        )
        drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        set_secondary(drop_hint)
        empty_layout.addWidget(drop_hint)
        empty_layout.addStretch()
        self.content.addWidget(empty)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        grid_widget = QWidget()
        grid_widget.setObjectName("tiles")
        self.grid = QGridLayout(grid_widget)
        self.grid.setContentsMargins(GRID_MARGIN, GRID_MARGIN, GRID_MARGIN, GRID_MARGIN)
        self.grid.setSpacing(TILE_SPACING)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.scroll.setWidget(grid_widget)
        # The number of columns follows the width of the visible part
        self.scroll.viewport().installEventFilter(self)
        self.content.addWidget(self.scroll)

        footer = QHBoxLayout()
        # What the last adding did, e.g. skipped files
        self.message_label = QLabel()
        set_secondary(self.message_label)
        self.message_label.setWordWrap(True)
        footer.addWidget(self.message_label, 1)
        self.next_button = QPushButton("Next step  →")
        self.next_button.setObjectName("primary")
        self.next_button.setMinimumWidth(130)
        self.next_button.clicked.connect(self._next)
        footer.addWidget(self.next_button)
        layout.addLayout(footer)

        self._update()

    def video_paths(self):
        return sort_videos(tile.path for tile in self.tiles.values())

    def add_paths(self, paths):
        # Add the videos among paths and the videos right in the folders among them;
        # tell what was skipped
        added = duplicates = not_videos = 0
        empty_folders = []
        for path in paths:
            if os.path.isdir(path):
                videos = find_videos(path)
                if not videos:
                    empty_folders.append(os.path.basename(os.path.normpath(path)) or path)
            elif is_video_file(path):
                videos = [path]
            else:
                not_videos += 1
                continue
            for video in videos:
                key = video_key(video)
                if key in self.tiles:
                    duplicates += 1
                    continue
                self.tiles[key] = VideoTile(os.path.abspath(video), self._remove)
                self.loader.load(video)
                added += 1

        messages = []
        if added:
            messages.append(f"Added {plural(added, 'video')}")
        if duplicates:
            messages.append(f"{plural(duplicates, 'video')} already in the list")
        if not_videos:
            messages.append(f"{plural(not_videos, 'file')} skipped: not videos")
        if empty_folders:
            messages.append("no videos in " + ", ".join(empty_folders))
        message = "; ".join(messages)
        self.message_label.setText(message[:1].upper() + message[1:] + ("." if message else ""))
        self._update()

    def clear(self):
        for tile in self.tiles.values():
            tile.deleteLater()
        self.tiles.clear()
        self.message_label.clear()
        self._update()

    def shutdown(self):
        self.loader.shutdown()

    def _remove(self, tile):
        del self.tiles[video_key(tile.path)]
        tile.deleteLater()
        self._update()

    def _on_loaded(self, path, info, png, error):
        # The video may have been removed while it was read
        tile = self.tiles.get(video_key(path))
        if tile is None:
            return
        if error is None:
            tile.set_preview(info, png)
        else:
            tile.set_error(error)

    def _browse_videos(self):
        patterns = " ".join(f"*{extension} *{extension.upper()}" for extension in VIDEO_EXTENSIONS)
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add videos", self.last_folder_var.get(), f"Videos ({patterns});;All files (*)"
        )
        if paths:
            self.last_folder_var.set(os.path.dirname(paths[0]))
            self.add_paths(paths)

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Add folder of videos", self.last_folder_var.get())
        if folder:
            self.last_folder_var.set(folder)
            self.add_paths([folder])

    def _next(self):
        unreadable = [os.path.basename(tile.path) for tile in self.tiles.values() if tile.error is not None]
        if unreadable:
            QMessageBox.warning(
                self, "Videos", "Remove the videos that can't be read:\n" + "\n".join(sorted(unreadable))
            )
            return
        self.on_next()

    def _update(self):
        # Show the tiles in the order of their names, the count and whether there is anything to do
        count = len(self.tiles)
        self.count_label.setText(plural(count, "video") if count else "")
        self.content.setCurrentIndex(1 if count else 0)
        self.next_button.setEnabled(count > 0)
        self.clear_button.setEnabled(count > 0)
        self.drop_area.setProperty("empty", count == 0)
        repolish(self.drop_area)
        self._layout_tiles(force=True)

    def _layout_tiles(self, force=False):
        # As many columns as fit in the visible width
        tile_width = PREVIEW_WIDTH + 2 * TILE_PADDING
        width = self.scroll.viewport().width() - 2 * GRID_MARGIN
        columns = max(1, (width + TILE_SPACING) // (tile_width + TILE_SPACING))
        if columns == self.columns and not force:
            return
        self.columns = columns
        while self.grid.count():
            self.grid.takeAt(0)
        by_path = {tile.path: tile for tile in self.tiles.values()}
        for i, path in enumerate(self.video_paths()):
            self.grid.addWidget(by_path[path], i // columns, i % columns)

    def eventFilter(self, watched, event):
        if watched is self.scroll.viewport() and event.type() == QEvent.Type.Resize:
            self._layout_tiles()
        return super().eventFilter(watched, event)

    def _set_dragging(self, dragging):
        self.drop_area.setProperty("dragging", dragging)
        repolish(self.drop_area)

    def dragEnterEvent(self, event):
        if any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()
            self._set_dragging(True)

    def dragLeaveEvent(self, event):
        self._set_dragging(False)

    def dropEvent(self, event):
        self._set_dragging(False)
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            event.acceptProposedAction()
            self.add_paths(paths)

    def variables(self):
        return [self.last_folder_var]

    def settings(self):
        # Saved under the name of the folder setting from before videos were added one by one
        return {"raw_videos_path": self.last_folder_var.get()}

    def load_settings(self, saved):
        folder = saved.get("raw_videos_path", "")
        self.last_folder_var.set(folder if isinstance(folder, str) and os.path.isdir(folder) else "")
