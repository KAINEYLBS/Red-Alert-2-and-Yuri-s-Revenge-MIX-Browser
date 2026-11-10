from __future__ import annotations

import math
from html import escape

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QRect,
    QSignalBlocker,
    QT_TRANSLATE_NOOP,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QImage,
    QMatrix4x4,
    QOpenGLFunctions,
    QPainter,
    QPalette,
    QPixmap,
    QStandardItem,
    QStandardItemModel,
    QVector3D,
)
from PySide6.QtOpenGL import (
    QOpenGLBuffer,
    QOpenGLShader,
    QOpenGLShaderProgram,
    QOpenGLTexture,
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollBar,
    QSlider,
    QStackedWidget,
    QTableView,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from mix_browser.features.archive.dat_format import DatRecord
from mix_browser.features.browser.asset_preview import (
    EntryPreviewResult,
    PALETTE_GROUPS,
    PALETTE_SELECTION_STAGES,
    PaletteOption,
    VoxelModel,
    indexed_frame_image,
)
from mix_browser.features.browser.document_preview import (
    DecodedDocument,
    DocumentPreviewPane,
)
from mix_browser.features.browser.palette_naming_guide import (
    PaletteNamingGuideDialog,
)
from mix_browser.features.browser.vlc_video_player import VlcMediaPlayer
from mix_browser.shared.application_style import BROWSER_TOOLBAR_CONTROL_HEIGHT

_GL_DEPTH_TEST = 0x0B71
_GL_LEQUAL = 0x0203
_GL_COLOR_BUFFER_BIT = 0x00004000
_GL_DEPTH_BUFFER_BIT = 0x00000100
_GL_FLOAT = 0x1406
_GL_TRIANGLES = 0x0004


# @arch mix-browser.dat-preview-table-model model | en: Exposes parsed DAT records to a virtualized preview table | zh: 将解析后的 DAT 记录提供给虚拟化预览表格
class _DatPreviewTableModel(QAbstractTableModel):
    _HEADERS = tuple(
        QT_TRANSLATE_NOOP("_DatPreviewTableModel", label)
        for label in ("Group", "Name", "Description")
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._records: tuple[DatRecord, ...] = ()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._records)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._records):
            return None
        record = self._records[index.row()]
        values = (record.group, record.name, record.description)
        if role in {Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole}:
            return values[index.column()]
        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if (
            orientation == Qt.Orientation.Horizontal
            and 0 <= section < len(self._HEADERS)
        ):
            return self.tr(self._HEADERS[section])
        if orientation == Qt.Orientation.Vertical:
            return section + 1
        return None

    def set_records(self, records: tuple[DatRecord, ...]) -> None:
        self.beginResetModel()
        self._records = records
        self.endResetModel()


class _PaletteGrid(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette: PaletteOption | None = None
        self.setMinimumSize(240, 240)
        self.setMouseTracking(True)

    def set_palette(self, palette: PaletteOption | None) -> None:
        self._palette = palette
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        palette = self._palette
        if palette is None:
            return
        cell_width = self.width() / 16
        cell_height = self.height() / 16
        for index, (red, green, blue) in enumerate(palette.colors[:256]):
            row, column = divmod(index, 16)
            rect_x = round(column * cell_width)
            rect_y = round(row * cell_height)
            next_x = round((column + 1) * cell_width)
            next_y = round((row + 1) * cell_height)
            painter.fillRect(
                rect_x,
                rect_y,
                max(1, next_x - rect_x),
                max(1, next_y - rect_y),
                QColor(red, green, blue),
            )
            painter.setPen(QColor(0, 0, 0, 72))
            painter.drawRect(rect_x, rect_y, max(1, next_x - rect_x - 1), max(1, next_y - rect_y - 1))

    def mouseMoveEvent(self, event) -> None:
        palette = self._palette
        if palette is None or self.width() <= 0 or self.height() <= 0:
            self.setToolTip("")
            return
        column = min(15, max(0, int(event.position().x() * 16 / self.width())))
        row = min(15, max(0, int(event.position().y() * 16 / self.height())))
        index = row * 16 + column
        if index < palette.color_count:
            red, green, blue = palette.colors[index]
            self.setToolTip(self.tr('{0}: RGB({1}, {2}, {3})').format(index, red, green, blue))
        else:
            self.setToolTip(self.tr('{0}: Unused').format(index))


class _ZoomableImageView(QGraphicsView):
    zoom_requested = Signal(float)
    _MIN_VISIBLE_PAN_PIXELS = 32.0

    def __init__(
        self,
        scene: QGraphicsScene,
        image_item: QGraphicsPixmapItem,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(scene, parent)
        self._image_item = image_item
        self._pan_start_position = None
        self._pan_start_item_position = None
        self._pan_start_image_rect = None
        self._pan_start_horizontal = 0
        self._pan_start_vertical = 0
        self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y() or event.pixelDelta().y()
        if delta == 0:
            super().wheelEvent(event)
            return
        self.zoom_requested.emit(delta / 120)
        event.accept()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._pan_start_position = event.position()
            self._pan_start_item_position = self._image_item.pos()
            self._pan_start_image_rect = self._image_rect_in_viewport()
            self._pan_start_horizontal = self.horizontalScrollBar().value()
            self._pan_start_vertical = self.verticalScrollBar().value()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if (
            self._pan_start_position is None
            or self._pan_start_item_position is None
            or self._pan_start_image_rect is None
        ):
            super().mouseMoveEvent(event)
            return

        delta = event.position() - self._pan_start_position
        scale_x = max(abs(self.transform().m11()), 0.001)
        scale_y = max(abs(self.transform().m22()), 0.001)
        horizontal = self.horizontalScrollBar()
        vertical = self.verticalScrollBar()
        viewport = self.viewport().size()
        image_rect = self._pan_start_image_rect
        horizontal_delta = self._clamped_pan_delta(
            delta.x(), image_rect.left(), image_rect.width(), viewport.width()
        )
        vertical_delta = self._clamped_pan_delta(
            delta.y(), image_rect.top(), image_rect.height(), viewport.height()
        )
        # Apply any drag beyond the scrollbar range as an image offset.
        if horizontal.maximum() > 0:
            horizontal.setValue(
                self._clamped_scroll_value(
                    horizontal,
                    self._pan_start_horizontal,
                    horizontal_delta,
                )
            )
            scroll_delta = self._pan_start_horizontal - horizontal.value()
            self._image_item.setX(
                self._pan_start_item_position.x()
                + (horizontal_delta - scroll_delta) / scale_x
            )
        else:
            self._image_item.setX(
                self._pan_start_item_position.x() + horizontal_delta / scale_x
            )
        if vertical.maximum() > 0:
            vertical.setValue(
                self._clamped_scroll_value(
                    vertical,
                    self._pan_start_vertical,
                    vertical_delta,
                )
            )
            scroll_delta = self._pan_start_vertical - vertical.value()
            self._image_item.setY(
                self._pan_start_item_position.y()
                + (vertical_delta - scroll_delta) / scale_y
            )
        else:
            self._image_item.setY(
                self._pan_start_item_position.y() + vertical_delta / scale_y
            )
        event.accept()

    @classmethod
    def _clamped_pan_delta(
        cls,
        pointer_delta: float,
        image_start: float,
        image_extent: float,
        viewport_extent: int,
    ) -> float:
        visible_pixels = min(cls._MIN_VISIBLE_PAN_PIXELS, image_extent)
        minimum_delta = visible_pixels - (image_start + image_extent)
        maximum_delta = viewport_extent - visible_pixels - image_start
        return min(maximum_delta, max(minimum_delta, pointer_delta))

    @staticmethod
    def _clamped_scroll_value(
        scrollbar: QScrollBar,
        start_value: int,
        image_delta: float,
    ) -> int:
        target_value = start_value - round(image_delta)
        return min(scrollbar.maximum(), max(scrollbar.minimum(), target_value))

    def _image_rect_in_viewport(self) -> QRect:
        image_rect = self._image_item.mapRectToScene(
            self._image_item.boundingRect()
        )
        return self.mapFromScene(image_rect).boundingRect()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._pan_start_position is not None:
            self._pan_start_position = None
            self._pan_start_item_position = None
            self._pan_start_image_rect = None
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class _VoxelModelView(QOpenGLWidget):
    zoom_changed = Signal(float)
    _VERTEX_STRIDE = 7 * 4
    _CAMERA_DISTANCE = 3.2
    _VERTICAL_FOV = 38.0
    _DEFAULT_YAW = -45.0
    _VERTEX_SHADER = """#version 120
attribute vec3 aPosition;
attribute vec3 aNormal;
attribute float aColorIndex;
uniform mat4 uMvp;
uniform mat3 uNormalMatrix;
varying vec3 vNormal;
varying float vColorIndex;
void main() {
    gl_Position = uMvp * vec4(aPosition, 1.0);
    vNormal = normalize(uNormalMatrix * aNormal);
    vColorIndex = aColorIndex;
}
"""
    _FRAGMENT_SHADER = """#version 120
uniform sampler2D uPalette;
varying vec3 vNormal;
varying float vColorIndex;
void main() {
    vec2 palettePosition = vec2((vColorIndex + 0.5) / 256.0, 0.5);
    vec3 baseColor = texture2D(uPalette, palettePosition).rgb;
    vec3 lightDirection = normalize(vec3(-0.35, -0.45, 0.82));
    float light = 0.32 + 0.68 * max(dot(normalize(vNormal), lightDirection), 0.0);
    gl_FragColor = vec4(baseColor * light, 1.0);
}
"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # This format request is limited to the VXL preview widget instance.
        surface_format = self.format()
        surface_format.setVersion(2, 0)
        surface_format.setDepthBufferSize(24)
        self.setFormat(surface_format)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._model: VoxelModel | None = None
        self._palette: PaletteOption | None = None
        self._zoom = 0.2
        self._yaw = 0.0
        self._pitch = 0.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self._drag_mode: str | None = None
        self._last_pointer = None
        self._gl: QOpenGLFunctions | None = None
        self._program: QOpenGLShaderProgram | None = None
        self._vertex_buffer = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        self._palette_texture: QOpenGLTexture | None = None
        self._palette_dirty = True
        self._vertex_count = 0
        self._render_error: str | None = None

    def set_model(self, model: VoxelModel, palette: PaletteOption) -> None:
        self._model = model
        self._palette = palette
        self._palette_dirty = True
        self._reset_orientation()
        self._zoom = 0.2
        self.zoom_changed.emit(self._zoom)
        if self._gl is not None:
            self.makeCurrent()
            try:
                self._upload_model()
            finally:
                self.doneCurrent()
        self.update()

    def clear_model(self) -> None:
        self._model = None
        self._palette = None
        self._vertex_count = 0
        self._palette_dirty = True
        if self._gl is not None and self.isValid():
            self.makeCurrent()
            try:
                if self._vertex_buffer.isCreated():
                    self._vertex_buffer.destroy()
                if self._palette_texture is not None:
                    self._palette_texture.destroy()
                    self._palette_texture = None
            finally:
                self.doneCurrent()
        self.update()

    def set_palette(self, palette: PaletteOption) -> None:
        self._palette = palette
        self._palette_dirty = True
        self.update()

    def set_zoom(self, zoom: float) -> None:
        zoom = min(8.0, max(0.001, zoom))
        if zoom == self._zoom:
            return
        self._zoom = zoom
        self.zoom_changed.emit(zoom)
        self.update()

    def fit_default_zoom(self, maximum_zoom: float) -> float:
        width = max(1, self.width())
        height = max(1, self.height())
        aspect = width / height
        vertical_half_angle = math.radians(self._VERTICAL_FOV / 2)
        horizontal_half_angle = math.atan(
            math.tan(vertical_half_angle) * aspect
        )
        limiting_half_angle = min(vertical_half_angle, horizontal_half_angle)
        camera_distance = math.hypot(
            self._CAMERA_DISTANCE,
            self._CAMERA_DISTANCE * 0.62,
        )
        bounding_sphere_radius = math.sqrt(3)
        fit_zoom = (
            camera_distance
            * math.sin(limiting_half_angle)
            / bounding_sphere_radius
            * 0.9
        )
        return max(0.001, min(maximum_zoom, fit_zoom))

    def reset_view(self) -> None:
        self._reset_orientation()
        self.set_zoom(0.2)
        self.update()

    def _reset_orientation(self) -> None:
        self._yaw = self._DEFAULT_YAW
        self._pitch = 0.0
        self._pan_x = 0.0
        self._pan_y = 0.0

    def initializeGL(self) -> None:
        self._gl = self.context().functions()
        self._gl.initializeOpenGLFunctions()
        self._gl.glEnable(_GL_DEPTH_TEST)
        self._gl.glDepthFunc(_GL_LEQUAL)

        program = QOpenGLShaderProgram(self)
        if not program.addShaderFromSourceCode(
            QOpenGLShader.ShaderTypeBit.Vertex,
            self._VERTEX_SHADER,
        ):
            self._render_error = program.log()
            return
        if not program.addShaderFromSourceCode(
            QOpenGLShader.ShaderTypeBit.Fragment,
            self._FRAGMENT_SHADER,
        ):
            self._render_error = program.log()
            return
        if not program.link():
            self._render_error = program.log()
            return
        self._program = program
        self._vertex_buffer.setUsagePattern(QOpenGLBuffer.UsagePattern.StaticDraw)
        if not self._vertex_buffer.create():
            self._render_error = self.tr("The VXL vertex buffer could not be created.")
            return
        self._upload_model()

    def _upload_model(self) -> None:
        if self._model is None:
            return
        if not self._vertex_buffer.isCreated() and not self._vertex_buffer.create():
            self._render_error = self.tr("The VXL vertex buffer could not be created.")
            return
        if not self._vertex_buffer.bind():
            self._render_error = self.tr("The VXL vertex buffer could not be bound.")
            return
        self._vertex_buffer.allocate(self._model.vertices, len(self._model.vertices))
        self._vertex_buffer.release()
        self._vertex_count = self._model.vertex_count

    def _upload_palette(self) -> None:
        palette = self._palette
        if palette is None:
            return
        image = QImage(256, 1, QImage.Format.Format_RGBA8888)
        for index in range(256):
            red, green, blue = (
                palette.colors[index]
                if index < len(palette.colors)
                else (0, 0, 0)
            )
            image.setPixelColor(index, 0, QColor(red, green, blue))
        if self._palette_texture is not None:
            self._palette_texture.destroy()
        self._palette_texture = QOpenGLTexture(image)
        self._palette_texture.setMinificationFilter(QOpenGLTexture.Filter.Nearest)
        self._palette_texture.setMagnificationFilter(QOpenGLTexture.Filter.Nearest)
        self._palette_dirty = False

    def paintGL(self) -> None:
        gl = self._gl
        if gl is None:
            return
        background = self.palette().color(QPalette.ColorRole.Base)
        gl.glViewport(
            0,
            0,
            round(self.width() * self.devicePixelRatioF()),
            round(self.height() * self.devicePixelRatioF()),
        )
        gl.glClearColor(background.redF(), background.greenF(), background.blueF(), 1.0)
        gl.glClear(_GL_COLOR_BUFFER_BIT | _GL_DEPTH_BUFFER_BIT)
        if self._render_error:
            painter = QPainter(self)
            painter.setPen(self.palette().color(QPalette.ColorRole.Text))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                self._render_error,
            )
            return
        if self._model is None or self._program is None or self._vertex_count <= 0:
            return
        if self._palette_dirty:
            self._upload_palette()
        if self._palette_texture is None:
            return

        aspect = max(1.0, self.width()) / max(1.0, self.height())
        projection = QMatrix4x4()
        projection.perspective(self._VERTICAL_FOV, aspect, 0.1, 100.0)
        view = QMatrix4x4()
        view.lookAt(
            QVector3D(0.0, -self._CAMERA_DISTANCE, self._CAMERA_DISTANCE * 0.62),
            QVector3D(0.0, 0.0, 0.0),
            QVector3D(0.0, 0.0, 1.0),
        )
        view.translate(self._pan_x, self._pan_y, 0.0)
        model = QMatrix4x4()
        model.rotate(self._yaw, 0.0, 0.0, 1.0)
        model.rotate(self._pitch, 1.0, 0.0, 0.0)
        model.scale(self._zoom)

        if not self._program.bind() or not self._vertex_buffer.bind():
            self._render_error = self.tr("The VXL renderer could not bind its resources.")
            self._program.release()
            self.update()
            return
        self._palette_texture.bind(0)
        self._program.setUniformValue("uMvp", projection * view * model)
        self._program.setUniformValue("uNormalMatrix", model.normalMatrix())
        self._program.setUniformValue("uPalette", 0)
        stride = self._VERTEX_STRIDE
        position_location = self._program.attributeLocation("aPosition")
        normal_location = self._program.attributeLocation("aNormal")
        color_location = self._program.attributeLocation("aColorIndex")
        for location, offset, size in (
            (position_location, 0, 3),
            (normal_location, 12, 3),
            (color_location, 24, 1),
        ):
            self._program.enableAttributeArray(location)
            self._program.setAttributeBuffer(location, _GL_FLOAT, offset, size, stride)
        gl.glDrawArrays(_GL_TRIANGLES, 0, self._vertex_count)
        for location in (position_location, normal_location, color_location):
            self._program.disableAttributeArray(location)
        self._palette_texture.release()
        self._vertex_buffer.release()
        self._program.release()

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y() or event.pixelDelta().y()
        if not delta:
            event.ignore()
            return
        self.set_zoom(self._zoom + delta / 120 * 0.1)
        event.accept()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_mode = "rotate"
        elif event.button() in {Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton}:
            self._drag_mode = "pan"
        else:
            super().mousePressEvent(event)
            return
        self._last_pointer = event.position()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_mode is None or self._last_pointer is None:
            super().mouseMoveEvent(event)
            return
        delta = event.position() - self._last_pointer
        self._last_pointer = event.position()
        if self._drag_mode == "rotate":
            self._yaw = (self._yaw + delta.x() * 0.5) % 360.0
            self._pitch = min(89.0, max(-89.0, self._pitch + delta.y() * 0.5))
        else:
            viewport_height = max(1, self.height())
            world_per_pixel = (
                2.0
                * self._CAMERA_DISTANCE
                * 0.3443
                / viewport_height
                / max(self._zoom, 0.1)
            )
            self._pan_x += delta.x() * world_per_pixel
            self._pan_y -= delta.y() * world_per_pixel
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() in {
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.MiddleButton,
            Qt.MouseButton.RightButton,
        }:
            self._drag_mode = None
            self._last_pointer = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)


# @arch mix-browser.entry-preview component | en: Renders selected MIX entry previews | zh: 呈现选中的 MIX 条目预览
class EntryPreviewPane(QWidget):
    auto_play_preference_changed = Signal(str, bool)

    # VXL has no native display size; keep the requested 20% initial zoom.
    _VXL_DEFAULT_DISPLAY_SCALE = 0.2
    _MIN_IMAGE_ZOOM = 0.001

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(280)
        self._result: EntryPreviewResult | None = None
        self._frame_index = 0
        self._palette_index = 0
        self._palette_manually_selected = False
        self._image_zoom = 1.0
        self._auto_play_animations = False
        self._auto_play_audio = False
        self._auto_play_video = False
        self._combine_shp_shadow_frames = False
        self._is_active = False
        self._resume_animation_on_activate = False
        self._resume_media_on_activate = False
        self._default_fit_pending = False
        self._default_fit_scheduled = False
        self._scrubbing = False

        self._stack = QStackedWidget(self)
        self._empty = self._message_page(self.tr("Select an entry to preview."))
        self._loading = self._message_page(self.tr("Loading preview..."))
        self._message = self._message_page("")
        self._document = DocumentPreviewPane(self)
        self._dat_page = QWidget(self)
        dat_layout = QVBoxLayout(self._dat_page)
        dat_layout.setContentsMargins(0, 0, 0, 0)
        self._dat_title = QLabel(self._dat_page)
        dat_layout.addWidget(self._dat_title)
        self._dat_table = QTableView(self._dat_page)
        self._dat_table_model = _DatPreviewTableModel(self._dat_table)
        self._dat_table.setModel(self._dat_table_model)
        self._dat_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._dat_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._dat_table.setAlternatingRowColors(True)
        self._dat_table.setShowGrid(False)
        self._dat_table.verticalHeader().setVisible(False)
        dat_header = self._dat_table.horizontalHeader()
        dat_header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        dat_header.setStretchLastSection(True)
        self._dat_table.setColumnWidth(0, 110)
        self._dat_table.setColumnWidth(1, 180)
        dat_layout.addWidget(self._dat_table, 1)
        self._image_page = QWidget(self)
        image_layout = QVBoxLayout(self._image_page)
        image_layout.setContentsMargins(0, 0, 0, 0)
        self._image_notice = QLabel(self._image_page)
        self._image_notice.setWordWrap(True)
        self._image_controls = QWidget(self._image_page)
        controls_layout = QHBoxLayout(self._image_controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(6)
        controls_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self._frame_label = QLabel(self.tr("Frame"), self._image_controls)
        self._frame_label.setFixedHeight(BROWSER_TOOLBAR_CONTROL_HEIGHT)
        self._frame_combo = QComboBox(self._image_controls)
        self._frame_combo.setFixedHeight(BROWSER_TOOLBAR_CONTROL_HEIGHT)
        self._frame_combo.currentIndexChanged.connect(self._select_frame)
        self._play_button = QPushButton(self.tr("Pause"), self._image_controls)
        self._play_button.setFixedWidth(self._play_button.sizeHint().width())
        self._play_button.setFixedHeight(BROWSER_TOOLBAR_CONTROL_HEIGHT)
        self._play_button.setText(self.tr("Play"))
        self._play_button.clicked.connect(self._toggle_animation)
        self._auto_play_animation_checkbox = self._create_auto_play_checkbox(
            self._image_page,
            "animations",
            QT_TRANSLATE_NOOP(
                "EntryPreviewPane",
                "Automatically play SHP animations when previewed",
            ),
            QT_TRANSLATE_NOOP("EntryPreviewPane", "Auto-play SHP animations"),
        )
        self._auto_play_animation_checkbox.hide()
        self._shadow_combine_button = QToolButton(self._image_page)
        self._shadow_combine_button.setFixedHeight(BROWSER_TOOLBAR_CONTROL_HEIGHT)
        self._shadow_combine_button.setCheckable(True)
        shadow_action_labels = (
            self.tr("Merge shadows"),
            self.tr("Show original frames"),
        )
        shadow_action_width = 0
        for label in shadow_action_labels:
            self._shadow_combine_button.setText(label)
            shadow_action_width = max(
                shadow_action_width,
                self._shadow_combine_button.sizeHint().width(),
            )
        self._shadow_combine_button.setFixedWidth(shadow_action_width)
        self._update_shadow_combine_button()
        self._shadow_combine_button.setVisible(False)
        self._shadow_combine_button.toggled.connect(
            self.set_combine_shp_shadow_frames
        )
        self._palette_label = QLabel(self.tr("Palette"), self._image_controls)
        self._palette_label.setFixedHeight(BROWSER_TOOLBAR_CONTROL_HEIGHT)
        self._palette_combo = QComboBox(self._image_controls)
        self._palette_combo.setFixedHeight(BROWSER_TOOLBAR_CONTROL_HEIGHT)
        self._palette_model = QStandardItemModel(self._palette_combo)
        self._palette_combo.setModel(self._palette_model)
        self._palette_combo.currentIndexChanged.connect(self._select_palette)
        self._palette_help_button = QToolButton(self._image_controls)
        self._palette_help_button.setText(self.tr("?"))
        self._palette_help_button.setFixedSize(
            BROWSER_TOOLBAR_CONTROL_HEIGHT,
            BROWSER_TOOLBAR_CONTROL_HEIGHT,
        )
        self._palette_help_button.setToolTip(self.tr("Explain automatic palette selection"))
        self._palette_help_button.setAccessibleName(self.tr("Palette selection help"))
        self._palette_help_button.clicked.connect(self._show_palette_selection_help)
        controls_layout.addWidget(self._frame_label)
        controls_layout.addWidget(self._frame_combo)
        controls_layout.addWidget(self._play_button)
        controls_layout.addWidget(self._palette_label)
        controls_layout.addWidget(self._palette_combo, 1)
        controls_layout.addWidget(self._palette_help_button)
        image_layout.addWidget(self._image_controls)
        image_layout.addWidget(self._image_notice)
        zoom_layout = QHBoxLayout()
        zoom_layout.setContentsMargins(0, 0, 0, 0)
        zoom_layout.setSpacing(4)
        zoom_layout.addWidget(self._auto_play_animation_checkbox)
        zoom_layout.addWidget(self._shadow_combine_button)
        zoom_layout.addStretch(1)
        self._zoom_out_button = QPushButton(self.tr("-"), self._image_page)
        self._zoom_out_button.setFixedSize(32, 28)
        self._zoom_out_button.setToolTip(self.tr("Zoom out"))
        self._zoom_out_button.clicked.connect(lambda: self._step_image_zoom(-1))
        self._zoom_level_label = QLabel(self.tr("100%"), self._image_page)
        self._zoom_level_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._zoom_level_label.setFixedWidth(56)
        self._zoom_level_label.setToolTip(self.tr("Current image zoom"))
        self._zoom_reset_button = QPushButton(self.tr("Reset"), self._image_page)
        self._zoom_reset_button.setFixedSize(56, 28)
        self._zoom_reset_button.setToolTip(self.tr("Reset image size and position to 100%"))
        self._zoom_reset_button.clicked.connect(self._reset_image_zoom)
        self._zoom_in_button = QPushButton(self.tr("+"), self._image_page)
        self._zoom_in_button.setFixedSize(32, 28)
        self._zoom_in_button.setToolTip(self.tr("Zoom in"))
        self._zoom_in_button.clicked.connect(lambda: self._step_image_zoom(1))
        zoom_layout.addWidget(self._zoom_out_button)
        zoom_layout.addWidget(self._zoom_level_label)
        zoom_layout.addWidget(self._zoom_in_button)
        zoom_layout.addWidget(self._zoom_reset_button)
        image_layout.addLayout(zoom_layout)

        self._image_scene = QGraphicsScene(self._image_page)
        self._image_item = QGraphicsPixmapItem()
        self._image_scene.addItem(self._image_item)
        self._image_view = _ZoomableImageView(
            self._image_scene,
            self._image_item,
            self._image_page,
        )
        self._image_view.setFrameShape(QFrame.Shape.NoFrame)
        self._image_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_view.setDragMode(QGraphicsView.DragMode.NoDrag)
        self._image_view.setInteractive(False)
        self._image_view.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorViewCenter
        )
        self._image_view.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self._image_view.zoom_requested.connect(self._zoom_image_at_cursor)
        image_layout.addWidget(self._image_view, 1)
        self._voxel_view = _VoxelModelView(self._image_page)
        self._voxel_view.zoom_changed.connect(self._sync_voxel_zoom)
        self._voxel_view.hide()
        image_layout.addWidget(self._voxel_view, 1)

        self._palette_page = QWidget(self)
        palette_layout = QVBoxLayout(self._palette_page)
        palette_layout.setContentsMargins(0, 0, 0, 0)
        self._palette_title = QLabel(self._palette_page)
        palette_layout.addWidget(self._palette_title)
        self._palette_grid = _PaletteGrid(self._palette_page)
        palette_layout.addWidget(self._palette_grid, 1)

        self._media_page = QWidget(self)
        media_layout = QVBoxLayout(self._media_page)
        media_layout.setContentsMargins(0, 0, 0, 0)
        self._media_player = VlcMediaPlayer(self._media_page)
        self._media_player.playback_state_changed.connect(self._sync_vlc_media_controls)
        self._media_player.position_changed.connect(self._sync_media_position)
        self._media_player.duration_changed.connect(self._sync_media_duration)
        self._media_player.error_occurred.connect(self._on_vlc_media_error)
        self._media_placeholder = QLabel("", self._media_page)
        self._media_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._media_placeholder.setWordWrap(True)
        media_layout.addWidget(self._media_player, 1)
        media_layout.addWidget(self._media_placeholder, 1)
        transport = QHBoxLayout()
        self._auto_play_audio_checkbox = self._create_auto_play_checkbox(
            self._media_page,
            "audio",
            QT_TRANSLATE_NOOP(
                "EntryPreviewPane",
                "Automatically play audio when previewed",
            ),
            QT_TRANSLATE_NOOP("EntryPreviewPane", "Auto-play audio"),
        )
        self._auto_play_audio_checkbox.hide()
        self._auto_play_video_checkbox = self._create_auto_play_checkbox(
            self._media_page,
            "video",
            QT_TRANSLATE_NOOP(
                "EntryPreviewPane",
                "Automatically play video when previewed",
            ),
            QT_TRANSLATE_NOOP("EntryPreviewPane", "Auto-play video"),
        )
        self._auto_play_video_checkbox.hide()
        self._media_play = QPushButton(self.tr("Pause"), self._media_page)
        self._media_play.setFixedWidth(self._media_play.sizeHint().width())
        self._media_play.setText(self.tr("Play"))
        self._media_play.clicked.connect(self._toggle_media)
        self._position = QSlider(Qt.Orientation.Horizontal, self._media_page)
        self._position.setRange(0, 0)
        self._position.sliderPressed.connect(self._begin_scrubbing)
        self._position.sliderReleased.connect(self._end_scrubbing)
        self._position.sliderMoved.connect(self._seek_media)
        self._time = QLabel(self.tr("00:00 / 00:00"), self._media_page)
        self._time.setMinimumWidth(105)
        transport.addWidget(self._auto_play_audio_checkbox)
        transport.addWidget(self._auto_play_video_checkbox)
        transport.addWidget(self._media_play)
        transport.addWidget(self._position, 1)
        transport.addWidget(self._time)
        media_layout.addLayout(transport)

        for page in (
            self._empty,
            self._loading,
            self._message,
            self._document,
            self._dat_page,
            self._image_page,
            self._palette_page,
            self._media_page,
        ):
            self._stack.addWidget(page)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)

        self._animation_timer = QTimer(self)
        self._animation_timer.setInterval(100)
        self._animation_timer.timeout.connect(self._advance_frame)

    def prepare_media_runtime(self) -> bool:
        return self._media_player.prepare_runtime()

    @staticmethod
    def _message_page(text: str) -> QLabel:
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        return label

    def _create_auto_play_checkbox(
        self,
        parent: QWidget,
        preference: str,
        tool_tip: str,
        accessible_name: str,
    ) -> QCheckBox:
        button = QCheckBox(parent)
        button.setText(self.tr("Auto-play"))
        button.setCheckable(True)
        button.setFixedHeight(BROWSER_TOOLBAR_CONTROL_HEIGHT)
        button.setFixedWidth(button.sizeHint().width())
        button.setToolTip(self.tr(tool_tip))
        button.setAccessibleName(self.tr(accessible_name))
        button.toggled.connect(
            lambda enabled, key=preference: self._toggle_auto_play_preference(
                key,
                enabled,
            )
        )
        return button

    def show_empty(self) -> None:
        self._reset_media()
        self._result = None
        self._voxel_view.clear_model()
        self._document.show_empty()
        self._dat_model_clear()
        self._stack.setCurrentWidget(self._empty)

    def show_loading(self) -> None:
        self._reset_media()
        self._result = None
        self._voxel_view.clear_model()
        self._document.show_loading()
        self._dat_model_clear()
        self._stack.setCurrentWidget(self._loading)

    def show_result(
        self,
        result: EntryPreviewResult,
        encoding: str,
    ) -> DecodedDocument | None:
        self._reset_media()
        self._combine_shp_shadow_frames = False
        self._shadow_combine_button.hide()
        self._result = result
        if result.voxel_model is None:
            self._voxel_view.clear_model()
        if result.kind == "dat":
            self._dat_title.setText(
                self.tr('{0} | {1:,} records').format(result.dat_format, len(result.dat_records))
            )
            self._dat_table_model.set_records(result.dat_records)
            self._stack.setCurrentWidget(self._dat_page)
            return None
        self._dat_model_clear()
        if result.kind == "document" and result.document is not None:
            decoded = self._document.show_result(result.document, encoding)
            self._stack.setCurrentWidget(self._document)
            return decoded
        if result.kind == "message":
            self._message.setText(
                self.tr(result.message)
                if result.message
                else self.tr("Preview is not available for this entry.")
            )
            self._stack.setCurrentWidget(self._message)
            return None
        if result.kind in {"image", "model"}:
            self._prepare_image(result)
            self._stack.setCurrentWidget(self._image_page)
            self._reset_image_zoom()
            if self._auto_play_animations and self._display_frame_count(result) > 1:
                if self._is_active:
                    self._animation_timer.start()
                    self._play_button.setText(self.tr("Pause"))
                else:
                    self._resume_animation_on_activate = True
            return None
        if result.kind == "palette" and result.palette is not None:
            self._palette_title.setText(
                self.tr('{0} | {1} colors').format(result.palette.name, result.palette.color_count)
            )
            self._palette_grid.set_palette(result.palette)
            self._stack.setCurrentWidget(self._palette_page)
            return None
        if result.kind == "media":
            self._prepare_media(result)
            self._stack.setCurrentWidget(self._media_page)
            auto_play_media = (
                self._auto_play_video if result.is_video else self._auto_play_audio
            )
            if auto_play_media and self._media_play.isEnabled():
                if self._is_active:
                    self._play_media()
                else:
                    self._resume_media_on_activate = True
            return None
        self._message.setText(self.tr("Preview is not available for this entry."))
        self._stack.setCurrentWidget(self._message)
        return None

    def _dat_model_clear(self) -> None:
        self._dat_title.clear()
        self._dat_table_model.set_records(())

    def set_auto_play_preferences(
        self,
        *,
        animations: bool,
        audio: bool,
        video: bool,
    ) -> None:
        self._auto_play_animations = animations
        self._auto_play_audio = audio
        self._auto_play_video = video
        for button, enabled in (
            (self._auto_play_animation_checkbox, animations),
            (self._auto_play_audio_checkbox, audio),
            (self._auto_play_video_checkbox, video),
        ):
            blocker = QSignalBlocker(button)
            button.setChecked(enabled)
            del blocker

    def set_combine_shp_shadow_frames(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self._combine_shp_shadow_frames:
            return
        result = self._result
        if (
            result is None
            or not result.is_shp
            or len(result.frames) < 2
            or len(result.frames) % 2
        ):
            return
        self._combine_shp_shadow_frames = enabled
        self._update_shadow_combine_button()
        frame_count = self._display_frame_count(result)
        self._frame_index = min(
            max(self._frame_index, 0),
            max(frame_count - 1, 0),
        )
        self._populate_frame_choices(result)
        if frame_count < 2:
            self._animation_timer.stop()
            self._resume_animation_on_activate = False
        elif self._animation_timer.isActive():
            self._animation_timer.start()
        self._play_button.setText(
            self.tr("Pause") if self._animation_timer.isActive() else self.tr("Play")
        )
        self._refresh_image()

    def _update_shadow_combine_button(self) -> None:
        if self._combine_shp_shadow_frames:
            self._shadow_combine_button.setText(
                self.tr("Show original frames")
            )
            self._shadow_combine_button.setToolTip(
                self.tr(
                    "Turn off shadow merging and show the original SHP frames."
                )
            )
            self._shadow_combine_button.setAccessibleName(
                self.tr("Show original SHP frames")
            )
        else:
            self._shadow_combine_button.setText(self.tr("Merge shadows"))
            self._shadow_combine_button.setToolTip(
                self.tr(
                    "Overlay the second half of SHP frames beneath the first half."
                )
            )
            self._shadow_combine_button.setAccessibleName(
                self.tr("Merge SHP shadow frames")
            )

    def set_active(self, active: bool) -> None:
        if active == self._is_active:
            return
        self._is_active = active
        if not active:
            self._resume_animation_on_activate = self._animation_timer.isActive()
            if self._resume_animation_on_activate:
                self._animation_timer.stop()
                self._play_button.setText(self.tr("Play"))
            self._resume_media_on_activate = self._media_is_playing()
            if self._resume_media_on_activate:
                self._pause_media()
            return

        result = self._result
        if (
            self._resume_animation_on_activate
            and result is not None
            and self._display_frame_count(result) > 1
        ):
            self._animation_timer.start()
            self._play_button.setText(self.tr("Pause"))
        self._resume_animation_on_activate = False
        if self._resume_media_on_activate and self._media_play.isEnabled():
            self._play_media()
        self._resume_media_on_activate = False

    def show_document(self, result, encoding: str) -> DecodedDocument:
        return self._document.show_result(result, encoding)

    def _prepare_image(self, result: EntryPreviewResult) -> None:
        self._frame_index = 0
        self._palette_manually_selected = False
        is_voxel_model = result.voxel_model is not None
        self._image_view.setVisible(not is_voxel_model)
        self._voxel_view.setVisible(is_voxel_model)
        self._image_notice.setText(self.tr(result.message) if result.message else "")
        self._image_notice.setVisible(bool(result.message))
        can_pair_shadow_frames = (
            result.is_shp
            and len(result.frames) >= 2
            and len(result.frames) % 2 == 0
        )
        self._shadow_combine_button.setVisible(result.is_shp)
        self._shadow_combine_button.setEnabled(can_pair_shadow_frames)
        blocker = QSignalBlocker(self._shadow_combine_button)
        self._shadow_combine_button.setChecked(
            can_pair_shadow_frames and self._combine_shp_shadow_frames
        )
        del blocker
        self._update_shadow_combine_button()
        if not can_pair_shadow_frames:
            self._shadow_combine_button.setToolTip(
                self.tr("SHP shadow merging requires an even number of frames.")
            )
        self._populate_frame_choices(result)
        self._play_button.setText(self.tr("Play"))
        self._populate_palette_choices(result, result.default_palette_index)
        if result.voxel_model is not None and result.palettes:
            self._voxel_view.set_model(
                result.voxel_model,
                result.palettes[self._palette_index],
            )
            self._zoom_reset_button.setToolTip(self.tr("Reset VXL view and zoom to 20%"))
            self._zoom_level_label.setToolTip(self.tr("Current VXL zoom"))
        else:
            self._zoom_reset_button.setToolTip(self.tr("Reset image size and position to 100%"))
            self._zoom_level_label.setToolTip(self.tr("Current image zoom"))
        self._refresh_image()

    def _display_frame_count(self, result: EntryPreviewResult) -> int:
        if (
            self._combine_shp_shadow_frames
            and result.is_shp
            and len(result.frames) % 2 == 0
        ):
            return len(result.frames) // 2
        return len(result.frames)

    def _populate_frame_choices(self, result: EntryPreviewResult) -> None:
        frame_count = self._display_frame_count(result)
        blocker = QSignalBlocker(self._frame_combo)
        self._frame_combo.clear()
        for index in range(frame_count):
            self._frame_combo.addItem(str(index + 1), index)
        if frame_count:
            self._frame_combo.setCurrentIndex(
                min(max(self._frame_index, 0), frame_count - 1)
            )
        del blocker
        has_multiple_frames = frame_count > 1
        self._frame_label.setVisible(has_multiple_frames)
        self._frame_combo.setVisible(has_multiple_frames)
        self._play_button.setVisible(has_multiple_frames)
        self._auto_play_animation_checkbox.setVisible(
            result.is_shp and has_multiple_frames
        )
        blocker = QSignalBlocker(self._auto_play_animation_checkbox)
        self._auto_play_animation_checkbox.setChecked(self._auto_play_animations)
        del blocker

    def _populate_palette_choices(
        self,
        result: EntryPreviewResult,
        selected_palette_index: int,
    ) -> None:
        self._palette_index = self._normalized_palette_index(
            result,
            selected_palette_index,
        )
        has_frames = bool(result.frames)
        signal_blocker = QSignalBlocker(self._palette_combo)
        self._palette_model.clear()
        self._palette_combo.clear()
        previous_group: str | None = None
        group_labels = {key: self.tr(label) for key, label in PALETTE_GROUPS}
        group_labels["other"] = group_labels["game"]
        for index, palette in enumerate(result.palettes):
            group = palette.group if palette.group in group_labels else "game"
            if group != previous_group:
                group_item = QStandardItem(self.tr("- {0} -").format(group_labels[group]))
                group_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self._palette_model.appendRow(group_item)
            source = palette.source
            if source.startswith("User library: "):
                source = self.tr("User library: {0}").format(source[len("User library: "):])
            elif source.startswith("Game: "):
                source = self.tr("Game: {0}").format(source[len("Game: "):])
            elif source:
                source = self.tr(source)
            palette_name = self.tr("Grayscale") if palette.group == "fallback" else palette.name
            label = f"{palette_name} ({source})" if source else palette_name
            self._palette_combo.addItem(label, index)
            previous_group = group
        selected_combo_index = self._palette_combo.findData(self._palette_index)
        if selected_combo_index >= 0:
            self._palette_combo.setCurrentIndex(selected_combo_index)
        del signal_blocker
        has_palette_choice = len(result.palettes) > 0
        self._palette_label.setVisible(has_palette_choice)
        self._palette_combo.setVisible(has_palette_choice)
        self._palette_help_button.setVisible(has_palette_choice)
        self._palette_combo.setEnabled(len(result.palettes) > 1)
        self._image_controls.setVisible(has_frames or has_palette_choice)

    @staticmethod
    def _normalized_palette_index(
        result: EntryPreviewResult,
        palette_index: int,
    ) -> int:
        if 0 <= palette_index < len(result.palettes):
            return palette_index
        if 0 <= result.default_palette_index < len(result.palettes):
            return result.default_palette_index
        return 0

    def update_palette_sources(self, result: EntryPreviewResult) -> None:
        current = self._result
        if (
            current is None
            or current.kind not in {"image", "model"}
            or result.kind != current.kind
        ):
            return
        selected_palette = None
        if (
            self._palette_manually_selected
            and 0 <= self._palette_index < len(current.palettes)
        ):
            selected_palette = current.palettes[self._palette_index]
        self._result = result
        selected_index = result.default_palette_index
        if selected_palette is not None:
            selected_index = next(
                (
                    index
                    for index, palette in enumerate(result.palettes)
                    if palette == selected_palette
                ),
                result.default_palette_index,
            )
        self._image_notice.setText(self.tr(result.message) if result.message else "")
        self._image_notice.setVisible(bool(result.message))
        self._populate_palette_choices(result, selected_index)
        if result.voxel_model is not None and result.palettes:
            self._voxel_view.set_palette(result.palettes[self._palette_index])
        else:
            self._refresh_image()

    def show_palette_lookup_failure(self) -> None:
        if self._image_notice.text() == self.tr("Checking configured game palettes..."):
            self._image_notice.setText(
                self.tr("Game palettes could not be loaded; the current palette is shown.")
            )

    def _show_palette_selection_help(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(self.tr("Palette Selection"))
        dialog.resize(760, 620)
        dialog.setMinimumSize(560, 360)
        stage_items = "".join(
            "<li><b>"
            + escape(self.tr(stage.title))
            + "</b><ul>"
            + "".join(f"<li>{escape(self.tr(detail))}</li>" for detail in stage.details)
            + "</ul></li>"
            for stage in PALETTE_SELECTION_STAGES
        )
        group_titles = ", ".join(
            f"<code>- {escape(self.tr(title))} -</code>" for _, title in PALETTE_GROUPS
        )
        help_browser = QTextBrowser(dialog)
        help_browser.setOpenExternalLinks(False)
        help_browser.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        help_browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        help_browser.setHtml(
            f"<p><b>{escape(self.tr('Automatic selection priority'))}</b></p>"
            f"<ol>{stage_items}</ol>"
            f"<p><b>{escape(self.tr('Candidate list groups, in display order:'))}</b> {group_titles}. "
            f"{escape(self.tr('The first group contains the always-available grayscale palette.'))} "
            f"{escape(self.tr('The candidate list order is separate from automatic selection priority.'))}</p>"
        )
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, dialog)
        buttons.rejected.connect(dialog.reject)
        naming_guide = buttons.addButton(
            self.tr("Asset Filename Guide..."),
            QDialogButtonBox.ButtonRole.ActionRole,
        )
        naming_guide.clicked.connect(
            lambda: PaletteNamingGuideDialog(dialog).exec()
        )
        layout = QVBoxLayout(dialog)
        layout.addWidget(help_browser, 1)
        layout.addWidget(buttons)
        dialog.exec()

    def _refresh_image(self) -> None:
        result = self._result
        if result is None:
            return
        if result.voxel_model is not None:
            self._image_view.hide()
            self._voxel_view.show()
            return
        self._voxel_view.hide()
        self._image_view.show()
        if result.image is not None:
            image = result.image
        elif result.frames and result.palettes:
            frame_count = self._display_frame_count(result)
            self._frame_index = min(
                max(self._frame_index, 0),
                frame_count - 1,
            )
            self._palette_index = self._normalized_palette_index(
                result,
                self._palette_index,
            )
            palette = result.palettes[self._palette_index]
            if (
                self._combine_shp_shadow_frames
                and result.is_shp
                and len(result.frames) % 2 == 0
            ):
                frame = result.frames[self._frame_index]
                shadow = result.frames[len(result.frames) // 2 + self._frame_index]
                image = indexed_frame_image(
                    shadow,
                    palette,
                    transparent_zero=True,
                    shadow_mask=True,
                ).convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
                frame_image = indexed_frame_image(
                    frame,
                    palette,
                    transparent_zero=True,
                )
                painter = QPainter(image)
                painter.drawImage(0, 0, frame_image)
                painter.end()
            else:
                image = indexed_frame_image(
                    result.frames[self._frame_index],
                    palette,
                    transparent_zero=True,
                )
        else:
            image = QImage()
        pixmap = QPixmap.fromImage(image) if not image.isNull() else QPixmap()
        self._image_item.setPixmap(pixmap)
        self._image_scene.setSceneRect(self._image_item.boundingRect())

    def _step_image_zoom(self, steps: float) -> None:
        zoom = min(
            8.0,
            max(self._MIN_IMAGE_ZOOM, self._image_zoom + steps * 0.1),
        )
        if zoom == self._image_zoom:
            return
        self._apply_image_zoom(zoom)

    def _apply_image_zoom(self, zoom: float) -> None:
        self._default_fit_pending = False
        if self._result is not None and self._result.voxel_model is not None:
            self._voxel_view.set_zoom(zoom)
            self._image_zoom = zoom
            self._sync_image_zoom_controls()
            return
        scale_factor = zoom / self._image_zoom
        self._image_view.scale(scale_factor, scale_factor)
        self._image_zoom = zoom
        self._sync_image_zoom_controls()

    def _zoom_image_at_cursor(self, steps: float) -> None:
        self._image_view.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse
        )
        try:
            self._step_image_zoom(steps)
        finally:
            self._image_view.setTransformationAnchor(
                QGraphicsView.ViewportAnchor.AnchorViewCenter
            )

    def _reset_image_zoom(self) -> None:
        self._default_fit_pending = False
        self._image_item.setPos(0, 0)
        self._image_scene.setSceneRect(self._image_item.boundingRect())
        self._image_view.resetTransform()
        if self._result is not None and self._result.voxel_model is not None:
            self._voxel_view.reset_view()
            self._image_zoom = self._VXL_DEFAULT_DISPLAY_SCALE
            self._zoom_reset_button.setToolTip(
                self.tr("Reset VXL view to its default size, fitting the preview area")
            )
        else:
            self._image_zoom = 1.0
            self._image_view.centerOn(self._image_item)
            self._zoom_reset_button.setToolTip(
                self.tr("Reset image to its default size, fitting the preview area up to 100%")
            )
        self._default_fit_pending = True
        self._apply_default_fit()
        self._sync_image_zoom_controls()

    def _apply_default_fit(self) -> None:
        if (
            not self._default_fit_pending
            or self._result is None
            or self._result.kind not in {"image", "model"}
        ):
            return
        if self._result.voxel_model is not None:
            if self._voxel_view.width() <= 1 or self._voxel_view.height() <= 1:
                self._queue_default_fit()
                return
            self._image_zoom = self._voxel_view.fit_default_zoom(
                self._VXL_DEFAULT_DISPLAY_SCALE
            )
            self._voxel_view.set_zoom(self._image_zoom)
        else:
            bounds = self._image_item.boundingRect()
            viewport = self._image_view.viewport().size()
            if bounds.width() <= 0 or bounds.height() <= 0:
                self._default_fit_pending = False
                return
            if viewport.width() <= 1 or viewport.height() <= 1:
                self._queue_default_fit()
                return
            self._image_zoom = max(
                self._MIN_IMAGE_ZOOM,
                min(
                    1.0,
                    viewport.width() / bounds.width(),
                    viewport.height() / bounds.height(),
                ),
            )
            if self._image_zoom < 1.0:
                self._image_zoom = max(
                    self._MIN_IMAGE_ZOOM,
                    self._image_zoom * 0.98,
                )
            self._image_view.scale(self._image_zoom, self._image_zoom)
            self._image_view.centerOn(self._image_item)
        self._default_fit_pending = False
        self._sync_image_zoom_controls()

    def _queue_default_fit(self) -> None:
        if self._default_fit_scheduled:
            return
        self._default_fit_scheduled = True
        QTimer.singleShot(0, self._complete_default_fit)

    def _complete_default_fit(self) -> None:
        self._default_fit_scheduled = False
        self._apply_default_fit()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if getattr(self, "_default_fit_pending", False):
            self._queue_default_fit()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if getattr(self, "_default_fit_pending", False):
            self._queue_default_fit()

    def _sync_image_zoom_controls(self) -> None:
        zoom_text = (
            f"{self._image_zoom:.1%}"
            if self._image_zoom < 0.01
            else f"{self._image_zoom:.0%}"
        )
        self._zoom_level_label.setText(zoom_text)
        self._zoom_out_button.setEnabled(self._image_zoom > self._MIN_IMAGE_ZOOM)
        self._zoom_in_button.setEnabled(self._image_zoom < 8.0)

    def _sync_voxel_zoom(self, zoom: float) -> None:
        self._image_zoom = zoom
        self._default_fit_pending = False
        self._sync_image_zoom_controls()

    def _select_frame(self, index: int) -> None:
        result = self._result
        if result is None or not 0 <= index < self._display_frame_count(result):
            return
        self._frame_index = index
        self._refresh_image()

    def _select_palette(self, index: int) -> None:
        result = self._result
        palette_index = self._palette_combo.itemData(index)
        if (
            result is None
            or not isinstance(palette_index, int)
            or not 0 <= palette_index < len(result.palettes)
        ):
            return
        self._palette_manually_selected = True
        self._palette_index = palette_index
        palette = result.palettes[palette_index]
        if (
            palette.name != "Grayscale"
            and self._image_notice.text().startswith(
                "No matching palette could be identified;"
            )
        ):
            self._image_notice.clear()
            self._image_notice.hide()
        if result.voxel_model is not None:
            self._voxel_view.set_palette(palette)
            return
        self._refresh_image()

    def _toggle_animation(self) -> None:
        if not self._is_active:
            return
        if self._animation_timer.isActive():
            self._animation_timer.stop()
            self._play_button.setText(self.tr("Play"))
        else:
            self._animation_timer.start()
            self._play_button.setText(self.tr("Pause"))

    def _toggle_auto_play_preference(
        self,
        preference: str,
        enabled: bool,
    ) -> None:
        result = self._result
        if preference == "animations":
            self._auto_play_animations = enabled
            if result is not None and result.is_shp and self._display_frame_count(result) > 1:
                if enabled:
                    if self._is_active:
                        self._animation_timer.start()
                        self._play_button.setText(self.tr("Pause"))
                    else:
                        self._resume_animation_on_activate = True
                else:
                    self._animation_timer.stop()
                    self._resume_animation_on_activate = False
                    self._play_button.setText(self.tr("Play"))
        else:
            is_video = preference == "video"
            if is_video:
                self._auto_play_video = enabled
            else:
                self._auto_play_audio = enabled
            if (
                result is not None
                and result.kind == "media"
                and result.is_video == is_video
                and self._media_play.isEnabled()
            ):
                if enabled:
                    if self._is_active:
                        self._play_media()
                    else:
                        self._resume_media_on_activate = True
                else:
                    self._pause_media()
                    self._resume_media_on_activate = False
        self.auto_play_preference_changed.emit(preference, enabled)

    def _advance_frame(self) -> None:
        result = self._result
        if result is None or self._display_frame_count(result) < 2:
            self._animation_timer.stop()
            return
        self._frame_index = (self._frame_index + 1) % self._display_frame_count(result)
        blocked = self._frame_combo.blockSignals(True)
        self._frame_combo.setCurrentIndex(self._frame_index)
        self._frame_combo.blockSignals(blocked)
        self._refresh_image()

    def _prepare_media(self, result: EntryPreviewResult) -> None:
        self._media_placeholder.clear()
        self._media_player.setVisible(result.is_video)
        self._media_placeholder.setVisible(not result.is_video)
        self._auto_play_audio_checkbox.setVisible(not result.is_video)
        self._auto_play_video_checkbox.setVisible(result.is_video)
        for button, enabled in (
            (self._auto_play_audio_checkbox, self._auto_play_audio),
            (self._auto_play_video_checkbox, self._auto_play_video),
        ):
            blocker = QSignalBlocker(button)
            button.setChecked(enabled)
            del blocker
        if not result.is_video:
            self._media_placeholder.setText(self.tr("WAV audio"))
        self._position.setRange(0, 0)
        self._time.setText(self.tr("00:00 / 00:00"))
        self._media_play.setEnabled(False)
        self._media_play.setEnabled(
            self._media_player.set_media_data(
                result.media_data,
                result.media_suffix or (".bik" if result.is_video else ".wav"),
            )
        )

    def _reset_media(self) -> None:
        self._animation_timer.stop()
        self._auto_play_audio_checkbox.hide()
        self._auto_play_video_checkbox.hide()
        self._default_fit_pending = False
        self._resume_animation_on_activate = False
        self._resume_media_on_activate = False
        self._media_player.stop()

    def shutdown(self) -> None:
        self._reset_media()
        self._media_player.shutdown()

    def _toggle_media(self) -> None:
        if not self._is_active:
            return
        if self._media_is_playing():
            self._pause_media()
        else:
            self._play_media()

    def _media_is_playing(self) -> bool:
        return self._media_player.is_playing

    def _play_media(self) -> None:
        self._media_player.play()

    def _pause_media(self) -> None:
        self._media_player.pause()

    def _sync_vlc_media_controls(self, playing: bool) -> None:
        self._media_play.setText(
            self.tr("Pause") if playing else self.tr("Play")
        )

    def _sync_media_position(self, position: int) -> None:
        if not self._scrubbing:
            blocked = self._position.blockSignals(True)
            self._position.setValue(position)
            self._position.blockSignals(blocked)
        self._update_time_label()

    def _sync_media_duration(self, duration: int) -> None:
        self._position.setRange(0, max(0, duration))
        self._update_time_label()

    def _begin_scrubbing(self) -> None:
        self._scrubbing = True

    def _end_scrubbing(self) -> None:
        self._seek_media(self._position.value())
        self._scrubbing = False

    def _seek_media(self, position: int) -> None:
        if self._scrubbing:
            self._media_player.seek(position)

    def _update_time_label(self) -> None:
        position = self._media_player.position_ms
        duration = self._media_player.duration_ms
        current = max(0, position) // 1000
        duration = max(0, duration) // 1000
        self._time.setText(self.tr('{0} / {1}').format(self._format_time(current), self._format_time(duration)))

    @staticmethod
    def _format_time(seconds: int) -> str:
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    def _on_vlc_media_error(self, message: str) -> None:
        self._media_player.hide()
        self._media_placeholder.setText(message)
        self._media_placeholder.setVisible(True)
