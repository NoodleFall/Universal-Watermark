import os
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QEvent, QFileInfo, QObject, Qt, Signal
from PySide6.QtGui import QFontMetrics, QPalette, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
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
from functions.video_files import find_videos, is_video_file
from functions.video_info import get_video_info, get_video_thumbnail
from ui.fields import bind_combo, make_title, set_secondary
from ui.var import Var

# Space between the tiles and inside each tile
TILE_SPACING = 10
TILE_PADDING = 8
# Space between the tiles and the edges of the list
GRID_MARGIN = 8
# Previews are read at twice the size of their box, so they stay sharp on high-DPI screens
PREVIEW_SCALE = 2

SORT_NAME = "Name"
SORT_CREATED = "Date created"
SORT_MODIFIED = "Date modified"
SORT_ADDED = "Date added"
SORT_DURATION = "Duration"
SORT_SIZE = "File size"
SORT_RESOLUTION = "Resolution"
# Sort orders of the videos: {name: key of a tile}; None for a tile whose
# duration or resolution isn't read yet, or can't be read
VIDEO_SORTS = {
    SORT_NAME: lambda tile: tile.name_key,
    SORT_CREATED: lambda tile: tile.created,
    SORT_MODIFIED: lambda tile: tile.modified,
    SORT_ADDED: lambda tile: tile.number,
    SORT_DURATION: lambda tile: tile.duration,
    SORT_SIZE: lambda tile: tile.size,
    SORT_RESOLUTION: lambda tile: tile.pixels,
}


def format_duration(seconds):
    # 83 -> "1:23", 3725 -> "1:02:05"
    seconds = round(seconds)
    hours, minutes, seconds = seconds // 3600, seconds // 60 % 60, seconds % 60
    return f"{hours}:{minutes:02}:{seconds:02}" if hours else f"{minutes}:{seconds:02}"


def format_size(size):
    # 532 -> "532 B", 45210000 -> "45.2 MB"
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1000 or unit == "GB":
            return f"{size} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1000


def format_date(date_time):
    return date_time.toString("dd.MM.yyyy")


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
    Tile of a video: its preview with a button that removes the video, its name, its length
    and resolution once they are read, and its file size and date. Keeps what the videos are
    sorted by; number is the order of adding.
    """

    def __init__(self, path, number, on_remove):
        super().__init__()
        self.path = path
        self.number = number
        self.on_remove = on_remove
        # Error message if the video can't be read, None otherwise
        self.error = None
        name = os.path.basename(path)
        # Videos with the same name from different folders by their folder
        self.name_key = (name.lower(), path.lower())
        file_info = QFileInfo(path)
        self.size = file_info.size()
        modified = file_info.lastModified()
        # The creation date isn't known on every system or file system
        created = file_info.birthTime()
        if not created.isValid():
            created = modified
        self.dates = {SORT_CREATED: created, SORT_MODIFIED: modified}
        self.created = created.toMSecsSinceEpoch()
        self.modified = modified.toMSecsSinceEpoch()
        # Read with the preview
        self.duration = None
        self.pixels = None
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
        remove.clicked.connect(self._remove_clicked)
        remove.adjustSize()
        remove.move(PREVIEW_WIDTH - remove.width() - 4, 4)

        name_label = QLabel(QFontMetrics(self.font()).elidedText(name, Qt.TextElideMode.ElideMiddle, PREVIEW_WIDTH))
        name_label.setToolTip(path)
        layout.addWidget(name_label)
        self.info_label = QLabel(" ")
        set_secondary(self.info_label)
        layout.addWidget(self.info_label)
        self.file_label = QLabel()
        self.file_label.setToolTip(
            f"Created: {created.toString('dd.MM.yyyy hh:mm')}\nModified: {modified.toString('dd.MM.yyyy hh:mm')}"
        )
        set_secondary(self.file_label)
        layout.addWidget(self.file_label)
        self.show_date(SORT_CREATED)

    def _remove_clicked(self):
        self.on_remove(self)

    def show_date(self, sort):
        # The modification date while sorting by it, otherwise the creation date
        date = self.dates.get(sort, self.dates[SORT_CREATED])
        self.file_label.setText(f"{format_size(self.size)} · {format_date(date)}")

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
        if info["duration"]:
            self.duration = info["duration"]
        self.pixels = info["width"] * info["height"]
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
    First page of the window: the videos to watermark, as tiles with their previews, in the
    chosen sort order, which is also the order of rendering. Videos are added with the buttons,
    or by dropping files and folders on the page; a folder adds the videos right in it.
    Adding and removing go to history, so they can be undone. on_next opens the settings.
    """

    def __init__(self, history, on_next):
        super().__init__()
        self.history = history
        self.on_next = on_next
        self.setAcceptDrops(True)
        # {video_key(path): tile} of the videos in the list
        self.tiles = {}
        # {video_key(path): [tiles]} of the videos being read, also the removed ones,
        # which undoing may bring back
        self.loading = {}
        # Number of the next added video, for sorting by the order of adding
        self.next_number = 0
        self.columns = 0
        # Folder the "Add" dialogs open in: the one videos were last added from
        self.last_folder_var = Var("")
        self.sort_var = Var(SORT_NAME)
        self.descending_var = Var(False)
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
        header.addWidget(QLabel("Sort:"))
        sort_menu = QComboBox()
        sort_menu.addItems(list(VIDEO_SORTS))
        bind_combo(sort_menu, self.sort_var)
        header.addWidget(sort_menu)
        self.direction_button = QToolButton()
        # A square next to the menu, as tall as it
        side = sort_menu.sizeHint().height()
        self.direction_button.setFixedSize(side, side)
        self.direction_button.clicked.connect(lambda: self.descending_var.set(not self.descending_var.get()))
        header.addWidget(self.direction_button)
        self.sort_var.changed.connect(self._on_sort_changed)
        self.descending_var.changed.connect(self._on_sort_changed)
        header.addSpacing(10)
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

        self._update_direction()
        self._update()

    def video_paths(self):
        # In the order shown
        return [tile.path for tile in self._sorted_tiles()]

    def _sorted_tiles(self):
        # Equal ones by name; the videos whose duration or resolution isn't known yet at the end
        key = VIDEO_SORTS[self.sort_var.get()]
        tiles = sorted(self.tiles.values(), key=lambda tile: tile.name_key)
        known = [tile for tile in tiles if key(tile) is not None]
        unknown = [tile for tile in tiles if key(tile) is None]
        # A stable sort: reversing keeps the equal ones by name
        known.sort(key=key, reverse=self.descending_var.get())
        return known + unknown

    def _on_sort_changed(self, *args):
        self._update_direction()
        sort = self.sort_var.get()
        for tile in self.tiles.values():
            tile.show_date(sort)
        self._layout_tiles(force=True)

    def _update_direction(self):
        descending = self.descending_var.get()
        self.direction_button.setText("↓" if descending else "↑")
        self.direction_button.setToolTip("Descending" if descending else "Ascending")

    def add_paths(self, paths):
        # Add the videos among paths and the videos right in the folders among them;
        # tell what was skipped
        added = []
        duplicates = not_videos = 0
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
                tile = VideoTile(os.path.abspath(video), self.next_number, self._remove)
                tile.show_date(self.sort_var.get())
                self.next_number += 1
                self.tiles[key] = tile
                added.append(tile)
                if key not in self.loading:
                    self.loader.load(video)
                self.loading.setdefault(key, []).append(tile)

        if added:
            self.history.push(lambda: self._take(added), lambda: self._put(added))
        messages = []
        if added:
            messages.append(f"Added {plural(len(added), 'video')}")
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
        tiles = list(self.tiles.values())
        self._take(tiles)
        self.history.push(lambda: self._put(tiles), lambda: self._take(tiles))

    def shutdown(self):
        self.loader.shutdown()

    def _remove(self, tile):
        self._take([tile])
        self.history.push(lambda: self._put([tile]), lambda: self._take([tile]))

    def _take(self, tiles):
        # Take the tiles out of the list, keeping them for undoing; without a parent,
        # the ones history no longer keeps are deleted
        for tile in tiles:
            del self.tiles[video_key(tile.path)]
            tile.setParent(None)
        self.message_label.clear()
        self._update()

    def _put(self, tiles):
        # Bring back tiles taken out, as they were
        for tile in tiles:
            self.tiles[video_key(tile.path)] = tile
            tile.show_date(self.sort_var.get())
        self.message_label.clear()
        self._update()

    def _on_loaded(self, path, info, png, error):
        # Also the tiles removed while the video was read: undoing may bring them back
        for tile in self.loading.pop(video_key(path), []):
            if error is None:
                tile.set_preview(info, png)
            else:
                tile.set_error(error)
        if self.sort_var.get() in (SORT_DURATION, SORT_RESOLUTION):
            self._layout_tiles(force=True)

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
        # Show the tiles in the sort order, the count and whether there is anything to do
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
        for i, tile in enumerate(self._sorted_tiles()):
            self.grid.addWidget(tile, i // columns, i % columns)
            # Tiles taken out and brought back are hidden until shown again
            tile.show()

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
        return [self.last_folder_var, self.sort_var, self.descending_var]

    def settings(self):
        # The folder is saved under the name of the folder setting from before videos were added one by one
        return {
            "raw_videos_path": self.last_folder_var.get(),
            "video_sort": self.sort_var.get(),
            "video_sort_descending": self.descending_var.get(),
        }

    def load_settings(self, saved):
        folder = saved.get("raw_videos_path", "")
        self.last_folder_var.set(folder if isinstance(folder, str) and os.path.isdir(folder) else "")
        sort = saved.get("video_sort")
        self.sort_var.set(sort if sort in VIDEO_SORTS else SORT_NAME)
        self.descending_var.set(bool(saved.get("video_sort_descending", False)))
