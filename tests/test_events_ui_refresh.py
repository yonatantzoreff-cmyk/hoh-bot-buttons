"""
Test for auto-refresh functionality in events UI.
Validates that the events_jacksonbot.html template includes necessary components.
"""
import re


def test_htmx_script_in_events_template():
    """Verify HTMX script is included in events template."""
    with open('templates/ui/events_jacksonbot.html', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check for HTMX script
    assert 'htmx.org' in content, "HTMX script not found in events template"
    assert '<script src="https://unpkg.com/htmx.org@' in content, "HTMX CDN script missing"


def test_last_updated_element_in_template():
    """Verify 'Last updated' timestamp element exists."""
    with open('templates/ui/events_jacksonbot.html', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check for lastUpdated element
    assert 'id="lastUpdated"' in content, "'lastUpdated' element not found"


def test_auto_refresh_constants_defined():
    """Verify auto-refresh constants are defined in JavaScript."""
    with open('templates/ui/events_jacksonbot.html', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check for auto-refresh interval constant
    assert 'AUTO_REFRESH_INTERVAL' in content, "AUTO_REFRESH_INTERVAL constant not defined"
    assert '5000' in content, "Auto-refresh interval should be 5000ms (5 seconds)"


def test_auto_refresh_functions_defined():
    """Verify auto-refresh functions are defined."""
    with open('templates/ui/events_jacksonbot.html', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check for auto-refresh functions
    assert 'function startAutoRefresh' in content, "startAutoRefresh function not found"
    assert 'function stopAutoRefresh' in content, "stopAutoRefresh function not found"
    assert 'function updateLastUpdatedTimestamp' in content, "updateLastUpdatedTimestamp function not found"


def test_auto_refresh_timer_variable():
    """Verify auto-refresh timer variable is declared."""
    with open('templates/ui/events_jacksonbot.html', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check for timer variable
    assert 'let autoRefreshTimer' in content, "autoRefreshTimer variable not declared"


def test_auto_refresh_started_on_load():
    """Verify auto-refresh is started on DOMContentLoaded."""
    with open('templates/ui/events_jacksonbot.html', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check if startAutoRefresh is called in initialization
    dom_content_loaded_section = re.search(
        r"document\.addEventListener\('DOMContentLoaded'.*?\}\);",
        content,
        re.DOTALL
    )
    assert dom_content_loaded_section, "DOMContentLoaded listener not found"
    
    section_text = dom_content_loaded_section.group()
    assert 'startAutoRefresh' in section_text, "startAutoRefresh not called in DOMContentLoaded"


def test_auto_refresh_cleanup_on_unload():
    """Verify auto-refresh is cleaned up on page unload."""
    with open('templates/ui/events_jacksonbot.html', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check if stopAutoRefresh is called on beforeunload
    beforeunload_section = re.search(
        r"window\.addEventListener\('beforeunload'.*?\}\);",
        content,
        re.DOTALL
    )
    assert beforeunload_section, "beforeunload listener not found"
    
    section_text = beforeunload_section.group()
    assert 'stopAutoRefresh' in section_text, "stopAutoRefresh not called in beforeunload"


def test_dirty_rows_check_in_auto_refresh():
    """Verify auto-refresh checks for dirty rows before refreshing."""
    with open('templates/ui/events_jacksonbot.html', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find the startAutoRefresh function - check the entire function including callbacks
    start_auto_refresh_match = re.search(
        r'function startAutoRefresh\(\)\s*\{(.*?)(?=\n\s*function\s|\n\s*//\s*Stop)',
        content,
        re.DOTALL
    )
    assert start_auto_refresh_match, "startAutoRefresh function not found"
    
    function_body = start_auto_refresh_match.group(1)
    # Check if it checks dirtyRows before refreshing (in setInterval callback)
    assert 'dirtyRows.size === 0' in function_body, "Auto-refresh should check dirtyRows before refreshing"


def test_htmx_script_in_ui_render_page():
    """Verify HTMX script is included in _render_page function."""
    with open('app/routers/ui.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check for HTMX script tag presence (simpler check)
    assert 'htmx.org' in content, "HTMX script not found in ui.py"
    assert 'unpkg.com/htmx.org' in content, "HTMX CDN script not found in ui.py"


def test_is_user_actively_editing_function_exists():
    """Verify isUserActivelyEditing function is defined."""
    with open('templates/ui/events_jacksonbot.html', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check for isUserActivelyEditing function
    assert 'function isUserActivelyEditing' in content, "isUserActivelyEditing function not found"


def test_active_editing_check_in_auto_refresh():
    """Verify auto-refresh checks if user is actively editing before refreshing."""
    with open('templates/ui/events_jacksonbot.html', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find the startAutoRefresh function
    start_auto_refresh_match = re.search(
        r'function startAutoRefresh\(\)\s*\{(.*?)(?=\n\s*function\s|\n\s*//\s*Stop)',
        content,
        re.DOTALL
    )
    assert start_auto_refresh_match, "startAutoRefresh function not found"
    
    function_body = start_auto_refresh_match.group(1)
    # Check if it checks isUserActivelyEditing before refreshing
    assert 'isUserActivelyEditing()' in function_body, "Auto-refresh should check isUserActivelyEditing before refreshing"
    assert '!isUserActivelyEditing()' in function_body, "Auto-refresh should NOT refresh when user is actively editing"


def test_active_editing_checks_active_element():
    """Verify isUserActivelyEditing checks document.activeElement."""
    with open('templates/ui/events_jacksonbot.html', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find the isUserActivelyEditing function - match until the next function
    is_editing_match = re.search(
        r'function isUserActivelyEditing\(\)\s*\{(.*?)(?=\n\s+// Start auto-refresh)',
        content,
        re.DOTALL
    )
    assert is_editing_match, "isUserActivelyEditing function not found"
    
    function_body = is_editing_match.group(1)
    # Check that it uses document.activeElement
    assert 'document.activeElement' in function_body, "isUserActivelyEditing should check document.activeElement"
    # Check that it looks for INPUT, TEXTAREA
    assert 'tagName' in function_body, "isUserActivelyEditing should check element tagName"
    assert 'INPUT' in function_body, "isUserActivelyEditing should check for INPUT elements"
    assert 'TEXTAREA' in function_body, "isUserActivelyEditing should check for TEXTAREA elements"


def test_active_editing_checks_events_container():
    """Verify isUserActivelyEditing checks if element is within events container."""
    with open('templates/ui/events_jacksonbot.html', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find the isUserActivelyEditing function
    is_editing_match = re.search(
        r'function isUserActivelyEditing\(\)\s*\{(.*?)(?=\n\s+// Start auto-refresh)',
        content,
        re.DOTALL
    )
    assert is_editing_match, "isUserActivelyEditing function not found"
    
    function_body = is_editing_match.group(1)
    # Check that it verifies element is in eventsContainer
    assert 'eventsContainer' in function_body, "isUserActivelyEditing should check if element is in eventsContainer"
    assert 'closest' in function_body, "isUserActivelyEditing should use closest() to check parent container"
