//! Core module - platform-independent types, traits, and utilities
//!
//! This module contains all the business logic that doesn't depend on Windows APIs.
//! Everything here can be compiled and tested on any platform (Linux, macOS, Windows).

pub mod animations;
pub mod color;
pub mod constants;
pub mod entity_utils;
pub mod io_traits;
pub mod map_utils;
pub mod protocol;
pub mod session;
pub mod status_template;
pub mod traits;
pub mod types;
pub mod warp_tracker;

// Re-export commonly used items
pub use animations::{get_animation_label, get_teleport_type, is_teleport_animation, Animation};
pub use constants::*;
pub use entity_utils::is_fog_rando_entity;
pub use io_traits::GameStats;
pub use map_utils::format_map_id;
pub use status_template::{render_template, RenderedLine, RenderedStatus, TemplateContext};
pub use traits::{GameStateReader, SpEffectChecker, WarpDetector};
pub use types::{PlayerPosition, WarpInfo};
pub use warp_tracker::{DiscoveryEvent, PendingWarp, WarpTracker};
