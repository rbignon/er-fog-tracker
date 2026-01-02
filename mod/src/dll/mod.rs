//! DLL module - Elden Ring mod entry point, UI, and configuration
//!
//! This module contains the DLL-specific code including:
//! - FogRandoTracker: main tracker logic and state
//! - UI overlay rendering
//! - Configuration loading
//! - WebSocket client for server communication
//! - Hotkey handling
//! - Logging setup

pub mod config;
mod frame_state;
pub mod hotkey;
pub mod icon_atlas;
pub mod log_reader;
pub mod logging;
pub mod tracker;
pub mod ui;
pub mod websocket;
