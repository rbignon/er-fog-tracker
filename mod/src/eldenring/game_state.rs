//! Elden Ring GameStateReader implementation
//!
//! Reads player position and animation state from Elden Ring memory
//! using libeldenring pointer chains.

use std::collections::HashSet;
use std::time::Duration;

use libeldenring::memedit::PointerChain;
use libeldenring::pointers::Pointers;

use crate::core::constants::{
    GreatRune, FIELD_AREA_PLAY_REGION_ID_OFFSET, GAMEDATAMAN_DEATH_COUNT_OFFSET, INVALID_MAP_ID,
    INVENTORY_ENTRY_ITEM_ID_OFFSET, INVENTORY_ENTRY_QUANTITY_OFFSET, INVENTORY_ENTRY_SIZE,
    INVENTORY_SCAN_BUFFER, ITEM_CATEGORY_GOODS, KEY_ITEMS_COUNT_OFFSET, KEY_ITEMS_HEAD_OFFSET,
    MESSMERS_KINDLING,
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
