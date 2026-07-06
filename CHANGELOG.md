# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Changed

#### Mod
* Overlay default colors now follow the SpeedFog graphic-charter foundations (deep blue-black background, off-white text, emerald discovered green, blue-grey border); default background opacity is now 0.55

### Fixed

#### Mod
* Stop reconnecting forever when the server permanently rejects the connection (e.g. an invalid or expired token, or a close code >= 4000); the overlay now shows a clear Error status instead of an endless reconnect loop

### Internal

#### Mod
* Add opt-in Tracy profiling behind the `profile-tracy` feature (off by default, zero cost when disabled). See `docs/MOD_PROFILING.md`.
* Parse overlay colors once at startup instead of re-parsing hex strings every frame (CachedColors)
* Answer server pings in the WebSocket worker thread instead of round-tripping through the main thread
* Cache Great Runes and Kindling counts (throttled) instead of re-scanning the key-item inventory on every overlay frame

## [1.4.1] - 2026-06-11

### Fixes

#### Mod
* Support Elden Ring v1.16.2

## [1.4.0] - 2026-01-24

### New Features

#### Mod
* Send game stats updates every 10 seconds for more responsive UI

#### Server
* Add Discord notification when player connects mod
* Detect musttrap fog gates as one-way connections
* Track and expose user last_seen_at timestamp
* Add Grace ID and zone_ids to resolution failure logs

#### Web
* Add 404 page for unknown routes
* Display last seen time on players list

### Bug Fixes

#### Mod
* Prevent waygate discovery loss on maps with continuous teleport animation cycles
* Display friendly message for 502 server errors

#### Server
* Update graces mapping
* Prevent entity_mapping expansion from causing false discoveries
* Disambiguate ASide/BSide when checking for conditional fog gates
* Disambiguate zone matches using warp_type and animation requirement
* Filter to mod-provided source zone instead of just prioritizing
* Skip entity_mapping source expansion when maps don't match or mod provides authoritative source_zone_id
* Include entity_mapping expansions for authoritative source zones
* Make entity_mapping target expansion a fallback mechanism
* Add preexisting-adjacent fallback for zone resolution
* Propagate preexisting links at game creation, in /mod/games endpoint, and when target is already discovered
* Propagate starting_zone_id through online game creation flow
* Use matched direction for backprop cost and propagation
* Skip backprop for bidirectional links when target already accessible
* Discover all parallel links between same zones
* Prefer random links for destination zone when re-traversing discovered gates
* Add bidirectional preexisting link gravesite <-> scadualtus
* Add m61_44_46_00 to rauhruins_romina maps for warp landing resolution
* Inject mod's source_zone_id when not in resolver candidates
* Restore Halightree Secret Medallion case
* Correctly match items case-insensitive
* Reduce log noise from periodic game stats updates

#### Web
* Propagate preexisting links when loading online game state

## [1.3.0] - 2026-01-15

### New Features

#### Mod
* Show undiscovered exits first in overlay

#### Server
* Add blocks_propagation for conditional fog gates
* Include Optional areas in World Shuffle mode
* Detect one-way fog gates using zone-based Cond: fields

#### Web
* Add players list page with connection status
* Hide undiscovered exits from restricted zones

### Bug Fixes

#### Server
* Update graces mapping
* Add Aliases support for zone name resolution
* Extend ASide/BSide zone resolution to all fog gates
* Resolve zone_query failure for zones with duplicate display names
* Fix blocks_propagation based on target_details, not source_details

#### Web
* Fix blocksPropagation not working in offline mode

## [1.2.0] - 2026-01-10

### New Features

#### Web
* Add feedback system with Discord integration (floating button, welcome modal, community section in help)
* Rename "Mod" indicator to "Game" and show it to viewers

### Bug Fixes

#### Mod
* Set the correct default server URL

#### Server
* Update graces mapping
* Include preexisting zones in get_discovered_nodes

#### Parser
* Skip randomizer routing lines and handle "(to ..." details

#### Web
* Style create game modal and add launcher hint
* Return zones as dict instead of list in transformZonesToApi
* Show toast instead of modal for spoiler parse errors
* Correct End Area zone ID from stone_platform to erdtree

### Improvements

#### Mod
* Throttle game stats inventory scan to once per second for performance

## [1.1.0] - 2026-01-06

### New Features

* Add game statistics tracking (runes, kindling, deaths, play time)

#### Server
* Add game_info.json export script for complete game data backup

#### Web
* Display game stats (runes, kindling, deaths, play time) in header
* Add streamer info panel with progress bar and last discovery display
* Add viewer count for host and host status indicator for viewers
* Improve tag display styling

### Bug Fixes

#### Server
* Skip Windows paths and randomizer log messages in spoiler parser
* Remove invalid zones during migration instead of failing

## [1.0.0] - 2026-01-06

### New Features

#### Mod
* Migrate protocol fields from zone_key to zone_id for improved zone identification

#### Server
* Add in-game display logging to zone_query and centralize resolution failure logs
* Migrate from UUIDs to zone_keys as primary identifiers

#### Web
* Migrate from display names to zone_keys as primary identifiers

### Bug Fixes

* Improve error handling and prevent race conditions across the stack
* Harden input validation across all components
* Fix discovery stats calculation to use zones dict for total_zones
* Update discovery stats in UI after API calls

#### Mod
* Handle StatsUpdated event in tracker
* Preserve zone and exits on server reconnection

#### Server
* Update graces mapping for Lakeside Crystal Cave and other zones
* Detect preexisting links in reverse direction in link_exists
* Mark "arriving at the sending gate" as one-way
* Show random links as exits even when parallel preexisting link exists

#### Web
* Display zone name instead of ID in placeholder tooltip
* Display zone names instead of IDs in discovery notifications
* Search on display names instead of zone_keys
* Fix zone_id usage in tag_update messages

### Improvements

* Repair integration tests for pytest compatibility

## [0.3.2] - 2026-01-04

### New Features

#### Mod
* Add configurable overlay position offsets

#### Server
* Add warp_type and resolution_method to Discovery Summary
* Add import_game.py script for game data import

### Bug Fixes

#### Server
* Update graces mapping

### Improvements

#### Server
* Integrate grace mapping into ZoneResolver

#### Web
* Improve help page accuracy and add table of contents
* Add overlay position options to help page

## [0.3.1] - 2026-01-03

### New Features

* Add log upload shortcut (Ctrl+F12)

#### Mod
* Add max_height config to limit overlay size
* Add UI notification for log upload result
* Add Trigger C for vanilla warp detection
* Add hotkey to show only undiscovered exits
* Change default values of config file

### Bug Fixes

#### Mod
* Add defensive panic protection to prevent potential crashes
* Support ISO 8601 timestamp format in log reader
* Hotkeys with same base key no longer interfere
* Truncate left label when it overlaps with right label in overlay
* Prevent Fast Travel from triggering false discovery

#### Server
* Fix graces IDs

### Improvements

#### Mod
* Improve warp_tracker architecture for extensibility

#### Server
* Use REPORTS_DIR config for log uploads

#### Web
* Update help page with missing config options

## [0.3.0] - 2026-01-01

### New Features

#### Mod
* Add same-map fallback for respawn zone resolution
* Add coffin warp animations for Lake of Rot and Deeproot Depths

#### Server
* Add source zone context for disambiguation

### Bug Fixes

* Include zone_key in all zone_query_ack responses

#### Mod
* Add new warp events
* Add animation event for Liurnia Divine Tower

#### Server
* Disambiguate Divine Tower elevator from pre-tower area
* Add sibling map fallback for zone resolution
* Correct zone mappings for overworld graces
* Update graces mapping
* Apply "dropping" one-way pattern only to preexisting links
* Resolve Shadow Keep Church District at elevator spawn point
* Improve one-way detection for sending gate patterns

#### Web
* Auto-select discovered zone and respect viewer mode

#### Launcher
* Improve icon visibility and add to title bar

### Improvements

#### Server
* Add reference to graces.json for zone_query
* Add regression tests for priority filtering bug

#### Web
* Remove deprecated execCommand clipboard fallback

## [0.2.0] - 2025-12-30

Major release introducing the in-game mod, Windows launcher, and FastAPI backend.

### New Features

* Add version checking across all components
* Add grace entity ID for precise fast travel zone resolution

#### Mod
* In-game overlay with WebSocket client for real-time server synchronization
* Overlay UI showing current zone, exits, and discovery stats
* Template system with variables: `{zone}`, `{exits}`, `{discovered}`, `{total}`, `{deaths}`, `{igt}`, `{runes}`, `{kindling}`
* Icon support: Great Runes, Messmer's Kindling, death counter
* Configurable colors, transparency, and font settings
* Hook lua_warp to capture grace entity ID for fast travel
* Add zone scaling to template variables
* Add Abductor Virgin grab as teleport animation
* Add PLACIDUSAX_LIE_DOWN animation detection
* Add ERDTREE_BURN animation detection
* Debug console option for troubleshooting

#### Server
* FastAPI backend with PostgreSQL and Twitch OAuth authentication
* Multi-user game management with WebSocket real-time synchronization
* Zone resolution using map IDs, coordinates, and grace entity IDs
* Discovery back-propagation to connected zones
* Add cache revalidation for static files in nginx config
* Discover all valid fog links to ensure 100% resolution
* Add PlayRegionId (Col) support for exact zone resolution
* Add LOG_LEVEL configuration
* Add debug logging for mod websocket and discovery

#### Web
* Redesign landing page with screenshots and feature highlights
* Complete help page with screenshots and template docs
* Add setup guide help page
* Add tip about creating games from the launcher
* Improve search UX with persistent filter and clear button
* Add avatar and Twitch link on watch page

#### Launcher
* Native Windows GUI for managing game sessions
* Auto-connect to server on startup
* Show version in window title
* Add connecting screen during auto-connect
* Add clickable link to Fog Tracker Dashboard
* Improve Waiting and Injected screens layout

### Bug Fixes

* Prevent viewers from creating/undoing discoveries
* Stormveil Main Gate zone and test for null map_id

#### Mod
* Reduce brightness of grayed runes
* Capture TargetGrace when warp starts
* Read grace entity ID from correct offset
* Correct Kindling param_id and remove Miquella's Great Rune
* Scan inventory beyond reported count for Great Runes
* Add warp_requested validation for various animations
* Filter POST_BOSS_WARP false positives
* Change rune icons positions
* Vertically center text when icons are larger than font

#### Server
* Update graces mapping
* Expand parent map IDs to include child tile zones
* Include boss zones in zone resolution candidates
* Make zone candidate ordering deterministic
* Detect one-way preexisting links from fog.txt To: structure
* Check reverse direction in link_exists for bidirectional random links
* Use correct destination zone when multiple matches tie
* Handle Medal warp discovery without source position
* List ambiguous zone candidates in zone_query logs

#### Web
* Update screenshots and tweak scrollbar/image styles
* Display HTTP URL instead of WebSocket in mod setup
* Improve game card date formatting
* Show 'Seed X' instead of 'Untitled' for games without label
* Handle 401 responses with automatic logout
* Redirect to dashboard when host session is replaced

#### Launcher
* Rename 'Change Token' to 'Disconnect' and preserve fields
* Mask token input as password field
* Disable server/token fields during connection
* Increase version dialog height for full text display
* Define version logic directly in launcher binary
* Move Dashboard button next to Connect
* Update token hint to mention Dashboard

#### Parser
* Add one-way patterns for transporter chest and Deeproot

### Improvements

* Unify one-way link logic and rename is_inherently_one_way to is_one_way
* Move key item detection to server and preserve all link/zone fields

#### Mod
* Centralize per-frame memory reads with FrameSnapshot
* Use texture atlas for all icons
* Use num_enum for enum-to-int conversions
* Simplify sending gate handling in teleport_label
* Replace magic numbers with Animation and GreatRune enums
* Add exhaustive animation list from CE table
* Simplify warp validation and add entity-based trigger
* Extract memory reading into game_state module

#### Server
* Extract helper methods for discovery handling
* Set default env vars in conftest for CI tests
* Centralize spoiler log parsing on server

#### Web
* Improve help page content and styling
* Unify page headers with common .page-header class
* Simplify header with CSS grid layout

## [0.1.0] - 2025-12-21

Initial release of the Fog Gate Randomizer Tracker.

### New Features

#### Web
* Interactive D3.js force-directed graph visualization for fog gate connections
* Explorer Mode with progressive discovery and automatic save/load per seed
* Full Spoiler Mode to view entire randomized map at once
* Pathfinding with shortest path highlighting from Chapel of Anticipation
* Frontier highlighting to see unexplored areas and access points
* Item log integration with key item locations displayed on gates
* Area tagging with custom tags for tracking progress (Boss, Key, etc.)
* Stream to OBS with real-time WebSocket synchronization for browser sources
* Discovery counter overlay for viewer mode
* Progress bar with customizable size and position
* Tag filtering in stats panel with viewer sync
* Keyboard shortcuts for common actions
* Toast notifications replacing browser alerts
* Golden arch favicon with fog effect
* Offline mode with local browser storage without account requirement
