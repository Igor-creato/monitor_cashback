"""Contract checks for the mobile WebView ADR."""

from __future__ import annotations

from pathlib import Path

DOC_PATH = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "mobile-webview-flow-decision.md"
)


def test_mobile_webview_flow_decision_documents_contract_and_boundaries() -> None:
    content = DOC_PATH.read_text(encoding="utf-8")

    required_fragments = [
        "WebView-only capture",
        "не извлекает cookies/tokens из нативных приложений Ozon/WB/Yandex Market",
        "GET /wp-json/cashback/v1/price-assistant/consent",
        "POST /wp-json/cashback/v1/price-assistant/connections",
        (
            "POST /wp-json/cashback/v1/price-assistant/connections/"
            "{connection_id}/session-bundle"
        ),
        "GET /wp-json/cashback/v1/price-assistant/sync-status",
        "DELETE /wp-json/cashback/v1/price-assistant/connections/{connection_id}",
        "savello-mobile-webview-0.1.0",
        "Mobile-only states",
        "`marketplace_selected`",
        "`webview_login_open`",
        "`consent_pending`",
        "`bundle_uploading`",
        "`local_session_clearing`",
        "Backend/public states",
        "`reconnect_required`",
        "Consent показывается после подтвержденного входа",
        "Android CookieManager.getCookie",
        "Android Keystore",
        "WKWebView",
        "WKHTTPCookieStore",
        "ASWebAuthenticationSession",
        "Только HTTPS/TLS",
        "no native marketplace app cookie/token interception path",
        "Explicit Non-Goals",
    ]

    for fragment in required_fragments:
        assert fragment in content

    prohibited_fragments = [
        "FastAPI напрямую",
        "реальные cookie/token names утверждены",
        "captcha bypass",
    ]

    for fragment in prohibited_fragments:
        assert fragment not in content
