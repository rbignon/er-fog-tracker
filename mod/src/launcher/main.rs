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
mod process_monitor;
mod spoiler_validator;

use app::LauncherApp;

fn main() -> eframe::Result<()> {
    // Initialize logging for debug builds
    #[cfg(debug_assertions)]
    {
        tracing_subscriber::fmt::init();
    }

    let options = eframe::NativeOptions {
        viewport: eframe::egui::ViewportBuilder::default()
            .with_inner_size([500.0, 450.0])
            .with_min_inner_size([400.0, 350.0])
            .with_title("FogRandoTracker Launcher"),
        ..Default::default()
    };

    eframe::run_native(
        "FogRandoTracker Launcher",
        options,
        Box::new(|cc| Ok(Box::new(LauncherApp::new(cc)))),
    )
}
