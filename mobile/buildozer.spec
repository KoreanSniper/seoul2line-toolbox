[app]
title = S2 Toolbox
package.name = s2toolbox
package.domain = io.seoul2line
source.dir = .
source.include_exts = py,png,ttf,txt
source.exclude_dirs = tests,local_data,bin,.buildozer,__pycache__,build_scripts
version = 0.1.0
requirements = python3,kivy==2.3.1,pyjnius
orientation = portrait
fullscreen = 0
icon.filename = %(source.dir)s/assets/toolbox-logo.png
android.api = 35
android.minapi = 26
android.archs = arm64-v8a
android.ndk = 28c
android.ndk_api = 26
android.accept_sdk_license = False
android.add_src = android_src
android.extra_manifest_xml = android/manifest-extra.xml
p4a.commit = 58d21141f17c889bf8585f5665921d72028f8831

[buildozer]
log_level = 2
warn_on_root = 1
