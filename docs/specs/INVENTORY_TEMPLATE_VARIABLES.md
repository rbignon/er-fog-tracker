# Inventory Template Variables Implementation

## Overview

Add two new template variables to the status line template system:
- `{runes}` - Count of possessed Great Runes (0-8)
- `{kindling}` - Count of Messmer's Kindling items

## Motivation

For Fog Gate Randomizer runs, tracking progression items is useful:
- Great Runes indicate boss completion progress
- Messmer's Kindling indicates DLC exploration progress

Future enhancement: display icons for specific Great Runes (out of scope for this implementation).

## Usage Example

```toml
# In fog_rando_tracker.toml
status_template = "{zone}$>{status} {discovered}/{total} | R:{runes} K:{kindling}"
```

This would display: `Limgrave                    ● 42/100 | R:3 K:2`

---

## Technical Background

### Memory Structure

Great Runes and Kindling are stored in the **key_items** inventory array.

#### Pointer Chain

```
GameDataMan
  └→ +0x8 [ptr] → PlayerGameData
                    └→ +0x428 [ptr] → key_items_head (array)
                    └→ +0x430 [u32] → key_items_count
```

#### Inventory Entry Structure (0x18 bytes)

| Offset | Type | Field |
|--------|------|-------|
| 0x00 | u32 | gaitem_handle |
| 0x04 | i32 | item_id (bits 28-31: category, bits 0-27: param_id) |
| 0x08 | u32 | quantity |
| 0x0C | u32 | sort_id |
| 0x14 | i32 | pot_group |

### Item IDs

All items are **Goods** (category = 4).

**Great Runes:**

| Item | param_id (restored) | param_id (unrestored) |
|------|---------------------|----------------------|
| Godrick's Great Rune | 191 | 8148 |
| Radahn's Great Rune | 192 | 8149 |
| Morgott's Great Rune | 193 | 8150 |
| Rykard's Great Rune | 194 | 8151 |
| Mohg's Great Rune | 195 | 8152 |
| Malenia's Great Rune | 196 | 8153 |
| Great Rune of the Unborn | 10080 | - |
| Miquella's Great Rune | 2008000 | - |

**Messmer's Kindling:**

| Item | param_id |
|------|----------|
| Messmer's Kindling | 2007509 |

### Deduplication

Restored and unrestored Great Runes count as the same rune. The count represents unique runes possessed, not total items.

---

## Implementation Plan

### 1. Add Constants (`mod/src/core/constants.rs`)

```rust
// =============================================================================
// INVENTORY READING
// =============================================================================

/// Item category for Goods (consumables, key items)
pub const ITEM_CATEGORY_GOODS: u8 = 4;

/// Offset from PlayerGameData to key_items_head pointer
pub const KEY_ITEMS_HEAD_OFFSET: usize = 0x428;

/// Offset from PlayerGameData to key_items_count
pub const KEY_ITEMS_COUNT_OFFSET: usize = 0x430;

/// Size of each inventory entry (EquipInventoryDataListEntry)
pub const INVENTORY_ENTRY_SIZE: usize = 0x18;

/// Offset to item_id within inventory entry
pub const INVENTORY_ENTRY_ITEM_ID_OFFSET: usize = 0x04;

/// Offset to quantity within inventory entry
pub const INVENTORY_ENTRY_QUANTITY_OFFSET: usize = 0x08;

// Great Rune param_ids (restored versions)
pub const GREAT_RUNE_GODRICK: u32 = 191;
pub const GREAT_RUNE_RADAHN: u32 = 192;
pub const GREAT_RUNE_MORGOTT: u32 = 193;
pub const GREAT_RUNE_RYKARD: u32 = 194;
pub const GREAT_RUNE_MOHG: u32 = 195;
pub const GREAT_RUNE_MALENIA: u32 = 196;
pub const GREAT_RUNE_UNBORN: u32 = 10080;
pub const GREAT_RUNE_MIQUELLA: u32 = 2008000;

// Great Rune param_ids (unrestored versions)
pub const GREAT_RUNE_UNRESTORED_START: u32 = 8148;
pub const GREAT_RUNE_UNRESTORED_END: u32 = 8153;

/// Messmer's Kindling param_id
pub const MESSMERS_KINDLING: u32 = 2007509;
```

### 2. Add Template Variables (`mod/src/core/status_template.rs`)

#### Update TemplateContext

```rust
pub struct TemplateContext {
    // ... existing fields ...

    /// Number of Great Runes possessed (deduplicated)
    pub runes: Option<u32>,
    /// Number of Messmer's Kindling items
    pub kindling: Option<u32>,
}

impl Default for TemplateContext {
    fn default() -> Self {
        Self {
            // ... existing fields ...
            runes: None,
            kindling: None,
        }
    }
}
```

#### Update substitute_variables

```rust
fn substitute_variables(template: &str, ctx: &TemplateContext, has_status: &mut bool) -> String {
    // ... existing substitutions ...

    // {runes} - Great Runes count
    let runes_value = ctx.runes.map(|r| r.to_string()).unwrap_or_default();
    result = result.replace("{runes}", &runes_value);

    // {kindling} - Messmer's Kindling count
    let kindling_value = ctx.kindling.map(|k| k.to_string()).unwrap_or_default();
    result = result.replace("{kindling}", &kindling_value);

    result
}
```

#### Add Tests

```rust
#[test]
fn test_runes() {
    let ctx = TemplateContext {
        runes: Some(5),
        ..default_ctx()
    };
    let result = render_template("Runes: {runes}/8", &ctx);
    assert_eq!(result.lines[0].left_text(), Some("Runes: 5/8"));
}

#[test]
fn test_kindling() {
    let ctx = TemplateContext {
        kindling: Some(3),
        ..default_ctx()
    };
    let result = render_template("Kindling: {kindling}", &ctx);
    assert_eq!(result.lines[0].left_text(), Some("Kindling: 3"));
}

#[test]
fn test_runes_none() {
    let ctx = TemplateContext {
        runes: None,
        ..default_ctx()
    };
    let result = render_template("R:{runes}", &ctx);
    assert_eq!(result.lines[0].left_text(), Some("R:"));
}
```

### 3. Add Memory Reading (`mod/src/eldenring/game_state.rs`)

```rust
use crate::core::constants::{
    GREAT_RUNE_GODRICK, GREAT_RUNE_RADAHN, GREAT_RUNE_MORGOTT,
    GREAT_RUNE_RYKARD, GREAT_RUNE_MOHG, GREAT_RUNE_MALENIA,
    GREAT_RUNE_UNBORN, GREAT_RUNE_MIQUELLA,
    GREAT_RUNE_UNRESTORED_START, GREAT_RUNE_UNRESTORED_END,
    MESSMERS_KINDLING, ITEM_CATEGORY_GOODS,
    KEY_ITEMS_HEAD_OFFSET, KEY_ITEMS_COUNT_OFFSET,
    INVENTORY_ENTRY_SIZE, INVENTORY_ENTRY_ITEM_ID_OFFSET,
    INVENTORY_ENTRY_QUANTITY_OFFSET,
};

impl GameState {
    // ... existing methods ...

    /// Read the count of possessed Great Runes
    ///
    /// Returns the number of unique Great Runes (0-8).
    /// Restored and unrestored versions are deduplicated.
    pub fn read_great_runes_count(&self) -> Option<u32> {
        self.count_inventory_items(Self::is_great_rune)
    }

    /// Read the count of Messmer's Kindling
    pub fn read_kindling_count(&self) -> Option<u32> {
        self.sum_inventory_items(|param_id| param_id == MESSMERS_KINDLING)
    }

    /// Get PlayerGameData pointer
    fn get_player_game_data(&self) -> Option<usize> {
        let game_data_man = self.pointers.base_addresses.game_data_man;
        // GameDataMan -> +0x8 -> PlayerGameData
        PointerChain::<usize>::new(&[game_data_man, 0x8]).read()
    }

    /// Count unique items matching a predicate (for Great Runes)
    fn count_inventory_items<F>(&self, matches: F) -> Option<u32>
    where
        F: Fn(u32) -> bool,
    {
        let player_game_data = self.get_player_game_data()?;

        let key_items_head = PointerChain::<usize>::new(&[
            player_game_data + KEY_ITEMS_HEAD_OFFSET,
        ]).read()?;

        let key_items_count = PointerChain::<u32>::new(&[
            player_game_data + KEY_ITEMS_COUNT_OFFSET,
        ]).read()?;

        // Sanity check
        if key_items_count > 500 {
            return None;
        }

        let mut found = std::collections::HashSet::new();

        for i in 0..key_items_count {
            let entry_addr = key_items_head + (i as usize) * INVENTORY_ENTRY_SIZE;

            let item_id = PointerChain::<i32>::new(&[
                entry_addr + INVENTORY_ENTRY_ITEM_ID_OFFSET,
            ]).read()?;

            let category = ((item_id >> 28) & 0xF) as u8;
            let param_id = (item_id & 0x0FFFFFFF) as u32;

            if category == ITEM_CATEGORY_GOODS && matches(param_id) {
                // Normalize unrestored to restored for deduplication
                let normalized = Self::normalize_great_rune(param_id);
                found.insert(normalized);
            }
        }

        Some(found.len() as u32)
    }

    /// Sum quantities of items matching a predicate (for Kindling)
    fn sum_inventory_items<F>(&self, matches: F) -> Option<u32>
    where
        F: Fn(u32) -> bool,
    {
        let player_game_data = self.get_player_game_data()?;

        let key_items_head = PointerChain::<usize>::new(&[
            player_game_data + KEY_ITEMS_HEAD_OFFSET,
        ]).read()?;

        let key_items_count = PointerChain::<u32>::new(&[
            player_game_data + KEY_ITEMS_COUNT_OFFSET,
        ]).read()?;

        if key_items_count > 500 {
            return None;
        }

        let mut total = 0u32;

        for i in 0..key_items_count {
            let entry_addr = key_items_head + (i as usize) * INVENTORY_ENTRY_SIZE;

            let item_id = PointerChain::<i32>::new(&[
                entry_addr + INVENTORY_ENTRY_ITEM_ID_OFFSET,
            ]).read()?;

            let quantity = PointerChain::<u32>::new(&[
                entry_addr + INVENTORY_ENTRY_QUANTITY_OFFSET,
            ]).read().unwrap_or(0);

            let category = ((item_id >> 28) & 0xF) as u8;
            let param_id = (item_id & 0x0FFFFFFF) as u32;

            if category == ITEM_CATEGORY_GOODS && matches(param_id) {
                total += quantity;
            }
        }

        Some(total)
    }

    /// Check if param_id is a Great Rune
    fn is_great_rune(param_id: u32) -> bool {
        matches!(param_id,
            GREAT_RUNE_GODRICK | GREAT_RUNE_RADAHN | GREAT_RUNE_MORGOTT |
            GREAT_RUNE_RYKARD | GREAT_RUNE_MOHG | GREAT_RUNE_MALENIA |
            GREAT_RUNE_UNBORN | GREAT_RUNE_MIQUELLA |
            GREAT_RUNE_UNRESTORED_START..=GREAT_RUNE_UNRESTORED_END
        )
    }

    /// Normalize unrestored Great Rune param_id to restored version
    fn normalize_great_rune(param_id: u32) -> u32 {
        if (GREAT_RUNE_UNRESTORED_START..=GREAT_RUNE_UNRESTORED_END).contains(&param_id) {
            // 8148 -> 191, 8149 -> 192, etc.
            param_id - GREAT_RUNE_UNRESTORED_START + GREAT_RUNE_GODRICK
        } else {
            param_id
        }
    }
}
```

### 4. Add Tracker Wrappers (`mod/src/dll/tracker.rs`)

```rust
impl FogRandoTracker {
    // ... existing methods ...

    /// Get the Great Runes count from game memory
    pub fn read_great_runes_count(&self) -> Option<u32> {
        self.game_state.read_great_runes_count()
    }

    /// Get the Messmer's Kindling count from game memory
    pub fn read_kindling_count(&self) -> Option<u32> {
        self.game_state.read_kindling_count()
    }
}
```

### 5. Wire Up Template Context (`mod/src/dll/ui.rs`)

```rust
fn build_template_context(&self) -> TemplateContext {
    let map_id = self.get_current_position().map(|(id, _)| format_map_id(id));

    TemplateContext {
        zone: self.current_zone().map(String::from),
        zone_unknown_text: self.config.overlay.zone_unknown_text.clone(),
        discovered: self.discovery_stats().map(|s| s.discovered).unwrap_or(0),
        total: self.discovery_stats().map(|s| s.total).unwrap_or(0),
        server_enabled: self.is_server_enabled(),
        server_connected: matches!(self.ws_status(), ConnectionStatus::Connected),
        map_id,
        deaths: self.read_deaths(),
        igt_ms: self.read_igt(),
        runes: self.read_great_runes_count(),      // NEW
        kindling: self.read_kindling_count(),       // NEW
    }
}
```

### 6. Update Documentation (`mod/fog_rando_tracker.toml`)

Add to the template variables documentation:

```toml
# Status line template
# Variables:
#   {zone}       - Current zone name (or zone_unknown_text if unknown)
#   {discovered} - Number of discovered random links
#   {total}      - Total number of random links
#   {progress}   - Discovery percentage (0-100)
#   {status}     - Server connection indicator (colored dot)
#   {map}        - Current map ID (e.g., "m60_44_36_00")
#   {deaths}     - Total death count for the character
#   {igt}        - In-game time (format: H:MM:SS)
#   {runes}      - Number of Great Runes possessed (0-8)
#   {kindling}   - Number of Messmer's Kindling items
```

---

## Testing

### Unit Tests

- `test_runes` - Basic substitution
- `test_kindling` - Basic substitution
- `test_runes_none` - None value handling
- `test_kindling_none` - None value handling

### Manual Testing

1. Load a save with known Great Runes
2. Verify `{runes}` shows correct count
3. Pick up a Great Rune, verify count updates
4. Verify restored/unrestored are deduplicated
5. Test with Kindling items

---

## Files Modified

| File | Changes |
|------|---------|
| `mod/src/core/constants.rs` | Add inventory constants |
| `mod/src/core/status_template.rs` | Add `runes`, `kindling` to context + substitution |
| `mod/src/eldenring/game_state.rs` | Add inventory reading methods |
| `mod/src/dll/tracker.rs` | Add wrapper methods |
| `mod/src/dll/ui.rs` | Wire up in `build_template_context` |
| `mod/fog_rando_tracker.toml` | Document new variables |

---

## Future Enhancements

- Display icons for specific Great Runes (requires UI work)
- Track which specific runes are possessed (enum set)
- Add `{runes_list}` variable showing "G R M R M M U Q" style output

---

*Created: 2025-12-27*
