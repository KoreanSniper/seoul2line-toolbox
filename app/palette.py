
def palette(dark_mode) -> dict[str, str]:
        if dark_mode:
            return {
                "app": "#0b0f14",
                "sidebar": "#0d1117",
                "nav": "#111820",
                "panel": "#151c24",
                "panel_soft": "#19232d",
                "surface": "#0f1620",
                "surface_hover": "#172331",
                "field": "#0d141d",
                "border": "#263342",
                "border_soft": "#1e2936",
                "text": "#edf2f7",
                "muted": "#91a0b4",
                "subtle": "#657386",
                "accent": "#2dd4bf",
                "accent_text": "#071311",
                "accent_soft": "#123934",
                "danger": "#ef4444",
            }
        return {
            "app": "#eef2f6",
            "sidebar": "#ffffff",
            "nav": "#f6f8fb",
            "panel": "#ffffff",
            "panel_soft": "#f6f8fb",
            "surface": "#ffffff",
            "surface_hover": "#eef3f7",
            "field": "#ffffff",
            "border": "#bfccd8",
            "border_soft": "#d8e0e8",
            "text": "#16202a",
            "muted": "#53616e",
            "subtle": "#7a8794",
            "accent": "#0f8f78",
            "accent_text": "#ffffff",
            "accent_soft": "#dff5f1",
            "danger": "#dc2626",
        }

