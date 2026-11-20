package com.dali.aoe3assistant;

import android.app.Activity;
import android.app.DownloadManager;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.view.Window;
import android.view.WindowManager;
import android.webkit.DownloadListener;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class MainActivity extends Activity {
    private static final String PREFS_NAME = "AoE3CoachPrefs";
    private static final String KEY_SERVER_URL = "server_url";
    private static final String APP_VERSION = "1.3.0";
    private static final int APP_VERSION_CODE = 4;
    private static final String DEFAULT_SERVER_URL = "http://192.168.1.154:8765";

    private WebView webView;
    private ExecutorService httpExecutor;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        requestWindowFeature(Window.FEATURE_NO_TITLE);
        Window window = getWindow();
        if (window != null) {
            window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
            window.addFlags(WindowManager.LayoutParams.FLAG_DRAWS_SYSTEM_BAR_BACKGROUNDS);
            window.setStatusBarColor(Color.parseColor("#080D14"));
            window.setNavigationBarColor(Color.parseColor("#080D14"));
        }

        httpExecutor = Executors.newCachedThreadPool();

        webView = new WebView(this);
        webView.setBackgroundColor(Color.parseColor("#080D14"));

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setAllowFileAccess(true);
        settings.setAllowContentAccess(true);
        settings.setAllowFileAccessFromFileURLs(true);
        settings.setAllowUniversalAccessFromFileURLs(true);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        settings.setMediaPlaybackRequiresUserGesture(false);
        settings.setCacheMode(WebSettings.LOAD_DEFAULT);
        settings.setUseWideViewPort(true);
        settings.setLoadWithOverviewMode(true);
        settings.setTextZoom(100);

        webView.addJavascriptInterface(new AoE3NativeBridge(), "AoE3Native");

        webView.setWebChromeClient(new WebChromeClient());
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                if (uri != null) {
                    String urlStr = uri.toString();
                    if (urlStr.endsWith(".apk") || urlStr.endsWith(".exe")) {
                        startApkDownload(urlStr, APP_VERSION);
                        return true;
                    }
                }
                return false;
            }
        });

        webView.setDownloadListener(new DownloadListener() {
            @Override
            public void onDownloadStart(String url, String userAgent, String contentDisposition, String mimetype, long contentLength) {
                startApkDownload(url, APP_VERSION);
            }
        });

        setContentView(webView);
        webView.loadUrl("file:///android_asset/index.html");
    }

    private void startApkDownload(String apkUrl, String versionLabel) {
        try {
            DownloadManager dm = (DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE);
            if (dm != null) {
                Uri uri = Uri.parse(apkUrl);
                DownloadManager.Request req = new DownloadManager.Request(uri);
                req.setTitle("AoE3 Russia Coach APK Update");
                req.setDescription("Downloading AoE3Assistant.apk (v" + versionLabel + ")");
                req.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
                req.setMimeType("application/vnd.android.package-archive");
                req.setAllowedOverMetered(true);
                req.setAllowedOverRoaming(true);
                String fileName = "AoE3Assistant.apk";
                req.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, fileName);
                dm.enqueue(req);
                Toast.makeText(this, "Downloading AoE3Assistant.apk to Downloads... Tap notification when finished to install.", Toast.LENGTH_LONG).show();
                return;
            }
        } catch (Throwable ignored) {
        }
        try {
            Intent browserIntent = new Intent(Intent.ACTION_VIEW, Uri.parse(apkUrl));
            browserIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(browserIntent);
        } catch (Throwable e) {
            Toast.makeText(this, "Could not start download: " + e.getMessage(), Toast.LENGTH_LONG).show();
        }
    }

    private static String escapeJsString(String s) {
        if (s == null) return "";
        StringBuilder sb = new StringBuilder(s.length() + 32);
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '\\': sb.append("\\\\"); break;
                case '"': sb.append("\\\""); break;
                case '\'': sb.append("\\'"); break;
                case '\n': sb.append("\\n"); break;
                case '\r': sb.append("\\r"); break;
                case '\t': sb.append("\\t"); break;
                case '\u2028': sb.append("\\u2028"); break;
                case '\u2029': sb.append("\\u2029"); break;
                default:
                    if (c < 0x20) {
                        sb.append(String.format(Locale.US, "\\u%04x", (int) c));
                    } else {
                        sb.append(c);
                    }
                    break;
            }
        }
        return sb.toString();
    }

    public class AoE3NativeBridge {

        @JavascriptInterface
        public String getAppVersion() {
            return APP_VERSION;
        }

        @JavascriptInterface
        public int getVersionCode() {
            return APP_VERSION_CODE;
        }

        @JavascriptInterface
        public String getSavedServerUrl() {
            SharedPreferences prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
            return prefs.getString(KEY_SERVER_URL, DEFAULT_SERVER_URL);
        }

        @JavascriptInterface
        public void saveServerUrl(String url) {
            if (url == null) return;
            SharedPreferences prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
            prefs.edit().putString(KEY_SERVER_URL, url.trim()).apply();
        }

        @JavascriptInterface
        public boolean getTtsEnabled() {
            return false;
        }

        @JavascriptInterface
        public void setTtsEnabled(boolean enabled) {
            // Audio removed by design
        }

        @JavascriptInterface
        public void speak(String text) {
            // Audio removed by design
        }

        @JavascriptInterface
        public void vibrate(int durationMs) {
            try {
                Vibrator v = (Vibrator) getSystemService(Context.VIBRATOR_SERVICE);
                if (v != null && v.hasVibrator()) {
                    int ms = Math.max(20, Math.min(durationMs, 500));
                    if (Build.VERSION.SDK_INT >= 26) {
                        v.vibrate(VibrationEffect.createOneShot(ms, VibrationEffect.DEFAULT_AMPLITUDE));
                    } else {
                        v.vibrate(ms);
                    }
                }
            } catch (Throwable ignored) {
            }
        }

        @JavascriptInterface
        public void showToast(final String msg) {
            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    Toast.makeText(MainActivity.this, msg, Toast.LENGTH_SHORT).show();
                }
            });
        }

        @JavascriptInterface
        public void downloadApk(final String apkUrl, final String versionLabel) {
            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    startApkDownload(apkUrl, versionLabel != null ? versionLabel : APP_VERSION);
                }
            });
        }

        @JavascriptInterface
        public void openExternalUrl(final String url) {
            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    try {
                        Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
                        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                        startActivity(intent);
                    } catch (Throwable e) {
                        Toast.makeText(MainActivity.this, "Cannot open URL: " + e.getMessage(), Toast.LENGTH_SHORT).show();
                    }
                }
            });
        }

        @JavascriptInterface
        public void httpGetAsync(final String reqId, final String urlStr) {
            if (httpExecutor == null) return;
            httpExecutor.execute(new Runnable() {
                @Override
                public void run() {
                    int status = 0;
                    String responseBody = "";
                    HttpURLConnection conn = null;
                    try {
                        URL url = new URL(urlStr);
                        conn = (HttpURLConnection) url.openConnection();
                        conn.setInstanceFollowRedirects(true);
                        conn.setRequestMethod("GET");
                        conn.setConnectTimeout(3000);
                        conn.setReadTimeout(4000);
                        conn.setRequestProperty("Accept", "application/json, text/plain, */*");
                        conn.setRequestProperty("User-Agent", "AoE3Assistant-Android/" + APP_VERSION);
                        status = conn.getResponseCode();
                        InputStream is = (status >= 200 && status < 400) ? conn.getInputStream() : conn.getErrorStream();
                        if (is != null) {
                            BufferedReader reader = new BufferedReader(new InputStreamReader(is, StandardCharsets.UTF_8));
                            StringBuilder sb = new StringBuilder();
                            String line;
                            while ((line = reader.readLine()) != null) {
                                sb.append(line).append('\n');
                            }
                            reader.close();
                            responseBody = sb.toString();
                        }
                    } catch (Throwable e) {
                        status = -1;
                        responseBody = e.getMessage() != null ? e.getMessage() : "Network error";
                    } finally {
                        if (conn != null) {
                            try {
                                conn.disconnect();
                            } catch (Throwable ignored) {
                            }
                        }
                    }
                    final int finalStatus = status;
                    final String escapedId = escapeJsString(reqId);
                    final String escapedBody = escapeJsString(responseBody);
                    runOnUiThread(new Runnable() {
                        @Override
                        public void run() {
                            if (webView != null) {
                                String js = "window.__onNativeHttp && window.__onNativeHttp(\""
                                        + escapedId + "\", " + finalStatus + ", \"" + escapedBody + "\");";
                                webView.evaluateJavascript(js, null);
                            }
                        }
                    });
                }
            });
        }

        @JavascriptInterface
        public void httpPostAsync(final String reqId, final String urlStr, final String jsonPayload) {
            if (httpExecutor == null) return;
            httpExecutor.execute(new Runnable() {
                @Override
                public void run() {
                    int status = 0;
                    String responseBody = "";
                    HttpURLConnection conn = null;
                    try {
                        URL url = new URL(urlStr);
                        conn = (HttpURLConnection) url.openConnection();
                        conn.setInstanceFollowRedirects(true);
                        conn.setRequestMethod("POST");
                        conn.setDoOutput(true);
                        conn.setConnectTimeout(3000);
                        conn.setReadTimeout(4000);
                        conn.setRequestProperty("Content-Type", "application/json; charset=UTF-8");
                        conn.setRequestProperty("Accept", "application/json");
                        conn.setRequestProperty("User-Agent", "AoE3Assistant-Android/" + APP_VERSION);
                        byte[] bytes = (jsonPayload != null ? jsonPayload : "{}").getBytes(StandardCharsets.UTF_8);
                        OutputStream os = conn.getOutputStream();
                        os.write(bytes);
                        os.flush();
                        os.close();
                        status = conn.getResponseCode();
                        InputStream is = (status >= 200 && status < 400) ? conn.getInputStream() : conn.getErrorStream();
                        if (is != null) {
                            BufferedReader reader = new BufferedReader(new InputStreamReader(is, StandardCharsets.UTF_8));
                            StringBuilder sb = new StringBuilder();
                            String line;
                            while ((line = reader.readLine()) != null) {
                                sb.append(line).append('\n');
                            }
                            reader.close();
                            responseBody = sb.toString();
                        }
                    } catch (Throwable e) {
                        status = -1;
                        responseBody = e.getMessage() != null ? e.getMessage() : "Network error";
                    } finally {
                        if (conn != null) {
                            try {
                                conn.disconnect();
                            } catch (Throwable ignored) {
                            }
                        }
                    }
                    final int finalStatus = status;
                    final String escapedId = escapeJsString(reqId);
                    final String escapedBody = escapeJsString(responseBody);
                    runOnUiThread(new Runnable() {
                        @Override
                        public void run() {
                            if (webView != null) {
                                String js = "window.__onNativeHttp && window.__onNativeHttp(\""
                                        + escapedId + "\", " + finalStatus + ", \"" + escapedBody + "\");";
                                webView.evaluateJavascript(js, null);
                            }
                        }
                    });
                }
            });
        }
    }

    @Override
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onDestroy() {
        if (httpExecutor != null) {
            try {
                httpExecutor.shutdownNow();
            } catch (Throwable ignored) {
            }
        }
        super.onDestroy();
    }
}
