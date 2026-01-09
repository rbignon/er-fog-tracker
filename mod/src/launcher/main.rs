// FogRandoTracker Launcher - GUI application for managing game sessions

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
