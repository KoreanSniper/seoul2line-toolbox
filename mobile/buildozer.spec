[app]
title = S2 Toolbox
package.name = s2toolbox
package.domain = io.seoul2line
source.dir = .
source.include_exts = py,png,ttf,txt
source.exclude_dirs = tests,local_data,bin,.buildozer,__pycache__
version = 0.1.0
requirements = python3,kivy==2.3.1
orientation = portrait
fullscreen = 0
icon.filename = %(source.dir)s/assets/toolbox-logo.png
android.api = 35
android.minapi = 26
android.archs = arm64-v8a
android.accept_sdk_license = False

[buildozer]
log_level = 2
warn_on_root = 1
