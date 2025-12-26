# Code Review Response

## Review Comment: HTMX Duplication

**Comment:** "HTMX script is loaded twice - once in the template head and once in the global `_render_page()` function."

**Response:** This is a false positive. There is no duplication.

### Explanation:

The repository has two different rendering approaches:

1. **JacksonBot Events UI** (`/ui/events`):
   - Uses standalone template: `templates/ui/events_jacksonbot.html`
   - Returned directly via `HTMLResponse(content=f.read())`
   - Does NOT use `_render_page()` function
   - HTMX script included once in the template head

2. **Legacy UI pages** (contacts, messages, etc.):
   - Use `_render_page()` function in `app/routers/ui.py`
   - HTMX script included once in `_render_page()`

### Code Evidence:

```python
# app/routers/ui.py, line 602
@router.get("/ui/events", response_class=HTMLResponse)
async def list_events() -> HTMLResponse:
    """JacksonBot redesigned events UI."""
    with open("templates/ui/events_jacksonbot.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())  # Direct return - no _render_page()
```

### Conclusion:

The HTMX script appears in both locations to support both rendering approaches:
- Events page gets HTMX from its standalone template
- Legacy pages get HTMX from _render_page()

**No duplication occurs** because pages use one approach or the other, never both.
