"""Resolution-independent gradients and line icons for the desktop shell."""
from __future__ import annotations

import math
import tkinter as tk

from PIL import Image, ImageDraw, ImageTk
import numpy as np


TOOL_ICONS = {
    'home.overview': 'grid', 'home.system_monitor': 'monitor',
    'gaming.launchers': 'play', 'gaming.music': 'music', 'gaming.workspace_presets': 'briefcase',
    'developer.minecraft_commands': 'cube', 'developer.code_editor': 'code',
    'developer.git': 'git', 'developer.terminal': 'terminal',
    'developer.utilities': 'convert', 'developer.scratchpad': 'notebook',
    'network.status': 'network', 'network.lan_remote': 'lan',
    'files.manager': 'folder', 'files.converter': 'convert', 'files.cursor_editor': 'cursor',
    'files.clipboard_history': 'clipboard', 'files.diff': 'diff',
    'files.process_manager': 'process', 'files.screenshot': 'crop',
    'automation.editor': 'workflow', 'automation.history': 'history', 'automation.manager': 'list',
    'minigame.hub': 'game', 'minigame.starsystem_gpu': 'orbit', 'minigame.trsim': 'train',
    'minigame.factory': 'factory', 'minigame.korean_stocks': 'stocks',
    'minigame.micro_warfare': 'tank', 'minigame.orbit_lab': 'rocket',
    'settings.preferences': 'palette', 'settings.paths': 'path', 'settings.hotkeys': 'keyboard',
    'settings.plugins': 'puzzle', 'settings.updates': 'download', 'example_plugin.demo': 'puzzle',
}


def tool_icon(tool_id):
    return TOOL_ICONS.get(tool_id, 'puzzle')


def blend(first: str, second: str, amount: float) -> str:
    a, b = tuple(bytes.fromhex(first[1:])), tuple(bytes.fromhex(second[1:]))
    return '#' + ''.join(f'{round(x + (y - x) * amount):02x}' for x, y in zip(a, b))


def gradient_image(master, width, height, first, last, *, radius=0, border=None,
                   glow=None, stripes=False, horizontal=False, backing=None):
    """Render at a bounded working size, then scale smoothly for large windows."""
    width, height = max(2, int(width)), max(2, int(height))
    scale = min(1, 720 / max(width, height))
    w, h = max(2, round(width * scale)), max(2, round(height * scale))
    start, end = (np.array(tuple(bytes.fromhex(color[1:])), dtype=float) for color in (first, last))
    yy, xx = np.mgrid[0:h, 0:w]
    fraction = (xx / max(1, w - 1) if horizontal else
                .28 * xx / max(1, w - 1) + .72 * yy / max(1, h - 1))[..., None]
    pixels = start + (end - start) * fraction
    if glow:
        hot = np.array(tuple(bytes.fromhex(glow[1:])))
        light = np.maximum(0, 1 - np.hypot((w - xx) / w, yy / h) * 1.6)[..., None] * .75
        pixels = pixels * (1 - light) + hot * light
    image = Image.fromarray(np.round(pixels).astype('uint8'))
    if stripes:
        overlay = Image.new('RGBA', (w, h))
        draw = ImageDraw.Draw(overlay)
        for x in (int(w * .72), int(w * .86), int(w * 1.01)):
            draw.polygon([(x, 0), (x + w * .07, 0), (x - h * .22, h * .3),
                          (x - h * .22 - w * .07, h * .3)], fill=(110, 100, 60, 12))
        draw.polygon([(0, h), (w * .12, h * .78), (w * .21, h), (w, h * .8), (w, h)],
                     fill=(150, 120, 70, 5))
        image = Image.alpha_composite(image.convert('RGBA'), overlay)
    if (w, h) != (width, height):
        image = image.resize((width, height), Image.Resampling.BILINEAR)
    image = image.convert('RGBA')
    mask = Image.new('L', image.size)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, width - 1, height - 1), radius=radius, fill=255)
    image.putalpha(mask)
    if border:
        ImageDraw.Draw(image).rounded_rectangle((0, 0, width - 1, height - 1),
                                               radius=radius, outline=border, width=1)
    if backing is not None:
        # Match the exact parent pixels behind rounded embedded Canvas widgets.
        background = backing.convert('RGBA').resize(image.size)
        background.alpha_composite(image)
        image = background
    result = ImageTk.PhotoImage(image, master=master)
    result.source_image = image
    return result


def icon(canvas, name, x, y, size, color, *, width=2, tags='icon'):
    """Draw a small consistent icon without relying on installed symbol fonts."""
    def line(*points):
        canvas.create_line(*[value for a, b in zip(points[::2], points[1::2])
                             for value in (x + a * size, y + b * size)],
                           fill=color, width=width, capstyle='round', joinstyle='round', tags=tags)

    def rect(a, b, c, d):
        canvas.create_rectangle(x + a * size, y + b * size, x + c * size, y + d * size,
                                outline=color, width=width, tags=tags)

    def oval(a, b, c, d):
        canvas.create_oval(x + a * size, y + b * size, x + c * size, y + d * size,
                          outline=color, width=width, tags=tags)

    if name == 'search':
        oval(.12, .08, .7, .66)
        line(.65, .63, .91, .91)
    elif name == 'monitor':
        rect(.08, .12, .92, .7)
        line(.5, .7, .5, .9, .3, .9, .7, .9)
    elif name == 'home':
        line(.08, .45, .5, .08, .92, .45)
        line(.2, .36, .2, .9, .42, .9, .42, .6, .62, .6, .62, .9, .8, .9, .8, .36)
    elif name == 'network':
        oval(.08, .08, .92, .92)
        oval(.32, .08, .68, .92)
        line(.08, .5, .92, .5)
        line(.18, .27, .82, .27)
        line(.18, .73, .82, .73)
    elif name == 'folder':
        line(.08, .27, .08, .85, .92, .85, .92, .3, .49, .3, .39, .15, .08, .15, .08, .27, .92, .27)
    elif name == 'briefcase':
        rect(.1, .32, .9, .86)
        line(.32, .32, .32, .13, .68, .13, .68, .32)
        line(.1, .51, .9, .51)
        line(.5, .44, .5, .65)
    elif name == 'grid':
        for a, b in ((.1, .1), (.57, .1), (.1, .57), (.57, .57)):
            rect(a, b, a + .3, b + .3)
    elif name == 'chart':
        line(.08, .9, .94, .9)
        for a, b in ((.25, .5), (.5, .16), (.75, .35)):
            line(a, .9, a, b)
    elif name == 'game':
        line(.2, .25, .8, .25, .95, .7, .85, .87, .65, .65, .35, .65, .15, .87, .05, .7, .2, .25)
        line(.22, .42, .22, .62)
        line(.12, .52, .32, .52)
        oval(.66, .42, .7, .46)
        oval(.79, .54, .83, .58)
    elif name == 'power':
        canvas.create_arc(x + size * .1, y + size * .1, x + size * .9, y + size * .9,
                          start=55, extent=250, style='arc', outline=color, width=width, tags=tags)
        line(.5, .02, .5, .48)
    elif name == 'play':
        line(.28, .12, .86, .5, .28, .88, .28, .12)
    elif name == 'music':
        line(.4, .72, .4, .2, .86, .1, .86, .62)
        line(.4, .34, .86, .24)
        oval(.12, .66, .4, .88)
        oval(.58, .56, .86, .78)
    elif name == 'cube':
        line(.5, .06, .9, .28, .9, .74, .5, .96, .1, .74, .1, .28, .5, .06)
        line(.1, .28, .5, .52, .9, .28)
        line(.5, .52, .5, .96)
    elif name in ('code', 'terminal'):
        if name == 'terminal':
            rect(.06, .14, .94, .86)
            line(.2, .36, .36, .5, .2, .64)
            line(.49, .65, .77, .65)
        else:
            line(.3, .22, .06, .5, .3, .78)
            line(.7, .22, .94, .5, .7, .78)
            line(.6, .1, .4, .9)
    elif name == 'git':
        oval(.16, .08, .36, .28)
        oval(.16, .72, .36, .92)
        oval(.66, .12, .86, .32)
        line(.26, .28, .26, .72)
        line(.76, .32, .76, .48, .26, .65)
    elif name == 'notebook':
        rect(.2, .08, .86, .92)
        for yy in (.28, .48, .68):
            line(.1, yy, .29, yy)
        line(.4, .32, .7, .32)
        line(.4, .52, .7, .52)
    elif name == 'convert':
        line(.14, .3, .86, .3, .68, .12)
        line(.86, .3, .68, .48)
        line(.86, .7, .14, .7, .32, .52)
        line(.14, .7, .32, .88)
    elif name == 'lan':
        rect(.35, .05, .65, .31)
        line(.5, .31, .5, .55)
        line(.2, .69, .2, .55, .8, .55, .8, .69)
        rect(.05, .69, .35, .93)
        rect(.65, .69, .95, .93)
    elif name == 'cursor':
        line(.18, .07, .21, .86, .41, .65, .58, .96, .74, .87, .56, .56, .85, .54, .18, .07)
    elif name == 'clipboard':
        line(.32, .16, .14, .16, .14, .93, .86, .93, .86, .16, .68, .16)
        rect(.32, .06, .68, .28)
        line(.32, .48, .68, .48)
        line(.32, .67, .59, .67)
    elif name == 'diff':
        rect(.06, .12, .4, .88)
        rect(.6, .12, .94, .88)
        line(.13, .4, .33, .4)
        line(.67, .4, .87, .4)
        line(.77, .3, .77, .5)
    elif name == 'process':
        rect(.24, .24, .76, .76)
        rect(.4, .4, .6, .6)
        for value in (.34, .66):
            line(value, .07, value, .24)
            line(value, .76, value, .93)
            line(.07, value, .24, value)
            line(.76, value, .93, value)
    elif name == 'crop':
        line(.2, .05, .2, .8, .95, .8)
        line(.05, .2, .8, .2, .8, .95)
    elif name == 'workflow':
        rect(.06, .37, .32, .63)
        rect(.68, .06, .94, .32)
        rect(.68, .68, .94, .94)
        line(.32, .5, .5, .5, .5, .19, .68, .19)
        line(.5, .5, .5, .81, .68, .81)
    elif name == 'history':
        canvas.create_arc(x + .12 * size, y + .1 * size, x + .9 * size, y + .9 * size,
                          start=145, extent=-300, style='arc', outline=color, width=width, tags=tags)
        line(.06, .12, .06, .4, .34, .4)
        line(.5, .27, .5, .52, .68, .63)
    elif name == 'list':
        for yy in (.2, .5, .8):
            rect(.1, yy - .06, .22, yy + .06)
            line(.38, yy, .9, yy)
    elif name == 'train':
        rect(.2, .08, .8, .76)
        rect(.3, .2, .7, .44)
        oval(.3, .58, .36, .64)
        oval(.64, .58, .7, .64)
        line(.33, .76, .16, .94)
        line(.67, .76, .84, .94)
        line(.25, .85, .75, .85)
    elif name == 'factory':
        line(.08, .9, .08, .45, .34, .28, .34, .48, .6, .3, .6, .9, .08, .9)
        line(.72, .9, .72, .1, .9, .1, .9, .9, .6, .9)
        line(.2, .66, .2, .76)
        line(.42, .66, .42, .76)
    elif name == 'stocks':
        for xx, a, b in ((.2, .45, .8), (.5, .24, .66), (.8, .12, .43)):
            line(xx, a - .1, xx, b + .1)
            rect(xx - .08, a, xx + .08, b)
    elif name == 'orbit':
        oval(.08, .32, .92, .68)
        oval(.32, .08, .68, .92)
        oval(.39, .39, .61, .61)
        oval(.77, .29, .91, .43)
    elif name == 'rocket':
        line(.32, .64, .36, .27, .5, .05, .64, .27, .68, .64, .32, .64)
        line(.32, .42, .12, .67, .12, .8, .32, .7)
        line(.68, .42, .88, .67, .88, .8, .68, .7)
        oval(.44, .26, .56, .38)
        line(.4, .76, .5, .96, .6, .76)
    elif name == 'tank':
        oval(.06, .59, .94, .91)
        rect(.25, .35, .65, .59)
        line(.65, .42, .94, .26)
        for xx in (.24, .5, .76):
            oval(xx - .06, .68, xx + .06, .8)
    elif name == 'palette':
        oval(.06, .06, .94, .94)
        for a, b in ((.27, .25), (.54, .18), (.72, .4)):
            oval(a - .055, b - .055, a + .055, b + .055)
        oval(.38, .62, .58, .82)
    elif name == 'path':
        rect(.07, .1, .33, .36)
        rect(.67, .64, .93, .9)
        line(.33, .23, .76, .23, .76, .48, .23, .48, .23, .77, .67, .77)
    elif name == 'keyboard':
        rect(.04, .2, .96, .8)
        for yy in (.37, .53):
            for xx in (.2, .4, .6, .8):
                line(xx - .03, yy, xx + .03, yy)
        line(.32, .68, .68, .68)
    elif name == 'puzzle':
        line(.08, .25, .35, .25)
        canvas.create_arc(x + .35 * size, y + .05 * size, x + .65 * size, y + .45 * size,
                          start=0, extent=180, style='arc', outline=color, width=width, tags=tags)
        line(.65, .25, .92, .25, .92, .55, .75, .55, .75, .75, .92, .75, .92, .92, .08, .92, .08, .25)
    elif name == 'download':
        line(.5, .06, .5, .65)
        line(.28, .45, .5, .67, .72, .45)
        line(.1, .67, .1, .9, .9, .9, .9, .67)
    else:
        points = []
        for index in range(32):
            angle = index * math.pi / 16
            r = .43 if index % 4 in (0, 3) else .34
            points.extend((x + size * (.5 + math.cos(angle) * r), y + size * (.5 + math.sin(angle) * r)))
        canvas.create_polygon(points, fill='', outline=color, width=width, tags=tags)
        oval(.33, .33, .67, .67)


def icon_image(master, name, color, size=20):
    """Render the same line icon for Tk buttons, with antialiasing."""
    image = Image.new('RGBA', (size * 4, size * 4))
    draw = ImageDraw.Draw(image)

    class Painter:
        def create_line(self, *points, fill, width=1, **_):
            draw.line(list(zip(points[::2], points[1::2])), fill=fill, width=round(width), joint='curve')

        def create_rectangle(self, *box, outline, width=1, **_):
            draw.rectangle(box, outline=outline, width=round(width))

        def create_oval(self, *box, outline, width=1, **_):
            draw.ellipse(box, outline=outline, width=round(width))

        def create_polygon(self, points, fill='', outline=None, width=1, **_):
            draw.polygon(points, fill=fill or None, outline=outline, width=round(width))

        def create_arc(self, *box, start, extent, outline, width=1, **_):
            first, last = (-start - extent, -start) if extent >= 0 else (-start, -start - extent)
            draw.arc(box, first, last, fill=outline, width=round(width))

    icon(Painter(), name, 0, 0, size * 4, color, width=6)
    return ImageTk.PhotoImage(image.resize((size, size), Image.Resampling.LANCZOS), master=master)
