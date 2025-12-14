// Build script for FogRandoTracker
// Copies the config file to the output directory after build

use std::env;
use std::fs;
use std::path::Path;

fn main() {
    // Tell Cargo to rerun this script if the config file changes
    println!("cargo:rerun-if-changed=fog_rando_tracker.toml");

    // Get the output directory from Cargo
    let out_dir = env::var("OUT_DIR").unwrap();

    // The OUT_DIR is something like target/release/build/fog-rando-tracker-xxx/out
    // We need to go up to target/release or target/debug
    let out_path = Path::new(&out_dir);

    // Navigate up to find the profile directory (release/debug)
    // OUT_DIR = target/<profile>/build/<crate>-<hash>/out
    let target_dir = out_path
        .ancestors()
        .nth(3) // Go up 3 levels from 'out'
        .expect("Could not find target directory");

    // Copy config file
    let config_src = Path::new("fog_rando_tracker.toml");
    let config_dst = target_dir.join("fog_rando_tracker.toml");

    if config_src.exists() {
        fs::copy(config_src, &config_dst).expect("Failed to copy config file");
        println!(
            "cargo:warning=Copied config file to {}",
            config_dst.display()
        );
    } else {
        println!("cargo:warning=Config file not found: fog_rando_tracker.toml");
    }
}
