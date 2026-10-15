#ifndef S2_BLOOM_GLSL
#define S2_BLOOM_GLSL

vec3 extractBloom(vec3 hdrColor, float threshold) {
    float brightness = max(max(hdrColor.r, hdrColor.g), hdrColor.b);
    float amount = smoothstep(threshold, threshold * 1.6, brightness);
    return hdrColor * amount;
}

vec3 combineBloom(vec3 hdrColor, vec3 bloomColor, float strength) {
    return hdrColor + bloomColor * max(strength, 0.0);
}

#endif
