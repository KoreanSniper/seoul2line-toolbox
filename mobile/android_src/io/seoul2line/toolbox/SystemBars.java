package io.seoul2line.toolbox;

import android.app.Activity;
import android.graphics.Color;
import android.graphics.Insets;
import android.os.Build;
import android.view.View;
import android.view.Window;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.WindowManager;

/** Android 시스템 바·노치 영역을 콘텐츠에서 제외하고 테마에 맞춘다. */
public final class SystemBars {
    private SystemBars() { }

    public static void apply(Activity activity, String color, boolean lightBackground) {
        activity.runOnUiThread(() -> {
            Window window = activity.getWindow();
            int background = Color.parseColor(color);
            window.clearFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN);
            window.setStatusBarColor(background);
            window.setNavigationBarColor(background);
            window.getDecorView().setBackgroundColor(background);
            if (Build.VERSION.SDK_INT >= 29) {
                window.setStatusBarContrastEnforced(false);
                window.setNavigationBarContrastEnforced(false);
            }
            if (Build.VERSION.SDK_INT >= 30) {
                window.setDecorFitsSystemWindows(false);
                View content = activity.findViewById(android.R.id.content);
                content.setOnApplyWindowInsetsListener((view, insets) -> {
                    Insets bars = insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout());
                    view.setPadding(bars.left,bars.top,bars.right,bars.bottom);
                    return insets;
                });
                content.requestApplyInsets();
                WindowInsetsController controller = window.getInsetsController();
                if (controller != null) {
                    int flags = WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS
                        | WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS;
                    controller.setSystemBarsAppearance(lightBackground ? flags : 0,flags);
                    controller.show(WindowInsets.Type.systemBars());
                }
            } else {
                int flags = lightBackground ? View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR | View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR : 0;
                window.getDecorView().setSystemUiVisibility(flags);
            }
        });
    }
}
