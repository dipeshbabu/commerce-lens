from commercelens.api.presentation import (
    dashboard_shell,
    escape_html,
    portal_href,
    portal_shell,
    preformatted_json,
    table,
)


def test_escape_html_handles_none_and_markup() -> None:
    assert escape_html(None) == ""
    assert escape_html('<script data-value="1">') == ("&lt;script data-value=&quot;1&quot;&gt;")


def test_dashboard_shell_preserves_navigation_and_escapes_title() -> None:
    result = dashboard_shell("Operator <view>", "<p>trusted content</p>", "?admin_token=test")

    assert "<title>Operator &lt;view&gt; - CommerceLens</title>" in result
    assert 'href="/dashboard?admin_token=test"' in result
    assert "<p>trusted content</p>" in result


def test_portal_shell_preserves_navigation_and_escapes_title() -> None:
    result = portal_shell("Customer <view>", "<p>trusted content</p>", "?api_key=test")

    assert "<title>Customer &lt;view&gt; - CommerceLens</title>" in result
    assert 'href="/portal?api_key=test"' in result
    assert "customer portal" in result


def test_table_renders_empty_and_populated_states() -> None:
    empty = table(["Name", "<Value>"], [])
    populated = table(["Name"], [["<strong>trusted cell</strong>"]])

    assert "&lt;Value&gt;" in empty
    assert "colspan='2'" in empty
    assert "No records" in empty
    assert "<td><strong>trusted cell</strong></td>" in populated


def test_preformatted_json_is_deterministic_and_escaped() -> None:
    result = preformatted_json({"z": "<tag>", "a": 1})

    assert result.startswith("<pre>{")
    assert result.index("&quot;a&quot;") < result.index("&quot;z&quot;")
    assert "&lt;tag&gt;" in result


def test_portal_href_appends_existing_query() -> None:
    assert portal_href("/portal/jobs/job_1", "?api_key=test") == ("/portal/jobs/job_1?api_key=test")
