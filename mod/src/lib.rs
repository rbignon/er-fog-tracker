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
use libeldenring::version::{get_version, Version};
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
// HELPER FUNCTIONS
// =============================================================================

/// Convert Version enum to a display string (Version doesn't implement Debug)
fn version_to_string(version: Version) -> &'static str {
    match version {
        Version::V1_02_0 => "1.02.0",
        Version::V1_02_1 => "1.02.1",
        Version::V1_02_2 => "1.02.2",
        Version::V1_02_3 => "1.02.3",
        Version::V1_03_0 => "1.03.0",
        Version::V1_03_1 => "1.03.1",
        Version::V1_03_2 => "1.03.2",
        Version::V1_04_0 => "1.04.0",
        Version::V1_04_1 => "1.04.1",
        Version::V1_05_0 => "1.05.0",
        Version::V1_06_0 => "1.06.0",
        Version::V1_07_0 => "1.07.0",
        Version::V1_08_0 => "1.08.0",
        Version::V1_08_1 => "1.08.1",
        Version::V1_09_0 => "1.09.0",
        Version::V1_09_1 => "1.09.1",
        Version::V1_10_0 => "1.10.0",
        Version::V1_10_1 => "1.10.1",
        Version::V1_12_0 => "1.12.0",
        Version::V1_12_1 => "1.12.1",
        Version::V1_12_2 => "1.12.2",
        Version::V1_12_3 => "1.12.3",
        Version::V1_14_0 => "1.14.0",
        Version::V1_15_0 => "1.15.0",
        Version::V1_16_0 => "1.16.0",
        Version::V2_00_0 => "2.00.0",
        Version::V2_00_1 => "2.00.1",
        Version::V2_01_0 => "2.01.0",
        Version::V2_02_0 => "2.02.0",
        Version::V2_02_1 => "2.02.1",
        Version::V2_02_2 => "2.02.2",
        Version::V2_02_3 => "2.02.3",
        Version::V2_03_0 => "2.03.0",
        Version::V2_03_1 => "2.03.1",
        _ => "unknown",
    }
}

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
        info!(
            version = version_to_string(get_version()),
            "Detected game version"
        );
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
