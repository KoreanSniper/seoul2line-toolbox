#version 120

varying vec2 v_uv;

uniform sampler2D u_hdr;
uniform sampler2D u_bloom;
uniform float u_exposure;
uniform float u_bloomStrength;

#include "tonemap.glsl"
#include "bloom.glsl"

void main() {
    vec3 hdr = texture(u_hdr, v_uv).rgb;
    vec3 bloom = texture(u_bloom, v_uv).rgb;
    vec3 mapped = exposureToneMap(combineBloom(hdr, bloom, u_bloomStrength), u_exposure);
    gl_FragColor = vec4(gammaCorrect(mapped), 1.0);
}
