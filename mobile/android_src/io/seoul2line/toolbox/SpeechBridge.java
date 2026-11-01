package io.seoul2line.toolbox;

import android.app.Activity;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.speech.tts.TextToSpeech;
import android.speech.tts.UtteranceProgressListener;
import android.speech.tts.Voice;
import org.json.JSONArray;
import org.json.JSONObject;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** Android 전용 음성 엔진. 모든 엔진 조작은 메인 스레드에서 수행한다. */
public final class SpeechBridge {
    public interface Listener { void onEvent(String event, String payload); }
    private final Activity activity;
    private final Listener listener;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Map<String, Voice> voices = new HashMap<>();
    private TextToSpeech engine;
    private volatile boolean closed = false;
    private volatile int generation = 0;
    private volatile String session = "";
    private boolean ready = false;
    private String activeId = "";

    private SpeechBridge(Activity activity, Listener listener) {
        this.activity = activity;
        this.listener = listener;
    }

    public static SpeechBridge create(Activity activity, Listener listener) {
        return new SpeechBridge(activity, listener);
    }

    private void state(String event, String id, String message) {
        if (closed) return;
        try {
            listener.onEvent(event, new JSONObject().put("id", id).put("message", message).put("session", session).toString());
        } catch (Exception ignored) { }
    }

    public void initialize(String packageName, String sessionId) {
        handler.post(() -> {
            if (closed) return;
            final int current = ++generation;
            session = sessionId;
            ready = false;
            voices.clear();
            activeId = "";
            if (engine != null) {
                try { engine.stop(); } catch (Exception ignored) { }
                try { engine.shutdown(); } catch (Exception ignored) { }
                engine = null;
            }
            try {
                TextToSpeech.OnInitListener init = status -> handler.post(() -> finishInit(current, status, sessionId));
                engine = packageName == null || packageName.isEmpty()
                    ? new TextToSpeech(activity, init) : new TextToSpeech(activity, init, packageName);
            } catch (Exception error) {
                state("error", "", "음성 엔진을 열지 못했습니다. Android TTS 설정을 확인해 주세요.");
            }
        });
    }

    private void finishInit(final int current, int status, String sessionId) {
        if (closed || current != generation || engine == null) return;
        try {
            JSONArray enginesJson = new JSONArray();
            for (TextToSpeech.EngineInfo info : engine.getEngines()) {
                enginesJson.put(new JSONObject().put("id", info.name).put("label", info.label));
            }
            JSONArray voicesJson = new JSONArray();
            if (status == TextToSpeech.SUCCESS) {
                Set<Voice> available = engine.getVoices();
                List<Voice> sorted = available == null ? new ArrayList<>() : new ArrayList<>(available);
                sorted.sort(Comparator.comparing(Voice::getName));
                for (Voice voice : sorted) {
                    Set<String> features = voice.getFeatures();
                    if (!"ko".equals(voice.getLocale().getLanguage()) || voice.isNetworkConnectionRequired()
                        || (features != null && features.contains(TextToSpeech.Engine.KEY_FEATURE_NOT_INSTALLED))) continue;
                    voices.put(voice.getName(), voice);
                    voicesJson.put(new JSONObject().put("id", voice.getName()).put("label", voice.getName()));
                }
                engine.setOnUtteranceProgressListener(new UtteranceProgressListener() {
                    private void event(String event, String id, String message) {
                        if (current == generation) state(event, id, message);
                    }
                    @Override public void onStart(String id) { event("started", id, "읽는 중입니다."); }
                    @Override public void onDone(String id) { event("done", id, "읽기를 마쳤습니다."); }
                    @Override public void onError(String id) { event("error", id, "음성 출력에 실패했습니다."); }
                    @Override public void onError(String id, int code) { onError(id); }
                    @Override public void onStop(String id, boolean interrupted) { event("stopped", id, "읽기를 중지했습니다."); }
                });
            }
            ready = status == TextToSpeech.SUCCESS && !voices.isEmpty();
            String message = ready ? "오프라인 한국어 음성 준비 완료"
                : "사용 가능한 한국어 오프라인 음성이 없습니다. Android TTS 설정에서 음성 데이터를 설치해 주세요.";
            listener.onEvent("catalogue", new JSONObject().put("engines", enginesJson).put("voices", voicesJson)
                .put("ready", ready).put("message", message).put("session", sessionId).toString());
        } catch (Exception error) {
            state("error", "", "음성 목록을 읽지 못했습니다. 다른 엔진을 선택해 주세요.");
        }
    }

    public void speak(String text, String voiceName, float rate, String id) {
        handler.post(() -> {
            if (closed) return;
            if (!ready || engine == null || !voices.containsKey(voiceName)) {
                state("error", id, "한국어 오프라인 음성을 먼저 준비해 주세요."); return;
            }
            if (text == null || text.trim().isEmpty() || text.length() > TextToSpeech.getMaxSpeechInputLength()) {
                state("error", id, "읽을 내용을 입력하고 글자 수 제한을 확인해 주세요."); return;
            }
            try {
                if (engine.setVoice(voices.get(voiceName)) != TextToSpeech.SUCCESS
                    || engine.setSpeechRate(Math.max(0.5f, Math.min(2.0f, rate))) != TextToSpeech.SUCCESS) {
                    state("error", id, "음성 또는 읽기 속도를 적용하지 못했습니다."); return;
                }
                activeId = id;
                if (engine.speak(text, TextToSpeech.QUEUE_FLUSH, new Bundle(), id) != TextToSpeech.SUCCESS) {
                    activeId = "";
                    state("error", id, "읽기 요청에 실패했습니다.");
                }
            } catch (Exception error) {
                state("error", id, "음성 엔진 연결이 끊겼습니다. 엔진을 다시 준비해 주세요.");
            }
        });
    }

    public void stop() {
        handler.post(() -> {
            if (closed) return;
            String id = activeId;
            activeId = "";
            try {
                if (engine != null) engine.stop();
                state("stopped", id, "읽기를 중지했습니다.");
            } catch (Exception error) { state("error", id, "음성 엔진에 중지 요청을 보내지 못했습니다."); }
        });
    }

    public void close() {
        closed = true;
        handler.post(() -> {
            ++generation;
            ready = false;
            voices.clear();
            if (engine != null) {
                try { engine.stop(); } catch (Exception ignored) { }
                try { engine.shutdown(); } catch (Exception ignored) { }
                engine = null;
            }
        });
    }
}
