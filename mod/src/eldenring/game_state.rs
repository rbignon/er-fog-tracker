//! Elden Ring GameStateReader implementation
//!
//! Reads player position and animation state from Elden Ring memory
//! using libeldenring pointer chains.

use std::collections::HashSet;
use std::time::Duration;

use libeldenring::memedit::PointerChain;
use libeldenring::pointers::Pointers;

use crate::core::constants::{
    GreatRune, FIELD_AREA_PLAY_REGION_ID_OFFSET, GAMEDATAMAN_DEATH_COUNT_OFFSET,
    GREAT_RUNE_UNRESTORED_RANGE, INVALID_MAP_ID, INVENTORY_ENTRY_ITEM_ID_OFFSET,
    INVENTORY_ENTRY_QUANTITY_OFFSET, INVENTORY_ENTRY_SIZE, INVENTORY_SCAN_BUFFER,
    ITEM_CATEGORY_GOODS, KEY_ITEMS_COUNT_OFFSET, KEY_ITEMS_HEAD_OFFSET, MESSMERS_KINDLING,
};
use crate::core::map_utils::format_map_id;
use crate::core::traits::GameStateReader;
use crate::core::types::PlayerPosition;

/// Elden Ring game state reader
///
/// Uses libeldenring to read from Elden Ring's memory.
pub struct GameState {
    pointers: Pointers,
    play_region_id_ptr: PointerChain<u32>,
    death_count_ptr: PointerChain<u32>,
}

impl GameState {
    /// Create a new GameState reader
    pub fn new() -> Self {
        let pointers = Pointers::new();

        // Create pointer chain for PlayRegionId (FieldArea + 0xE4)
        let play_region_id_ptr = PointerChain::<u32>::new(&[
            pointers.base_addresses.field_area,
            FIELD_AREA_PLAY_REGION_ID_OFFSET,
        ]);

        // Create pointer chain for death count (GameDataMan + 0x94)
        let death_count_ptr = PointerChain::<u32>::new(&[
            pointers.base_addresses.game_data_man,
            GAMEDATAMAN_DEATH_COUNT_OFFSET,
        ]);

        Self {
            pointers,
            play_region_id_ptr,
            death_count_ptr,
        }
    }

    /// Get base addresses (for creating SpEffect and GameMan readers)
    pub fn base_addresses(&self) -> &libeldenring::prelude::base_addresses::BaseAddresses {
        &self.pointers.base_addresses
    }

    /// Read the death count from game memory
    ///
    /// Returns the total number of deaths for the current character.
    pub fn read_deaths(&self) -> Option<u32> {
        self.death_count_ptr.read()
    }

    /// Read the in-game time from game memory
    ///
    /// Returns the IGT in milliseconds.
    pub fn read_igt(&self) -> Option<u32> {
        // libeldenring reads IGT as usize but it's actually a u32 in milliseconds
        self.pointers.igt.read().map(|v| v as u32)
    }

    /// Read the set of possessed Great Runes
    ///
    /// Returns the set of unique Great Runes the player has.
    /// Restored and unrestored versions are deduplicated.
    pub fn read_great_runes(&self) -> Option<HashSet<GreatRune>> {
        let (key_items_head, key_items_count) = self.read_key_items_info()?;

        let mut found_runes: HashSet<GreatRune> = HashSet::new();

        // Scan beyond the reported count - the count field can be inaccurate
        // We add a buffer of 20 extra slots to catch items beyond the count
        let scan_count = key_items_count + INVENTORY_SCAN_BUFFER;

        for i in 0..scan_count {
            let entry_addr = key_items_head + (i as usize) * INVENTORY_ENTRY_SIZE;

            // Read item_id at entry + 0x04
            let item_id: i32 = PointerChain::new(&[entry_addr + INVENTORY_ENTRY_ITEM_ID_OFFSET])
                .read()
                .unwrap_or(0);

            // Skip empty/invalid slots (item_id == 0 or -1)
            if item_id == 0 || item_id == -1 {
                continue;
            }

            let category = ((item_id >> 28) & 0xF) as u8;
            let param_id = (item_id & 0x0FFFFFFF) as u32;

            if category == ITEM_CATEGORY_GOODS {
                if let Some(rune) = GreatRune::from_param_id(param_id) {
                    found_runes.insert(rune);
                }
            }
        }

        Some(found_runes)
    }

    /// Read the count of possessed Great Runes
    ///
    /// Returns the number of unique Great Runes (0-7).
    /// Restored and unrestored versions are deduplicated.
    pub fn read_great_runes_count(&self) -> Option<u32> {
        self.read_great_runes().map(|set| set.len() as u32)
    }

    /// Read the count of Messmer's Kindling
    ///
    /// Returns the total quantity of Kindling items.
    pub fn read_kindling_count(&self) -> Option<u32> {
        let (key_items_head, key_items_count) = self.read_key_items_info()?;

        let mut total = 0u32;

        // Scan beyond the reported count - the count field can be inaccurate
        let scan_count = key_items_count + INVENTORY_SCAN_BUFFER;

        for i in 0..scan_count {
            let entry_addr = key_items_head + (i as usize) * INVENTORY_ENTRY_SIZE;

            // Read item_id at entry + 0x04
            let item_id: i32 = PointerChain::new(&[entry_addr + INVENTORY_ENTRY_ITEM_ID_OFFSET])
                .read()
                .unwrap_or(0);

            // Skip empty/invalid slots
            if item_id == 0 || item_id == -1 {
                continue;
            }

            let category = ((item_id >> 28) & 0xF) as u8;
            let param_id = (item_id & 0x0FFFFFFF) as u32;

            if category == ITEM_CATEGORY_GOODS && param_id == MESSMERS_KINDLING {
                // Read quantity at entry + 0x08
                let quantity: u32 =
                    PointerChain::new(&[entry_addr + INVENTORY_ENTRY_QUANTITY_OFFSET])
                        .read()
                        .unwrap_or(0);
                total += quantity;
            }
        }

        Some(total)
    }

    /// Debug: dump all key items to find the correct Kindling param_id
    ///
    /// Logs all items in key_items inventory with their param_id and quantity.
    /// Also specifically identifies Great Runes (restored and unrestored).
    pub fn debug_dump_key_items(&self) {
        use tracing::info;

        let Some((key_items_head, key_items_count)) = self.read_key_items_info() else {
            info!("[DEBUG] Failed to read key_items_info");
            return;
        };

        // Scan beyond the reported count - the count field can be inaccurate
        let scan_count = key_items_count + INVENTORY_SCAN_BUFFER;

        info!(
            "[DEBUG] key_items: head=0x{:X}, count={} (scanning {} slots)",
            key_items_head, key_items_count, scan_count
        );

        // Track found Great Runes for summary
        let mut found_runes: Vec<(u32, bool, GreatRune)> = Vec::new(); // (param_id, is_restored, rune)

        for i in 0..scan_count {
            let entry_addr = key_items_head + (i as usize) * INVENTORY_ENTRY_SIZE;

            let item_id: i32 = PointerChain::new(&[entry_addr + INVENTORY_ENTRY_ITEM_ID_OFFSET])
                .read()
                .unwrap_or(0);

            // Skip empty/invalid slots
            if item_id == 0 || item_id == -1 {
                continue;
            }

            let quantity: u32 = PointerChain::new(&[entry_addr + INVENTORY_ENTRY_QUANTITY_OFFSET])
                .read()
                .unwrap_or(0);

            let category = ((item_id >> 28) & 0xF) as u8;
            let param_id = (item_id & 0x0FFFFFFF) as u32;

            // Check for Great Rune
            let mut marker = String::new();

            // Mark items beyond the reported count
            let beyond_count = i >= key_items_count;
            if beyond_count {
                marker = " [BEYOND COUNT]".to_string();
            }

            if category == ITEM_CATEGORY_GOODS {
                // Check if it's a Great Rune
                if let Some(rune) = GreatRune::from_param_id(param_id) {
                    let is_restored = !GREAT_RUNE_UNRESTORED_RANGE.contains(&param_id);
                    let status = if is_restored {
                        "RESTORED"
                    } else {
                        "UNRESTORED"
                    };
                    let prefix = if beyond_count { " [BEYOND COUNT]" } else { "" };
                    marker = format!("{} <-- GREAT RUNE: {:?} ({})", prefix, rune, status);
                    found_runes.push((param_id, is_restored, rune));
                }

                // Check for Kindling
                if param_id == MESSMERS_KINDLING {
                    let prefix = if beyond_count { " [BEYOND COUNT]" } else { "" };
                    marker = format!("{} <-- KINDLING (qty={})", prefix, quantity);
                }
            }

            // Highlight items with quantity 4 (potential Kindling)
            if quantity == 4 && marker.is_empty() {
                marker = " <-- QTY 4!".to_string();
            }

            info!(
                "[DEBUG] [{:3}] cat={} param_id={:8} (0x{:08X}) qty={}{}",
                i, category, param_id, param_id, quantity, marker
            );
        }

        // Summary of Great Runes
        info!("[DEBUG] ========== GREAT RUNES SUMMARY ==========");
        if found_runes.is_empty() {
            info!("[DEBUG] No Great Runes found in inventory");
        } else {
            for (param_id, is_restored, rune) in &found_runes {
                let status = if *is_restored {
                    "RESTORED"
                } else {
                    "UNRESTORED"
                };
                info!(
                    "[DEBUG] {:?}: param_id={} (0x{:08X}) - {}",
                    rune, param_id, param_id, status
                );
            }
            // Deduplicated count
            let unique_runes: std::collections::HashSet<_> =
                found_runes.iter().map(|(_, _, r)| r).collect();
            info!("[DEBUG] Total unique runes: {} / 7", unique_runes.len());
        }
        info!("[DEBUG] ============================================");

        // Additional debug: show ALL items with small param_ids that might be unknown Great Runes
        info!("[DEBUG] ========== POTENTIAL GREAT RUNES (param_id < 500) ==========");
        for i in 0..key_items_count {
            let entry_addr = key_items_head + (i as usize) * INVENTORY_ENTRY_SIZE;
            let item_id: i32 = PointerChain::new(&[entry_addr + INVENTORY_ENTRY_ITEM_ID_OFFSET])
                .read()
                .unwrap_or(0);
            let category = ((item_id >> 28) & 0xF) as u8;
            let param_id = (item_id & 0x0FFFFFFF) as u32;

            if category == ITEM_CATEGORY_GOODS && param_id < 500 {
                let known = GreatRune::from_param_id(param_id)
                    .map(|r| format!("{:?}", r))
                    .unwrap_or_else(|| "UNKNOWN".to_string());
                info!(
                    "[DEBUG] [{:3}] param_id={:3} (0x{:04X}) -> {}",
                    i, param_id, param_id, known
                );
            }
        }
        info!("[DEBUG] ============================================================");

        // Also show the param_id ranges for reference
        info!(
            "[DEBUG] Reference - Restored param_ids: Godrick=191, Radahn=192, Morgott=193, Rykard=194, Mohg=195, Malenia=196, Unborn=10080"
        );
        info!(
            "[DEBUG] Reference - Unrestored param_ids: 8148=Godrick, 8149=Radahn, 8150=Morgott, 8151=Rykard, 8152=Mohg, 8153=Malenia"
        );
    }

    /// Read key items inventory info (head pointer and count)
    fn read_key_items_info(&self) -> Option<(usize, u32)> {
        let game_data_man = self.pointers.base_addresses.game_data_man;

        // GameDataMan -> +0x8 -> PlayerGameData -> +0x428 -> key_items_head
        let key_items_head: usize =
            PointerChain::new(&[game_data_man, 0x8, KEY_ITEMS_HEAD_OFFSET]).read()?;

        // GameDataMan -> +0x8 -> PlayerGameData -> +0x430 -> key_items_count
        let key_items_count: u32 =
            PointerChain::new(&[game_data_man, 0x8, KEY_ITEMS_COUNT_OFFSET]).read()?;

        // Sanity check to avoid iterating too many items
        if key_items_count > 500 {
            return None;
        }

        Some((key_items_head, key_items_count))
    }
}

impl Default for GameState {
    fn default() -> Self {
        Self::new()
    }
}

impl GameStateReader for GameState {
    fn wait_for_game_loaded(&self) {
        let poll_interval = Duration::from_millis(100);
        loop {
            if let Some(menu_timer) = self.pointers.menu_timer.read() {
                if menu_timer > 0. {
                    break;
                }
            }
            std::thread::sleep(poll_interval);
        }
    }

    fn read_position(&self) -> Option<PlayerPosition> {
        let [x, y, z, _, _] = self.pointers.global_position.read()?;
        let map_id = self.pointers.global_position.read_map_id()?;

        // Check if position is valid (not during loading screen)
        if map_id == INVALID_MAP_ID || (x == 0.0 && y == 0.0 && z == 0.0) {
            return None;
        }

        Some(PlayerPosition {
            map_id,
            map_id_str: format_map_id(map_id),
            x,
            y,
            z,
            play_region_id: self.play_region_id_ptr.read(),
        })
    }

    fn read_animation(&self) -> Option<u32> {
        self.pointers.cur_anim.read()
    }
}
