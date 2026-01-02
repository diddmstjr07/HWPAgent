package com.hwp.agent;

import android.os.Bundle;
import android.webkit.CookieManager;
import com.getcapacitor.Bridge;
import com.getcapacitor.BridgeActivity;
import java.util.HashMap;
import java.net.MalformedURLException;
import java.net.URL;

public class MainActivity extends BridgeActivity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        Bridge bridge = getBridge();
        if (bridge == null) {
            return;
        }

        String appUrl = bridge.getAppUrl();
        if (appUrl == null || !appUrl.startsWith("http")) {
            return;
        }

        String appToken = getString(R.string.app_token);
        if (appToken == null || appToken.trim().isEmpty()) {
            return;
        }

        String adminUrl = appUrl.endsWith("/") ? appUrl + "admin" : appUrl + "/admin";
        bridge.getWebView().post(() -> {
            setAppTokenCookie(appUrl, appToken.trim());
            HashMap<String, String> headers = new HashMap<>();
            headers.put("X-App-Token", appToken.trim());
            bridge.getWebView().loadUrl(adminUrl, headers);
        });
    }

    private void setAppTokenCookie(String appUrl, String appToken) {
        CookieManager cookieManager = CookieManager.getInstance();
        cookieManager.setAcceptCookie(true);
        String baseUrl = appUrl;
        try {
            URL parsed = new URL(appUrl);
            int port = parsed.getPort();
            String host = parsed.getHost();
            String scheme = parsed.getProtocol();
            if (port > 0 && port != parsed.getDefaultPort()) {
                baseUrl = scheme + "://" + host + ":" + port;
            } else {
                baseUrl = scheme + "://" + host;
            }
        } catch (MalformedURLException ignored) {
        }
        String cookie = "app_token=" + appToken + "; Path=/; SameSite=Lax";
        if (baseUrl.startsWith("https://")) {
            cookie += "; Secure";
        }
        cookieManager.setCookie(baseUrl, cookie);
        cookieManager.flush();
    }
}
