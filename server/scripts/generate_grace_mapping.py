#!/usr/bin/env python3
"""
Generate grace entity ID to zone mapping.

This script extracts grace data from a Cheat Engine table and maps each grace
to the corresponding zone in fog.txt based on map ID and name matching.
"""

import json
import sys
from pathlib import Path

# Grace data extracted from CE table (entity_id:grace_name)
GRACES_RAW = """
1002950:Murkwater Cave
1012950:Earthbore Cave
1022950:Tombsward Cave
1032950:Groveside Cave
1042950:Stillwater Cave
1052950:Lakeside Crystal Cave
1062950:Academy Crystal Cave
1072950:Seethewater Cave
1092950:Volcano Cave
1102950:Dragonbarrow Cave
1112950:Sellia Hideaway
1122950:Cave of the Forlorn
1152950:Coastal Cave
1172950:Highroad Cave
1182950:Perfumer's Grotto
1192950:Sage's Cave
1202950:Abandoned Cave
1212950:Gaol Cave
1222950:Spiritcaller's Cave
10002950:Godrick the Grafted
10002951:Margit, the Fell Omen
10002952:Castleward Tunnel
10002953:Gateside Chamber
10002954:Stormveil Cliffside
10002955:Rampart Tower
10002956:Liftside Chamber
10002957:Secluded Cell
10002958:Stormveil Main Gate
11052950:Elden Throne
11052951:Erdtree Sanctuary
11052952:East Capital Rampart
11052953:Leyndell, Capital of Ash
11052954:Queen's Bedchamber
11052955:Divine Bridge
11102950:Table of Lost Grace
12012950:Dragonkin Soldier of Nokstella
12012951:Ainsel River Well Depths
12012952:Ainsel River Sluice Gate
12012953:Ainsel River Downstream
12012954:Ainsel River Main
12012955:Nokstella, Eternal City
12012956:Lake of Rot Shoreside
12012958:Grand Cloister
12012959:Nokstella Waterfall Basin
12022950:Great Waterfall Basin
12022951:Mimic Tear
12022953:Siofra River Bank
12022954:Worshippers' Woods
12022956:Ancestral Woods
12022957:Aqueduct-Facing Cliffs
12022958:Night's Sacred Ground
12022959:Below the Well
12032950:Prince of Death's Throne
12032951:Root-Facing Cliffs
12032952:Great Waterfall Crest
12032953:Deeproot Depths
12032954:The Nameless Eternal City
12032955:Across the Roots
12042950:Astel, Naturalborn of the Void
12052950:Cocoon of the Empyrean
12052951:Palace Approach Ledge-Road
12052952:Dynasty Mausoleum Entrance
12052953:Dynasty Mausoleum Midpoint
12072950:Siofra River Well Depths
12072951:Nokron, Eternal City
13002950:Maliketh, the Black Blade
13002951:Dragonlord Placidusax
13002952:Dragon Temple Altar
13002953:Crumbling Beast Grave
13002954:Crumbling Beast Grave Depths
13002955:Tempest-Facing Balcony
13002956:Dragon Temple
13002957:Dragon Temple Transept
13002958:Dragon Temple Lift
13002959:Dragon Temple Rooftop
13002960:Beside the Great Bridge
14002950:Raya Lucaria Grand Library
14002951:Debate Parlour
14002952:Church of the Cuckoo
14002953:Schoolhouse Classroom
15002950:Malenia, Goddess of Rot
15002951:Prayer Room
15002952:Elphael Inner Wall
15002953:Drainage Channel
15002954:Haligtree Roots
15002955:Haligtree Promenade
15002956:Haligtree Canopy
15002957:Haligtree Town
15002958:Haligtree Town Plaza
16002950:Rykard, Lord of Blasphemy
16002951:Temple of Eiglay
16002952:Volcano Manor
16002953:Prison Town Church
16002954:Guest Hall
16002960:Audience Pathway
16002962:Abductor Virgin
16002964:Subterranean Inquisition Chamber
18002950:Cave of Knowledge
18002951:Stranded Graveyard
19002950:Fractured Marika
1033402950:Altar South
1033442950:Revenger's Shack
1033462950:Foot of the Four Belfries
1033472950:The Four Belfries
1034412950:Moonlight Altar
1034422950:Village of the Albinaurics
1034432950:Converted Tower
1034442950:Temple Quarter
1034462950:Crystalline Woods
1034472951:Sorcerer's Isle
1034482950:Northern Liurnia Lake Shore
1034492950:Road to the Manor
1034502950:Ranni's Rise
1034502951:Ranni's Chamber
1035422950:Cathedral of Manus Celes
1035432950:Folly on the Lake
1035452950:South Raya Lucaria Gate
1035462950:Academy Gate
1035472950:East Gate Bridge Trestle
1035502950:Manor Upper Level
1035502951:Manor Lower Level
1035502952:Royal Moongazing Grounds
1035502953:Main Caria Manor Gate
1035532950:Seethewater Terminus
1036412950:Slumbering Wolf Shack
1036432950:Boilprawn Shack
1036432951:Fallen Ruins of the Lake
1036452950:Gate Town North
1036482950:East Raya Lucaria Gate
1036492950:Bellum Church
1036492951:The Ravine
1036502950:Behind Caria Manor
1036522950:Craftsman's Shack
1036542951:Ninth Mt. Gelmir Campsite
1036542952:Road of Iniquity
1037422950:Scenic Isle
1037442950:Academy Gate Town
1037462950:Church of Vows
1037482950:Mausoleum Compound
1037492950:Church of Inhibition
1037512950:Abandoned Coffin
1037522951:Seethewater River
1037532950:Primeval Sorcerer Azur
1038402950:Liurnia Lake Shore
1038412950:Laskyar Ruins
1038432950:Gate Town Bridge
1038452950:Artist's Shack
1038452951:Eastern Liurnia Lake Shore
1038462950:Eastern Tableland
1038472950:Ruined Labyrinth
1038482950:Frenzied Flame Village Outskirts
1038502950:Grand Lift of Dectus
1038502951:Ravine-Veiled Village
1038502952:Altus Plateau
1038512950:Erdtree-Gazing Hill
1038542950:First Mt. Gelmir Campsite
1039402950:Lake-Facing Cliffs
1039412950:Liurnia Highway South
1039422950:Liurnia Highway North
1039442950:Jarburg
1039512950:Altus Highway Junction
1039532950:Bridge of Iniquity
1039542950:Shaded Castle Ramparts
1039542951:Shaded Castle Inner Gate
1039542952:Castellan's Hall
1040522950:Forest-Spanning Greatbridge
1040532950:Bower of Bounty
1040542950:Road of Iniquity Side Path
1041322950:Isolated Merchant's Shack
1041332950:Fourth Church of Marika
1041352950:Church of Dragon Communion
1041382950:Stormhill Shack
1041522951:Rampartside Path
1041542950:Windmill Village
1042332950:Tombsward
1042362950:Church of Elleh
1042362951:The First Step
1042372950:Gatefront
1042382950:Warmaster's Shack
1042512950:Outer Wall Phantom Tree
1042552950:Windmill Heights
1043302950:Morne Moangrave
1043312950:Castle Morne Lift
1043312951:Behind The Castle
1043312952:Beside the Rampart Gaol
1043342950:Church of Pilgrimage
1043352950:Seaside Ruins
1043372950:Agheel Lake North
1043382950:Murkwater Coast
1043392950:Saintsbridge
1043502950:Minor Erdtree Church
1043532950:Hermit Merchant's Shack
1043532951:Outer Wall Battleground
1044332950:Castle Morne Rampart
1044332951:South of the Lookout Tower
1044332952:Ailing Village Outskirts
1044342950:Bridge of Sacrifice
1044352950:Agheel Lake South
1044362950:Waypoint Ruins Cellar
1044372950:Mistwood Outskirts
1044382950:Artist's Shack
1044392950:Summonwater Village Outskirts
1045332950:Beside the Crater-Pocked Glade
1045362950:Fort Haight West
1045522950:Capital Rampart
1046382950:Third Church of Marika
1046402950:Smoldering Church
1046402951:Rotview Balcony
1047392950:Fort Gael North
1047402950:Caelem Ruins
1047512950:Forbidden Lands
1047582950:Apostate Derelict
1048362950:Cathedral of Dragon Communion
1048372950:Caelid Highway South
1048382950:Aeonia Swamp Shore
1048382951:Astray from Caelid Highway North
1048392950:Smoldering Wall
1048402950:Deep Siofra Well
1048402951:Dragonbarrow West
1048412950:Isolated Merchant's Shack
1048572950:Ordina, Liturgical Town
1049372950:Southern Aeonia Swamp Bank
1049382950:Heart of Aeonia
1049382951:Inner Aeonia
1049392950:Sellia Backstreets
1049392951:Chair-Crypt of Sellia
1049392952:Sellia Under-Stair
1049532950:Zamor Ruins
1049532951:Grand Lift of Rold
1049542950:Consecrated Snowfield
1049552950:Inner Consecrated Snowfield
1050362950:Impassable Greatbridge
1050382950:Church of the Plague
1050402950:Dragonbarrow Fork
1051362950:Redmane Castle Plaza
1051362951:Chamber Outside the Plaza
1051392950:Fort Faroth
1051432950:Bestial Sanctum
1051532950:Church of Repose
1051562950:Ancient Snow Valley Ruins
1051572950:Snow Valley Ruins Overlook
1051572951:Castle Sol Main Gate
1051572952:Church of the Eclipse
1051572953:Castle Sol Rooftop
1052382950:Starscourge Radahn
1052412950:Lenne's Rise
1052422950:Farum Greatbridge
1052532950:Foot of the Forge
1052542950:Giant's Gravepost
1052562950:Whiteridge Road
1052572950:Freezing Lake
1053522950:Fire Giant
1054532950:Forge of the Giants
1054552950:First Church of Marika
""".strip()


def entity_id_to_map_id(entity_id: int) -> str:
    """Convert grace entity ID to map ID string.

    Grace entity IDs encode the map:
    - Legacy dungeons: AABB0295x → mAA_BB_00_00
    - Overworld: 10XXYY295x → m60_XX_YY_00
    - Mini-dungeons: short IDs like 1002950 → m31_00_00_00 (caves), etc.
    """
    entity_str = str(entity_id)

    # Overworld graces: 10XXYY295x (10 digits)
    if len(entity_str) == 10 and entity_str.startswith("10"):
        xx = int(entity_str[2:4])
        yy = int(entity_str[4:6])
        return f"m60_{xx:02d}_{yy:02d}_00"

    # Legacy dungeons: AABB0295x (8-9 digits)
    # Extract AA and BB from the entity ID
    # Format varies: 10002950 → m10_00, 11052950 → m11_05, etc.
    grace_suffixes = (
        "2950",
        "2951",
        "2952",
        "2953",
        "2954",
        "2955",
        "2956",
        "2957",
        "2958",
        "2959",
        "2960",
        "2962",
        "2964",
    )
    if len(entity_str) >= 8 and entity_str.endswith(grace_suffixes):
        # Remove the last 4 digits (295x)
        prefix = entity_str[:-4]
        if len(prefix) >= 4:
            aa = int(prefix[:2])
            bb = int(prefix[2:4])
            return f"m{aa:02d}_{bb:02d}_00_00"

    # Mini-dungeons: 7 digits like 1002950, 1012950, etc.
    if len(entity_str) == 7:
        # These are m31_XX_00_00 or m32_XX_00_00 (caves, catacombs, tunnels)
        # The pattern is: 1XX2950 where XX maps to the dungeon
        prefix = entity_str[:3]  # e.g., "100", "101", etc.
        dungeon_idx = int(prefix[1:])  # e.g., 0, 1, 2, ...
        # Map to m31 (caves) or m32 (tunnels) based on dungeon type
        # This is a simplification - actual mapping needs more data
        return f"m31_{dungeon_idx:02d}_00_00"

    return ""


def parse_graces() -> dict[int, str]:
    """Parse grace data into entity_id -> name mapping."""
    graces = {}
    for line in GRACES_RAW.split("\n"):
        if ":" in line:
            entity_id_str, name = line.split(":", 1)
            graces[int(entity_id_str)] = name.strip()
    return graces


def parse_fog_zones(fog_txt_path: Path) -> dict[str, list[str]]:
    """Parse fog.txt to get zone_name -> [map_ids] mapping.

    Returns a dict where keys are zone display names (Text field)
    and values are lists of map IDs.
    """
    zones = {}
    current_name = None
    current_text = None
    current_maps = []

    with open(fog_txt_path) as f:
        for line in f:
            line = line.rstrip()

            # New zone definition
            if line.startswith("- Name:"):
                # Save previous zone
                if current_text and current_maps:
                    zones[current_text] = current_maps

                current_name = line.split(":", 1)[1].strip()
                current_text = None
                current_maps = []

            # Zone display name
            elif line.startswith("  Text:") and current_name:
                current_text = line.split(":", 1)[1].strip()

            # Zone maps
            elif line.startswith("  Maps:") and current_name:
                maps_str = line.split(":", 1)[1].strip()
                current_maps = maps_str.split()

        # Save last zone
        if current_text and current_maps:
            zones[current_text] = current_maps

    return zones


def find_zone_for_grace(grace_name: str, map_id: str, zones: dict[str, list[str]]) -> str | None:
    """Find the best matching zone for a grace.

    First tries exact name match, then map-based match.
    """
    grace_name_lower = grace_name.lower()

    # Try exact match on zone name
    for zone_name in zones:
        if grace_name_lower == zone_name.lower():
            return zone_name
        # Check if grace name is contained in zone name
        if grace_name_lower in zone_name.lower():
            return zone_name

    # Try to find a zone that contains this map
    matching_zones = []
    for zone_name, zone_maps in zones.items():
        if map_id in zone_maps:
            matching_zones.append(zone_name)

    if len(matching_zones) == 1:
        return matching_zones[0]

    # Multiple matches - try to pick the best one based on name similarity
    if matching_zones:
        # Prefer zones with similar names
        for zone in matching_zones:
            zone_lower = zone.lower()
            if any(word in zone_lower for word in grace_name_lower.split()):
                return zone
        # Return first match as fallback
        return matching_zones[0]

    return None


def generate_mapping(fog_txt_path: Path) -> dict:
    """Generate the grace entity ID to zone mapping."""
    graces = parse_graces()
    zones = parse_fog_zones(fog_txt_path)

    mapping = {}
    unmatched = []

    for entity_id, grace_name in graces.items():
        map_id = entity_id_to_map_id(entity_id)
        zone = find_zone_for_grace(grace_name, map_id, zones)

        if zone:
            mapping[str(entity_id)] = {
                "grace_name": grace_name,
                "zone": zone,
                "map_id": map_id,
            }
        else:
            unmatched.append(
                {
                    "entity_id": entity_id,
                    "grace_name": grace_name,
                    "map_id": map_id,
                }
            )

    return {
        "mapping": mapping,
        "unmatched": unmatched,
        "stats": {
            "total_graces": len(graces),
            "matched": len(mapping),
            "unmatched": len(unmatched),
        },
    }


def main():
    script_dir = Path(__file__).parent
    fog_txt = script_dir.parent / "data" / "fog.txt"
    output_file = script_dir.parent / "data" / "graces.json"

    if not fog_txt.exists():
        print(f"Error: {fog_txt} not found")
        sys.exit(1)

    result = generate_mapping(fog_txt)

    # Save to file
    with open(output_file, "w") as f:
        json.dump(result, f, indent=2)

    print(f"Generated mapping: {output_file}")
    print(f"Stats: {result['stats']}")

    if result["unmatched"]:
        print("\nUnmatched graces:")
        for item in result["unmatched"][:10]:
            print(f"  {item['entity_id']}: {item['grace_name']} ({item['map_id']})")
        if len(result["unmatched"]) > 10:
            print(f"  ... and {len(result['unmatched']) - 10} more")


if __name__ == "__main__":
    main()
