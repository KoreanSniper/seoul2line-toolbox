#version 120

varying vec2 v_uv;

uniform float u_time;
uniform vec2 u_center;
uniform vec2 u_resolution;
uniform float u_active;
uniform float u_strength;
uniform float u_worldScale;
uniform float u_angle;
uniform vec3 u_color;

float hash21(vec2 p) {
    p = fract(p * vec2(234.34, 435.31));
    p += dot(p, p + 31.47);
    return fract(p.x * p.y);
}

float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    float a = hash21(i);
    float b = hash21(i + vec2(1.0, 0.0));
    float c = hash21(i + vec2(0.0, 1.0));
    float d = hash21(i + vec2(1.0, 1.0));
    return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}

void main() {
    if (u_active < 0.5) {
        gl_FragColor = vec4(0.0);
        return;
    }

    vec2 p = v_uv - u_center;
    p.x *= u_resolution.x / max(u_resolution.y, 1.0);

    float d = length(p);
    float angle = atan(p.y, p.x);
    float facing = cos(angle - u_angle);
    float t = clamp(u_time, 0.0, 1.0);
    float expansion = pow(t, 0.55);
    float energy = max(u_strength, 0.1);
    float n = noise(p * 56.0 + vec2(t * 8.0, -t * 5.0));
    float directional = 0.72 + max(facing, 0.0) * 0.52 + n * 0.20;
    float worldRadius = 5.0 + expansion * (28.0 + energy * 8.0);
    float radius = worldRadius * u_worldScale * directional;

    float core = 1.0 - smoothstep(radius * 0.03, radius * 0.18, d);
    float hotShell = (1.0 - smoothstep(radius * 0.14, radius * 0.72, d)) * (0.74 + n * 0.42);
    float vapor = (1.0 - smoothstep(radius * 0.34, radius * 1.35, d)) * smoothstep(0.02, 0.65, t);
    float shock = 1.0 - smoothstep(0.0, 0.004 + t * 0.009, abs(d - radius * 1.08));
    float debris = step(0.82, noise(normalize(p + vec2(0.0001)) * 19.0 + t * 3.0)) * (1.0 - smoothstep(radius * 0.55, radius * 1.35, d));
    float plume = smoothstep(-0.35, 0.95, facing) * (1.0 - smoothstep(radius * 0.22, radius * 1.45, d));

    float flash = exp(-t * 7.0);
    float fade = pow(max(1.0 - t, 0.0), 1.55);
    float flicker = 0.94 + sin(t * 82.0) * 0.045 + sin(t * 139.0) * 0.025;

    vec3 white = vec3(8.0, 7.5, 6.4);
    vec3 yellow = mix(vec3(5.2, 3.3, 0.34), u_color * 4.2, 0.28);
    vec3 orange = mix(vec3(4.6, 0.92, 0.08), u_color * 2.5, 0.34);
    vec3 dust = mix(vec3(0.42, 0.30, 0.22), u_color * 0.75, 0.45);

    vec3 color = vec3(0.0);
    color += dust * vapor * 1.25;
    color += orange * hotShell * 1.1;
    color += yellow * hotShell * 1.55;
    color += white * core * (1.8 + flash * 3.5);
    color += dust * plume * 0.95;
    color += mix(yellow, dust, t) * shock * 1.25;
    color += yellow * debris * fade * 1.8;
    color *= fade * flicker;

    float alpha = max(max(core, hotShell), max(vapor, max(shock, debris)));
    gl_FragColor = vec4(color, clamp(alpha * fade, 0.0, 1.0));
}
