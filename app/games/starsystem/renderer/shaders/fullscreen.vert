#version 120

varying vec2 v_uv;

void main() {
    v_uv = gl_MultiTexCoord0.xy;
    gl_Position = gl_Vertex;
}
