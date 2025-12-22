// FogRandoTracker Launcher - GUI application for managing game sessions
// Copyright (C) 2024 wospins
//
// This program is free software: you can redistribute it and/or modify
// it under the terms of the GNU Affero General Public License as published
// by the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod api_client;
mod app;
mod config;
mod emevd;
mod process_monitor;
mod rando_folder;
mod spoiler_validator;

fn main() {
    // Initialize logging for debug builds
    #[cfg(debug_assertions)]
    {
        tracing_subscriber::fmt::init();
    }

    app::run_app();
}
