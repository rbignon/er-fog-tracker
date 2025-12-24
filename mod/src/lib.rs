// FogRandoTracker - Fog Gate Randomizer Tracker for Elden Ring
// Copyright (C) 2024 wospins
//
// This program is free software: you can redistribute it and/or modify
// it under the terms of the GNU Affero General Public License as published
// by the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.
//
// This program is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
// GNU Affero General Public License for more details.
//
// You should have received a copy of the GNU Affero General Public License
// along with this program. If not, see <https://www.gnu.org/licenses/>.
//
// This project uses code from eldenring-practice-tool by johndisandonato
// which is also licensed under AGPL-3.0.
// Original source: https://github.com/veeenu/eldenring-practice-tool

// =============================================================================
// MODULES
// =============================================================================

mod config;
mod game_state;
mod hotkey;
mod logging;
mod tracker;
mod ui;
mod websocket;

// =============================================================================
// IMPORTS
// =============================================================================

use std::ffi::c_void;
use std::path::PathBuf;

use hudhook::hooks::dx12::ImguiDx12Hooks;
use hudhook::{eject, Hudhook};
use tracing::{error, info};
#[allow(unused_imports)]
use windows::Win32::Foundation::HINSTANCE;
use windows::Win32::System::Console::{AllocConsole, SetConsoleTitleW};
#[allow(unused_imports)]
use windows::Win32::System::SystemServices::DLL_PROCESS_ATTACH;

use crate::config::Config;
use crate::logging::init_logging;
use crate::tracker::FogRandoTracker;

// =============================================================================
// DLL ENTRY POINT
// =============================================================================

/// Allocate a console window for debug output
fn setup_debug_console() {
    unsafe {
        let _ = AllocConsole();
        let title: Vec<u16> = "FogRandoTracker Debug Console\0".encode_utf16().collect();
        let _ = SetConsoleTitleW(windows::core::PCWSTR(title.as_ptr()));
    }
}

/// Resolve log file path (relative to DLL directory or absolute)
fn resolve_log_path(hmodule: HINSTANCE, log_file: &str) -> Option<PathBuf> {
    if log_file.is_empty() {
        return None;
    }

    let path = PathBuf::from(log_file);
    if path.is_absolute() {
        Some(path)
    } else {
        Config::get_dll_directory(hmodule).map(|dir| dir.join(log_file))
    }
}

fn start_mod(hmodule: HINSTANCE) {
    // Try to load config early to setup logging
    let (enable_console, log_path) = if let Ok(config) = Config::load(hmodule) {
        let log_path = resolve_log_path(hmodule, &config.logging.log_file);
        (config.logging.console, log_path)
    } else {
        (false, None)
    };

    // Setup console if enabled (must be done before logging init)
    if enable_console {
        setup_debug_console();
    }

    // Initialize logging (console and/or file)
    if enable_console || log_path.is_some() {
        init_logging(enable_console, log_path);
        info!("FogRandoTracker logging initialized");
    }

    let tracker = match FogRandoTracker::new(hmodule) {
        Some(t) => t,
        None => {
            eject();
            return;
        }
    };

    if let Err(e) = Hudhook::builder()
        .with::<ImguiDx12Hooks>(tracker)
        .with_hmodule(hmodule)
        .build()
        .apply()
    {
        error!("Couldn't apply hooks: {e:?}");
        eject();
    }
}

#[no_mangle]
#[allow(clippy::missing_safety_doc)]
pub unsafe extern "system" fn DllMain(hmodule: HINSTANCE, reason: u32, _: *mut c_void) -> bool {
    if reason == DLL_PROCESS_ATTACH {
        // Check game version
        if libeldenring::version::check_version().is_err() {
            return false;
        }

        std::thread::spawn(move || {
            start_mod(hmodule);
        });
    }

    true
}
