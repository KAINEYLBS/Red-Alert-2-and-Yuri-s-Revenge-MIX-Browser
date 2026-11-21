from __future__ import annotations

import logging

from PySide6.QtCore import QObject
from PySide6.QtGui import (
    QOffscreenSurface,
    QOpenGLContext,
    QOpenGLFunctions,
    QSurfaceFormat,
)
from PySide6.QtOpenGL import QOpenGLShader, QOpenGLShaderProgram

logger = logging.getLogger(__name__)

_VERTEX_SHADER = """#version 120
attribute vec3 aPosition;
attribute vec3 aNormal;
attribute float aColor;
uniform mat4 uMvp;
uniform mat4 uPart;
uniform mat3 uNormalMatrix;
varying vec3 vNormal;
varying float vColorIndex;
void main() {
    gl_Position = uMvp * uPart * vec4(aPosition, 1.0);
    vNormal = normalize(uNormalMatrix * aNormal);
    vColorIndex = aColor;
}
"""
_FRAGMENT_SHADER = """#version 120
varying vec3 vNormal;
varying float vColorIndex;
uniform sampler1D uPalette;
void main() {
    vec3 lightDirection = normalize(vec3(-0.35, -0.45, 0.82));
    float light = 0.32 + 0.68 * max(dot(normalize(vNormal), lightDirection), 0.0);
    vec3 color = texture1D(uPalette, (vColorIndex + 0.5) / 256.0).rgb;
    gl_FragColor = vec4(color * light, 1.0);
}
"""


def create_voxel_shader_program(
    parent: QObject,
) -> QOpenGLShaderProgram | None:
    program = QOpenGLShaderProgram(parent)
    if not program.addShaderFromSourceCode(
        QOpenGLShader.ShaderTypeBit.Vertex,
        _VERTEX_SHADER,
    ):
        return _discard_shader_program(program)
    if not program.addShaderFromSourceCode(
        QOpenGLShader.ShaderTypeBit.Fragment,
        _FRAGMENT_SHADER,
    ):
        return _discard_shader_program(program)
    if not program.link():
        return _discard_shader_program(program)
    return program


def _discard_shader_program(
    program: QOpenGLShaderProgram,
) -> None:
    logger.error("VXL renderer shader setup failed: %s", program.log())
    program.setParent(None)
    del program
    return None


# @arch mix-browser.voxel-renderer-resources service | en: Initializes and retains shared OpenGL resources for voxel previews | zh: 初始化并保留体素预览共用的 OpenGL 资源
class VoxelRendererResources(QObject):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._surface: QOffscreenSurface | None = None
        self._context: QOpenGLContext | None = None
        self._program: QOpenGLShaderProgram | None = None
        self._error = ""

    @property
    def initialized(self) -> bool:
        return (
            self._surface is not None
            and self._surface.isValid()
            and self._context is not None
            and self._context.isValid()
            and self._program is not None
            and self._program.isLinked()
        )

    def initialize(self) -> bool:
        if self.initialized:
            return True
        self._error = ""
        previous_context = QOpenGLContext.currentContext()
        previous_surface = (
            previous_context.surface() if previous_context is not None else None
        )
        surface = QOffscreenSurface()
        surface.setFormat(QSurfaceFormat.defaultFormat())
        surface.create()
        if not surface.isValid():
            self._error = "The offscreen OpenGL surface could not be created."
            logger.error("VXL renderer initialization failed: %s", self._error)
            return False

        context = QOpenGLContext()
        context.setFormat(surface.format())
        global_context = QOpenGLContext.globalShareContext()
        if global_context is not None:
            context.setShareContext(global_context)
        if not context.create():
            self._error = "The shared OpenGL context could not be created."
            logger.error("VXL renderer initialization failed: %s", self._error)
            surface.destroy()
            return False

        program: QOpenGLShaderProgram | None = None
        try:
            if not context.makeCurrent(surface):
                self._error = "The shared OpenGL context could not be made current."
                return False
            functions: QOpenGLFunctions = context.functions()
            functions.initializeOpenGLFunctions()
            program = create_voxel_shader_program(self)
            if program is None:
                self._error = "The shared voxel shader program could not be linked."
                return False

            surface.setParent(self)
            context.setParent(self)
            self._surface = surface
            self._context = context
            self._program = program
            return True
        except RuntimeError as error:
            self._error = str(error)
            logger.exception("VXL renderer initialization failed")
            return False
        finally:
            if QOpenGLContext.currentContext() is context:
                context.doneCurrent()
            if (
                previous_context is not None
                and previous_surface is not None
                and previous_context.isValid()
            ):
                previous_context.makeCurrent(previous_surface)
            if not self.initialized:
                if program is not None:
                    program.removeAllShaders()
                    program.setParent(None)
                    del program
                if context.isValid():
                    context.setParent(None)
                surface.setParent(None)
                surface.destroy()
                logger.error("VXL renderer initialization failed: %s", self._error)

    def program_for_context(
        self,
        context: QOpenGLContext,
    ) -> QOpenGLShaderProgram | None:
        if not self.initialized and not self.initialize():
            return None
        if self._context is None or not QOpenGLContext.areSharing(
            context,
            self._context,
        ):
            self._error = (
                "The preview OpenGL context does not share the initialized renderer."
            )
            logger.error("VXL renderer initialization failed: %s", self._error)
            return None
        self._error = ""
        return self._program
