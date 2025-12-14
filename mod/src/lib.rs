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
mod tracker;
mod ui;
mod websocket;

// =============================================================================
// IMPORTS
// =============================================================================

use std::ffi::c_void;

use hudhook::hooks::dx12::ImguiDx12Hooks;
use hudhook::{eject, Hudhook};
#[allow(unused_imports)]
use windows::Win32::Foundation::HINSTANCE;
#[allow(unused_imports)]
use windows::Win32::System::SystemServices::DLL_PROCESS_ATTACH;
use windows::Win32::System::Console::{AllocConsole, SetConsoleTitleW};

use crate::config::Config;
use crate::tracker::FogRandoTracker;

// =============================================================================
// DLL ENTRY POINT
// =============================================================================

/// Allocate a console window for debug output
fn setup_debug_console() {
    unsafe {
        let _ = AllocConsole();
        let title: Vec<u16> = "FogRandoTracker Debug Console\0"
            .encode_utf16()
            .collect();
        let _ = SetConsoleTitleW(windows::core::PCWSTR(title.as_ptr()));
    }
}

fn start_mod(hmodule: HINSTANCE) {
    // Try to load config early to check for debug_console
    if let Ok(config) = Config::load(hmodule) {
        if config.debug_console {
            setup_debug_console();
            println!("[FogRandoTracker] Debug console enabled");
        }
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
        eprintln!("Couldn't apply hooks: {e:?}");
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
