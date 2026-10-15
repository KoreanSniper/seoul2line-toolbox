#version 120
varying vec2 v_uv;

uniform vec2 u_resolution;
uniform vec2 u_camera;
uniform float u_zoom;
uniform vec2 u_blackHole;
uniform float u_blackHoleMass;
uniform float u_eventRadius;
uniform float u_lensPower;
uniform float u_showGrid;
uniform float u_gridStep;
uniform float u_gridAlpha;
uniform int u_warpCount;
uniform vec2 u_warpPositions[32];
uniform float u_warpMasses[32];
uniform float u_warpRadii[32];
uniform float u_time;

#include "tonemap.glsl"
#include "blackhole.glsl"

float hash21(vec2 p) {
    p = fract(p * vec2(123.34, 456.21));
    p += dot(p, p + 45.32);
    return fract(p.x * p.y);
}

vec3 sampleSky(vec2 worldPos) {
    float cellSize = 96.0;
    vec2 cell = floor(worldPos / cellSize);
    vec2 local = fract(worldPos / cellSize);
    float h = hash21(cell);
    vec2 starPos = vec2(hash21(cell + 11.7), hash21(cell + 29.3));
    float pixelRadius = mix(0.006, 0.018, hash21(cell + 53.1)) / max(u_zoom, 0.35);
    float d = length(local - starPos);
    float star = (1.0 - smoothstep(pixelRadius * 0.25, pixelRadius, d)) * step(0.945, h);
    float glow = (1.0 - smoothstep(pixelRadius, pixelRadius * 4.8, d)) * step(0.985, h);
    vec3 base = vec3(0.014, 0.021, 0.038);
    vec3 starColor = mix(vec3(0.45, 0.58, 1.0), vec3(1.0, 0.82, 0.55), hash21(cell + 4.2));
    return base + starColor * (star * 2.4 + glow * 0.55);
}

vec2 warpGridPoint(vec2 worldPos) {
    vec2 warped = worldPos;
    for (int i = 0; i < 32; i++) {
        if (i >= u_warpCount) {
            break;
        }
        vec2 delta = worldPos - u_warpPositions[i];
        float r2 = dot(delta, delta) + 800.0;
        float dist = sqrt(r2);
        float pressure = max(u_warpMasses[i], u_warpRadii[i] * u_warpRadii[i] * 12.0);
        float push = min(30.0, pressure / r2 * 24.0) * u_lensPower;
        warped += delta / dist * push;
    }
    return warped;
}

float gridMask(vec2 worldPos) {
    if (u_showGrid < 0.5) {
        return 0.0;
    }
    vec2 warped = warpGridPoint(worldPos);
    vec2 grid = abs(fract(warped / max(u_gridStep, 1.0) - 0.5) - 0.5) / fwidth(warped / max(u_gridStep, 1.0));
    float line = 1.0 - min(min(grid.x, grid.y), 1.0);
    float axisX = 1.0 - smoothstep(0.0, 1.6 / max(u_zoom, 0.001), abs(warped.y));
    float axisY = 1.0 - smoothstep(0.0, 1.6 / max(u_zoom, 0.001), abs(warped.x));
    return max(line * u_gridAlpha * 0.44, max(axisX, axisY) * u_gridAlpha * 0.34);
}

void main() {
    vec2 screen = (v_uv - 0.5) * u_resolution;
    vec2 world = u_camera + vec2(screen.x, -screen.y) / max(u_zoom, 0.001);
    vec2 toHole = u_blackHole - world;
    float dist = length(toHole);
    float eventMask = eventHorizonMask(dist, u_eventRadius);

    vec2 rayDir = normalize(vec2(screen.x, -screen.y + 0.0001));
    vec2 traced = traceBentPhoton(world, rayDir, u_blackHole, u_blackHoleMass * u_lensPower * 0.000003, 24.0 / max(u_zoom, 0.2), 42);
    vec3 sky = sampleSky(traced);

    vec2 diskLocal = world - u_blackHole;
    diskLocal.y *= 3.3;
    float diskRadius = length(diskLocal) / max(u_eventRadius * 4.8, 1.0);
    float diskAngle = atan(diskLocal.y, diskLocal.x) + u_time * 0.35;
    vec3 disk = accretionDiskColor(diskRadius, diskAngle, u_lensPower);

    float grid = gridMask(world);
    vec3 gridColor = mix(vec3(0.05, 0.09, 0.15), vec3(0.10, 0.25, 0.28), grid);
    vec3 color = sky + disk + gridColor * grid;
    color = mix(color, vec3(0.0), eventMask);
    gl_FragColor = vec4(exposureToneMap(color, 1.0), 1.0);
}
