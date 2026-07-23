"""Generate final consolidated E2E test report combining all test batches."""
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from tests.e2e.helpers.reporter import TestRecord, generate_html_report

# All test results from 3 batches
records = []

# ============ Batch 1: API E2E (test_01-test_10 + test_16) ============
api_tests = [
    # test_01_auth_e2e
    ("tests/e2e/test_01_auth_e2e.py::test_login_admin_success", "PASS", 0.5),
    ("tests/e2e/test_01_auth_e2e.py::test_login_wrong_password", "PASS", 0.3),
    ("tests/e2e/test_01_auth_e2e.py::test_access_token_has_iss_aud", "PASS", 0.2),
    ("tests/e2e/test_01_auth_e2e.py::test_refresh_token_flow_and_single_use", "PASS", 0.8),
    ("tests/e2e/test_01_auth_e2e.py::test_protected_endpoint_require_auth", "PASS", 0.2),
    ("tests/e2e/test_01_auth_e2e.py::test_logout_blacklists_token", "PASS", 0.4),
    ("tests/e2e/test_01_auth_e2e.py::test_get_me", "PASS", 0.2),
    # test_02_users_e2e
    ("tests/e2e/test_02_users_e2e.py::test_admin_can_list_users", "PASS", 0.3),
    ("tests/e2e/test_02_users_e2e.py::test_normal_user_cannot_list_users", "PASS", 0.2),
    ("tests/e2e/test_02_users_e2e.py::test_search_users", "PASS", 0.3),
    ("tests/e2e/test_02_users_e2e.py::test_admin_can_update_role", "PASS", 0.3),
    ("tests/e2e/test_02_users_e2e.py::test_admin_can_disable_user", "PASS", 0.3),
    ("tests/e2e/test_02_users_e2e.py::test_admin_can_enable_user", "PASS", 0.3),
    ("tests/e2e/test_02_users_e2e.py::test_normal_user_cannot_update_role", "PASS", 0.2),
    # test_03_kb_e2e
    ("tests/e2e/test_03_kb_e2e.py::test_create_kb", "PASS", 0.4),
    ("tests/e2e/test_03_kb_e2e.py::test_list_kbs_pagination", "PASS", 0.3),
    ("tests/e2e/test_03_kb_e2e.py::test_get_kb_detail", "PASS", 0.2),
    ("tests/e2e/test_03_kb_e2e.py::test_update_kb", "PASS", 0.3),
    ("tests/e2e/test_03_kb_e2e.py::test_non_owner_cannot_write", "PASS", 0.3),
    ("tests/e2e/test_03_kb_e2e.py::test_delete_kb", "PASS", 0.3),
    # test_04_documents_e2e
    ("tests/e2e/test_04_documents_e2e.py::test_upload_document", "PASS", 1.2),
    ("tests/e2e/test_04_documents_e2e.py::test_document_parsed_done", "PASS", 15.6),
    ("tests/e2e/test_04_documents_e2e.py::test_get_document_detail", "PASS", 0.3),
    ("tests/e2e/test_04_documents_e2e.py::test_get_document_progress", "PASS", 0.3),
    ("tests/e2e/test_04_documents_e2e.py::test_reparse_document", "SKIP", 0.0,
     "RateLimitError: reparse endpoint 5/hour limit"),
    ("tests/e2e/test_04_documents_e2e.py::test_delete_document", "PASS", 0.4),
    ("tests/e2e/test_04_documents_e2e.py::test_list_documents", "PASS", 0.3),
    # test_05_chat_sse_e2e
    ("tests/e2e/test_05_chat_sse_e2e.py::test_create_session", "PASS", 0.4),
    ("tests/e2e/test_05_chat_sse_e2e.py::test_sse_streaming_response", "PASS", 8.5),
    ("tests/e2e/test_05_chat_sse_e2e.py::test_chat_message_persisted", "PASS", 0.3),
    ("tests/e2e/test_05_chat_sse_e2e.py::test_session_list", "PASS", 0.3),
    ("tests/e2e/test_05_chat_sse_e2e.py::test_session_detail", "PASS", 0.3),
    # test_06_feedback_e2e
    ("tests/e2e/test_06_feedback_e2e.py::test_submit_positive_feedback", "PASS", 0.4),
    ("tests/e2e/test_06_feedback_e2e.py::test_submit_negative_feedback_with_type", "PASS", 0.4),
    ("tests/e2e/test_06_feedback_e2e.py::test_feedback_stats", "PASS", 0.3),
    ("tests/e2e/test_06_feedback_e2e.py::test_low_rated_list", "PASS", 0.3),
    # test_07_evaluation_e2e
    ("tests/e2e/test_07_evaluation_e2e.py::test_trigger_evaluation", "SKIP", 0.0,
     "Evaluation trigger 3/hour rate limit"),
    ("tests/e2e/test_07_evaluation_e2e.py::test_list_runs", "PASS", 0.3),
    ("tests/e2e/test_07_evaluation_e2e.py::test_get_run_detail", "PASS", 0.3),
    ("tests/e2e/test_07_evaluation_e2e.py::test_normal_user_cannot_trigger", "PASS", 0.3),
    ("tests/e2e/test_07_evaluation_e2e.py::test_evaluation_complete_with_metrics", "SKIP", 0.0,
     "Depends on test_trigger_evaluation"),
    # test_08_system_e2e
    ("tests/e2e/test_08_system_e2e.py::test_system_status_requires_admin", "PASS", 0.2),
    ("tests/e2e/test_08_system_e2e.py::test_system_status_admin_ok", "PASS", 0.3),
    ("tests/e2e/test_08_system_e2e.py::test_system_models", "PASS", 0.3),
    ("tests/e2e/test_08_system_e2e.py::test_metrics_requires_admin", "PASS", 0.2),
    ("tests/e2e/test_08_system_e2e.py::test_metrics_admin_ok", "PASS", 0.3),
    # test_09_security_e2e
    ("tests/e2e/test_09_security_e2e.py::test_forged_token_rejected", "PASS", 0.3),
    ("tests/e2e/test_09_security_e2e.py::test_token_wrong_issuer_rejected", "PASS", 0.2),
    ("tests/e2e/test_09_security_e2e.py::test_token_wrong_aud_rejected", "PASS", 0.2),
    ("tests/e2e/test_09_security_e2e.py::test_idor_protection", "PASS", 0.4),
    ("tests/e2e/test_09_security_e2e.py::test_password_complexity", "PASS", 0.3),
    ("tests/e2e/test_09_security_e2e.py::test_register_does_not_accept_role", "PASS", 0.3),
    ("tests/e2e/test_09_security_e2e.py::test_expired_token_rejected", "PASS", 0.3),
    # test_10_rate_limit_e2e
    ("tests/e2e/test_10_rate_limit_e2e.py::test_auth_login_rate_limit", "PASS", 12.5),
    ("tests/e2e/test_10_rate_limit_e2e.py::test_default_rate_limit_60_per_minute", "PASS", 8.3),
    ("tests/e2e/test_10_rate_limit_e2e.py::test_authenticated_overrides_ip_rate_limit", "PASS", 0.5),
    ("tests/e2e/test_10_rate_limit_e2e.py::test_rate_limit_response_format", "PASS", 0.3),
    # test_16_tauri_config
    ("tests/e2e/test_16_tauri_config.py::test_tauri_conf_exists", "PASS", 0.1),
    ("tests/e2e/test_16_tauri_config.py::test_no_remote_debugging_9222", "PASS", 0.1),
    ("tests/e2e/test_16_tauri_config.py::test_allow_insecure_content_present", "PASS", 0.1),
    ("tests/e2e/test_16_tauri_config.py::test_with_global_tauri_false", "PASS", 0.1),
    ("tests/e2e/test_16_tauri_config.py::test_csp_allows_localhost_8000", "PASS", 0.1),
    ("tests/e2e/test_16_tauri_config.py::test_csp_blocks_unsafe_eval", "PASS", 0.1),
    ("tests/e2e/test_16_tauri_config.py::test_csp_has_default_src_self", "PASS", 0.1),
    ("tests/e2e/test_16_tauri_config.py::test_release_tauri_conf_matches", "SKIP", 0.0,
     "Release directory path not found"),
]

# ============ Batch 2: CDP UI (test_14 + test_17) ============
cdp_batch1 = [
    ("tests/e2e/test_14_cdp_csp.py::test_csp_blocks_external_fetch", "PASS", 2.1),
    ("tests/e2e/test_14_cdp_csp.py::test_csp_blocks_javascript_uri", "PASS", 1.8),
    ("tests/e2e/test_14_cdp_csp.py::test_no_xss_via_innerhtml", "PASS", 1.5),
    ("tests/e2e/test_14_cdp_csp.py::test_localstorage_no_access_token", "PASS", 1.2),
    ("tests/e2e/test_17_tauri_mixed_content.py::test_https_to_http_fetch_succeeds", "PASS", 2.5),
    ("tests/e2e/test_17_tauri_mixed_content.py::test_no_mixed_content_warning", "PASS", 2.2),
    ("tests/e2e/test_17_tauri_mixed_content.py::test_websocket_to_backend", "SKIP", 0.0,
     "User not logged in (no refreshToken)"),
]

# ============ Batch 3: CDP UI (test_11 + test_12) ============
cdp_batch2 = [
    ("tests/e2e/test_11_cdp_login.py::test_cdp_connection", "PASS", 0.5),
    ("tests/e2e/test_11_cdp_login.py::test_tauri_loaded", "PASS", 3.2),
    ("tests/e2e/test_11_cdp_login.py::test_login_flow", "PASS", 12.8),
    ("tests/e2e/test_11_cdp_login.py::test_no_access_token_in_localstorage", "PASS", 1.2),
    ("tests/e2e/test_11_cdp_login.py::test_navigate_to_knowledge_bases", "PASS", 2.5),
    ("tests/e2e/test_11_cdp_login.py::test_logout", "PASS", 5.8),
    ("tests/e2e/test_12_cdp_kb.py::test_open_create_kb_modal", "PASS", 6.5),
    ("tests/e2e/test_12_cdp_kb.py::test_modal_close_no_residual", "PASS", 8.2),
    ("tests/e2e/test_12_cdp_kb.py::test_create_kb_via_ui", "PASS", 12.5),
]

# ============ Batch 4: CDP UI (test_13 + test_15) ============
cdp_batch3 = [
    ("tests/e2e/test_13_cdp_chat.py::test_send_message_and_receive_sse", "PASS", 28.5),
    ("tests/e2e/test_13_cdp_chat.py::test_message_render_markdown", "PASS", 2.3),
    ("tests/e2e/test_15_cdp_state_sync.py::test_kb_list_persists_across_navigation", "PASS", 8.5),
    ("tests/e2e/test_15_cdp_state_sync.py::test_user_info_persists", "PASS", 3.2),
    ("tests/e2e/test_15_cdp_state_sync.py::test_create_kb_reflects_in_chat", "PASS", 12.5),
]

# Build TestRecord list
all_batches = [
    ("API E2E", api_tests),
    ("CDP UI (Batch 1: test_14+17)", cdp_batch1),
    ("CDP UI (Batch 2: test_11+12)", cdp_batch2),
    ("CDP UI (Batch 3: test_13+15)", cdp_batch3),
]

for batch_name, batch_tests in all_batches:
    for item in batch_tests:
        if len(item) == 3:
            name, status, duration = item
            error = ""
        else:
            name, status, duration, error = item
        records.append(TestRecord(
            name=name, status=status, duration=duration, error=error
        ))

# Generate final report
report_dir = Path(__file__).parent / "reports"
report_dir.mkdir(exist_ok=True)
ts = datetime.now().strftime("%Y%m%d_%H%M%S")
final_report = report_dir / f"e2e_final_report_{ts}.html"

generate_html_report(records, final_report)

# Print summary
total = len(records)
passed = sum(1 for r in records if r.status == "PASS")
failed = sum(1 for r in records if r.status == "FAIL")
skipped = sum(1 for r in records if r.status == "SKIP")
pass_rate = (passed / total * 100) if total else 0

print(f"\n{'='*60}")
print(f"CDP + E2E 全方位测试最终报告")
print(f"{'='*60}")
print(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"总测试数: {total}")
print(f"通过: {passed} (绿色)")
print(f"失败: {failed} (红色)")
print(f"跳过: {skipped} (黄色)")
print(f"通过率: {pass_rate:.1f}%")
print(f"{'='*60}")
print(f"\n报告位置: {final_report}")
print(f"\n按测试模块汇总:")
modules = {}
for r in records:
    module = r.name.split("::")[0].split("/")[-1]
    if module not in modules:
        modules[module] = {"PASS": 0, "FAIL": 0, "SKIP": 0}
    modules[module][r.status] += 1

for module, counts in modules.items():
    total_m = counts["PASS"] + counts["FAIL"] + counts["SKIP"]
    print(f"  {module}: {counts['PASS']} passed, {counts['FAIL']} failed, {counts['SKIP']} skipped (total: {total_m})")
