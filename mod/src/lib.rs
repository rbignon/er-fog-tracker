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

// Core module is always available (platform-independent, testable on Linux)
pub mod core;

// Windows-only modules
#[cfg(target_os = "windows")]
mod eldenring;

#[cfg(target_os = "windows")]
mod dll;

// Launcher module (Windows-only, feature-gated)
#[cfg(all(target_os = "windows", feature = "launcher"))]
pub mod launcher;

// =============================================================================
// IMPORTS (Windows only)
// =============================================================================

#[cfg(target_os = "windows")]
use std::ffi::c_void;
#[cfg(target_os = "windows")]
use std::path::PathBuf;

#[cfg(target_os = "windows")]
use hudhook::hooks::dx12::ImguiDx12Hooks;
#[cfg(target_os = "windows")]
use hudhook::{eject, Hudhook};
#[cfg(target_os = "windows")]
use tracing::{error, info};
#[cfg(target_os = "windows")]
use windows::Win32::Foundation::HINSTANCE;
#[cfg(target_os = "windows")]
use windows::Win32::System::Console::{AllocConsole, SetConsoleTitleW};
#[cfg(target_os = "windows")]
use windows::Win32::System::SystemServices::DLL_PROCESS_ATTACH;

#[cfg(target_os = "windows")]
use crate::dll::config::Config;
#[cfg(target_os = "windows")]
use crate::dll::logging::init_logging;
#[cfg(target_os = "windows")]
use crate::dll::tracker::FogRandoTracker;

// =============================================================================
// DLL ENTRY POINT (Windows only)
// =============================================================================

#[cfg(target_os = "windows")]
mod dll_entry {
    use super::*;

    /// Allocate a console window for debug output
    pub fn setup_debug_console() {
        unsafe {
            let _ = AllocConsole();
            let title: Vec<u16> = "FogRandoTracker Debug Console\0".encode_utf16().collect();
            let _ = SetConsoleTitleW(windows::core::PCWSTR(title.as_ptr()));
        }
    }

    /// Resolve log file path (relative to DLL directory or absolute)
    pub fn resolve_log_path(hmodule: HINSTANCE, log_file: &str) -> Option<PathBuf> {
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

    pub fn start_mod(hmodule: HINSTANCE) {
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
}

#[cfg(target_os = "windows")]
#[no_mangle]
#[allow(clippy::missing_safety_doc)]
pub unsafe extern "system" fn DllMain(hmodule: HINSTANCE, reason: u32, _: *mut c_void) -> bool {
    // NOTE: DLL unloading is not supported. Once loaded, this DLL must remain
    // loaded for the lifetime of the game process. Attempting to unload it
    // (via injector eject or FreeLibrary) may crash the game due to:
    // - Race conditions between active hook calls and detour disable
    // - Background threads (WebSocket) accessing unmapped memory
    // - Rust static variables not having Drop called on DLL unload
    //
    // This is standard practice for game mods - they are typically not
    // designed to be unloaded cleanly.
    if reason == DLL_PROCESS_ATTACH {
        // Check game version
        if libeldenring::version::check_version().is_err() {
            return false;
        }

        std::thread::spawn(move || {
            dll_entry::start_mod(hmodule);
        });
    }

    true
}
