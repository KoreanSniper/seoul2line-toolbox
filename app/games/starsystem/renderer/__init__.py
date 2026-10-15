"""Renderer building blocks for the star system sandbox."""

from .shader_program import ShaderProgram, ShaderSourceError, load_shader_source

__all__ = ["ShaderProgram", "ShaderSourceError", "load_shader_source"]
