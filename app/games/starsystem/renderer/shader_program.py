from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


SHADER_DIR = Path(__file__).resolve().parent / "shaders"
INCLUDE_RE = re.compile(r'^\s*#include\s+"([^"]+)"\s*$', re.MULTILINE)


class ShaderSourceError(RuntimeError):
    pass


def load_shader_source(name: str, seen: set[Path] | None = None) -> str:
    path = (SHADER_DIR / name).resolve()
    if not path.is_file():
        raise ShaderSourceError(f"셰이더 파일을 찾을 수 없습니다: {name}")

    seen = seen or set()
    if path in seen:
        chain = " -> ".join(item.name for item in seen)
        raise ShaderSourceError(f"순환 include 감지: {chain} -> {path.name}")

    seen.add(path)
    source = path.read_text(encoding="utf-8")

    def replace(match: re.Match[str]) -> str:
        include_name = match.group(1)
        return load_shader_source(include_name, set(seen))

    return INCLUDE_RE.sub(replace, source)


@dataclass
class ShaderProgram:
    vertex_name: str
    fragment_name: str
    program: int | None = None

    def compile(self) -> int:
        from OpenGL import GL

        vertex = _compile_shader(GL.GL_VERTEX_SHADER, load_shader_source(self.vertex_name))
        fragment = _compile_shader(GL.GL_FRAGMENT_SHADER, load_shader_source(self.fragment_name))
        program = GL.glCreateProgram()
        GL.glAttachShader(program, vertex)
        GL.glAttachShader(program, fragment)
        GL.glLinkProgram(program)
        ok = GL.glGetProgramiv(program, GL.GL_LINK_STATUS)
        GL.glDeleteShader(vertex)
        GL.glDeleteShader(fragment)
        if not ok:
            log = GL.glGetProgramInfoLog(program).decode("utf-8", errors="replace")
            GL.glDeleteProgram(program)
            raise ShaderSourceError(f"셰이더 링크 실패: {self.vertex_name} + {self.fragment_name}\n{log}")
        self.program = program
        return program

    def use(self) -> None:
        from OpenGL import GL

        if self.program is None:
            self.compile()
        GL.glUseProgram(self.program)

    def delete(self) -> None:
        from OpenGL import GL

        if self.program is not None:
            GL.glDeleteProgram(self.program)
            self.program = None


def _compile_shader(shader_type: int, source: str) -> int:
    from OpenGL import GL

    shader = GL.glCreateShader(shader_type)
    GL.glShaderSource(shader, source)
    GL.glCompileShader(shader)
    ok = GL.glGetShaderiv(shader, GL.GL_COMPILE_STATUS)
    if not ok:
        log = GL.glGetShaderInfoLog(shader).decode("utf-8", errors="replace")
        GL.glDeleteShader(shader)
        raise ShaderSourceError(f"셰이더 컴파일 실패\n{log}")
    return shader
