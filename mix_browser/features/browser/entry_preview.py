from __future__ import annotations

import math
from functools import lru_cache
from html import escape

from PySide6.QtCore import (
    QAbstractTableModel,
    QEvent,
    QItemSelectionModel,
    QModelIndex,
    QPointF,
    QRect,
    QSignalBlocker,
    QSize,
    QT_TRANSLATE_NOOP,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QIcon,
    QImage,
    QMatrix4x4,
    QMouseEvent,
    QOpenGLContext,
    QOpenGLFunctions,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
    QWheelEvent,
    QStandardItem,
    QStandardItemModel,
    QVector3D,
    QVector4D,
)
from PySide6.QtOpenGL import (
    QOpenGLBuffer,
    QOpenGLShaderProgram,
    QOpenGLTexture,
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollBar,
    QSlider,
    QStackedWidget,
    QStyle,
    QStyleOptionComboBox,
    QStyleOptionViewItem,
    QStylePainter,
    QStyledItemDelegate,
    QTableView,
    QTreeView,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid as is_qobject_valid

from mix_browser.features.archive.dat_format import DatRecord
from mix_browser.features.browser.asset_preview import (
    EntryPreviewResult,
    PALETTE_GROUPS,
    PALETTE_SELECTION_STAGES,
    PALETTE_USE_GROUPS,
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
from mix_browser.features.browser.voxel_renderer import (
    VoxelRendererResources,
    create_voxel_shader_program,
)
from mix_browser.shared.application_style import BROWSER_TOOLBAR_CONTROL_HEIGHT
from mix_browser.shared.interaction_help import (
    InteractionHelpButton,
    InteractionHelpCatalog,
)

_GL_DEPTH_TEST = 0x0B71
_GL_LEQUAL = 0x0203
_GL_DEPTH_BUFFER_BIT = 0x00000100
_GL_FLOAT = 0x1406
_GL_TRIANGLES = 0x0004


# @arch mix-browser.palette-choice-control component | en: Displays a selected palette and opens the palette tree | zh: 显示当前色盘并打开色盘树
class _PaletteComboBox(QComboBox):
    palette_step_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._display_text = ""
        self._popup_open_on_press: bool | None = None
        self._wheel_delta_remainder = 0

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._popup_open_on_press = self.view().isVisible()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        popup_open_on_press = self._popup_open_on_press
        self._popup_open_on_press = None
        super().mouseReleaseEvent(event)
        if (
            event.button() == Qt.MouseButton.LeftButton
            and popup_open_on_press is not None
            and self.rect().contains(event.position().toPoint())
        ):
            should_be_open = not popup_open_on_press
            if self.view().isVisible() != should_be_open:
                if should_be_open:
                    self.showPopup()
                else:
                    self.hidePopup()

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y() or event.pixelDelta().y()
        if not delta:
            event.ignore()
            return
        self._wheel_delta_remainder += delta
        steps = int(self._wheel_delta_remainder / 120)
        self._wheel_delta_remainder -= steps * 120
        if steps:
            self.palette_step_requested.emit(-steps)
        event.accept()

    def set_display_text(self, text: str) -> None:
        self.setToolTip(text)
        if text == self._display_text:
            return
        self._display_text = text
        self.setAccessibleName(text or self.tr("Palette"))
        self.update()

    def paintEvent(self, event) -> None:
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        text_rect = self.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox,
            option,
            QStyle.SubControl.SC_ComboBoxEditField,
            self,
        )
        arrow_rect = self.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox,
            option,
            QStyle.SubControl.SC_ComboBoxArrow,
            self,
        )
        frame_width = self.style().pixelMetric(
            QStyle.PixelMetric.PM_ComboBoxFrameWidth,
            option,
            self,
        )
        text_width = max(
            0,
            min(text_rect.right() + 1, arrow_rect.left())
            - text_rect.left()
            - frame_width
            - 6,
        )
        option.currentText = self.fontMetrics().elidedText(
            self._display_text,
            Qt.TextElideMode.ElideRight,
            text_width,
        )
        painter = QStylePainter(self)
        painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, option)
        painter.drawControl(QStyle.ControlElement.CE_ComboBoxLabel, option)


class _PaletteTreeView(QTreeView):
    def mousePressEvent(self, event: QMouseEvent) -> None:
        index = self.indexAt(event.position().toPoint())
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._is_expandable_group(index)
        ):
            self.setExpanded(index, not self.isExpanded(index))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._is_expandable_group(self.indexAt(event.position().toPoint())):
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if self._is_expandable_group(self.indexAt(event.position().toPoint())):
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _is_expandable_group(self, index: QModelIndex) -> bool:
        model = self.model()
        return (
            index.isValid()
            and model is not None
            and model.rowCount(index) > 0
            and not index.flags() & Qt.ItemFlag.ItemIsSelectable
        )


class _PaletteTreeItemDelegate(QStyledItemDelegate):
    def __init__(self, view: QTreeView) -> None:
        super().__init__(view)
        self._view = view
        self._viewport = view.viewport()
        self._hovered_index = QModelIndex()
        view.setMouseTracking(True)
        self._viewport.setMouseTracking(True)
        self._viewport.installEventFilter(self)
        model = view.model()
        if model is not None:
            model.modelReset.connect(self._on_model_reset)

    def eventFilter(self, watched, event) -> bool:
        if not is_qobject_valid(self) or not is_qobject_valid(self._view):
            return False
        if watched is self._viewport:
            if not is_qobject_valid(self._viewport):
                return False
            if event.type() == QEvent.Type.MouseMove and isinstance(
                event, QMouseEvent
            ):
                index = self._view.indexAt(event.position().toPoint())
                if (
                    not index.isValid()
                    or not index.flags() & Qt.ItemFlag.ItemIsSelectable
                ):
                    index = QModelIndex()
                self._set_hovered_index(index)
            elif event.type() == QEvent.Type.Leave:
                self._set_hovered_index(QModelIndex())
            return False
        return super().eventFilter(watched, event)

    def paint(self, painter, option, index: QModelIndex) -> None:
        item_option = QStyleOptionViewItem(option)
        self.initStyleOption(item_option, index)
        if not index.flags() & Qt.ItemFlag.ItemIsSelectable:
            item_option.state &= ~(
                QStyle.StateFlag.State_Selected
                | QStyle.StateFlag.State_MouseOver
            )
        elif index == self._hovered_index:
            item_option.state |= QStyle.StateFlag.State_MouseOver
        else:
            item_option.state &= ~QStyle.StateFlag.State_MouseOver
        super().paint(painter, item_option, index)

    def _set_hovered_index(self, index: QModelIndex) -> None:
        if not is_qobject_valid(self._view) or not is_qobject_valid(
            self._viewport
        ):
            return
        if index == self._hovered_index:
            return
        previous = self._hovered_index
        self._hovered_index = index
        if previous.isValid():
            self._viewport.update(self._view.visualRect(previous))
        if index.isValid():
            self._viewport.update(self._view.visualRect(index))

    def _on_model_reset(self) -> None:
        if not is_qobject_valid(self._view) or not is_qobject_valid(
            self._viewport
        ):
            return
        self._hovered_index = QModelIndex()
        self._viewport.update()


@lru_cache(maxsize=1)
def _checkerboard_tile() -> QPixmap:
    tile = QPixmap(24, 24)
    tile.fill(QColor("#f1f1f1"))
    painter = QPainter(tile)
    painter.fillRect(0, 0, 12, 12, QColor("#d1d1d1"))
    painter.fillRect(12, 12, 12, 12, QColor("#d1d1d1"))
    painter.end()
    return tile


def _preview_background_brush(mode: str, custom_color: str) -> QBrush:
    if mode == "checkerboard":
        return QBrush(_checkerboard_tile())
    colors = {
        "dark": QColor("#242424"),
        "light": QColor("#f4f4f4"),
        "green": QColor("#00a000"),
        "custom": QColor(custom_color),
    }
    return QBrush(colors.get(mode, QColor("#242424")))


def _preview_text_color(mode: str, custom_color: str) -> QColor:
    if mode == "checkerboard":
        return QColor("#171717")
    backgrounds = {
        "dark": QColor("#242424"),
        "light": QColor("#f4f4f4"),
        "green": QColor("#00a000"),
        "custom": QColor(custom_color),
    }
    background = backgrounds.get(mode, QColor("#242424"))
    if not background.isValid():
        background = QColor("#242424")

    def linear(channel: float) -> float:
        if channel <= 0.04045:
            return channel / 12.92
        return ((channel + 0.055) / 1.055) ** 2.4

    luminance = (
        0.2126 * linear(background.redF())
        + 0.7152 * linear(background.greenF())
        + 0.0722 * linear(background.blueF())
    )
    return QColor("#000000" if luminance >= 0.179 else "#ffffff")


def _draw_contrast_border(painter: QPainter, rect: QRect) -> None:
    painter.save()
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor(0, 0, 0, 210), 3))
    painter.drawRect(rect)
    painter.setPen(QPen(QColor(255, 255, 255, 225), 1, Qt.PenStyle.DashLine))
    painter.drawRect(rect)
    painter.restore()


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
    zoom_requested = Signal(float, QPointF)
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
        self.zoom_requested.emit(delta / 120, event.position())
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


# @arch mix-browser.media-preview-surface component | en: Frames VLC video at its detected aspect ratio and paints the selected background and outline | zh: 按 VLC 检测到的画幅比例显示视频，并绘制所选背景和边界
class _MediaPreviewSurface(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(160)
        self._media_player: VlcMediaPlayer | None = None
        self._placeholder: QLabel | None = None
        self._video_mode = False
        self._asset_boundaries_visible = False
        self._aspect_ratio: float | None = None
        self._content_rect = QRect()
        self._background_mode = "checkerboard"
        self._custom_background_color = "#00a000"
        self._text_color = _preview_text_color(
            self._background_mode,
            self._custom_background_color,
        )

    def set_content(
        self,
        media_player: VlcMediaPlayer,
        placeholder: QLabel,
    ) -> None:
        self._media_player = media_player
        self._placeholder = placeholder
        self._refresh_placeholder_text_color()
        self._layout_content()

    def set_video_mode(self, enabled: bool) -> None:
        self._video_mode = bool(enabled)
        if not enabled:
            self._aspect_ratio = None
        self._layout_content()

    def set_video_size(self, width: int, height: int) -> None:
        self._aspect_ratio = (
            width / height
            if self._video_mode and width > 0 and height > 0
            else None
        )
        self._layout_content()

    def set_preview_background(self, mode: str, custom_color: str) -> None:
        self._background_mode = mode
        self._custom_background_color = custom_color
        self._text_color = _preview_text_color(mode, custom_color)
        self._refresh_placeholder_text_color()
        self.update()

    def set_asset_boundaries_visible(self, visible: bool) -> None:
        self._asset_boundaries_visible = bool(visible)
        self.update()

    def set_placeholder_text(self, text: str) -> None:
        if self._placeholder is not None:
            self._placeholder.setText(text)
            self._refresh_placeholder_text_color()

    def _refresh_placeholder_text_color(self) -> None:
        if self._placeholder is not None:
            self._placeholder.setStyleSheet(
                f"color: {self._text_color.name()};"
            )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._layout_content()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(
            self.rect(),
            _preview_background_brush(
                self._background_mode,
                self._custom_background_color,
            ),
        )
        if (
            self._asset_boundaries_visible
            and self._video_mode
            and not self._content_rect.isEmpty()
        ):
            border = self._content_rect.adjusted(-2, -2, 1, 1)
            _draw_contrast_border(painter, border)
        painter.end()

    def _layout_content(self) -> None:
        margin = 3 if self._video_mode else 0
        available = self.rect().adjusted(margin, margin, -margin, -margin)
        if available.width() <= 0 or available.height() <= 0:
            self._content_rect = QRect()
        elif self._aspect_ratio:
            width = available.width()
            height = available.height()
            if width / height > self._aspect_ratio:
                width = round(height * self._aspect_ratio)
            else:
                height = round(width / self._aspect_ratio)
            self._content_rect = QRect(0, 0, width, height)
            self._content_rect.moveCenter(available.center())
        else:
            self._content_rect = available
        for widget in (self._media_player, self._placeholder):
            if widget is not None:
                widget.setGeometry(self._content_rect)
        self.update()


class _VoxelModelView(QOpenGLWidget):
    zoom_changed = Signal(float)
    _VERTEX_STRIDE = 7 * 4
    _CAMERA_DISTANCE = 32.0
    _CAMERA_ELEVATION_RATIO = 0.62
    _VERTICAL_FOV = 38.0
    _DEFAULT_YAW = -45.0
    _OBLIQUE_VIEW = "oblique"
    _FREE_ROTATION_VIEW = "free-rotation"
    _DEFAULT_OBLIQUE_AZIMUTH = -45.0
    _DEFAULT_OBLIQUE_ELEVATION = math.degrees(
        math.atan(_CAMERA_ELEVATION_RATIO)
    )

    def __init__(
        self,
        parent: QWidget | None = None,
        renderer_resources: VoxelRendererResources | None = None,
    ) -> None:
        super().__init__(parent)
        # Keep this widget compatible with the application-wide shared GL context.
        surface_format = self.format()
        surface_format.setVersion(2, 0)
        surface_format.setDepthBufferSize(24)
        self.setFormat(surface_format)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._model: VoxelModel | None = None
        self._frame_index = 0
        self._palette: PaletteOption | None = None
        self._zoom = 1.0
        self._view_mode = self._OBLIQUE_VIEW
        self._yaw = 0.0
        self._pitch = 0.0
        self._oblique_azimuth = self._DEFAULT_OBLIQUE_AZIMUTH
        self._oblique_elevation = self._DEFAULT_OBLIQUE_ELEVATION
        self._pan_x = 0.0
        self._pan_y = 0.0
        self._drag_mode: str | None = None
        self._last_pointer = None
        self._background_mode = "checkerboard"
        self._custom_background_color = "#00a000"
        self._asset_boundaries_visible = False
        self._render_text_color = _preview_text_color(
            self._background_mode,
            self._custom_background_color,
        )
        self._renderer_resources = renderer_resources
        self._gl: QOpenGLFunctions | None = None
        self._program: QOpenGLShaderProgram | None = None
        self._owns_program = False
        self._vertex_buffer = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        self._palette_texture: QOpenGLTexture | None = None
        self._geometry_dirty = True
        self._palette_dirty = True
        self._vertex_count = 0
        self._render_error: str | None = None

    def set_model(self, model: VoxelModel, palette: PaletteOption) -> None:
        self._model = model
        self._frame_index = 0
        self._palette = palette
        self._geometry_dirty = True
        self._palette_dirty = True
        self._reset_orientation()
        self._zoom = 1.0
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
        self._geometry_dirty = True
        self._palette_dirty = True
        if self._gl is not None and self.isValid():
            self.makeCurrent()
            try:
                if self._vertex_buffer.isCreated():
                    self._vertex_buffer.destroy()
            finally:
                self.doneCurrent()
        self.update()

    def set_palette(self, palette: PaletteOption) -> None:
        self._palette = palette
        self._palette_dirty = True
        self.update()

    def set_preview_background(self, mode: str, custom_color: str) -> None:
        self._background_mode = mode
        self._custom_background_color = custom_color
        self._render_text_color = _preview_text_color(mode, custom_color)
        self.update()

    def set_asset_boundaries_visible(self, visible: bool) -> None:
        self._asset_boundaries_visible = bool(visible)
        self.update()

    def set_frame(self, frame_index: int) -> None:
        if self._model is None:
            return
        frame_index = min(max(frame_index, 0), self._model.frame_count - 1)
        if frame_index == self._frame_index:
            return
        self._frame_index = frame_index
        self.update()

    def set_zoom(self, zoom: float) -> None:
        zoom = min(8.0, max(0.001, zoom))
        if zoom == self._zoom:
            return
        self._zoom = zoom
        self.zoom_changed.emit(zoom)
        self.update()

    def set_view_mode(self, mode: str) -> None:
        if mode not in {self._OBLIQUE_VIEW, self._FREE_ROTATION_VIEW}:
            return
        if mode == self._view_mode:
            return
        self._view_mode = mode
        self.update()

    def reset_view(self) -> None:
        self._reset_orientation()
        self.set_zoom(1.0)
        self.update()

    def _reset_orientation(self) -> None:
        self._yaw = self._DEFAULT_YAW
        self._pitch = 0.0
        self._oblique_azimuth = self._DEFAULT_OBLIQUE_AZIMUTH
        self._oblique_elevation = self._DEFAULT_OBLIQUE_ELEVATION
        self._pan_x = 0.0
        self._pan_y = 0.0

    def _camera_position(self) -> QVector3D:
        if self._view_mode == self._FREE_ROTATION_VIEW:
            return QVector3D(
                0.0,
                -self._CAMERA_DISTANCE,
                self._CAMERA_DISTANCE * self._CAMERA_ELEVATION_RATIO,
            )
        azimuth = math.radians(self._oblique_azimuth)
        elevation = math.radians(self._oblique_elevation)
        distance = self._CAMERA_DISTANCE * math.sqrt(
            1.0 + self._CAMERA_ELEVATION_RATIO**2
        )
        horizontal_distance = distance * math.cos(elevation)
        return QVector3D(
            horizontal_distance * math.cos(azimuth),
            horizontal_distance * math.sin(azimuth),
            distance * math.sin(elevation),
        )

    def initializeGL(self) -> None:
        context = self.context()
        if context is not None:
            context.aboutToBeDestroyed.connect(
                self._cleanup_gl_resources,
                Qt.ConnectionType.DirectConnection,
            )
        self._gl = self.context().functions()
        self._gl.initializeOpenGLFunctions()
        self._gl.glEnable(_GL_DEPTH_TEST)
        self._gl.glDepthFunc(_GL_LEQUAL)

        self._render_error = None
        self._program = None
        self._owns_program = False
        if self._renderer_resources is not None and context is not None:
            self._program = self._renderer_resources.program_for_context(context)
        if self._program is None:
            self._program = create_voxel_shader_program(self)
            self._owns_program = self._program is not None
        if self._program is None:
            self._render_error = self.tr("The VXL renderer could not be initialized.")
            return
        self._vertex_buffer.setUsagePattern(QOpenGLBuffer.UsagePattern.StaticDraw)
        if not self._vertex_buffer.create():
            self._render_error = self.tr("The VXL vertex buffer could not be created.")
            return
        texture = QOpenGLTexture(QOpenGLTexture.Target.Target1D)
        texture.setSize(256)
        texture.setFormat(QOpenGLTexture.TextureFormat.RGB8_UNorm)
        texture.setMinMagFilters(
            QOpenGLTexture.Filter.Nearest,
            QOpenGLTexture.Filter.Nearest,
        )
        texture.setWrapMode(QOpenGLTexture.WrapMode.ClampToEdge)
        texture.allocateStorage(
            QOpenGLTexture.PixelFormat.RGB,
            QOpenGLTexture.PixelType.UInt8,
        )
        if not texture.isStorageAllocated():
            texture.destroy()
            del texture
            self._render_error = self.tr("The VXL renderer could not be initialized.")
            return
        self._palette_texture = texture
        self._upload_model()

    def _cleanup_gl_resources(self) -> None:
        context = self.context()
        if context is None:
            return
        already_current = QOpenGLContext.currentContext() is context
        if not already_current:
            self.makeCurrent()
        try:
            if self._vertex_buffer.isCreated():
                self._vertex_buffer.destroy()
            if self._palette_texture is not None:
                self._palette_texture.destroy()
                self._palette_texture = None
            if self._owns_program and self._program is not None:
                program = self._program
                program.removeAllShaders()
                program.setParent(None)
                self._program = None
                self._owns_program = False
                del program
            else:
                self._program = None
        finally:
            self._gl = None
            self._vertex_count = 0
            self._geometry_dirty = True
            self._palette_dirty = True
            if not already_current:
                self.doneCurrent()

    def _upload_model(self) -> None:
        if (
            self._model is None
            or self._palette is None
            or self._palette_texture is None
        ):
            return
        if self._geometry_dirty:
            if not self._vertex_buffer.isCreated() and not self._vertex_buffer.create():
                self._render_error = self.tr("The VXL vertex buffer could not be created.")
                return
            if not self._vertex_buffer.bind():
                self._render_error = self.tr("The VXL vertex buffer could not be bound.")
                return
            self._vertex_buffer.allocate(
                self._model.vertices,
                len(self._model.vertices),
            )
            self._vertex_buffer.release()
            self._vertex_count = self._model.vertex_count
            self._geometry_dirty = False
        if self._palette_dirty:
            colors = self._palette.colors[:256]
            if len(colors) < 256:
                colors = (*colors, *((0, 0, 0),) * (256 - len(colors)))
            palette_data = bytes(component for color in colors for component in color)
            self._palette_texture.setData(
                QOpenGLTexture.PixelFormat.RGB,
                QOpenGLTexture.PixelType.UInt8,
                palette_data,
            )
            self._palette_dirty = False

    def paintGL(self) -> None:
        gl = self._gl
        if gl is None:
            return
        painter = QPainter(self)
        painter.fillRect(
            self.rect(),
            _preview_background_brush(
                self._background_mode,
                self._custom_background_color,
            ),
        )
        painter.end()
        gl.glViewport(
            0,
            0,
            round(self.width() * self.devicePixelRatioF()),
            round(self.height() * self.devicePixelRatioF()),
        )
        gl.glEnable(_GL_DEPTH_TEST)
        gl.glDepthFunc(_GL_LEQUAL)
        gl.glDepthMask(True)
        gl.glClear(_GL_DEPTH_BUFFER_BIT)
        if self._render_error:
            painter = QPainter(self)
            painter.setPen(self._render_text_color)
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                self._render_error,
            )
            painter.end()
            return
        if self._model is None or self._program is None:
            return
        if self._geometry_dirty or self._palette_dirty:
            self._upload_model()
        if self._vertex_count <= 0:
            return

        aspect = max(1.0, self.width()) / max(1.0, self.height())
        projection = QMatrix4x4()
        projection.perspective(self._VERTICAL_FOV, aspect, 0.1, 100.0)
        camera_up = QVector3D(0.0, 0.0, 1.0)
        if self._view_mode == self._OBLIQUE_VIEW:
            azimuth = math.radians(self._oblique_azimuth)
            elevation = math.radians(self._oblique_elevation)
            camera_up = QVector3D(
                -math.sin(elevation) * math.cos(azimuth),
                -math.sin(elevation) * math.sin(azimuth),
                math.cos(elevation),
            )
        camera_view = QMatrix4x4()
        camera_view.lookAt(
            self._camera_position(),
            QVector3D(0.0, 0.0, 0.0),
            camera_up,
        )
        pan = QMatrix4x4()
        pan.translate(self._pan_x, self._pan_y, 0.0)
        view = pan * camera_view
        model = QMatrix4x4()
        if self._view_mode == self._FREE_ROTATION_VIEW:
            model.rotate(self._yaw, 0.0, 0.0, 1.0)
            model.rotate(self._pitch, 1.0, 0.0, 0.0)
        model.scale(self._zoom)
        mvp = projection * view * model

        if not self._program.bind() or not self._vertex_buffer.bind():
            self._render_error = self.tr("The VXL renderer could not bind its resources.")
            self._program.release()
            self.update()
            return
        self._program.setUniformValue("uMvp", mvp)
        if self._palette_texture is None or not self._palette_texture.isCreated():
            self._render_error = self.tr("The VXL renderer could not bind its resources.")
            self._vertex_buffer.release()
            self._program.release()
            self.update()
            return
        self._palette_texture.bind(0)
        self._program.setUniformValue("uPalette", 0)
        stride = self._VERTEX_STRIDE
        position_location = self._program.attributeLocation("aPosition")
        normal_location = self._program.attributeLocation("aNormal")
        color_location = self._program.attributeLocation("aColor")
        for location, offset, size in (
            (position_location, 0, 3),
            (normal_location, 12, 3),
            (color_location, 24, 1),
        ):
            self._program.enableAttributeArray(location)
            self._program.setAttributeBuffer(location, _GL_FLOAT, offset, size, stride)
        frame = self._model.frame_transforms[self._frame_index]
        for limb_index, (first_vertex, vertex_count) in enumerate(self._model.limb_ranges):
            if not vertex_count:
                continue
            values = frame[limb_index]
            part = QMatrix4x4()
            for row in range(4):
                offset = row * 4
                part.setRow(
                    row,
                    QVector4D(*values[offset : offset + 4]),
                )
            self._program.setUniformValue("uPart", part)
            self._program.setUniformValue(
                "uNormalMatrix",
                (model * part).normalMatrix(),
            )
            gl.glDrawArrays(_GL_TRIANGLES, first_vertex, vertex_count)
        for location in (position_location, normal_location, color_location):
            self._program.disableAttributeArray(location)
        self._vertex_buffer.release()
        self._palette_texture.release()
        self._program.release()
        painter = QPainter(self)
        self._paint_model_bounds(painter, mvp)
        painter.end()

    def _paint_model_bounds(self, painter: QPainter, mvp: QMatrix4x4) -> None:
        model = self._model
        if (
            not self._asset_boundaries_visible
            or model is None
            or not model.frame_bounds
        ):
            return
        bounds = model.frame_bounds[
            min(self._frame_index, len(model.frame_bounds) - 1)
        ]
        lower = bounds[:3]
        upper = bounds[3:]
        projected = []
        for corner_mask in range(8):
            corner = QVector4D(
                upper[0] if corner_mask & 1 else lower[0],
                upper[1] if corner_mask & 2 else lower[1],
                upper[2] if corner_mask & 4 else lower[2],
                1.0,
            )
            clip = mvp.map(corner)
            if clip.w() <= 0:
                projected.append(None)
            else:
                x = (clip.x() / clip.w() + 1.0) * self.width() * 0.5
                y = (1.0 - clip.y() / clip.w()) * self.height() * 0.5
                projected.append(QPointF(x, y))

        edges = tuple(
            (first, second)
            for first in range(8)
            for second in range(first + 1, 8)
            if (first ^ second).bit_count() == 1
        )
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(0, 0, 0, 210), 3))
        for first, second in edges:
            if projected[first] is not None and projected[second] is not None:
                painter.drawLine(projected[first], projected[second])
        painter.setPen(QPen(QColor(255, 255, 255, 225), 1, Qt.PenStyle.DashLine))
        for first, second in edges:
            if projected[first] is not None and projected[second] is not None:
                painter.drawLine(projected[first], projected[second])
        painter.restore()

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y() or event.pixelDelta().y()
        if not delta:
            event.ignore()
            return
        self.zoom_at(
            self._zoom + delta / 120 * 0.1,
            event.position(),
        )
        event.accept()

    def zoom_at(self, zoom: float, position: QPointF) -> None:
        zoom = min(8.0, max(0.001, zoom))
        if zoom == self._zoom:
            return
        scale_ratio = zoom / self._zoom
        distance = self._camera_position().length()
        world_per_pixel = (
            2.0
            * distance
            * math.tan(math.radians(self._VERTICAL_FOV * 0.5))
            / max(1, self.height())
        )
        offset = position - QPointF(self.width() * 0.5, self.height() * 0.5)
        self._pan_x += (1.0 - scale_ratio) * (
            offset.x() * world_per_pixel - self._pan_x
        )
        self._pan_y -= (1.0 - scale_ratio) * (
            offset.y() * world_per_pixel + self._pan_y
        )
        self.set_zoom(zoom)

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
            if self._view_mode == self._OBLIQUE_VIEW:
                self._oblique_azimuth = (
                    self._oblique_azimuth - delta.x() * 0.5
                ) % 360.0
                self._oblique_elevation = min(
                    90.0,
                    max(-90.0, self._oblique_elevation + delta.y() * 0.5),
                )
            else:
                self._yaw = (self._yaw + delta.x() * 0.5) % 360.0
                self._pitch = min(
                    89.0,
                    max(-89.0, self._pitch + delta.y() * 0.5),
                )
        else:
            viewport_height = max(1, self.height())
            world_per_pixel = (
                2.0
                * self._camera_position().length()
                * math.tan(math.radians(self._VERTICAL_FOV * 0.5))
                / viewport_height
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
    background_preference_changed = Signal(str, str)
    boundary_visibility_preference_changed = Signal(bool)
    transparent_index_preference_changed = Signal(bool)
    palette_use_categories_preference_changed = Signal(bool)
    voxel_view_mode_preference_changed = Signal(str)

    # Keep VXL and HVA geometry in native game units with one shared view scale.
    _VXL_DEFAULT_DISPLAY_SCALE = 1.0
    _MIN_IMAGE_ZOOM = 0.001

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        renderer_resources: VoxelRendererResources | None = None,
        interaction_help: InteractionHelpCatalog | None = None,
        palette_use_categories_enabled: bool = True,
        voxel_view_mode: str = "oblique",
    ) -> None:
        super().__init__(parent)
        self.setMinimumWidth(280)
        self._result: EntryPreviewResult | None = None
        self._frame_index = 0
        self._palette_index = 0
        self._palette_cycle_order: list[int] = []
        self._palette_display_labels: dict[int, str] = {}
        self._palette_model_indices: dict[int, QModelIndex] = {}
        self._palette_manually_selected = False
        self._palette_use_categories_enabled = palette_use_categories_enabled
        self._image_zoom = 1.0
        self._auto_play_shp_animations = False
        self._auto_play_hva_animations = False
        self._auto_play_audio = False
        self._auto_play_video = False
        self._combine_shp_shadow_frames = False
        self._preview_background_mode = "checkerboard"
        self._custom_background_color = "#00a000"
        self._asset_boundaries_visible = False
        self._transparent_index_is_transparent = False
        self._is_active = False
        self._resume_animation_on_activate = False
        self._resume_media_on_activate = False
        self._media_started = False
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
            "animation",
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
        self._palette_combo = _PaletteComboBox(self._image_controls)
        self._palette_combo.setFixedHeight(BROWSER_TOOLBAR_CONTROL_HEIGHT)
        self._palette_combo.setMaxVisibleItems(16)
        self._palette_model = QStandardItemModel(self._palette_combo)
        self._palette_combo.setModel(self._palette_model)
        self._palette_tree = _PaletteTreeView(self._palette_combo)
        self._palette_tree.setHeaderHidden(True)
        self._palette_tree.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._palette_tree.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._palette_tree.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._palette_tree.setUniformRowHeights(True)
        self._palette_tree.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self._palette_combo.setView(self._palette_tree)
        self._palette_tree.setItemDelegate(
            _PaletteTreeItemDelegate(self._palette_tree)
        )
        self._palette_tree.clicked.connect(self._select_palette)
        self._palette_tree.activated.connect(self._select_palette)
        self._palette_combo.palette_step_requested.connect(self._step_palette)
        self._palette_use_categories_checkbox = QCheckBox(
            self.tr("By use"),
            self._image_controls,
        )
        self._palette_use_categories_checkbox.setFixedHeight(
            BROWSER_TOOLBAR_CONTROL_HEIGHT
        )
        self._palette_use_categories_checkbox.setChecked(
            self._palette_use_categories_enabled
        )
        self._palette_use_categories_checkbox.setToolTip(
            self.tr("Group palette candidates by use")
        )
        self._palette_use_categories_checkbox.setAccessibleName(
            self.tr("Group palette candidates by use")
        )
        self._palette_use_categories_checkbox.toggled.connect(
            self._on_palette_use_categories_toggled
        )
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
        controls_layout.addWidget(self._palette_use_categories_checkbox)
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
        self._voxel_view_mode_combo = QComboBox(self._image_page)
        self._voxel_view_mode_combo.setFixedSize(
            116,
            BROWSER_TOOLBAR_CONTROL_HEIGHT,
        )
        self._voxel_view_mode_combo.addItem(
            self.tr("Orbit view"),
            _VoxelModelView._OBLIQUE_VIEW,
        )
        self._voxel_view_mode_combo.addItem(
            self.tr("Free rotation"),
            _VoxelModelView._FREE_ROTATION_VIEW,
        )
        self._voxel_view_mode_combo.setToolTip(
            self.tr("Choose how to navigate VXL and HVA model previews.")
        )
        self._voxel_view_mode_combo.setAccessibleName(self.tr("Model view"))
        initial_view_mode_index = self._voxel_view_mode_combo.findData(
            voxel_view_mode
        )
        if initial_view_mode_index >= 0:
            self._voxel_view_mode_combo.setCurrentIndex(initial_view_mode_index)
        self._voxel_view_mode_combo.currentIndexChanged.connect(
            self._select_voxel_view_mode
        )
        zoom_layout.addWidget(self._voxel_view_mode_combo)
        self._voxel_view_mode_combo.hide()
        self._interaction_help_button = (
            InteractionHelpButton(
                interaction_help,
                self.tr("Preview interactions"),
                self._image_page,
                group=self.tr("Image and model previews"),
                size=BROWSER_TOOLBAR_CONTROL_HEIGHT,
                align_popup_right=True,
            )
            if interaction_help is not None
            else None
        )
        if self._interaction_help_button is not None:
            zoom_layout.addWidget(self._interaction_help_button)
        image_layout.addLayout(zoom_layout)

        self._image_scene = QGraphicsScene(self._image_page)
        self._image_item = QGraphicsPixmapItem()
        self._image_scene.addItem(self._image_item)
        self._image_boundary_shadow = QGraphicsRectItem(self._image_item)
        self._image_boundary_shadow.setZValue(1)
        shadow_pen = QPen(QColor(0, 0, 0, 210), 3)
        shadow_pen.setCosmetic(True)
        self._image_boundary_shadow.setPen(shadow_pen)
        self._image_boundary = QGraphicsRectItem(self._image_item)
        self._image_boundary.setZValue(2)
        boundary_pen = QPen(QColor(255, 255, 255, 225), 1, Qt.PenStyle.DashLine)
        boundary_pen.setCosmetic(True)
        self._image_boundary.setPen(boundary_pen)
        self._image_boundary.hide()
        self._image_boundary_shadow.hide()
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
            QGraphicsView.ViewportAnchor.NoAnchor
        )
        self._image_view.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self._image_view.zoom_requested.connect(self._zoom_image_at_cursor)
        image_layout.addWidget(self._image_view, 1)
        self._voxel_view = _VoxelModelView(
            self._image_page,
            renderer_resources,
        )
        self._voxel_view.zoom_changed.connect(self._sync_voxel_zoom)
        self._voxel_view.set_view_mode(voxel_view_mode)
        self._voxel_view.hide()
        image_layout.addWidget(self._voxel_view, 1)
        self._frame_notice = QLabel(self._image_page)
        self._frame_notice.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._frame_notice.setWordWrap(True)
        self._frame_notice.hide()
        image_layout.addWidget(self._frame_notice)

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
        self._media_canvas = _MediaPreviewSurface(self._media_page)
        self._media_player = VlcMediaPlayer(self._media_canvas)
        self._media_player.playback_state_changed.connect(self._sync_vlc_media_controls)
        self._media_player.position_changed.connect(self._sync_media_position)
        self._media_player.duration_changed.connect(self._sync_media_duration)
        self._media_player.video_size_changed.connect(self._media_canvas.set_video_size)
        self._media_player.media_ready_changed.connect(self._on_media_ready_changed)
        self._media_player.error_occurred.connect(self._on_vlc_media_error)
        self._media_placeholder = QLabel("", self._media_canvas)
        self._media_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._media_placeholder.setWordWrap(True)
        self._media_canvas.set_content(self._media_player, self._media_placeholder)
        media_layout.addWidget(self._media_canvas, 1)
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
        self._background_controls = QWidget(self)
        background_layout = QHBoxLayout(self._background_controls)
        background_layout.setContentsMargins(0, 0, 0, 0)
        background_layout.setSpacing(6)
        self._background_label = QLabel(
            self.tr("Background"),
            self._background_controls,
        )
        self._background_label.setFixedHeight(BROWSER_TOOLBAR_CONTROL_HEIGHT)
        self._background_combo = QComboBox(self._background_controls)
        self._background_combo.setFixedHeight(BROWSER_TOOLBAR_CONTROL_HEIGHT)
        self._background_combo.setToolTip(
            self.tr("Changes the preview background; it does not remove colors from the asset.")
        )
        self._background_combo.addItem(self.tr("Checkerboard"), "checkerboard")
        self._background_combo.addItem(self.tr("Dark"), "dark")
        self._background_combo.addItem(self.tr("Light"), "light")
        self._background_combo.addItem(self.tr("Green"), "green")
        self._background_combo.addItem(self.tr("Custom color"), "custom")
        self._background_combo.currentIndexChanged.connect(
            self._select_preview_background
        )
        self._background_color_button = QToolButton(self._background_controls)
        self._background_color_button.setFixedSize(
            BROWSER_TOOLBAR_CONTROL_HEIGHT,
            BROWSER_TOOLBAR_CONTROL_HEIGHT,
        )
        self._background_color_button.setToolTip(
            self.tr("Choose preview background color")
        )
        self._background_color_button.setAccessibleName(
            self.tr("Choose preview background color")
        )
        self._background_color_button.clicked.connect(
            self._choose_preview_background_color
        )
        self._asset_boundaries_checkbox = QCheckBox(
            self.tr("Show asset boundaries"),
            self._background_controls,
        )
        self._asset_boundaries_checkbox.setFixedHeight(
            BROWSER_TOOLBAR_CONTROL_HEIGHT
        )
        self._asset_boundaries_checkbox.setChecked(False)
        self._asset_boundaries_checkbox.toggled.connect(
            self._on_asset_boundaries_toggled
        )
        self._transparent_index_checkbox = QCheckBox(
            self.tr("Transparent index"),
            self._background_controls,
        )
        self._transparent_index_checkbox.setFixedHeight(
            BROWSER_TOOLBAR_CONTROL_HEIGHT
        )
        self._transparent_index_checkbox.setToolTip(
            self.tr(
                "When checked, the format-defined transparent palette index is transparent; when unchecked, its palette color is shown."
            )
        )
        self._transparent_index_checkbox.setChecked(False)
        self._transparent_index_checkbox.toggled.connect(
            self._on_transparent_index_toggled
        )
        background_layout.addWidget(self._background_label)
        background_layout.addWidget(self._background_combo)
        background_layout.addWidget(self._background_color_button)
        background_layout.addWidget(self._asset_boundaries_checkbox)
        background_layout.addWidget(self._transparent_index_checkbox)
        background_layout.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._background_controls)
        layout.addWidget(self._stack)

        self._animation_timer = QTimer(self)
        self._animation_timer.setInterval(100)
        self._animation_timer.timeout.connect(self._advance_frame)
        self.set_preview_background(
            self._preview_background_mode,
            self._custom_background_color,
        )
        self._background_controls.hide()

    @staticmethod
    def _message_page(text: str) -> QLabel:
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        return label

    def set_preview_background(self, mode: str, custom_color: str) -> None:
        if mode not in {"checkerboard", "dark", "light", "green", "custom"}:
            mode = "checkerboard"
        color = QColor(custom_color)
        if not color.isValid():
            color = QColor("#00a000")
        custom_color = color.name(QColor.NameFormat.HexRgb)
        self._preview_background_mode = mode
        self._custom_background_color = custom_color

        blocker = QSignalBlocker(self._background_combo)
        index = self._background_combo.findData(mode)
        if index >= 0:
            self._background_combo.setCurrentIndex(index)
        del blocker
        self._image_view.setBackgroundBrush(
            _preview_background_brush(mode, custom_color)
        )
        self._voxel_view.set_preview_background(mode, custom_color)
        self._media_canvas.set_preview_background(mode, custom_color)
        self._refresh_background_color_button(color)

    def set_asset_boundaries_visible(self, visible: bool) -> None:
        self._asset_boundaries_visible = bool(visible)
        blocker = QSignalBlocker(self._asset_boundaries_checkbox)
        self._asset_boundaries_checkbox.setChecked(self._asset_boundaries_visible)
        del blocker
        self._voxel_view.set_asset_boundaries_visible(
            self._asset_boundaries_visible
        )
        self._media_canvas.set_asset_boundaries_visible(
            self._asset_boundaries_visible
        )
        self._update_image_boundary_visibility()

    def set_transparent_index_transparent(self, transparent: bool) -> None:
        transparent = bool(transparent)
        if transparent == self._transparent_index_is_transparent:
            return
        self._transparent_index_is_transparent = transparent
        blocker = QSignalBlocker(self._transparent_index_checkbox)
        self._transparent_index_checkbox.setChecked(
            self._transparent_index_is_transparent
        )
        del blocker
        if self._result is not None and self._result.is_shp:
            self._refresh_image()

    def _on_asset_boundaries_toggled(self, visible: bool) -> None:
        self.set_asset_boundaries_visible(visible)
        self.boundary_visibility_preference_changed.emit(bool(visible))

    def _on_transparent_index_toggled(self, transparent: bool) -> None:
        self.set_transparent_index_transparent(transparent)
        self.transparent_index_preference_changed.emit(bool(transparent))

    def _select_preview_background(self, index: int) -> None:
        mode = self._background_combo.itemData(index)
        if not mode:
            return
        if mode == "custom":
            self._choose_preview_background_color()
            return
        self.set_preview_background(mode, self._custom_background_color)
        self.background_preference_changed.emit(
            self._preview_background_mode,
            self._custom_background_color,
        )

    def _choose_preview_background_color(self) -> None:
        selected = QColorDialog.getColor(
            QColor(self._custom_background_color),
            self,
            self.tr("Choose preview background color"),
        )
        if not selected.isValid():
            blocker = QSignalBlocker(self._background_combo)
            index = self._background_combo.findData(self._preview_background_mode)
            if index >= 0:
                self._background_combo.setCurrentIndex(index)
            del blocker
            return
        color = selected.name(QColor.NameFormat.HexRgb)
        self.set_preview_background("custom", color)
        self.background_preference_changed.emit("custom", color)

    def _refresh_background_color_button(self, color: QColor) -> None:
        swatch = QPixmap(18, 18)
        swatch.fill(color)
        painter = QPainter(swatch)
        painter.setPen(QPen(QColor(0, 0, 0, 210), 1))
        painter.drawRect(0, 0, 17, 17)
        painter.end()
        self._background_color_button.setIcon(QIcon(swatch))
        self._background_color_button.setIconSize(QSize(18, 18))

    def _update_background_controls(self) -> None:
        result = self._result
        supported = result is not None and (
            result.kind in {"image", "model"}
            or result.kind == "media"
        )
        has_boundaries = result is not None and (
            result.is_shp
            or result.voxel_model is not None
            or (result.kind == "media" and result.is_video)
        )
        has_transparent_index = bool(
            result is not None
            and result.is_shp
            and result.frames
            and result.palettes
        )
        self._background_controls.setVisible(supported)
        self._asset_boundaries_checkbox.setVisible(has_boundaries)
        self._transparent_index_checkbox.setVisible(has_transparent_index)

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
        self._update_background_controls()
        self._voxel_view.clear_model()
        self._document.show_empty()
        self._dat_model_clear()
        self._stack.setCurrentWidget(self._empty)

    def show_loading(self) -> None:
        self._reset_media()
        self._result = None
        self._update_background_controls()
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
        self._update_background_controls()
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
            if (
                self._supports_animation_playback(result)
                and self._auto_play_animation_for_result(result)
            ):
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
            if auto_play_media:
                if self._media_play.isEnabled():
                    if self._is_active:
                        self._play_media()
                    else:
                        self._resume_media_on_activate = True
                elif self._media_player.has_pending_media:
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
        shp_animations: bool,
        hva_animations: bool,
        audio: bool,
        video: bool,
    ) -> None:
        self._auto_play_shp_animations = shp_animations
        self._auto_play_hva_animations = hva_animations
        self._auto_play_audio = audio
        self._auto_play_video = video
        animation_preference = (
            self._animation_preference_for_result(self._result)
            if self._result is not None
            else None
        )
        animation_enabled = (
            self._auto_play_animation_preference(animation_preference)
            if animation_preference is not None
            else False
        )
        for button, enabled in (
            (self._auto_play_animation_checkbox, animation_enabled),
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
            self._resume_media_on_activate = (
                self._media_is_playing()
                or (
                    self._resume_media_on_activate
                    and self._media_player.has_pending_media
                )
            )
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
            self._resume_media_on_activate = False
            self._play_media()

    def show_document(self, result, encoding: str) -> DecodedDocument:
        return self._document.show_result(result, encoding)

    def prepare_video_surface(self) -> None:
        self._media_player.prepare_video_surface()

    def _prepare_image(self, result: EntryPreviewResult) -> None:
        self._animation_timer.stop()
        self._resume_animation_on_activate = False
        self._frame_index = 0
        self._palette_manually_selected = False
        is_voxel_model = result.voxel_model is not None
        self._image_view.setVisible(not is_voxel_model)
        self._voxel_view.setVisible(is_voxel_model)
        self._voxel_view_mode_combo.setVisible(is_voxel_model)
        image_notices = tuple(
            self.tr(notice)
            for notice in (result.preview_notice, result.message)
            if notice
        )
        self._image_notice.setText("\n".join(image_notices))
        self._image_notice.setVisible(bool(image_notices))
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
            self._zoom_reset_button.setToolTip(self.tr("Reset VXL view to native scale"))
            self._zoom_level_label.setToolTip(self.tr("Current VXL zoom"))
        else:
            self._zoom_reset_button.setToolTip(self.tr("Reset image size and position to 100%"))
            self._zoom_level_label.setToolTip(self.tr("Current image zoom"))
        self._refresh_image()

    def _display_frame_count(self, result: EntryPreviewResult) -> int:
        if result.voxel_model is not None:
            return result.voxel_model.frame_count
        if (
            self._combine_shp_shadow_frames
            and result.is_shp
            and len(result.frames) % 2 == 0
        ):
            return len(result.frames) // 2
        return len(result.frames)

    def _supports_animation_playback(self, result: EntryPreviewResult) -> bool:
        return (
            self._animation_preference_for_result(result) is not None
            and self._display_frame_count(result) > 1
        )

    @staticmethod
    def _animation_preference_for_result(
        result: EntryPreviewResult,
    ) -> str | None:
        if result.is_shp:
            return "shp_animations"
        if result.voxel_model is not None and result.voxel_model.has_hva:
            return "hva_animations"
        return None

    def _auto_play_animation_preference(self, preference: str) -> bool:
        if preference == "hva_animations":
            return self._auto_play_hva_animations
        return self._auto_play_shp_animations

    def _auto_play_animation_for_result(self, result: EntryPreviewResult) -> bool:
        preference = self._animation_preference_for_result(result)
        return (
            preference is not None
            and self._auto_play_animation_preference(preference)
        )

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
        supports_animation_playback = self._supports_animation_playback(result)
        self._frame_label.setVisible(has_multiple_frames)
        self._frame_combo.setVisible(has_multiple_frames)
        self._play_button.setVisible(supports_animation_playback)
        self._auto_play_animation_checkbox.setVisible(supports_animation_playback)
        animation_preference = self._animation_preference_for_result(result)
        if animation_preference is not None:
            if animation_preference == "hva_animations":
                self._auto_play_animation_checkbox.setToolTip(
                    self.tr("Automatically play HVA animations when previewed")
                )
                self._auto_play_animation_checkbox.setAccessibleName(
                    self.tr("Auto-play HVA animations")
                )
            else:
                self._auto_play_animation_checkbox.setToolTip(
                    self.tr("Automatically play SHP animations when previewed")
                )
                self._auto_play_animation_checkbox.setAccessibleName(
                    self.tr("Auto-play SHP animations")
                )
        blocker = QSignalBlocker(self._auto_play_animation_checkbox)
        self._auto_play_animation_checkbox.setChecked(
            animation_preference is not None
            and self._auto_play_animation_preference(animation_preference)
        )
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
        grouped_entries: dict[str, list[tuple[int, str, tuple[str, ...]]]] = {}
        cycle_order: list[int] = []
        seen_palette_indices: set[int] = set()
        palette_display_labels: dict[int, str] = {}
        palette_model_indices: dict[int, QModelIndex] = {}
        selected_item: QStandardItem | None = None
        selected_label = ""
        group_labels = {key: self.tr(label) for key, label in PALETTE_GROUPS}
        use_labels = {key: self.tr(label) for key, label in PALETTE_USE_GROUPS}
        for index, palette in enumerate(result.palettes):
            group = palette.group
            if group == "other" or group not in group_labels:
                group = "game"
            source = palette.source
            if source.startswith("User library: "):
                source = self.tr("User library: {0}").format(source[len("User library: "):])
            elif source.startswith("Game: "):
                source = self.tr("Game: {0}").format(source[len("Game: "):])
            elif source:
                source = self.tr(source)
            palette_name = self.tr("Grayscale") if palette.group == "fallback" else palette.name
            use_categories = tuple(
                category
                for category, _label in PALETTE_USE_GROUPS
                if category != "other" and category in palette.use_categories
            )
            if len(use_categories) > 1:
                palette_name = self.tr("{0} (multiple uses)").format(palette_name)
            label = f"{palette_name} ({source})" if source else palette_name
            palette_display_labels[index] = label
            grouped_entries.setdefault(group, []).append(
                (index, label, use_categories)
            )

        for group, _group_label in PALETTE_GROUPS:
            entries = grouped_entries.get(group)
            if not entries:
                continue
            group_item = QStandardItem(group_labels[group])
            group_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self._palette_model.appendRow(group_item)
            sorted_entries = sorted(
                entries,
                key=lambda entry: (entry[1].casefold(), entry[1]),
            )
            if not self._palette_use_categories_enabled:
                for index, label, _uses in sorted_entries:
                    palette_item = QStandardItem(label)
                    palette_item.setData(index, Qt.ItemDataRole.UserRole)
                    group_item.appendRow(palette_item)
                    palette_model_indices.setdefault(index, palette_item.index())
                    if index not in seen_palette_indices:
                        cycle_order.append(index)
                        seen_palette_indices.add(index)
                    if index == self._palette_index:
                        selected_item = palette_item
                        selected_label = label
                continue

            categorized_entries: dict[str, list[tuple[int, str]]] = {}
            for index, label, uses in sorted_entries:
                categories = uses or ("other",)
                for category in categories:
                    categorized_entries.setdefault(category, []).append(
                        (index, label)
                    )
            for category, _label in PALETTE_USE_GROUPS:
                category_entries = categorized_entries.get(category)
                if not category_entries:
                    continue
                category_item = QStandardItem(use_labels[category])
                category_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                group_item.appendRow(category_item)
                for index, label in category_entries:
                    palette_item = QStandardItem(label)
                    palette_item.setData(index, Qt.ItemDataRole.UserRole)
                    category_item.appendRow(palette_item)
                    palette_model_indices.setdefault(index, palette_item.index())
                    if index not in seen_palette_indices:
                        cycle_order.append(index)
                        seen_palette_indices.add(index)
                    if index == self._palette_index:
                        selected_item = palette_item
                        selected_label = label
        self._palette_cycle_order = cycle_order
        self._palette_display_labels = palette_display_labels
        self._palette_model_indices = palette_model_indices
        self._palette_tree.expandAll()
        if selected_item is not None:
            selected_index = selected_item.index()
            self._palette_tree.setCurrentIndex(selected_index)
            self._palette_tree.selectionModel().select(
                selected_index,
                QItemSelectionModel.SelectionFlag.ClearAndSelect
                | QItemSelectionModel.SelectionFlag.Rows,
            )
            self._palette_tree.scrollTo(
                selected_index,
                QAbstractItemView.ScrollHint.PositionAtCenter,
            )
        self._palette_combo.set_display_text(selected_label)
        self._palette_tree.setMinimumWidth(0)
        self._palette_tree.resizeColumnToContents(0)
        popup_width = (
            self._palette_tree.columnWidth(0)
            + 2 * self._palette_tree.frameWidth()
            + self._palette_tree.verticalScrollBar().sizeHint().width()
            + 12
        )
        self._palette_tree.setMinimumWidth(
            max(self._palette_combo.width(), popup_width)
        )
        del signal_blocker
        has_palette_choice = len(result.palettes) > 0
        self._palette_label.setVisible(has_palette_choice)
        self._palette_combo.setVisible(has_palette_choice)
        self._palette_use_categories_checkbox.setVisible(has_palette_choice)
        self._palette_help_button.setVisible(has_palette_choice)
        self._palette_combo.setEnabled(len(result.palettes) > 1)
        self._image_controls.setVisible(has_frames or has_palette_choice)

    def set_palette_use_categories_enabled(self, enabled: bool) -> None:
        if self._palette_use_categories_enabled == enabled:
            return
        self._palette_use_categories_enabled = enabled
        blocker = QSignalBlocker(self._palette_use_categories_checkbox)
        self._palette_use_categories_checkbox.setChecked(enabled)
        del blocker
        result = self._result
        if result is not None and result.kind in {"image", "model"}:
            self._populate_palette_choices(result, self._palette_index)

    def set_voxel_view_mode(self, mode: str) -> None:
        if mode not in {
            _VoxelModelView._OBLIQUE_VIEW,
            _VoxelModelView._FREE_ROTATION_VIEW,
        }:
            mode = _VoxelModelView._OBLIQUE_VIEW
        blocker = QSignalBlocker(self._voxel_view_mode_combo)
        index = self._voxel_view_mode_combo.findData(mode)
        if index >= 0:
            self._voxel_view_mode_combo.setCurrentIndex(index)
        del blocker
        self._voxel_view.set_view_mode(mode)

    def _select_voxel_view_mode(self, index: int) -> None:
        mode = self._voxel_view_mode_combo.itemData(index)
        if mode not in {
            _VoxelModelView._OBLIQUE_VIEW,
            _VoxelModelView._FREE_ROTATION_VIEW,
        }:
            return
        self._voxel_view.set_view_mode(mode)
        self.voxel_view_mode_preference_changed.emit(mode)

    def _on_palette_use_categories_toggled(self, enabled: bool) -> None:
        self.set_palette_use_categories_enabled(enabled)
        self.palette_use_categories_preference_changed.emit(enabled)

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
        image_notices = tuple(
            self.tr(notice)
            for notice in (result.preview_notice, result.message)
            if notice
        )
        self._image_notice.setText("\n".join(image_notices))
        self._image_notice.setVisible(bool(image_notices))
        self._populate_palette_choices(result, selected_index)
        if result.voxel_model is not None and result.palettes:
            self._voxel_view.set_palette(result.palettes[self._palette_index])
        else:
            self._refresh_image()

    def show_palette_lookup_failure(self) -> None:
        result = self._result
        if result is None or result.kind not in {"image", "model"}:
            return
        notices = [
            self.tr(notice)
            for notice in (result.preview_notice, result.message)
            if notice and notice != "Checking configured game palettes..."
        ]
        notices.append(
            self.tr("Game palettes could not be loaded; the current palette is shown.")
        )
        self._image_notice.setText("\n".join(notices))

    def _show_palette_selection_help(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(self.tr("Palette Selection"))
        dialog.resize(760, 620)
        dialog.setMinimumSize(560, 360)

        def render_stage(stage) -> str:
            detail_arguments = dict(stage.detail_format_arguments)
            details = []
            for index, detail in enumerate(stage.details):
                translated_detail = self.tr(detail)
                arguments = detail_arguments.get(index)
                if arguments is not None:
                    translated_detail = translated_detail.format(*arguments)
                details.append(f"<li>{escape(translated_detail)}</li>")
            return (
                f"<li><b>{escape(self.tr(stage.title))}</b><ul>"
                f"{''.join(details)}</ul></li>"
            )

        stage_items = "".join(
            render_stage(stage) for stage in PALETTE_SELECTION_STAGES
        )
        group_titles = ", ".join(
            f"<code>{escape(self.tr(title))}</code>" for _, title in PALETTE_GROUPS
        )
        use_group_titles = ", ".join(
            f"<code>{escape(self.tr(title))}</code>"
            for _, title in PALETTE_USE_GROUPS
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
            f"<p><b>{escape(self.tr('Use categories, in display order:'))}</b> {use_group_titles}. "
            f"{escape(self.tr('Use categories follow Art references and built-in palette rules; candidates without a recognized use appear under Other or Unclassified.'))} "
            f"{escape(self.tr('A palette with more than one identified use appears in every matching category and is marked as multiple uses.'))}</p>"
        )
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, dialog)
        close_button = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close_button is not None:
            close_button.setText(self.tr("Close"))
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
        empty_frame = False
        if result.is_shp and result.frames:
            frame_count = self._display_frame_count(result)
            if frame_count > 0:
                frame_index = min(max(self._frame_index, 0), frame_count - 1)
                displayed_frames = [result.frames[frame_index]]
                if (
                    self._combine_shp_shadow_frames
                    and len(result.frames) % 2 == 0
                ):
                    displayed_frames.append(
                        result.frames[len(result.frames) // 2 + frame_index]
                    )
                empty_frame = all(frame.is_empty for frame in displayed_frames)
        self._frame_notice.setText(
            self.tr("The selected SHP frame is empty and contains no image data.")
            if empty_frame
            else ""
        )
        self._frame_notice.setVisible(empty_frame)
        if result.voxel_model is not None:
            self._image_boundary.hide()
            self._image_boundary_shadow.hide()
            self._image_view.hide()
            self._voxel_view.set_frame(self._frame_index)
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
                    transparent_zero=self._transparent_index_is_transparent,
                    shadow_mask=True,
                ).convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
                frame_image = indexed_frame_image(
                    frame,
                    palette,
                    transparent_zero=self._transparent_index_is_transparent,
                )
                painter = QPainter(image)
                painter.drawImage(0, 0, frame_image)
                painter.end()
            else:
                image = indexed_frame_image(
                    result.frames[self._frame_index],
                    palette,
                    transparent_zero=self._transparent_index_is_transparent,
                )
        else:
            image = QImage()
        pixmap = QPixmap.fromImage(image) if not image.isNull() else QPixmap()
        self._image_item.setPixmap(pixmap)
        self._image_scene.setSceneRect(self._image_item.boundingRect())
        image_bounds = self._image_item.boundingRect()
        if result.is_shp and not pixmap.isNull():
            boundary = image_bounds.adjusted(0.5, 0.5, -0.5, -0.5)
            self._image_boundary_shadow.setRect(boundary)
            self._image_boundary.setRect(boundary)
        self._update_image_boundary_visibility()

    def _update_image_boundary_visibility(self) -> None:
        result = self._result
        pixmap = self._image_item.pixmap()
        visible = bool(
            self._asset_boundaries_visible
            and result is not None
            and result.is_shp
            and not pixmap.isNull()
        )
        self._image_boundary.setVisible(visible)
        self._image_boundary_shadow.setVisible(visible)

    def _step_image_zoom(
        self,
        steps: float,
        anchor: QPointF | None = None,
    ) -> None:
        zoom = min(
            8.0,
            max(self._MIN_IMAGE_ZOOM, self._image_zoom + steps * 0.1),
        )
        if zoom == self._image_zoom:
            return
        self._apply_image_zoom(zoom, anchor)

    def _apply_image_zoom(
        self,
        zoom: float,
        anchor: QPointF | None = None,
    ) -> None:
        self._default_fit_pending = False
        if self._result is not None and self._result.voxel_model is not None:
            self._voxel_view.set_zoom(zoom)
            self._image_zoom = zoom
            self._sync_image_zoom_controls()
            return
        if anchor is None:
            anchor = QPointF(self._image_view.viewport().rect().center())
        anchor_point = anchor.toPoint()
        image_point = self._image_item.mapFromScene(
            self._image_view.mapToScene(anchor_point)
        )
        scale_factor = zoom / self._image_zoom
        self._image_view.scale(scale_factor, scale_factor)
        mapped_anchor = self._image_view.mapFromScene(
            self._image_item.mapToScene(image_point)
        )
        offset = anchor - QPointF(mapped_anchor)
        scale_x = max(abs(self._image_view.transform().m11()), 0.001)
        scale_y = max(abs(self._image_view.transform().m22()), 0.001)
        self._image_item.moveBy(offset.x() / scale_x, offset.y() / scale_y)
        self._image_zoom = zoom
        self._sync_image_zoom_controls()

    def _zoom_image_at_cursor(self, steps: float, position: QPointF) -> None:
        self._step_image_zoom(steps, position)

    def _reset_image_zoom(self) -> None:
        self._default_fit_pending = False
        self._image_item.setPos(0, 0)
        self._image_scene.setSceneRect(self._image_item.boundingRect())
        self._image_view.resetTransform()
        if self._result is not None and self._result.voxel_model is not None:
            self._voxel_view.reset_view()
            self._image_zoom = self._VXL_DEFAULT_DISPLAY_SCALE
            self._zoom_reset_button.setToolTip(
                self.tr("Reset VXL view to native scale")
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
            self._image_zoom = self._VXL_DEFAULT_DISPLAY_SCALE
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

    def _select_palette(self, index: QModelIndex) -> None:
        palette_index = index.data(Qt.ItemDataRole.UserRole)
        palette_label = index.data(Qt.ItemDataRole.DisplayRole)
        self._apply_palette_choice(
            palette_index,
            str(palette_label or ""),
            close_popup=True,
        )

    def _step_palette(self, step: int) -> None:
        if not self._palette_cycle_order:
            return
        try:
            current_position = self._palette_cycle_order.index(self._palette_index)
        except ValueError:
            current_position = 0
        target_position = min(
            max(current_position + step, 0),
            len(self._palette_cycle_order) - 1,
        )
        if target_position == current_position:
            return
        palette_index = self._palette_cycle_order[target_position]
        self._apply_palette_choice(
            palette_index,
            self._palette_display_labels[palette_index],
            close_popup=False,
        )

    def _apply_palette_choice(
        self,
        palette_index: object,
        palette_label: str,
        *,
        close_popup: bool,
    ) -> None:
        result = self._result
        if (
            result is None
            or not isinstance(palette_index, int)
            or not 0 <= palette_index < len(result.palettes)
        ):
            return
        self._palette_combo.set_display_text(palette_label)
        tree_index = self._palette_model_indices.get(palette_index)
        if tree_index is not None and tree_index.isValid():
            self._palette_tree.setCurrentIndex(tree_index)
            self._palette_tree.selectionModel().select(
                tree_index,
                QItemSelectionModel.SelectionFlag.ClearAndSelect
                | QItemSelectionModel.SelectionFlag.Rows,
            )
            if self._palette_tree.isVisible():
                self._palette_tree.scrollTo(
                    tree_index,
                    QAbstractItemView.ScrollHint.PositionAtCenter,
                )
        if close_popup:
            self._palette_combo.hidePopup()
        self._palette_manually_selected = True
        if palette_index == self._palette_index:
            return
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
        if preference == "animation":
            animation_preference = (
                self._animation_preference_for_result(result)
                if result is not None
                else None
            )
            if animation_preference is None:
                return
            if animation_preference == "hva_animations":
                self._auto_play_hva_animations = enabled
            else:
                self._auto_play_shp_animations = enabled
            if self._supports_animation_playback(result):
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
            preference = animation_preference
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
                and (
                    self._media_play.isEnabled()
                    or self._media_player.has_pending_media
                )
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
        self._media_started = False
        self._media_canvas.set_video_mode(result.is_video)
        self._media_canvas.set_placeholder_text("")
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
            self._media_canvas.set_placeholder_text(self.tr("WAV audio"))
        self._position.setRange(0, 0)
        self._time.setText(self.tr("00:00 / 00:00"))
        self._media_play.setEnabled(False)
        ready = self._media_player.set_media_data(
            result.media_data,
            result.media_suffix or (".bik" if result.is_video else ".wav"),
        )
        self._media_play.setEnabled(ready)
        if ready:
            if result.is_video:
                self._show_video_ready_prompt()
            else:
                self._media_player.hide()
                self._media_canvas.set_placeholder_text(self.tr("WAV audio"))
                self._media_placeholder.show()
        elif self._media_player.has_pending_media:
            self._media_player.hide()
            self._media_canvas.set_placeholder_text(
                self.tr("Preparing media playback...")
            )
            self._media_placeholder.show()

    def _show_video_ready_prompt(self) -> None:
        self._media_player.hide()
        self._media_canvas.set_placeholder_text(
            self.tr("Click Play to start the video preview.")
        )
        self._media_placeholder.show()

    def _reset_media(self) -> None:
        self._animation_timer.stop()
        self._media_canvas.set_video_mode(False)
        self._auto_play_audio_checkbox.hide()
        self._auto_play_video_checkbox.hide()
        self._default_fit_pending = False
        self._resume_animation_on_activate = False
        self._resume_media_on_activate = False
        self._media_started = False
        self._media_play.setEnabled(False)
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
        if self._media_player.has_pending_media:
            self._resume_media_on_activate = True
            return
        if not self._media_play.isEnabled():
            return
        result = self._result
        if result is not None and result.is_video:
            self._media_started = True
            self._media_placeholder.hide()
            self._media_player.show()
        self._media_player.play()

    def _pause_media(self) -> None:
        self._media_player.pause()

    def _sync_vlc_media_controls(self, playing: bool) -> None:
        self._media_play.setText(
            self.tr("Pause") if playing else self.tr("Play")
        )

    def _on_media_ready_changed(self, ready: bool) -> None:
        self._media_play.setEnabled(ready)
        if not ready:
            return
        result = self._result
        if result is None or result.kind != "media":
            return
        if result.is_video:
            if self._media_started:
                self._media_player.show()
                self._media_placeholder.hide()
            else:
                self._show_video_ready_prompt()
        else:
            self._media_player.hide()
            self._media_canvas.set_placeholder_text(self.tr("WAV audio"))
            self._media_placeholder.show()
        if self._resume_media_on_activate and self._is_active:
            self._resume_media_on_activate = False
            self._play_media()

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
        self._media_started = False
        self._media_play.setEnabled(False)
        self._resume_media_on_activate = False
        self._media_player.hide()
        self._media_canvas.set_placeholder_text(message)
        self._media_placeholder.setVisible(True)
