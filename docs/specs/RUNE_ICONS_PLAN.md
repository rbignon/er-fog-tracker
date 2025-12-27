# Implementation Plan: Great Rune Icons in Status Template

## Overview

Add a `{rune_icons}` variable to the status template system that displays 7 Great Rune icons. Each icon is colored when possessed and grayed out when not.

## Files to Create

| File | Description |
|------|-------------|
| `mod/src/dll/rune_icons.rs` | Texture loading via `include_bytes!` + `image` crate |
| `mod/assets/runes/*.png` | 14 images (7 colored + 7 gray), 128×128 PNG |

## Files to Modify

| File | Changes |
|------|---------|
| `Cargo.toml` | Add `image` dependency |
| `core/status_template.rs` | Add `ContentSpan::RuneIcons` + parsing for `{rune_icons}` |
| `eldenring/game_state.rs` | Add `read_great_runes()` → `HashSet<GreatRune>` |
| `dll/tracker.rs` | Store `rune_textures` + `possessed_runes` |
| `dll/ui.rs` | Load textures in `initialize()`, render icons in `render_rune_icons()` |
| `dll/mod.rs` | Export new module |

## Technical Details

### Image Assets

Location: `mod/assets/runes/`

Files (128×128 PNG with transparency):
- `godrick.png`, `godrick_gray.png`
- `radahn.png`, `radahn_gray.png`
- `morgott.png`, `morgott_gray.png`
- `rykard.png`, `rykard_gray.png`
- `mohg.png`, `mohg_gray.png`
- `malenia.png`, `malenia_gray.png`
- `unborn.png`, `unborn_gray.png`

### Texture Loading

Use hudhook's `RenderContext::load_texture(data, width, height)` in `initialize()`.
Decode PNG to RGBA using the `image` crate.

### Template Rendering

New enum variant to handle mixed text/image content:

```rust
pub enum ContentSpan {
    Text(TextSpan),
    RuneIcons,
}
```

### Icon Display

- Icons scale proportionally to `font_size`
- Use `Image::new(texture_id, [size, size]).build(ui)`
- 2px spacing between icons

### Game State

Expose `read_great_runes()` returning `HashSet<GreatRune>` instead of just count.

## Implementation Order

1. Add `image` dependency to Cargo.toml
2. Create `rune_icons.rs` (embedded bytes + loading)
3. Modify `game_state.rs` (expose HashSet)
4. Modify `status_template.rs` (ContentSpan + parsing)
5. Modify `tracker.rs` (new fields)
6. Modify `ui.rs` (initialize + render)
7. Update `dll/mod.rs` exports
8. Tests
