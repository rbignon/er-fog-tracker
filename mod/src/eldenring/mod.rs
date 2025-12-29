//! Elden Ring memory reading module
//!
//! This module contains all the code that reads from the Elden Ring process memory,
//! including player position, animation state, warp detection, and SpEffects.
//!
//! The implementations here satisfy the traits defined in `core::traits`.

mod game_man;
mod game_state;
mod memory;
mod sp_effect;
pub mod warp_hook;

pub use game_man::GameMan;
pub use game_state::GameState;
pub use sp_effect::SpEffect;
