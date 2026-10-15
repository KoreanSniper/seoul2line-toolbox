#ifndef S2_TONEMAP_GLSL
#define S2_TONEMAP_GLSL

vec3 acesToneMap(vec3 color) {
    const float a = 2.51;
    const float b = 0.03;
    const float c = 2.43;
    const float d = 0.59;
    const float e = 0.14;
    return clamp((color * (a * color + b)) / (color * (c * color + d) + e), 0.0, 1.0);
}

vec3 exposureToneMap(vec3 hdrColor, float exposure) {
    vec3 exposed = max(hdrColor, vec3(0.0)) * max(exposure, 0.0);
    return acesToneMap(exposed);
}

vec3 gammaCorrect(vec3 color) {
    return pow(max(color, vec3(0.0)), vec3(1.0 / 2.2));
}

#endif
