// Zone name mapping for Elden Ring map IDs
//
// Maps map_id (area number + grid coordinates) to human-readable zone names.
// Used to display zone names for fog wall traversals.
// Data extracted from fog randomizer (fog.txt).

// DLC zone boundaries intentionally overlap at edges (e.g., Gravesite Plain / Charo's Hidden Grave)
#![allow(overlapping_range_endpoints)]

// =============================================================================
// MAP ID UTILITIES
// =============================================================================

/// Parse a u32 map_id into its components (area_no, grid_x, grid_z, dd)
///
/// The map_id is packed as: 0xWWXXYYDD
/// - WW = area number (60 for overworld)
/// - XX = grid X index
/// - YY = grid Z index
/// - DD = always 00
pub fn parse_map_id(map_id: u32) -> (u8, u8, u8, u8) {
    let ww = ((map_id >> 24) & 0xFF) as u8;
    let xx = ((map_id >> 16) & 0xFF) as u8;
    let yy = ((map_id >> 8) & 0xFF) as u8;
    let dd = (map_id & 0xFF) as u8;
    (ww, xx, yy, dd)
}

/// Format a map_id as a string "mWW_XX_YY_DD"
pub fn format_map_id(map_id: u32) -> String {
    let (ww, xx, yy, dd) = parse_map_id(map_id);
    format!("m{:02}_{:02}_{:02}_{:02}", ww, xx, yy, dd)
}

// =============================================================================
// LEGACY DUNGEON / UNDERGROUND AREA NAMES (by area number)
// =============================================================================

/// Get zone name for legacy dungeons and special areas (non-overworld maps)
fn get_legacy_zone_name(area_no: u8, grid_x: u8) -> Option<&'static str> {
    match area_no {
        // Major legacy dungeons
        10 => Some("Stormveil Castle"),
        11 => match grid_x {
            0 => Some("Leyndell, Royal Capital"),
            5 => Some("Leyndell, Ashen Capital"),
            10 => Some("Roundtable Hold"),
            _ => Some("Leyndell"),
        },
        13 => Some("Crumbling Farum Azula"),
        14 => Some("Academy of Raya Lucaria"),
        15 => Some("Miquella's Haligtree"),
        16 => Some("Volcano Manor"),
        18 => Some("Stranded Graveyard"),
        19 => Some("Erdtree"),

        // Underground areas (area 12 with different grid_x values)
        12 => match grid_x {
            1 => Some("Ainsel River"),
            2 => Some("Nokron, Eternal City"),
            3 => Some("Deeproot Depths"),
            4 => Some("Ainsel River"),
            5 => Some("Mohgwyn Palace"),
            7 => Some("Siofra River Bank"),
            8 => Some("Siofra River"),
            9 => Some("Nokron, Eternal City"),
            _ => Some("Underground"),
        },

        // DLC legacy dungeons
        20 => match grid_x {
            0 => Some("Belurat, Tower Settlement"),
            1 => Some("Enir-Ilim"),
            _ => Some("Belurat"),
        },
        21 => match grid_x {
            0 => Some("Shadow Keep"),
            1 => Some("Specimen Storehouse"),
            2 => Some("Shadow Keep - West Rampart"),
            _ => Some("Shadow Keep"),
        },
        22 => Some("Stone Coffin Fissure"),
        25 => Some("Finger Birthing Grounds"),
        28 => Some("Midra's Manse"),

        // Catacombs (area 30) - specific names by grid_x
        30 => match grid_x {
            0 => Some("Tombsward Catacombs"),
            1 => Some("Impaler's Catacombs"),
            2 => Some("Stormfoot Catacombs"),
            3 => Some("Road's End Catacombs"),
            4 => Some("Murkwater Catacombs"),
            5 => Some("Black Knife Catacombs"),
            6 => Some("Cliffbottom Catacombs"),
            7 => Some("Wyndham Catacombs"),
            8 => Some("Sainted Hero's Grave"),
            9 => Some("Gelmir Hero's Grave"),
            10 => Some("Auriza Hero's Grave"),
            11 => Some("Deathtouched Catacombs"),
            12 => Some("Unsightly Catacombs"),
            13 => Some("Auriza Side Tomb"),
            14 => Some("Minor Erdtree Catacombs"),
            15 => Some("Caelid Catacombs"),
            16 => Some("War-Dead Catacombs"),
            17 => Some("Giant-Conquering Hero's Grave"),
            18 => Some("Giants' Mountaintop Catacombs"),
            19 => Some("Consecrated Snowfield Catacombs"),
            20 => Some("Hidden Path to the Haligtree"),
            _ => Some("Catacombs"),
        },

        // Caves (area 31) - specific names by grid_x
        31 => match grid_x {
            0 => Some("Murkwater Cave"),
            1 => Some("Earthbore Cave"),
            2 => Some("Tombsward Cave"),
            3 => Some("Groveside Cave"),
            4 => Some("Stillwater Cave"),
            5 => Some("Lakeside Crystal Cave"),
            6 => Some("Academy Crystal Cave"),
            7 => Some("Seethewater Cave"),
            9 => Some("Volcano Cave"),
            10 => Some("Dragonbarrow Cave"),
            11 => Some("Sellia Hideaway"),
            12 => Some("Cave of the Forlorn"),
            15 => Some("Coastal Cave"),
            17 => Some("Highroad Cave"),
            18 => Some("Perfumer's Grotto"),
            19 => Some("Sage's Cave"),
            20 => Some("Abandoned Cave"),
            21 => Some("Gaol Cave"),
            22 => Some("Spiritcaller's Cave"),
            _ => Some("Cave"),
        },

        // Tunnels (area 32) - specific names by grid_x
        32 => match grid_x {
            0 => Some("Morne Tunnel"),
            1 => Some("Limgrave Tunnels"),
            2 => Some("Raya Lucaria Crystal Tunnel"),
            4 => Some("Old Altus Tunnel"),
            5 => Some("Altus Tunnel"),
            7 => Some("Gael Tunnel"),
            8 => Some("Sellia Crystal Tunnel"),
            11 => Some("Yelough Anix Tunnel"),
            _ => Some("Tunnel"),
        },

        // Divine Towers (area 34) - specific names by grid_x
        34 => match grid_x {
            10 => Some("Divine Tower of Limgrave"),
            11 => Some("Divine Tower of Liurnia"),
            12 => Some("Divine Tower of West Altus"),
            13 => Some("Divine Tower of Caelid"),
            14 => Some("Divine Tower of East Altus"),
            15 => Some("Isolated Divine Tower"),
            _ => Some("Divine Tower"),
        },

        35 => Some("Subterranean Shunning-Grounds"),
        39 => Some("Ruin-Strewn Precipice"),

        // DLC Catacombs (area 40)
        40 => match grid_x {
            0 => Some("Fog Rift Catacombs"),
            1 => Some("Scorpion River Catacombs"),
            2 => Some("Darklight Catacombs"),
            _ => Some("Catacombs"),
        },

        // DLC Gaols (area 41)
        41 => match grid_x {
            0 => Some("Belurat Gaol"),
            1 => Some("Bonny Gaol"),
            2 => Some("Lamenter's Gaol"),
            _ => Some("Gaol"),
        },

        // DLC Ruined Forges (area 42)
        42 => match grid_x {
            0 => Some("Ruined Forge Lava Intake"),
            2 => Some("Ruined Forge of Starfall Past"),
            3 => Some("Taylew's Ruined Forge"),
            _ => Some("Ruined Forge"),
        },

        // DLC misc (area 43)
        43 => match grid_x {
            0 => Some("Rivermouth Cave"),
            1 => Some("Dragon's Pit"),
            _ => Some("Dungeon"),
        },

        // Colosseums (area 45)
        45 => match grid_x {
            0 => Some("Royal Colosseum"),
            1 => Some("Caelid Colosseum"),
            2 => Some("Limgrave Colosseum"),
            _ => Some("Colosseum"),
        },

        _ => None,
    }
}

// =============================================================================
// OVERWORLD TILE MAPPING (precise per-tile names from fog randomizer)
// =============================================================================

/// Get precise zone name for overworld tiles
/// Data extracted from fog randomizer fog.txt
fn get_overworld_tile_name(area_no: u8, grid_x: u8, grid_z: u8) -> Option<&'static str> {
    match (area_no, grid_x, grid_z) {
        // Liurnia / Moonlight Altar
        (60, 33, 40) => Some("Moonlight Altar"),
        (60, 33, 41) => Some("Moonlight Altar"),
        (60, 33, 42) => Some("Moonlight Altar"),
        (60, 34, 41) => Some("Moonlight Altar"),
        (60, 34, 42) => Some("Moonlight Altar"),
        (60, 35, 41) => Some("Moonlight Altar"),
        (60, 35, 42) => Some("Moonlight Altar"),
        (60, 36, 41) => Some("Moonlight Altar"),
        (60, 36, 42) => Some("Moonlight Altar"),

        // Liurnia
        (60, 33, 43..=47) => Some("Liurnia"),
        (60, 34, 43..=50) => Some("Liurnia"),
        (60, 35, 43..=50) => Some("Liurnia"),
        (60, 36, 43..=50) => Some("Liurnia"),
        (60, 37, 41..=48) => Some("Liurnia"),
        (60, 37, 50) => Some("Liurnia"),
        (60, 38, 39..=48) => Some("Liurnia"),
        (60, 38, 50) => Some("Liurnia"),
        (60, 39, 39..=46) => Some("Liurnia"),
        (60, 39, 48) => Some("Liurnia"),
        (60, 40, 40) => Some("Liurnia"),

        // Liurnia Behind Caria Manor
        (60, 34, 51) => Some("Liurnia Behind Caria Manor"),
        (60, 35, 51) => Some("Liurnia Behind Caria Manor"),

        // Bellum Highway
        (60, 36, 47..=49) => Some("Bellum Highway"),
        (60, 37, 49) => Some("Bellum Highway"),
        (60, 38, 49) => Some("Bellum Highway"),
        (60, 39, 49) => Some("Bellum Highway"),

        // Mt. Gelmir
        (60, 35, 52..=54) => Some("Mt. Gelmir"),
        (60, 36, 53..=54) => Some("Mt. Gelmir"),
        (60, 37, 53..=55) => Some("Mt. Gelmir"),
        (60, 38, 53..=54) => Some("Mt. Gelmir"),
        (60, 39, 53..=54) => Some("Mt. Gelmir"),

        // Altus Plateau
        (60, 36, 51..=52) => Some("Altus Plateau"),
        (60, 37, 51..=52) => Some("Altus Plateau"),
        (60, 38, 51..=52) => Some("Altus Plateau"),
        (60, 39, 50..=52) => Some("Altus Plateau"),
        (60, 40, 50..=55) => Some("Altus Plateau"),
        (60, 41, 50..=55) => Some("Altus Plateau"),
        (60, 42, 52..=55) => Some("Altus Plateau"),
        (60, 43, 53..=54) => Some("Altus Plateau"),

        // Capital Outskirts
        (60, 42, 50..=51) => Some("Capital Outskirts"),
        (60, 43, 50..=52) => Some("Capital Outskirts"),
        (60, 44, 52..=53) => Some("Capital Outskirts"),
        (60, 45, 51..=53) => Some("Capital Outskirts"),

        // Weeping Peninsula
        (60, 40, 33) => Some("Weeping Peninsula"),
        (60, 41, 32..=34) => Some("Weeping Peninsula"),
        (60, 42, 32..=34) => Some("Weeping Peninsula"),
        (60, 43, 30..=33) => Some("Weeping Peninsula"),
        (60, 44, 31..=33) => Some("Weeping Peninsula"),
        (60, 45, 32..=34) => Some("Weeping Peninsula"),

        // Limgrave special
        (60, 41, 35) => Some("Church of Dragon Communion"),

        // Limgrave
        (60, 41, 36..=37) => Some("Limgrave"),
        (60, 42, 35..=38) => Some("Limgrave"),
        (60, 43, 34..=40) => Some("Limgrave"),
        (60, 44, 34..=39) => Some("Limgrave"),
        (60, 45, 35..=40) => Some("Limgrave"),
        (60, 46, 36..=40) => Some("Limgrave"),

        // Stormhill
        (60, 40, 38..=39) => Some("Stormhill"),
        (60, 41, 38..=39) => Some("Stormhill"),
        (60, 42, 39..=40) => Some("Stormhill"),

        // Caelid
        (60, 47, 37..=40) => Some("Caelid"),
        (60, 48, 36..=40) => Some("Caelid"),
        (60, 49, 36..=39) => Some("Caelid"),
        (60, 50, 36..=39) => Some("Caelid"),
        (60, 51, 35..=38) => Some("Caelid"),
        (60, 52, 37..=40) => Some("Caelid"),
        (60, 53, 38..=39) => Some("Caelid"),

        // Caelid Greatjar (special area)
        (60, 47, 41..=42) => Some("Caelid Greatjar"),
        (60, 49, 40) => Some("Caelid Greatjar"),

        // Dragonbarrow
        (60, 48, 41) => Some("Dragonbarrow"),
        (60, 49, 41) => Some("Dragonbarrow"),
        (60, 50, 40..=41) => Some("Dragonbarrow"),
        (60, 51, 39..=43) => Some("Dragonbarrow"),
        (60, 52, 41..=43) => Some("Dragonbarrow"),

        // Forbidden Lands
        (60, 47, 51) => Some("Forbidden Lands"),
        (60, 48, 51) => Some("Forbidden Lands"),
        (60, 49, 52..=53) => Some("Forbidden Lands"),

        // Consecrated Snowfield
        (60, 46, 55) => Some("Consecrated Snowfield"),
        (60, 46, 57) => Some("Consecrated Snowfield"),
        (60, 47, 55..=58) => Some("Consecrated Snowfield"),
        (60, 48, 54..=58) => Some("Consecrated Snowfield"),
        (60, 49, 54..=57) => Some("Consecrated Snowfield"),
        (60, 50, 55) => Some("Consecrated Snowfield"),

        // Mountaintops of the Giants
        (60, 50, 53..=54) => Some("Mountaintops of the Giants"),
        (60, 50, 56..=57) => Some("Mountaintops of the Giants"),
        (60, 51, 55..=58) => Some("Mountaintops of the Giants"),
        (60, 52, 55..=58) => Some("Mountaintops of the Giants"),
        (60, 53, 55..=58) => Some("Mountaintops of the Giants"),
        (60, 54, 55..=57) => Some("Mountaintops of the Giants"),

        // Flame Peak
        (60, 51, 52..=54) => Some("Flame Peak"),
        (60, 52, 52..=54) => Some("Flame Peak"),
        (60, 53, 52..=54) => Some("Flame Peak"),
        (60, 54, 53) => Some("Flame Peak"),

        // =========================================================================
        // DLC - Shadow of the Erdtree (area 61)
        // =========================================================================

        // Gravesite Plain
        (61, 44, 41) => Some("Gravesite Plain"),
        (61, 44, 43) => Some("Gravesite Plain"),
        (61, 45, 40..=44) => Some("Gravesite Plain"),
        (61, 46, 40..=44) => Some("Gravesite Plain"),
        (61, 47, 40..=45) => Some("Gravesite Plain"),
        (61, 48, 40..=43) => Some("Gravesite Plain"),
        (61, 49, 42..=43) => Some("Gravesite Plain"),

        // Cerulean Coast
        (61, 46, 35) => Some("Cerulean Coast"),
        (61, 46, 38..=39) => Some("Cerulean Coast"),
        (61, 47, 35..=40) => Some("Cerulean Coast"),
        (61, 48, 37..=39) => Some("Cerulean Coast"),
        (61, 49, 37..=38) => Some("Cerulean Coast"),
        (61, 50, 37) => Some("Cerulean Coast"),

        // Charo's Hidden Grave
        (61, 45, 39) => Some("Charo's Hidden Grave"),
        (61, 46, 39..=40) => Some("Charo's Hidden Grave"),
        (61, 47, 39..=40) => Some("Charo's Hidden Grave"),
        (61, 48, 38..=40) => Some("Charo's Hidden Grave"),
        (61, 49, 38..=39) => Some("Charo's Hidden Grave"),

        // Ellac River
        (61, 46, 43..=45) => Some("Ellac River"),
        (61, 47, 41..=43) => Some("Ellac River"),
        (61, 48, 40..=41) => Some("Ellac River"),

        // Castle Ensis
        (61, 47, 44) => Some("Castle Ensis"),
        (61, 48, 44) => Some("Castle Ensis"),

        // Rauh Base
        (61, 44, 46..=48) => Some("Rauh Base"),
        (61, 45, 45..=48) => Some("Rauh Base"),
        (61, 46, 46..=47) => Some("Rauh Base"),
        (61, 47, 47..=48) => Some("Rauh Base"),
        (61, 48, 48) => Some("Rauh Base"),

        // Ancient Ruins of Rauh
        (61, 44, 45) => Some("Ancient Ruins of Rauh"),
        (61, 45, 46) => Some("Ancient Ruins of Rauh"),
        (61, 46, 46..=48) => Some("Ancient Ruins of Rauh"),
        (61, 47, 46..=48) => Some("Ancient Ruins of Rauh"),

        // West Scadu Altus
        (61, 47, 44..=46) => Some("Scadu Altus"),
        (61, 48, 43..=47) => Some("Scadu Altus"),
        (61, 49, 43..=47) => Some("Scadu Altus"),
        (61, 50, 43..=45) => Some("Scadu Altus"),

        // East Scadu Altus
        (61, 49, 44) => Some("Scadu Altus"),
        (61, 50, 44..=47) => Some("Scadu Altus"),
        (61, 51, 44..=47) => Some("Scadu Altus"),
        (61, 52, 45..=47) => Some("Scadu Altus"),

        // Lower Scadu Altus
        (61, 51, 43) => Some("Lower Scadu Altus"),

        // Scaduview
        (61, 48, 49) => Some("Scaduview"),
        (61, 49, 48..=49) => Some("Scaduview"),

        // Hinterland
        (61, 49, 48) => Some("Hinterland"),
        (61, 50, 47..=49) => Some("Hinterland"),
        (61, 51, 47..=49) => Some("Hinterland"),
        (61, 52, 47..=49) => Some("Hinterland"),
        (61, 53, 48) => Some("Hinterland"),
        (61, 54, 48) => Some("Hinterland"),

        // Finger Ruins
        (61, 49, 39) => Some("Finger Ruins of Rhia"),
        (61, 50, 38..=41) => Some("Finger Ruins of Rhia"),
        (61, 51, 38..=41) => Some("Finger Ruins of Rhia"),
        (61, 53, 45..=47) => Some("Finger Ruins of Dheo"),
        (61, 54, 45..=47) => Some("Finger Ruins of Dheo"),

        // Abyssal Woods
        (61, 49, 40..=41) => Some("Abyssal Woods"),
        (61, 50, 42) => Some("Abyssal Woods"),
        (61, 51, 42) => Some("Abyssal Woods"),
        (61, 52, 40..=43) => Some("Abyssal Woods"),
        (61, 53, 40..=41) => Some("Abyssal Woods"),

        // Foot of the Jagged Peak
        (61, 49, 38..=41) => Some("Foot of the Jagged Peak"),
        (61, 50, 40..=41) => Some("Foot of the Jagged Peak"),
        (61, 51, 40..=41) => Some("Foot of the Jagged Peak"),
        (61, 52, 39..=40) => Some("Foot of the Jagged Peak"),

        // Jagged Peak
        (61, 53, 39..=40) => Some("Jagged Peak"),
        (61, 54, 39..=40) => Some("Jagged Peak"),
        (61, 55, 39) => Some("Jagged Peak"),

        _ => None,
    }
}

// =============================================================================
// FALLBACK REGION MAPPING (for tiles not in the precise mapping)
// =============================================================================

/// Fallback overworld region name from grid coordinates
/// Used when precise tile mapping is not available
fn get_fallback_overworld_region(area_no: u8, grid_x: u8, grid_z: u8) -> &'static str {
    match area_no {
        60 => {
            // Base game overworld
            match (grid_x, grid_z) {
                (33..=36, 40..=42) => "Moonlight Altar",
                (33..=40, 40..=50) => "Liurnia",
                (35..=40, 52..=56) => "Mt. Gelmir",
                (36..=43, 50..=56) => "Altus Plateau",
                (42..=46, 50..=54) => "Capital Outskirts",
                (40..=45, 30..=35) => "Weeping Peninsula",
                (40..=46, 35..=40) => "Limgrave",
                (40..=43, 36..=40) => "Stormhill",
                (47..=53, 35..=42) => "Caelid",
                (48..=53, 39..=44) => "Dragonbarrow",
                (47..=50, 51..=54) => "Forbidden Lands",
                (46..=50, 54..=58) => "Consecrated Snowfield",
                (50..=54, 52..=58) => "Mountaintops of the Giants",
                (51..=54, 52..=55) => "Flame Peak",
                _ => "Lands Between",
            }
        }
        61 => {
            // DLC underground/Shadow Realm
            match (grid_x, grid_z) {
                (44..=49, 40..=44) => "Gravesite Plain",
                (46..=50, 35..=40) => "Cerulean Coast",
                (44..=48, 45..=48) => "Rauh Base",
                (44..=47, 45..=48) => "Ancient Ruins of Rauh",
                (47..=52, 43..=47) => "Scadu Altus",
                (48..=52, 47..=49) => "Hinterland",
                (49..=54, 38..=43) => "Abyssal Woods",
                (49..=52, 38..=41) => "Foot of the Jagged Peak",
                (53..=55, 39..=40) => "Jagged Peak",
                _ => "Shadow Realm",
            }
        }
        _ => "Unknown",
    }
}

// =============================================================================
// PUBLIC API
// =============================================================================

/// Get the zone name for a given map_id
///
/// Returns a human-readable zone name based on the map_id.
/// For legacy dungeons, uses the area number.
/// For overworld maps, uses precise tile mapping with fallback to region bounds.
pub fn get_zone_name(map_id: u32) -> String {
    let (area_no, grid_x, grid_z, _) = parse_map_id(map_id);

    // Handle invalid map_id
    if map_id == 0xFFFFFFFF {
        return "Unknown".to_string();
    }

    match area_no {
        // Overworld (Lands Between surface and DLC)
        60 | 61 => {
            // Try precise tile mapping first
            if let Some(name) = get_overworld_tile_name(area_no, grid_x, grid_z) {
                name.to_string()
            } else {
                // Fallback to region-based mapping
                get_fallback_overworld_region(area_no, grid_x, grid_z).to_string()
            }
        }

        // Legacy dungeons and special areas
        _ => get_legacy_zone_name(area_no, grid_x)
            .unwrap_or("Unknown Area")
            .to_string(),
    }
}

/// Get the zone name from a map_id string (e.g., "m60_42_36_00")
#[allow(dead_code)]
pub fn get_zone_name_from_str(map_id_str: &str) -> String {
    // Parse "mAA_BB_CC_DD" format
    if !map_id_str.starts_with('m') || map_id_str.len() < 14 {
        return "Unknown".to_string();
    }

    let parts: Vec<&str> = map_id_str[1..].split('_').collect();
    if parts.len() != 4 {
        return "Unknown".to_string();
    }

    let area_no: u8 = parts[0].parse().unwrap_or(0);
    let grid_x: u8 = parts[1].parse().unwrap_or(0);
    let grid_z: u8 = parts[2].parse().unwrap_or(0);
    let dd: u8 = parts[3].parse().unwrap_or(0);

    // Reconstruct map_id as u32
    let map_id =
        ((area_no as u32) << 24) | ((grid_x as u32) << 16) | ((grid_z as u32) << 8) | (dd as u32);

    get_zone_name(map_id)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_limgrave() {
        // Church of Elleh area (m60_42_36_00)
        let map_id = 0x3C2A2400u32; // 60, 42, 36, 0
        assert_eq!(get_zone_name(map_id), "Limgrave");
    }

    #[test]
    fn test_stormhill() {
        // Stormhill area (m60_42_39_00)
        let map_id = 0x3C2A2700u32; // 60, 42, 39, 0
        assert_eq!(get_zone_name(map_id), "Stormhill");
    }

    #[test]
    fn test_stormveil() {
        // Stormveil Castle (m10_00_00_00)
        let map_id = 0x0A000000u32;
        assert_eq!(get_zone_name(map_id), "Stormveil Castle");
    }

    #[test]
    fn test_leyndell_royal() {
        // Leyndell Royal Capital (m11_00_00_00)
        let map_id = 0x0B000000u32;
        assert_eq!(get_zone_name(map_id), "Leyndell, Royal Capital");
    }

    #[test]
    fn test_leyndell_ashen() {
        // Leyndell Ashen Capital (m11_05_00_00)
        let map_id = 0x0B050000u32;
        assert_eq!(get_zone_name(map_id), "Leyndell, Ashen Capital");
    }

    #[test]
    fn test_siofra() {
        // Siofra River (m12_08_00_00)
        let map_id = 0x0C080000u32;
        assert_eq!(get_zone_name(map_id), "Siofra River");
    }

    #[test]
    fn test_mohgwyn() {
        // Mohgwyn Palace (m12_05_00_00)
        let map_id = 0x0C050000u32;
        assert_eq!(get_zone_name(map_id), "Mohgwyn Palace");
    }

    #[test]
    fn test_stormfoot_catacombs() {
        // Stormfoot Catacombs (m30_02_00_00)
        let map_id = 0x1E020000u32; // 30, 2, 0, 0
        assert_eq!(get_zone_name(map_id), "Stormfoot Catacombs");
    }

    #[test]
    fn test_murkwater_cave() {
        // Murkwater Cave (m31_00_00_00)
        let map_id = 0x1F000000u32; // 31, 0, 0, 0
        assert_eq!(get_zone_name(map_id), "Murkwater Cave");
    }

    #[test]
    fn test_limgrave_tunnels() {
        // Limgrave Tunnels (m32_01_00_00)
        let map_id = 0x20010000u32; // 32, 1, 0, 0
        assert_eq!(get_zone_name(map_id), "Limgrave Tunnels");
    }

    #[test]
    fn test_divine_tower_limgrave() {
        // Divine Tower of Limgrave (m34_10_00_00)
        let map_id = 0x220A0000u32; // 34, 10, 0, 0
        assert_eq!(get_zone_name(map_id), "Divine Tower of Limgrave");
    }

    #[test]
    fn test_fog_rift_catacombs() {
        // Fog Rift Catacombs (m40_00_00_00) - DLC
        let map_id = 0x28000000u32; // 40, 0, 0, 0
        assert_eq!(get_zone_name(map_id), "Fog Rift Catacombs");
    }

    #[test]
    fn test_dlc_gravesite_plain() {
        // Gravesite Plain (m61_45_41_00)
        let map_id = 0x3D2D2900u32; // 61, 45, 41, 0
        assert_eq!(get_zone_name(map_id), "Gravesite Plain");
    }

    #[test]
    fn test_dlc_scadu_altus() {
        // Scadu Altus (m61_49_45_00)
        let map_id = 0x3D312D00u32; // 61, 49, 45, 0
        assert_eq!(get_zone_name(map_id), "Scadu Altus");
    }

    #[test]
    fn test_from_string() {
        assert_eq!(get_zone_name_from_str("m60_42_36_00"), "Limgrave");
        assert_eq!(get_zone_name_from_str("m10_00_00_00"), "Stormveil Castle");
        assert_eq!(
            get_zone_name_from_str("m30_02_00_00"),
            "Stormfoot Catacombs"
        );
    }

    #[test]
    fn test_invalid_map_id() {
        assert_eq!(get_zone_name(0xFFFFFFFF), "Unknown");
    }
}
