package io.seoul2line.toolbox;

import android.app.Activity;
import android.database.Cursor;
import android.media.MediaPlayer;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;
import android.provider.OpenableColumns;
import org.json.JSONObject;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** 시스템 선택 파일을 앱 전용 저장소로 복사하고 로컬 오디오를 재생한다. */
public final class AudioBridge {
    public interface Listener { void onEvent(String event, String payload); }
    private final Activity activity;
    private final Listener listener;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private volatile boolean closed = false;
    private MediaPlayer player;
    private String activeId = "";

    private AudioBridge(Activity activity, Listener listener) { this.activity = activity; this.listener = listener; }
    public static AudioBridge create(Activity activity, Listener listener) { return new AudioBridge(activity, listener); }

    private void state(String event, String id, String message) {
        if (closed) return;
        try { listener.onEvent(event, new JSONObject().put("id",id).put("message",message).toString()); }
        catch (Exception ignored) { }
    }

    private void release() {
        if (player != null) {
            try { player.release(); } catch (Exception ignored) { }
            player = null;
        }
    }

    public void play(String path, String id) {
        handler.post(() -> {
            if (closed) return;
            release();
            activeId = id;
            try {
                player = new MediaPlayer();
                player.setOnPreparedListener(p -> {
                    if (closed || p != player) return;
                    try { p.start(); state("playing",id,"재생 중입니다."); }
                    catch (Exception error) { state("error",id,"오디오 출력을 시작하지 못했습니다."); release(); }
                });
                player.setOnCompletionListener(p -> {
                    if (p != player) return;
                    state("done",id,"재생을 마쳤습니다."); release();
                });
                player.setOnErrorListener((p, what, extra) -> {
                    if (p == player) { state("error",id,"이 기기에서 읽을 수 없는 오디오입니다."); release(); }
                    return true;
                });
                player.setDataSource(path);
                player.prepareAsync();
            } catch (Exception error) {
                state("error",id,"오디오를 열지 못했습니다. 파일을 확인해 주세요."); release();
            }
        });
    }

    public void stop() {
        handler.post(() -> { release(); state("stopped",activeId,"재생을 중지했습니다."); activeId = ""; });
    }

    public void copyDocument(String uriText, String destination) {
        if (closed) return;
        worker.execute(() -> {
            File target = new File(destination);
            boolean created = false, complete = false;
            try {
                String root = activity.getFilesDir().getCanonicalPath() + File.separator;
                if (!target.getCanonicalPath().startsWith(root) || !target.getName().matches("\\.incoming-[0-9a-f]{32}"))
                    throw new java.io.IOException();
                Uri uri = Uri.parse(uriText);
                if (!"content".equals(uri.getScheme())) throw new java.io.IOException();
                String name = "가져온 사운드", mime = activity.getContentResolver().getType(uri);
                try (Cursor cursor = activity.getContentResolver().query(uri,new String[]{OpenableColumns.DISPLAY_NAME},null,null,null)) {
                    if (cursor != null && cursor.moveToFirst()) name = cursor.getString(0);
                }
                created = target.createNewFile();
                if (!created) throw new java.io.IOException();
                long total = 0;
                try (InputStream source = activity.getContentResolver().openInputStream(uri);
                     FileOutputStream output = new FileOutputStream(target)) {
                    if (source == null) throw new java.io.IOException();
                    byte[] buffer = new byte[65536];
                    int count;
                    while ((count = source.read(buffer)) != -1) {
                        if (closed || (total += count) > 25L*1024*1024) throw new java.io.IOException();
                        output.write(buffer,0,count);
                    }
                }
                if (total == 0 || closed) throw new java.io.IOException();
                listener.onEvent("imported",new JSONObject().put("path",destination).put("name",name)
                    .put("mime",mime == null ? "" : mime).toString());
                complete = true;
            } catch (Exception error) {
                state("import_error","","파일을 가져오지 못했습니다. 25MiB 이하의 로컬 오디오를 선택해 주세요.");
            } finally {
                if (created && !complete) target.delete();
            }
        });
    }

    public void close() {
        closed = true;
        worker.shutdownNow();
        handler.post(this::release);
    }
}
